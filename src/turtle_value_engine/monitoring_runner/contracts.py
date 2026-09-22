"""Typed, immutable Phase 6-D2A unattended-runner contracts.

The runner package is a durable single-host wrapper around the Phase 6-D1
synchronous cycle.  It owns only runner activation/lease/receipt state; the
Phase 6-B acquisition, Phase 6-A planning/commit/cursor semantics, Phase 6-C
execution semantics and the D1 alert/cycle semantics stay behind their
existing public boundaries.  Every persisted runner artifact is canonical
JSON with a derived SHA-256 identity so a retry can prove whether it is
resuming the same activation or has encountered a conflicting state.
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
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from turtle_value_engine.monitoring.canonical import normalize_utc
from turtle_value_engine.monitoring_cycle.contracts import MonitoringCycleSpecV1

MONITORING_RUNNER_DOMAIN: Literal["monitoring-runner-v1"] = "monitoring-runner-v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_TOKEN_PATTERN = r"^[0-9a-f]{32}$"
_ZERO_HASH = "0" * 64
_SKIP_HASH_CONTEXT_KEY = "skip_derived_hash_validation"


class RunnerCompletion(StrEnum):
    """Terminal classifications of one unattended runner invocation."""

    COMPLETED_NEW = "COMPLETED_NEW"
    COMPLETED_RESUMED = "COMPLETED_RESUMED"
    COMPLETED_REPAIRED = "COMPLETED_REPAIRED"
    COMPLETED_REUSED = "COMPLETED_REUSED"


class LeaseState(StrEnum):
    """Liveness classification of one runner lease slot."""

    LIVE = "LIVE"
    ABANDONED = "ABANDONED"
    FREE = "FREE"


class _RunnerContract(BaseModel):
    """Shared canonical JSON and derived-hash plumbing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    _ZERO_FILL_FIELDS: ClassVar[tuple[str, ...]] = ("content_sha256",)

    def canonical_payload(
        self,
        *,
        exclude: set[str] | None = None,
        include: set[str] | None = None,
    ) -> dict:
        return self.model_dump(mode="json", exclude=exclude, include=include, warnings=False)

    def canonical_bytes(self) -> bytes:
        from turtle_value_engine.monitoring.canonical import canonical_json_bytes

        return canonical_json_bytes(self.canonical_payload())

    @classmethod
    def _coerced(cls, values: dict) -> Self:
        payload = dict(values)
        for name, field in cls.model_fields.items():
            if name in cls._ZERO_FILL_FIELDS and field.is_required():
                payload.setdefault(name, _ZERO_HASH)
        return cls.model_validate(payload, context={_SKIP_HASH_CONTEXT_KEY: True})


def _hash_checks_enabled(info: ValidationInfo) -> bool:
    context = info.context
    return not (isinstance(context, dict) and context.get(_SKIP_HASH_CONTEXT_KEY))


def _normalize_datetime(value: datetime) -> datetime:
    return normalize_utc(value)


