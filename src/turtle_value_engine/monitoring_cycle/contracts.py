"""Typed, immutable Phase 6-D1 cycle, execution-binding and alert contracts.

The cycle package is an orchestration boundary.  It owns neither filing
acquisition semantics, monitoring planning semantics nor re-analysis
semantics; those remain in the Phase 6-B, 6-A and 6-C packages respectively.
Every D1 artifact is canonical JSON with a derived SHA-256 identity so a
retry can prove whether it is reusing the same request or has encountered a
content conflict.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from turtle_value_engine.models import Company
from turtle_value_engine.monitoring.canonical import (
    canonical_json_bytes,
    canonical_sha256,
    normalize_utc,
)
from turtle_value_engine.monitoring.models import CanonicalEventType, MonitoringEventBatchV1
from turtle_value_engine.monitoring.policy import ImpactClass
from turtle_value_engine.monitoring_execution.contracts import ReanalysisJobStatus

MONITORING_CYCLE_CONTRACT: Literal["monitoring-cycle-v1"] = "monitoring-cycle-v1"
MONITORING_CYCLE_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
MONITORING_CYCLE_POLICY_ID: Literal["monitoring-cycle-v1"] = MONITORING_CYCLE_CONTRACT
MONITORING_CYCLE_POLICY_VERSION: Literal["1.0.0"] = MONITORING_CYCLE_SCHEMA_VERSION
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_ZERO_HASH = "0" * 64
_SKIP_HASH_CONTEXT_KEY = "skip_derived_hash_validation"


class CycleStatus(StrEnum):
    """Terminal outcomes of one synchronous monitoring cycle."""

    NO_CHANGE = "NO_CHANGE"
    ALERTS_EMITTED = "ALERTS_EMITTED"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
    FAILED = "FAILED"


class CycleFailureCode(StrEnum):
    """Stable, secret-free D1 blocker/failure categories."""

    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    INVALID_ACQUISITION_RESULT = "INVALID_ACQUISITION_RESULT"
    UNRESOLVED_CURRENT_RUN = "UNRESOLVED_CURRENT_RUN"
    MISSING_EXECUTION_DISPOSITION = "MISSING_EXECUTION_DISPOSITION"
    MISSING_EXECUTION_BINDING = "MISSING_EXECUTION_BINDING"
    EXECUTION_ATTENTION_REQUIRED = "EXECUTION_ATTENTION_REQUIRED"
    MONITORING_COMMIT_FAILED = "MONITORING_COMMIT_FAILED"
    CYCLE_STORE_FAILED = "CYCLE_STORE_FAILED"
    CYCLE_CONFLICT = "CYCLE_CONFLICT"
    LOWER_LEVEL_INELIGIBLE = "LOWER_LEVEL_INELIGIBLE"


class AlertKind(StrEnum):
    """Factual alert projections; none is an investment recommendation."""

    MATERIAL_EVENT = "MATERIAL_EVENT"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    REANALYSIS_BLOCKED = "REANALYSIS_BLOCKED"
    REANALYSIS_FAILED = "REANALYSIS_FAILED"
    REANALYSIS_SUCCEEDED = "REANALYSIS_SUCCEEDED"
    CYCLE_FAILED = "CYCLE_FAILED"


class _CycleContract(BaseModel):
    """Shared canonical JSON and derived-hash plumbing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def canonical_payload(
        self,
        *,
        exclude: set[str] | None = None,
        include: set[str] | None = None,
    ) -> dict:
        return self.model_dump(mode="json", exclude=exclude, include=include, warnings=False)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())

    @classmethod
    def _coerced(cls, values: dict) -> Self:
        payload = dict(values)
        for name, field in cls.model_fields.items():
            if (
                name
                in {
                    "catalog_id",
                    "acquisition_id",
                    "plan_id",
                    "alert_id",
                    "alert_batch_id",
                    "cycle_id",
                    "content_sha256",
                }
                and field.is_required()
            ):
                payload.setdefault(name, _ZERO_HASH)
        return cls.model_validate(payload, context={_SKIP_HASH_CONTEXT_KEY: True})


def _hash_checks_enabled(info: ValidationInfo) -> bool:
    context = info.context
    return not (isinstance(context, dict) and context.get(_SKIP_HASH_CONTEXT_KEY))


def _normalize_datetime(value: datetime) -> datetime:
    return normalize_utc(value)


def _normalize_datetime_optional(value: datetime | None) -> datetime | None:
    return None if value is None else normalize_utc(value)


