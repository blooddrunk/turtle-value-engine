"""Typed contracts for the Phase 6-D3 read-only monitoring operations projection.

The projection is an API/read model over the already-proven Phase 6-A, 6-C,
D1, D2A/R1 and D2B/R1/R2 durable stores.  It is never persisted as an
authoritative ledger: the underlying stores remain the only source of truth.
Every field is secret-free and free of local absolute paths; long machine
identifiers stay available for audit but carry no operational authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from turtle_value_engine.monitoring.models import MonitoringStatusV1
from turtle_value_engine.monitoring.policy import ImpactClass
from turtle_value_engine.monitoring_cycle.contracts import (
    CycleStatus,
    MonitoringAlertV1,
)
from turtle_value_engine.monitoring_delivery.contracts import MonitoringDeliveryStateV1
from turtle_value_engine.monitoring_execution.contracts import ReanalysisJobStatus

_HASH_PATTERN = r"^[0-9a-f]{64}$"

MONITORING_OPERATIONS_PROJECTION_CONTRACT = "monitoring_operations_projection_v1"
MONITORING_OPERATIONS_SOURCES_CONTRACT = "monitoring_operations_sources_v1"
MONITORING_OPERATIONS_SCHEMA_VERSION = "1.0.0"


class MonitoringOperationsSourcesV1(BaseModel):
    """Explicit non-secret source binding for one configured runner chain.

    This is an input contract, not a payload: it carries only local paths and
    identities needed to open the existing stores read-only.  It must never
    appear in an API/browser payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["monitoring_operations_sources_v1"] = (
        MONITORING_OPERATIONS_SOURCES_CONTRACT
    )
    schema_version: Literal["1.0.0"] = MONITORING_OPERATIONS_SCHEMA_VERSION
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    watchlist_path: StrictStr = Field(min_length=1, max_length=1024)
    monitoring_workspace_root: StrictStr = Field(min_length=1, max_length=1024)
    reanalysis_job_root: StrictStr = Field(min_length=1, max_length=1024)
    cycle_store_root: StrictStr = Field(min_length=1, max_length=1024)
    runner_root: StrictStr = Field(min_length=1, max_length=1024)
    delivery_root: StrictStr | None = Field(default=None, min_length=1, max_length=1024)
    lease_ttl_seconds: StrictInt = Field(default=900, ge=1, le=604800)


class MonitoringOperationsLeaseRecordV1(BaseModel):
    """Secret-free public lease record (holder token and hash excluded)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["monitoring_runner_lease_v1"] = "monitoring_runner_lease_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    acquired_at: datetime
    heartbeat_at: datetime
    lease_ttl_seconds: StrictInt = Field(ge=1, le=604800)


class MonitoringOperationsRunnerV1(BaseModel):
    """Read-only runner/lease status for the one configured runner identity.

    ``lease_state`` comes from the 6-D3-R1 non-interfering passive probe:
    ``LIVE``/``ABANDONED``/``FREE`` are proven classifications, while
    ``UNKNOWN`` is the explicit conservative state returned when liveness
    cannot be proven without competing for the authoritative work lock.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runner_id: StrictStr = Field(min_length=1, max_length=128)
    lease_state: Literal["LIVE", "ABANDONED", "FREE", "UNKNOWN"]
    lease_corrupt: StrictBool
    lease_record: MonitoringOperationsLeaseRecordV1 | None = None
    unfinished_activation_ids: list[StrictStr] = Field(default_factory=list, max_length=64)
    latest_terminal_activation_id: StrictStr | None = Field(
        default=None, pattern=_HASH_PATTERN
    )


class MonitoringOperationsReceiptV1(BaseModel):
    """Terminal D2A receipt facts bound to the projected activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    classification: Literal["CYCLE_TERMINAL"] = "CYCLE_TERMINAL"
    d1_status: StrictStr = Field(min_length=1, max_length=64)
    d1_failure_code: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    result_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    completed_at: datetime
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)


class MonitoringOperationsActivationV1(BaseModel):
    """The one projected activation: active when unfinished, else latest terminal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["ACTIVE", "LATEST_TERMINAL"]
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    as_of: datetime
    created_at: datetime
    request_fingerprint: StrictStr = Field(pattern=_HASH_PATTERN)
    intent_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    receipt: MonitoringOperationsReceiptV1 | None = None