class RunnerConfigV1(BaseModel):
    """Explicit, non-secret inputs for one unattended runner deployment.

    This is an input contract, not a persisted runner artifact: it carries
    only paths, policy flags and bounded operational metadata.  No credential
    value or secret reference may appear here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["monitoring_runner_config_v1"] = "monitoring_runner_config_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    watchlist_path: StrictStr = Field(min_length=1, max_length=512)
    monitoring_workspace_root: StrictStr = Field(min_length=1, max_length=512)
    reanalysis_job_root: StrictStr = Field(min_length=1, max_length=512)
    cycle_store_root: StrictStr = Field(min_length=1, max_length=512)
    runner_root: StrictStr = Field(min_length=1, max_length=512)
    cache_dir: StrictStr = Field(min_length=1, max_length=512)
    source_id: StrictStr = Field(default="CNINFO", min_length=1, max_length=100)
    adapter_version: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    acquisition_policy_id: StrictStr = Field(
        default="monitoring-acquisition-v1", min_length=1, max_length=128
    )
    acquisition_limit: StrictInt = Field(default=30, ge=1, le=30)
    network_allowed: StrictBool = False
    offline_replay: StrictBool = False
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_response_bytes: StrictInt = Field(default=512 * 1024, ge=1024, le=8 * 1024 * 1024)
    execution_catalog_path: StrictStr | None = Field(default=None, min_length=1, max_length=512)
    as_of: datetime | None = None
    published_from: date | None = None
    published_to: date | None = None
    window_days: StrictInt | None = Field(default=None, ge=1, le=366)
    lease_ttl_seconds: StrictInt = Field(default=900, ge=1, le=604800)

    _normalize_as_of = field_validator("as_of")(
        lambda value: None if value is None else normalize_utc(value)
    )

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        for name in (
            "runner_id",
            "watchlist_path",
            "monitoring_workspace_root",
            "reanalysis_job_root",
            "cycle_store_root",
            "runner_root",
            "cache_dir",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        if self.network_allowed and self.offline_replay:
            raise ValueError("runner acquisition mode cannot be live and offline at once")
        if not self.network_allowed and not self.offline_replay:
            raise ValueError(
                "runner acquisition mode must be explicit: network_allowed or offline_replay"
            )
        fixed_window = self.published_from is not None or self.published_to is not None
        if fixed_window:
            if self.published_from is None or self.published_to is None:
                raise ValueError("a fixed window needs both published_from and published_to")
            if self.published_from > self.published_to:
                raise ValueError("published_from must not be after published_to")
            if (self.published_to - self.published_from).days + 1 > 366:
                raise ValueError("fixed acquisition window exceeds 366 days")
            if self.window_days is not None:
                raise ValueError("fixed window and window_days are mutually exclusive")
        elif self.window_days is None:
            raise ValueError("acquisition window must be explicit: fixed dates or window_days")
        return self


class RunnerActivationIntentV1(_RunnerContract):
    """Durable activation intent persisted before entering Phase 6-D1.

    The intent freezes the exact resolved D1 request (including the resolved
    PIT ``as_of``) plus a request fingerprint over every explicit input needed
    to reproduce the same D1 invocation.  A retry after a crash resumes this
    activation instead of deriving a new cycle from a later wall clock.
    """

    contract: Literal["monitoring_runner_activation_v1"] = "monitoring_runner_activation_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"

    _ZERO_FILL_FIELDS: ClassVar[tuple[str, ...]] = ("activation_id", "content_sha256")

    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    created_at: datetime
    request_fingerprint: StrictStr = Field(pattern=_HASH_PATTERN)
    spec: MonitoringCycleSpecV1
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_created_at = field_validator("created_at")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_intent(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected_activation = canonical_sha256(
                {
                    "domain": "tve-monitoring-runner-activation-v1",
                    "runner_id": self.runner_id,
                    "cycle_id": self.spec.cycle_id,
                }
            )
            if self.activation_id != expected_activation:
                raise ValueError("activation_id does not match the frozen cycle request")
            expected_content = canonical_sha256(
                self.canonical_payload(exclude={"content_sha256"})
            )
            if self.content_sha256 != expected_content:
                raise ValueError("activation intent content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        runner_id: str,
        created_at: datetime,
        request_fingerprint: str,
        spec: MonitoringCycleSpecV1,
    ) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(
            {
                "runner_id": runner_id,
                "created_at": normalize_utc(created_at),
                "request_fingerprint": request_fingerprint,
                "spec": spec,
            }
        )
        activation_id = canonical_sha256(
            {
                "domain": "tve-monitoring-runner-activation-v1",
                "runner_id": runner_id,
                "cycle_id": spec.cycle_id,
            }
        )
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(
            payload
            | {
                "activation_id": activation_id,
                "content_sha256": canonical_sha256(payload | {"activation_id": activation_id}),
            }
        )


class RunnerLeaseV1(_RunnerContract):
    """Single-host lease record for one runner identity.

    Liveness is proven by an OS-level exclusive lock on the lease file, which
    the host releases when the holding process exits for any reason.  This
    record is the durable, machine-readable projection of the current holder;
    ``lease_ttl_seconds`` is operational metadata for humans and never
    authorizes taking a lease from a live holder.
    """

    contract: Literal["monitoring_runner_lease_v1"] = "monitoring_runner_lease_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    holder_token: StrictStr = Field(pattern=_TOKEN_PATTERN)
    activation_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    acquired_at: datetime
    heartbeat_at: datetime
    lease_ttl_seconds: StrictInt = Field(ge=1, le=604800)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_acquired_at = field_validator("acquired_at")(_normalize_datetime)
    _normalize_heartbeat_at = field_validator("heartbeat_at")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_lease(self, info: ValidationInfo) -> Self:
        if self.heartbeat_at < self.acquired_at:
            raise ValueError("lease heartbeat cannot precede acquisition")
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("lease record content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        runner_id: str,
        holder_token: str,
        activation_id: str | None,
        acquired_at: datetime,
        lease_ttl_seconds: int,
    ) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(
            {
                "runner_id": runner_id,
                "holder_token": holder_token,
                "activation_id": activation_id,
                "acquired_at": normalize_utc(acquired_at),
                "heartbeat_at": normalize_utc(acquired_at),
                "lease_ttl_seconds": lease_ttl_seconds,
            }
        )
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


class RunnerReceiptV1(_RunnerContract):
    """Terminal receipt binding one activation to exact D1 terminal artifacts."""

    contract: Literal["monitoring_runner_receipt_v1"] = "monitoring_runner_receipt_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    classification: Literal["CYCLE_TERMINAL"] = "CYCLE_TERMINAL"
    d1_status: StrictStr = Field(min_length=1, max_length=64)
    d1_failure_code: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    result_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    completed_at: datetime
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_completed_at = field_validator("completed_at")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_receipt(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("runner receipt content_sha256 does not match content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


class RunnerLatestPointerV1(_RunnerContract):
    """Atomic latest pointer naming the newest terminal runner receipt."""

    contract: Literal["monitoring_runner_latest_pointer_v1"] = (
        "monitoring_runner_latest_pointer_v1"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    receipt_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_latest(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("runner latest pointer content_sha256 mismatch")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


class RunnerActivePointerV1(_RunnerContract):
    """Atomic pointer naming the currently unfinished activation, if any."""

    contract: Literal["monitoring_runner_active_pointer_v1"] = (
        "monitoring_runner_active_pointer_v1"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    intent_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_active(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("runner active pointer content_sha256 mismatch")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


__all__ = [
    "MONITORING_RUNNER_DOMAIN",
    "LeaseState",
    "RunnerActivationIntentV1",
    "RunnerActivePointerV1",
    "RunnerCompletion",
    "RunnerConfigV1",
    "RunnerLatestPointerV1",
    "RunnerLeaseV1",
    "RunnerReceiptV1",
]
