"""Typed, immutable Phase 6-D2B notification-delivery contracts.

The delivery package consumes only a validated terminal Phase 6-D2A runner
receipt plus the exact Phase 6-D1 ``MonitoringCycleResultV1`` /
``MonitoringAlertBatchV1`` pair it binds.  It owns delivery intents, attempt
records and the atomic latest state in its own ledger; it never mutates D1 or
D2A state and never triggers provider, model or re-analysis work.  Every
persisted artifact is canonical JSON with a derived SHA-256 identity so a
retry can prove whether it is resuming the same delivery or has encountered
a conflicting state.  No secret value (webhook URL, bearer token) may ever
appear in any contract field.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from turtle_value_engine.monitoring.canonical import normalize_utc

MONITORING_DELIVERY_DOMAIN: Literal["monitoring-delivery-v1"] = "monitoring-delivery-v1"
WEBHOOK_TRANSPORT_ID: Literal["webhook-v1"] = "webhook-v1"
WEBHOOK_PAYLOAD_CONTRACT: Literal["monitoring_delivery_webhook_payload_v1"] = (
    "monitoring_delivery_webhook_payload_v1"
)
MAX_WEBHOOK_PAYLOAD_BYTES = 512 * 1024
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_ZERO_HASH = "0" * 64
_SKIP_HASH_CONTEXT_KEY = "skip_derived_hash_validation"


class DeliveryStatus(StrEnum):
    """Latest-state classifications of one delivery ledger entry."""

    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    NOOP = "NOOP"


class DeliveryFailureCode(StrEnum):
    """Safe, secret-free machine-readable failure classifications."""

    HTTP_RETRYABLE_STATUS = "HTTP_RETRYABLE_STATUS"
    HTTP_PERMANENT_STATUS = "HTTP_PERMANENT_STATUS"
    HTTP_REDIRECT_NOT_FOLLOWED = "HTTP_REDIRECT_NOT_FOLLOWED"
    CONNECT_FAILED_PRE_DISPATCH = "CONNECT_FAILED_PRE_DISPATCH"
    TIMEOUT_AFTER_DISPATCH = "TIMEOUT_AFTER_DISPATCH"
    CONNECTION_LOST_AFTER_DISPATCH = "CONNECTION_LOST_AFTER_DISPATCH"
    RESPONSE_BYTES_EXCEEDED = "RESPONSE_BYTES_EXCEEDED"
    RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"


ATTEMPT_CLASSIFICATIONS = (
    DeliveryStatus.DELIVERED,
    DeliveryStatus.RETRYABLE_FAILURE,
    DeliveryStatus.AMBIGUOUS,
    DeliveryStatus.PERMANENT_FAILURE,
)


class _DeliveryContract(BaseModel):
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


def _normalize_datetime_optional(value: datetime | None) -> datetime | None:
    return None if value is None else normalize_utc(value)


class DeliverySettingsV1(BaseModel):
    """Explicit, non-secret policy for one delivery destination.

    This is an input contract, not a persisted ledger artifact: it carries the
    stable destination identity and the bounded retry policy.  Secret
    references are resolved only in process memory by the caller; no
    credential value may ever appear here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["monitoring_delivery_settings_v1"] = "monitoring_delivery_settings_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    destination_id: StrictStr = Field(min_length=1, max_length=128)
    transport: Literal["webhook-v1"] = WEBHOOK_TRANSPORT_ID
    max_attempts: StrictInt = Field(default=5, ge=1, le=20)
    timeout_seconds: StrictFloat = Field(default=10.0, gt=0, le=60)
    backoff_base_seconds: StrictInt = Field(default=60, ge=0, le=3600)
    backoff_cap_seconds: StrictInt = Field(default=3600, ge=1, le=86400)
    max_response_bytes: StrictInt = Field(default=65536, ge=1024, le=1048576)
    receiver_idempotency_declared: StrictBool = False

    @model_validator(mode="after")
    def _validate_settings(self) -> Self:
        if not self.destination_id.strip():
            raise ValueError("destination_id must not be blank")
        if self.backoff_cap_seconds < self.backoff_base_seconds:
            raise ValueError("backoff_cap_seconds must not be below backoff_base_seconds")
        return self