def _path_value(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _listing_identity(value: str) -> str:
    text = value.strip().upper()
    if "." in text:
        code, market = text.rsplit(".", 1)
        if market in {"SH", "SZ", "HK", "BJ"}:
            return f"{market}{code}"
    return text


class MonitoringExecutionBindingV1(_CycleContract):
    """Explicit non-secret inputs for one listing's re-analysis request.

    A binding may point to a prepared input and/or prior analysis artifact, or
    carry an explicit company context for the existing preparation boundary.
    An omitted binding is meaningful: D1 treats it as a blocker for PARTIAL or
    FULL execution rather than inventing company facts.
    """

    contract: Literal["monitoring_execution_binding_v1"] = "monitoring_execution_binding_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    listing_id: StrictStr = Field(min_length=1, max_length=32)
    company: Company | None = None
    prepared_input_path: StrictStr | None = Field(default=None, max_length=512)
    prior_analysis_path: StrictStr | None = Field(default=None, max_length=512)
    resolver_key: StrictStr | None = Field(default=None, max_length=128)

    _blank_paths = field_validator(
        "prepared_input_path", "prior_analysis_path", "resolver_key", mode="before"
    )(_path_value)

    @model_validator(mode="after")
    def _validate_binding(self) -> Self:
        if self.company is not None and _listing_identity(
            self.company.primary_listing
        ) != _listing_identity(self.listing_id):
            raise ValueError("execution binding company does not match listing_id")
        return self


class MonitoringExecutionCatalogV1(_CycleContract):
    """Canonical collection of explicit per-listing execution bindings."""

    contract: Literal["monitoring_execution_catalog_v1"] = "monitoring_execution_catalog_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    bindings: list[MonitoringExecutionBindingV1] = Field(default_factory=list, max_length=256)
    catalog_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_catalog(self, info: ValidationInfo) -> Self:
        listing_ids = [binding.listing_id for binding in self.bindings]
        if listing_ids != sorted(listing_ids):
            raise ValueError("execution bindings must be sorted by listing_id")
        if len(listing_ids) != len(set(listing_ids)):
            raise ValueError("execution catalog contains duplicate listing bindings")
        if _hash_checks_enabled(info):
            expected = canonical_sha256(
                self.canonical_payload(exclude={"catalog_id", "content_sha256"})
            )
            if self.catalog_id != expected or self.content_sha256 != expected:
                raise ValueError("execution catalog identity does not match canonical content")
        return self

    @classmethod
    def build(cls, bindings: list[MonitoringExecutionBindingV1] | None = None) -> Self:
        coerced = cls._coerced(
            {"bindings": sorted(bindings or [], key=lambda item: item.listing_id)}
        )
        payload = coerced.canonical_payload(exclude={"catalog_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(payload | {"catalog_id": digest, "content_sha256": digest})

    def for_listing(self, listing_id: str) -> MonitoringExecutionBindingV1 | None:
        for binding in self.bindings:
            if binding.listing_id == listing_id:
                return binding
        return None


class MonitoringCycleSpecV1(_CycleContract):
    """Explicit request for exactly one point-in-time monitoring cycle."""

    contract: Literal["monitoring_cycle_spec_v1"] = "monitoring_cycle_spec_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cycle_policy_id: Literal["monitoring-cycle-v1"] = MONITORING_CYCLE_POLICY_ID
    cycle_policy_version: Literal["1.0.0"] = MONITORING_CYCLE_POLICY_VERSION
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    watchlist_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    as_of: datetime
    acquisition_policy_id: StrictStr = Field(min_length=1, max_length=128)
    source_id: StrictStr = Field(min_length=1, max_length=100)
    adapter_version: StrictStr = Field(min_length=1, max_length=128)
    published_from: date
    published_to: date
    acquisition_limit: int = Field(ge=1, le=30)
    network_allowed: StrictBool = False
    offline_replay: StrictBool = False
    event_impact_policy_id: Literal["event-impact-v1"] = "event-impact-v1"
    execution_policy_id: Literal["reanalysis-execution-v1"] = "reanalysis-execution-v1"
    execution_policy_version: Literal["1.0.0"] = "1.0.0"
    monitoring_workspace_root: StrictStr = Field(min_length=1, max_length=512)
    reanalysis_job_root: StrictStr = Field(min_length=1, max_length=512)
    cycle_store_root: StrictStr = Field(min_length=1, max_length=512)
    execution_catalog: MonitoringExecutionCatalogV1
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_as_of = field_validator("as_of")(_normalize_datetime)

    _IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "cycle_policy_id",
        "cycle_policy_version",
        "watchlist_id",
        "watchlist_content_sha256",
        "as_of",
        "acquisition_policy_id",
        "source_id",
        "adapter_version",
        "published_from",
        "published_to",
        "acquisition_limit",
        "network_allowed",
        "offline_replay",
        "event_impact_policy_id",
        "execution_policy_id",
        "execution_policy_version",
        "monitoring_workspace_root",
        "reanalysis_job_root",
        "cycle_store_root",
        "execution_catalog",
    )

    @model_validator(mode="after")
    def _validate_spec(self, info: ValidationInfo) -> Self:
        if self.published_from > self.published_to:
            raise ValueError("resolved acquisition window start must not be after end")
        if (self.published_to - self.published_from).days + 1 > 366:
            raise ValueError("resolved acquisition window exceeds 366 days")
        if self.network_allowed and self.offline_replay:
            raise ValueError("live network permission and offline replay are mutually exclusive")
        if not self.network_allowed and not self.offline_replay:
            raise ValueError("acquisition mode must be explicit: allow network or offline replay")
        for field_name in (
            "monitoring_workspace_root",
            "reanalysis_job_root",
            "cycle_store_root",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if _hash_checks_enabled(info):
            identity_payload = self.canonical_payload(include=set(self._IDENTITY_FIELDS))
            expected_cycle = canonical_sha256(
                {"domain": MONITORING_CYCLE_CONTRACT, **identity_payload}
            )
            if self.cycle_id != expected_cycle:
                raise ValueError("monitoring cycle_id does not match explicit request inputs")
            expected_content = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected_content:
                raise ValueError(
                    "monitoring cycle spec content_sha256 does not match canonical content"
                )
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        coerced = cls._coerced(dict(values))
        identity_payload = coerced.canonical_payload(include=set(cls._IDENTITY_FIELDS))
        cycle_id = canonical_sha256({"domain": MONITORING_CYCLE_CONTRACT, **identity_payload})
        payload = coerced.canonical_payload(exclude={"cycle_id", "content_sha256"})
        return cls.model_validate(
            payload
            | {
                "cycle_id": cycle_id,
                "content_sha256": canonical_sha256(payload | {"cycle_id": cycle_id}),
            }
        )


class MonitoringCycleAcquisitionV1(_CycleContract):
    """Immutable acquisition-stage receipt used for crash/retry recovery."""

    contract: Literal["monitoring_cycle_acquisition_v1"] = "monitoring_cycle_acquisition_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    spec_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    watchlist_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    prior_state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    source_id: StrictStr = Field(min_length=1, max_length=100)
    adapter_version: StrictStr = Field(min_length=1, max_length=128)
    published_from: date
    published_to: date
    network_allowed: StrictBool
    offline_replay: StrictBool
    retrieval_mode: Literal["LIVE", "CACHE_REPLAY", "INJECTED"]
    batch: MonitoringEventBatchV1
    acquisition_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_acquisition(self, info: ValidationInfo) -> Self:
        if self.batch.batch_id != self.batch.content_sha256:
            raise ValueError("acquisition batch identity is invalid")
        if self.network_allowed and self.offline_replay:
            raise ValueError("acquisition receipt cannot be live and offline")
        if self.retrieval_mode == "LIVE" and not self.network_allowed:
            raise ValueError("LIVE acquisition receipt requires network permission")
        if self.retrieval_mode == "CACHE_REPLAY" and not self.offline_replay:
            raise ValueError("CACHE_REPLAY receipt requires offline replay mode")
        if _hash_checks_enabled(info):
            payload = self.canonical_payload(exclude={"acquisition_id", "content_sha256"})
            expected = canonical_sha256(payload)
            if self.acquisition_id != expected or self.content_sha256 != expected:
                raise ValueError("cycle acquisition identity does not match canonical content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"acquisition_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(payload | {"acquisition_id": digest, "content_sha256": digest})


class MonitoringCyclePlanV1(_CycleContract):
    """Immutable plan-stage receipt binding D1 to a committed 6-A run."""

    contract: Literal["monitoring_cycle_plan_v1"] = "monitoring_cycle_plan_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    spec_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    prior_state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    next_state_id: StrictStr = Field(pattern=_HASH_PATTERN)
    event_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    monitoring_run_id: StrictStr = Field(pattern=_HASH_PATTERN)
    monitoring_run_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    request_ids: list[StrictStr] = Field(default_factory=list, max_length=256)
    plan_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_plan(self, info: ValidationInfo) -> Self:
        if self.request_ids != sorted(self.request_ids) or len(self.request_ids) != len(
            set(self.request_ids)
        ):
            raise ValueError("cycle plan request_ids must be sorted and unique")
        if _hash_checks_enabled(info):
            payload = self.canonical_payload(exclude={"plan_id", "content_sha256"})
            expected = canonical_sha256(payload)
            if self.plan_id != expected or self.content_sha256 != expected:
                raise ValueError("cycle plan identity does not match canonical content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"plan_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(payload | {"plan_id": digest, "content_sha256": digest})


class MonitoringAlertV1(_CycleContract):
    """One bounded, factual, secret-free immutable outbox item."""

    contract: Literal["monitoring_alert_v1"] = "monitoring_alert_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    alert_id: StrictStr = Field(pattern=_HASH_PATTERN)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    monitoring_run_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    event_batch_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    kind: AlertKind
    listing_id: StrictStr | None = Field(default=None, max_length=32)
    event_ids: list[StrictStr] = Field(default_factory=list, max_length=256)
    event_types: list[CanonicalEventType] = Field(default_factory=list, max_length=256)
    impact: ImpactClass | None = None
    available_at: datetime | None = None
    job_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    job_status: ReanalysisJobStatus | None = None
    failure_code: StrictStr | None = Field(default=None, max_length=128)
    analysis_id: StrictStr | None = Field(default=None, max_length=200)
    surface_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    message: StrictStr = Field(min_length=1, max_length=512)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_available_at = field_validator("available_at")(_normalize_datetime_optional)

    @model_validator(mode="after")
    def _validate_alert(self, info: ValidationInfo) -> Self:
        if len(self.event_ids) != len(set(self.event_ids)):
            raise ValueError("alert event_ids must be unique")
        if self.event_types and len(self.event_types) != len(self.event_ids):
            raise ValueError("alert event_types must align with event_ids")
        if self.kind is not AlertKind.CYCLE_FAILED and self.monitoring_run_id is None:
            raise ValueError("non-failure alert requires a monitoring_run_id")
        if self.event_ids and self.event_batch_id is None:
            raise ValueError("event-backed alert requires an event_batch_id")
        if self.kind is AlertKind.REANALYSIS_SUCCEEDED and self.surface_id is None:
            raise ValueError("successful re-analysis alert requires a surface_id")
        if _hash_checks_enabled(info):
            identity = {
                "domain": "tve-monitoring-alert-v1",
                "cycle_id": self.cycle_id,
                "kind": self.kind,
                "monitoring_run_id": self.monitoring_run_id,
                "event_batch_id": self.event_batch_id,
                "listing_id": self.listing_id,
                "event_ids": self.event_ids,
                "job_id": self.job_id,
                "reason_code": self.reason_code,
            }
            if self.alert_id != canonical_sha256(identity):
                raise ValueError("alert_id does not match deterministic semantic identity")
            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("alert content_sha256 does not match canonical content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        coerced = cls._coerced(dict(values))
        identity = {
            "domain": "tve-monitoring-alert-v1",
            "cycle_id": coerced.cycle_id,
            "kind": coerced.kind,
            "monitoring_run_id": coerced.monitoring_run_id,
            "event_batch_id": coerced.event_batch_id,
            "listing_id": coerced.listing_id,
            "event_ids": coerced.event_ids,
            "job_id": coerced.job_id,
            "reason_code": coerced.reason_code,
        }
        alert_id = canonical_sha256(identity)
        payload = coerced.canonical_payload(exclude={"alert_id", "content_sha256"})
        content = canonical_sha256(payload | {"alert_id": alert_id})
        return cls.model_validate(payload | {"alert_id": alert_id, "content_sha256": content})


class MonitoringAlertBatchV1(_CycleContract):
    """Deterministic immutable alert outbox for one cycle."""

    contract: Literal["monitoring_alert_batch_v1"] = "monitoring_alert_batch_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    alerts: list[MonitoringAlertV1] = Field(default_factory=list, max_length=1024)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_alert_batch(self, info: ValidationInfo) -> Self:
        alert_ids = [alert.alert_id for alert in self.alerts]
        if alert_ids != sorted(alert_ids) or len(alert_ids) != len(set(alert_ids)):
            raise ValueError("alert batch must contain unique alerts in canonical order")
        if any(
            alert.cycle_id != self.cycle_id or alert.watchlist_id != self.watchlist_id
            for alert in self.alerts
        ):
            raise ValueError("alert does not belong to this cycle/watchlist")
        if _hash_checks_enabled(info):
            payload = self.canonical_payload(exclude={"alert_batch_id", "content_sha256"})
            expected = canonical_sha256(payload)
            if self.alert_batch_id != expected or self.content_sha256 != expected:
                raise ValueError("alert batch identity does not match canonical content")
        return self

    @classmethod
    def build(cls, *, cycle_id: str, watchlist_id: str, alerts: list[MonitoringAlertV1]) -> Self:
        coerced = cls._coerced(
            {
                "cycle_id": cycle_id,
                "watchlist_id": watchlist_id,
                "alerts": sorted(alerts, key=lambda alert: alert.alert_id),
            }
        )
        payload = coerced.canonical_payload(exclude={"alert_batch_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(payload | {"alert_batch_id": digest, "content_sha256": digest})


class MonitoringCycleExecutionDispositionV1(_CycleContract):
    """The exact terminal Phase 6-C disposition required by one request."""

    contract: Literal["monitoring_cycle_execution_disposition_v1"] = (
        "monitoring_cycle_execution_disposition_v1"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: StrictStr = Field(pattern=_HASH_PATTERN)
    listing_id: StrictStr = Field(min_length=1, max_length=32)
    impact: ImpactClass
    job_id: StrictStr = Field(pattern=_HASH_PATTERN)
    job_content_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    status: ReanalysisJobStatus | None = None
    failure_code: StrictStr | None = Field(default=None, max_length=128)
    resolution: Literal["RESOLVED", "UNRESOLVED", "MISSING"]

    @model_validator(mode="after")
    def _validate_disposition(self) -> Self:
        if self.status is None and self.resolution != "MISSING":
            raise ValueError("missing job status must use MISSING resolution")
        if self.status is not None and self.resolution == "MISSING":
            raise ValueError("present job status cannot use MISSING resolution")
        expected = (
            "RESOLVED"
            if self.status
            in {
                ReanalysisJobStatus.SUCCEEDED,
                ReanalysisJobStatus.NO_ACTION,
                ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
            }
            else "UNRESOLVED"
        )
        if self.status is not None and self.resolution != expected:
            raise ValueError("execution disposition resolution does not match job status")
        return self


class MonitoringCycleResultV1(_CycleContract):
    """Terminal D1 result, including every lower-level execution disposition."""

    contract: Literal["monitoring_cycle_result_v1"] = "monitoring_cycle_result_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    spec_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    watchlist_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    as_of: datetime
    status: CycleStatus
    failure_code: CycleFailureCode | None = None
    message: StrictStr | None = Field(default=None, max_length=512)
    prior_state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    event_batch_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    event_batch_content_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    monitoring_run_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    monitoring_run_content_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    next_state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    execution: list[MonitoringCycleExecutionDispositionV1] = Field(
        default_factory=list, max_length=256
    )
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_as_of = field_validator("as_of")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_result(self, info: ValidationInfo) -> Self:
        request_ids = [item.request_id for item in self.execution]
        if request_ids != sorted(request_ids) or len(request_ids) != len(set(request_ids)):
            raise ValueError("cycle execution dispositions must be sorted and unique")
        if self.status is CycleStatus.FAILED and self.failure_code is None:
            raise ValueError("failed cycle requires a failure_code")
        if self.status is not CycleStatus.FAILED and self.failure_code in {
            CycleFailureCode.ACQUISITION_FAILED,
            CycleFailureCode.INVALID_ACQUISITION_RESULT,
            CycleFailureCode.MONITORING_COMMIT_FAILED,
            CycleFailureCode.CYCLE_STORE_FAILED,
        }:
            raise ValueError("acquisition/commit/store failure code requires FAILED status")
        if _hash_checks_enabled(info):
            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("cycle result content_sha256 does not match canonical content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


class MonitoringCyclePointerV1(_CycleContract):
    """Atomic latest pointer for one deterministic cycle identity."""

    contract: Literal["monitoring_cycle_pointer_v1"] = "monitoring_cycle_pointer_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    result_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_pointer(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("cycle latest pointer content_sha256 mismatch")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


__all__ = [
    "AlertKind",
    "CycleFailureCode",
    "CycleStatus",
    "MONITORING_CYCLE_CONTRACT",
    "MONITORING_CYCLE_POLICY_ID",
    "MONITORING_CYCLE_POLICY_VERSION",
    "MONITORING_CYCLE_SCHEMA_VERSION",
    "MonitoringAlertBatchV1",
    "MonitoringAlertV1",
    "MonitoringCycleAcquisitionV1",
    "MonitoringCycleExecutionDispositionV1",
    "MonitoringCyclePlanV1",
    "MonitoringCyclePointerV1",
    "MonitoringCycleResultV1",
    "MonitoringCycleSpecV1",
    "MonitoringExecutionBindingV1",
    "MonitoringExecutionCatalogV1",
]