class MonitoringOperationsCycleV1(BaseModel):
    """Terminal D1 cycle facts for the projected activation, when committed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    status: CycleStatus
    failure_code: StrictStr | None = Field(default=None, max_length=128)
    message: StrictStr | None = Field(default=None, max_length=512)
    as_of: datetime
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    monitoring_run_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    event_batch_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    next_state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    result_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    pointer_published: StrictBool
    alert_count: StrictInt = Field(ge=0)
    alerts: list[MonitoringAlertV1] = Field(default_factory=list, max_length=1024)


class MonitoringOperationsJobDetailV1(BaseModel):
    """Terminal Phase 6-C job facts read from the execution store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReanalysisJobStatus
    failure_code: StrictStr | None = Field(default=None, max_length=128)
    message: StrictStr | None = Field(default=None, max_length=512)
    attempt_number: StrictInt = Field(ge=1)
    evidence_codes: list[StrictStr] = Field(default_factory=list, max_length=32)
    analysis_id: StrictStr | None = Field(default=None, min_length=1)
    analysis_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    surface_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    surface_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)


class MonitoringOperationsJobV1(BaseModel):
    """One re-analysis job required by the projected cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: StrictStr = Field(pattern=_HASH_PATTERN)
    listing_id: StrictStr = Field(min_length=1, max_length=32)
    impact: ImpactClass
    job_id: StrictStr = Field(pattern=_HASH_PATTERN)
    job_content_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    disposition_status: ReanalysisJobStatus | None = None
    disposition_failure_code: StrictStr | None = Field(default=None, max_length=128)
    resolution: Literal["RESOLVED", "UNRESOLVED", "MISSING"]
    job: MonitoringOperationsJobDetailV1 | None = None


class MonitoringOperationsDeliveryAttemptV1(BaseModel):
    """One persisted delivery outcome (slot number may legitimately gap)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: StrictInt = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    classification: StrictStr = Field(min_length=1, max_length=64)
    http_status: StrictInt | None = None
    response_body_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    error_code: StrictStr | None = Field(default=None, max_length=128)
    retry_not_before: datetime | None = None


class MonitoringOperationsUnresolvedClaimV1(BaseModel):
    """The highest durable dispatch slot whose outcome never became durable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: StrictInt = Field(ge=1)
    idempotency_key: StrictStr = Field(min_length=1, max_length=256)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)


class MonitoringOperationsDeliveryV1(BaseModel):
    """One D2B delivery bound to the projected activation.

    ``state.attempt_count`` counts persisted attempt outcomes while
    ``dispatch_claim_count`` counts consumed authorized outbound transport
    slots; after an orphaned dispatch the two legitimately differ and the
    unresolved slot numbers stay explicit (6-D2B-R2).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery_id: StrictStr = Field(min_length=1, max_length=256)
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    destination_id: StrictStr = Field(min_length=1, max_length=128)
    transport: StrictStr = Field(min_length=1, max_length=64)
    payload_contract: StrictStr = Field(min_length=1, max_length=128)
    payload_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    empty_outbox: StrictBool
    created_at: datetime
    state: MonitoringDeliveryStateV1
    pointer_published: StrictBool
    pointer_status: Literal["CURRENT", "MISSING", "STALE_REPAIRABLE"]
    dispatch_claim_count: StrictInt = Field(ge=0)
    unresolved_claim_numbers: list[StrictInt] = Field(default_factory=list, max_length=64)
    unresolved_dispatch_claim: MonitoringOperationsUnresolvedClaimV1 | None = None
    attempts: list[MonitoringOperationsDeliveryAttemptV1] = Field(
        default_factory=list, max_length=64
    )


class MonitoringOperationsProjectionV1(BaseModel):
    """Versioned, secret-free read model over the configured monitoring chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["monitoring_operations_projection_v1"] = (
        MONITORING_OPERATIONS_PROJECTION_CONTRACT
    )
    schema_version: Literal["1.0.0"] = MONITORING_OPERATIONS_SCHEMA_VERSION
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    watchlist: MonitoringStatusV1
    runner: MonitoringOperationsRunnerV1
    activation: MonitoringOperationsActivationV1 | None = None
    cycle: MonitoringOperationsCycleV1 | None = None
    jobs: list[MonitoringOperationsJobV1] = Field(default_factory=list, max_length=256)
    deliveries_configured: StrictBool
    deliveries: list[MonitoringOperationsDeliveryV1] = Field(
        default_factory=list, max_length=64
    )


__all__ = [
    "MONITORING_OPERATIONS_PROJECTION_CONTRACT",
    "MONITORING_OPERATIONS_SCHEMA_VERSION",
    "MONITORING_OPERATIONS_SOURCES_CONTRACT",
    "MonitoringOperationsActivationV1",
    "MonitoringOperationsCycleV1",
    "MonitoringOperationsDeliveryAttemptV1",
    "MonitoringOperationsDeliveryV1",
    "MonitoringOperationsJobDetailV1",
    "MonitoringOperationsJobV1",
    "MonitoringOperationsLeaseRecordV1",
    "MonitoringOperationsProjectionV1",
    "MonitoringOperationsReceiptV1",
    "MonitoringOperationsRunnerV1",
    "MonitoringOperationsSourcesV1",
    "MonitoringOperationsUnresolvedClaimV1",
]