def delivery_identity(
    *,
    runner_id: str,
    activation_id: str,
    alert_batch_id: str,
    destination_id: str,
    payload_contract: str = WEBHOOK_PAYLOAD_CONTRACT,
) -> str:
    """Derive the deterministic delivery identity from non-secret inputs.

    A changed logical destination (new ``destination_id``) or payload contract
    version therefore produces a new delivery identity instead of silently
    inheriting a prior destination's ``DELIVERED`` state.
    """

    from turtle_value_engine.monitoring.canonical import canonical_sha256

    return canonical_sha256(
        {
            "domain": "tve-monitoring-delivery-v1",
            "runner_id": runner_id,
            "activation_id": activation_id,
            "alert_batch_id": alert_batch_id,
            "destination_id": destination_id,
            "payload_contract": payload_contract,
        }
    )


class MonitoringWebhookAlertV1(BaseModel):
    """One bounded, factual, secret-free alert projection inside the body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: StrictStr = Field(pattern=_HASH_PATTERN)
    kind: StrictStr = Field(min_length=1, max_length=64)
    listing_id: StrictStr | None = Field(default=None, max_length=32)
    impact: StrictStr | None = Field(default=None, max_length=64)
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    message: StrictStr = Field(min_length=1, max_length=512)


class MonitoringWebhookPayloadV1(_DeliveryContract):
    """Canonical bounded JSON request body for the generic webhook transport.

    The body is derived only from the validated alert batch plus non-secret
    delivery metadata.  It is fully deterministic: no wall-clock timestamp is
    included, so the same outbox always produces byte-identical request bytes
    and the same ``payload_sha256``.
    """

    contract: Literal["monitoring_delivery_webhook_payload_v1"] = (
        "monitoring_delivery_webhook_payload_v1"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    delivery_id: StrictStr = Field(pattern=_HASH_PATTERN)
    destination_id: StrictStr = Field(min_length=1, max_length=128)
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    as_of: datetime
    d1_status: StrictStr = Field(min_length=1, max_length=64)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_count: StrictInt = Field(ge=0, le=1024)
    alerts: list[MonitoringWebhookAlertV1] = Field(default_factory=list, max_length=1024)

    _normalize_as_of = field_validator("as_of")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_payload(self) -> Self:
        if self.alert_count != len(self.alerts):
            raise ValueError("payload alert_count must match the alerts list")
        return self


class MonitoringDeliveryIntentV1(_DeliveryContract):
    """Immutable delivery intent persisted before any outbound I/O.

    The intent binds the exact terminal D2A/D1 source identities and hashes,
    the deterministic delivery identity, the canonical payload hash and the
    bounded retry policy under which attempts are scheduled.  Recovery and
    repair read it back instead of trusting any mutable state.
    """

    contract: Literal["monitoring_delivery_intent_v1"] = "monitoring_delivery_intent_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"

    _ZERO_FILL_FIELDS: ClassVar[tuple[str, ...]] = ("delivery_id", "content_sha256")

    delivery_id: StrictStr = Field(pattern=_HASH_PATTERN)
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    activation_id: StrictStr = Field(pattern=_HASH_PATTERN)
    cycle_id: StrictStr = Field(pattern=_HASH_PATTERN)
    d1_status: StrictStr = Field(min_length=1, max_length=64)
    result_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    alert_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    destination_id: StrictStr = Field(min_length=1, max_length=128)
    transport: Literal["webhook-v1"] = WEBHOOK_TRANSPORT_ID
    payload_contract: Literal["monitoring_delivery_webhook_payload_v1"] = (
        WEBHOOK_PAYLOAD_CONTRACT
    )
    payload_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    payload_bytes: StrictInt = Field(ge=2, le=MAX_WEBHOOK_PAYLOAD_BYTES)
    empty_outbox: StrictBool
    max_attempts: StrictInt = Field(ge=1, le=20)
    timeout_seconds: StrictFloat = Field(gt=0, le=60)
    backoff_base_seconds: StrictInt = Field(ge=0, le=3600)
    backoff_cap_seconds: StrictInt = Field(ge=1, le=86400)
    receiver_idempotency_declared: StrictBool
    created_at: datetime
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_created_at = field_validator("created_at")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_intent(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected_delivery = delivery_identity(
                runner_id=self.runner_id,
                activation_id=self.activation_id,
                alert_batch_id=self.alert_batch_id,
                destination_id=self.destination_id,
                payload_contract=self.payload_contract,
            )
            if self.delivery_id != expected_delivery:
                raise ValueError("delivery_id does not match its non-secret source bindings")
            if self.backoff_cap_seconds < self.backoff_base_seconds:
                raise ValueError("backoff_cap_seconds must not be below backoff_base_seconds")
            expected_content = canonical_sha256(
                self.canonical_payload(exclude={"content_sha256"})
            )
            if self.content_sha256 != expected_content:
                raise ValueError("delivery intent content_sha256 does not match content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(dict(values))
        delivery_id = delivery_identity(
            runner_id=coerced.runner_id,
            activation_id=coerced.activation_id,
            alert_batch_id=coerced.alert_batch_id,
            destination_id=coerced.destination_id,
            payload_contract=coerced.payload_contract,
        )
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(
            payload
            | {
                "delivery_id": delivery_id,
                "content_sha256": canonical_sha256(payload | {"delivery_id": delivery_id}),
            }
        )

    def semantic_payload(self) -> dict:
        """Content identity excluding the creation timestamp.

        A resumed delivery rebuilds the intent from the same validated source
        artifacts; only ``created_at`` may legitimately differ, so identity
        conflicts are decided on every other field.
        """

        return self.canonical_payload(exclude={"created_at", "content_sha256"})


class MonitoringDeliveryAttemptV1(_DeliveryContract):
    """Immutable record of exactly one outbound HTTP exchange.

    The response body is persisted only as a bounded non-secret digest; raw
    untrusted response content is never stored.  Error text is a stable
    machine code so no endpoint URL, token or response content can leak
    through diagnostics.
    """

    contract: Literal["monitoring_delivery_attempt_v1"] = "monitoring_delivery_attempt_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    delivery_id: StrictStr = Field(pattern=_HASH_PATTERN)
    attempt_number: StrictInt = Field(ge=1, le=20)
    started_at: datetime
    finished_at: datetime
    classification: Literal[
        "DELIVERED", "RETRYABLE_FAILURE", "AMBIGUOUS", "PERMANENT_FAILURE"
    ]
    http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    response_body_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    error_code: DeliveryFailureCode | None = None
    retry_not_before: datetime | None = None
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_started_at = field_validator("started_at")(_normalize_datetime)
    _normalize_finished_at = field_validator("finished_at")(_normalize_datetime)
    _normalize_retry_not_before = field_validator("retry_not_before")(
        _normalize_datetime_optional
    )

    @model_validator(mode="after")
    def _validate_attempt(self, info: ValidationInfo) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("attempt finished_at cannot precede started_at")
        if self.classification == DeliveryStatus.DELIVERED and self.http_status is None:
            raise ValueError("delivered attempt requires an HTTP status")
        if self.http_status is None and self.error_code is None:
            raise ValueError("attempt without an HTTP status requires an error_code")
        if self.error_code is DeliveryFailureCode.RETRIES_EXHAUSTED:
            raise ValueError("RETRIES_EXHAUSTED is a state derivation, not an attempt code")
        if self.retry_not_before is not None and self.classification not in {
            DeliveryStatus.RETRYABLE_FAILURE,
            DeliveryStatus.AMBIGUOUS,
        }:
            raise ValueError("retry_not_before is only valid on retryable classifications")
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("delivery attempt content_sha256 does not match content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


class MonitoringDeliveryStateV1(_DeliveryContract):
    """Atomic latest state pointer for one delivery identity.

    The state is fully derived from the immutable intent plus the immutable
    attempt set, so a crash between an attempt write and this pointer's
    publication is repaired deterministically without repeating the request.
    """

    contract: Literal["monitoring_delivery_state_v1"] = "monitoring_delivery_state_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    delivery_id: StrictStr = Field(pattern=_HASH_PATTERN)
    status: DeliveryStatus
    terminal: StrictBool
    attempt_count: StrictInt = Field(ge=0, le=20)
    terminal_attempt_number: StrictInt | None = Field(default=None, ge=1, le=20)
    terminal_attempt_content_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    last_http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    last_error_code: DeliveryFailureCode | None = None
    next_attempt_not_before: datetime | None = None
    intent_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    updated_at: datetime
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_next_attempt_not_before = field_validator("next_attempt_not_before")(
        _normalize_datetime_optional
    )
    _normalize_updated_at = field_validator("updated_at")(_normalize_datetime)

    @model_validator(mode="after")
    def _validate_state(self, info: ValidationInfo) -> Self:
        if self.status is DeliveryStatus.NOOP:
            if not self.terminal or self.attempt_count != 0:
                raise ValueError("NOOP state is terminal with zero attempts")
        # ``AMBIGUOUS`` is terminal unless a receiver-declared idempotent retry
        # is explicitly scheduled; every other non-PENDING status is terminal.
        expected_terminal = self.status in _TERMINAL_STATUSES or (
            self.status is DeliveryStatus.AMBIGUOUS and self.next_attempt_not_before is None
        )
        if self.status is DeliveryStatus.PENDING and self.next_attempt_not_before is not None:
            raise ValueError("PENDING state cannot schedule a retry")
        if self.terminal != expected_terminal:
            raise ValueError("terminal flag must match the status classification")
        if self.attempt_count == 0 and self.terminal_attempt_number is not None:
            raise ValueError("zero attempts cannot carry a terminal attempt")
        if self.terminal_attempt_number is None and self.terminal_attempt_content_sha256:
            raise ValueError("terminal attempt hash requires a terminal attempt number")
        if self.attempt_count > 0 and self.last_http_status is None and (
            self.last_error_code is None
        ):
            raise ValueError("state with attempts requires a last status or error code")
        if _hash_checks_enabled(info):
            from turtle_value_engine.monitoring.canonical import canonical_sha256

            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("delivery state content_sha256 does not match content")
        return self

    @classmethod
    def build(cls, **values: object) -> Self:
        from turtle_value_engine.monitoring.canonical import canonical_sha256

        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


_TERMINAL_STATUSES = frozenset(
    {
        DeliveryStatus.DELIVERED,
        DeliveryStatus.PERMANENT_FAILURE,
        DeliveryStatus.NOOP,
    }
)


__all__ = [
    "ATTEMPT_CLASSIFICATIONS",
    "DeliveryFailureCode",
    "DeliverySettingsV1",
    "DeliveryStatus",
    "MAX_WEBHOOK_PAYLOAD_BYTES",
    "MONITORING_DELIVERY_DOMAIN",
    "MonitoringDeliveryAttemptV1",
    "MonitoringDeliveryIntentV1",
    "MonitoringDeliveryStateV1",
    "MonitoringWebhookAlertV1",
    "MonitoringWebhookPayloadV1",
    "WEBHOOK_PAYLOAD_CONTRACT",
    "WEBHOOK_TRANSPORT_ID",
    "delivery_identity",
]
