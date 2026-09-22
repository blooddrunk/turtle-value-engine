"""Durable Phase 6-D2B notification-delivery service.

One invocation loads and re-validates the exact terminal Phase 6-D2A runner
receipt plus the Phase 6-D1 result/alert-outbox pair it binds, persists an
immutable delivery intent **before** any outbound I/O, then performs bounded
attempts through one injected transport, persisting every attempt immutably
and the derived latest state atomically.  It never invokes the D1 boundary,
a provider, a model or re-analysis: delivery failure may only fail delivery.

The service never claims exactly-once delivery for an arbitrary HTTP
receiver.  The deterministic idempotency key is evidence a receiver may use;
uncertainty after dispatch is recorded as ``AMBIGUOUS`` and is never
automatically resent unless the configuration explicitly declares the
receiver enforces idempotent deduplication on that key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from turtle_value_engine.monitoring.canonical import canonical_sha256, normalize_utc
from turtle_value_engine.monitoring_cycle.contracts import (
    MonitoringAlertBatchV1,
    MonitoringCycleResultV1,
)
from turtle_value_engine.monitoring_cycle.store import MonitoringCycleStore
from turtle_value_engine.monitoring_runner.contracts import RunnerReceiptV1
from turtle_value_engine.monitoring_runner.store import RunnerStore

from .contracts import (
    MAX_WEBHOOK_PAYLOAD_BYTES,
    DeliveryFailureCode,
    DeliverySettingsV1,
    DeliveryStatus,
    MonitoringDeliveryAttemptV1,
    MonitoringDeliveryIntentV1,
    MonitoringDeliveryStateV1,
    MonitoringWebhookAlertV1,
    MonitoringWebhookPayloadV1,
    delivery_identity,
)
from .store import DeliveryLedgerError, DeliveryLedgerStore
from .transport import WebhookRequest, WebhookTransport

DeliveryClock = Callable[[], datetime]
EndpointResolver = Callable[[], str]
AuthResolver = Callable[[], str | None]


class MonitoringDeliveryError(ValueError):
    """Base class for D2B delivery failures (fail-closed)."""


class DeliveryNetworkDeniedError(MonitoringDeliveryError):
    """Raised when delivery was invoked without the explicit network opt-in."""


class DeliveryDisabledError(MonitoringDeliveryError):
    """Raised when delivery is not enabled for this destination."""


class DeliverySourceError(MonitoringDeliveryError):
    """Raised when the terminal D2A/D1 source artifacts fail validation."""


class DeliveryLedgerConflictError(MonitoringDeliveryError):
    """Raised when persisted delivery state is ambiguous, foreign or conflicting."""


class DeliveryPayloadError(MonitoringDeliveryError):
    """Raised when the canonical webhook payload cannot be built."""


class DeliveryEndpointUnresolvedError(MonitoringDeliveryError):
    """Raised when the secret endpoint reference resolves to nothing.

    The message names only the missing reference, never any resolved value.
    """


@dataclass(frozen=True, slots=True)
class DeliveryRunOutcome:
    """Terminal projection of one delivery invocation."""

    delivery_id: str
    status: DeliveryStatus
    intent: MonitoringDeliveryIntentV1
    state: MonitoringDeliveryStateV1
    http_requests: int
    reused: bool
    message: str


def build_webhook_payload(
    *,
    settings: DeliverySettingsV1,
    receipt: RunnerReceiptV1,
    result: MonitoringCycleResultV1,
    alerts: MonitoringAlertBatchV1,
) -> MonitoringWebhookPayloadV1:
    """Build the canonical bounded JSON body from validated sources only."""

    delivery_id = delivery_identity(
        runner_id=receipt.runner_id,
        activation_id=receipt.activation_id,
        alert_batch_id=alerts.alert_batch_id,
        destination_id=settings.destination_id,
    )
    payload = MonitoringWebhookPayloadV1(
        delivery_id=delivery_id,
        destination_id=settings.destination_id,
        runner_id=receipt.runner_id,
        activation_id=receipt.activation_id,
        cycle_id=receipt.cycle_id,
        watchlist_id=alerts.watchlist_id,
        as_of=normalize_utc(result.as_of),
        d1_status=receipt.d1_status,
        alert_batch_id=alerts.alert_batch_id,
        alert_batch_content_sha256=alerts.content_sha256,
        alert_count=len(alerts.alerts),
        alerts=[
            MonitoringWebhookAlertV1(
                alert_id=alert.alert_id,
                kind=alert.kind.value,
                listing_id=alert.listing_id,
                impact=None if alert.impact is None else alert.impact.value,
                reason_code=alert.reason_code,
                message=alert.message,
            )
            for alert in alerts.alerts
        ],
    )
    if len(payload.canonical_bytes()) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise DeliveryPayloadError(
            "DELIVERY_PAYLOAD_TOO_LARGE: canonical webhook body exceeds the bounded size"
        )
    return payload


def backoff_seconds(intent: MonitoringDeliveryIntentV1, attempt_number: int) -> int:
    """Bounded exponential backoff for the attempt that just finished."""

    return max(
        0,
        min(
            intent.backoff_cap_seconds,
            intent.backoff_base_seconds * (2 ** max(0, attempt_number - 1)),
        ),
    )


def derive_delivery_state(
    intent: MonitoringDeliveryIntentV1,
    attempts: list[MonitoringDeliveryAttemptV1],
) -> MonitoringDeliveryStateV1:
    """Derive the latest state purely from immutable artifacts.

    This function is the single source of truth for the published pointer, so
    normal publication and crash repair produce byte-identical state files
    and a pointer-write crash is always repairable without a new request.
    """

    if intent.empty_outbox:
        return MonitoringDeliveryStateV1.build(
            delivery_id=intent.delivery_id,
            status=DeliveryStatus.NOOP,
            terminal=True,
            attempt_count=0,
            intent_content_sha256=intent.content_sha256,
            updated_at=intent.created_at,
        )
    if not attempts:
        return MonitoringDeliveryStateV1.build(
            delivery_id=intent.delivery_id,
            status=DeliveryStatus.PENDING,
            terminal=False,
            attempt_count=0,
            intent_content_sha256=intent.content_sha256,
            updated_at=intent.created_at,
        )
    last = attempts[-1]
    if last.classification == DeliveryStatus.RETRYABLE_FAILURE and (
        len(attempts) >= intent.max_attempts
    ):
        return MonitoringDeliveryStateV1.build(
            delivery_id=intent.delivery_id,
            status=DeliveryStatus.PERMANENT_FAILURE,
            terminal=True,
            attempt_count=len(attempts),
            terminal_attempt_number=last.attempt_number,
            terminal_attempt_content_sha256=last.content_sha256,
            last_http_status=last.http_status,
            last_error_code=DeliveryFailureCode.RETRIES_EXHAUSTED,
            next_attempt_not_before=None,
            intent_content_sha256=intent.content_sha256,
            updated_at=last.finished_at,
        )
    if last.classification == DeliveryStatus.DELIVERED:
        status = DeliveryStatus.DELIVERED
    elif last.classification == DeliveryStatus.PERMANENT_FAILURE:
        status = DeliveryStatus.PERMANENT_FAILURE
    elif last.classification == DeliveryStatus.AMBIGUOUS:
        status = DeliveryStatus.AMBIGUOUS
    else:
        status = DeliveryStatus.RETRYABLE_FAILURE
    next_not_before = last.retry_not_before
    terminal = status in {
        DeliveryStatus.DELIVERED,
        DeliveryStatus.PERMANENT_FAILURE,
    } or (status is DeliveryStatus.AMBIGUOUS and next_not_before is None)
    return MonitoringDeliveryStateV1.build(
        delivery_id=intent.delivery_id,
        status=status,
        terminal=terminal,
        attempt_count=len(attempts),
        terminal_attempt_number=last.attempt_number if terminal else None,
        terminal_attempt_content_sha256=last.content_sha256 if terminal else None,
        last_http_status=last.http_status,
        last_error_code=last.error_code,
        next_attempt_not_before=None if terminal else next_not_before,
        intent_content_sha256=intent.content_sha256,
        updated_at=last.finished_at,
    )


def _terminal_message(state: MonitoringDeliveryStateV1) -> str:
    if state.status is DeliveryStatus.DELIVERED:
        return "notification delivered and acknowledged by a 2xx webhook response"
    if state.status is DeliveryStatus.NOOP:
        return "alert outbox was empty; no notification was required or sent"
    if state.status is DeliveryStatus.AMBIGUOUS:
        return (
            "post-dispatch uncertainty recorded as AMBIGUOUS; automatic resend is "
            "forbidden unless receiver idempotency is declared"
        )
    if state.status is DeliveryStatus.PERMANENT_FAILURE:
        if state.last_error_code == DeliveryFailureCode.RETRIES_EXHAUSTED:
            return "bounded retry budget exhausted; no further automatic attempts"
        return "receiver rejected the delivery with a non-retryable response"
    if state.next_attempt_not_before is not None:
        return "retryable delivery failure recorded; a later bounded retry is scheduled"
    return "delivery is pending its first outbound attempt"


class MonitoringDeliveryService:
    """One durable delivery invocation over the validated terminal outbox."""

    def __init__(
        self,
        *,
        settings: DeliverySettingsV1,
        ledger: DeliveryLedgerStore,
        runner_store: RunnerStore,
        cycle_store: MonitoringCycleStore,
        transport: WebhookTransport,
        endpoint_resolver: EndpointResolver,
        clock: DeliveryClock,
        runner_id: str,
        network_allowed: bool,
        auth_resolver: AuthResolver | None = None,
        enabled: bool = True,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.runner_store = runner_store
        self.cycle_store = cycle_store
        self.transport = transport
        self.endpoint_resolver = endpoint_resolver
        self.auth_resolver = auth_resolver or (lambda: None)
        self.clock = clock
        self.runner_id = runner_id
        self.network_allowed = network_allowed
        self.enabled = enabled

    # -- source binding -------------------------------------------------

    def _load_receipt(self, activation_id: str | None) -> RunnerReceiptV1:
        try:
            if activation_id is not None:
                receipt = self.runner_store.load_receipt(activation_id)
                if receipt is None:
                    raise DeliverySourceError(
                        "DELIVERY_SOURCE_MISSING: runner receipt not found for the "
                        "requested activation"
                    )
            else:
                latest = self.runner_store.load_latest(self.runner_id)
                if latest is None:
                    raise DeliverySourceError(
                        "DELIVERY_SOURCE_MISSING: no terminal runner activation exists "
                        "for this runner identity"
                    )
                receipt = self.runner_store.load_receipt(latest.activation_id)
                if receipt is None or receipt.content_sha256 != latest.receipt_content_sha256:
                    raise DeliverySourceError(
                        "DELIVERY_SOURCE_CONFLICT: runner latest pointer does not bind a "
                        "valid receipt"
                    )
        except DeliverySourceError:
            raise
        except Exception as exc:
            raise DeliverySourceError(
                f"DELIVERY_SOURCE_CORRUPT: cannot validate the runner receipt: {exc}"
            ) from exc
        if receipt.runner_id != self.runner_id:
            raise DeliverySourceError(
                "DELIVERY_SOURCE_CONFLICT: runner receipt belongs to another runner identity"
            )
        if receipt.classification != "CYCLE_TERMINAL":
            raise DeliverySourceError(
                "DELIVERY_SOURCE_CONFLICT: only a terminal runner receipt is deliverable"
            )
        return receipt

    def _load_terminal_pair(
        self, receipt: RunnerReceiptV1
    ) -> tuple[MonitoringCycleResultV1, MonitoringAlertBatchV1]:
        try:
            terminal = self.cycle_store.load_terminal(receipt.cycle_id, repair_pointer=False)
        except Exception as exc:
            raise DeliverySourceError(
                f"DELIVERY_SOURCE_CORRUPT: cannot validate D1 terminal artifacts: {exc}"
            ) from exc
        if terminal is None:
            raise DeliverySourceError(
                "DELIVERY_SOURCE_MISSING: the D1 terminal result/outbox pair is missing"
            )
        result, alerts = terminal
        mismatches: list[str] = []
        if result.cycle_id != receipt.cycle_id:
            mismatches.append("cycle identity")
        if result.content_sha256 != receipt.result_content_sha256:
            mismatches.append("result hash")
        if alerts.alert_batch_id != receipt.alert_batch_id:
            mismatches.append("alert batch identity")
        if alerts.content_sha256 != receipt.alert_batch_content_sha256:
            mismatches.append("alert batch hash")
        if result.alert_batch_id != alerts.alert_batch_id:
            mismatches.append("result-to-outbox binding")
        if result.alert_batch_content_sha256 != alerts.content_sha256:
            mismatches.append("result-to-outbox hash binding")
        if mismatches:
            raise DeliverySourceError(
                "DELIVERY_SOURCE_MISMATCH: "
                + ", ".join(mismatches)
                + " differ from the terminal runner receipt"
            )
        return result, alerts

    # -- intent ---------------------------------------------------------

    def _build_intent(
        self,
        *,
        receipt: RunnerReceiptV1,
        result: MonitoringCycleResultV1,
        alerts: MonitoringAlertBatchV1,
        payload: MonitoringWebhookPayloadV1,
        created_at: datetime,
    ) -> MonitoringDeliveryIntentV1:
        return MonitoringDeliveryIntentV1.build(
            runner_id=receipt.runner_id,
            activation_id=receipt.activation_id,
            cycle_id=receipt.cycle_id,
            d1_status=receipt.d1_status,
            result_content_sha256=result.content_sha256,
            alert_batch_id=alerts.alert_batch_id,
            alert_batch_content_sha256=alerts.content_sha256,
            destination_id=self.settings.destination_id,
            payload_sha256=canonical_sha256(payload.canonical_payload()),
            payload_bytes=len(payload.canonical_bytes()),
            empty_outbox=len(alerts.alerts) == 0,
            max_attempts=self.settings.max_attempts,
            timeout_seconds=self.settings.timeout_seconds,
            backoff_base_seconds=self.settings.backoff_base_seconds,
            backoff_cap_seconds=self.settings.backoff_cap_seconds,
            receiver_idempotency_declared=self.settings.receiver_idempotency_declared,
            created_at=normalize_utc(created_at),
        )

    def _load_or_create_intent(
        self,
        receipt: RunnerReceiptV1,
        result: MonitoringCycleResultV1,
        alerts: MonitoringAlertBatchV1,
    ) -> tuple[MonitoringDeliveryIntentV1, bool]:
        """Persist the immutable intent before any outbound I/O."""

        payload = build_webhook_payload(
            settings=self.settings, receipt=receipt, result=result, alerts=alerts
        )
        fresh = self._build_intent(
            receipt=receipt,
            result=result,
            alerts=alerts,
            payload=payload,
            created_at=self.clock(),
        )
        if not self.ledger.intent_exists(fresh.delivery_id):
            self.ledger.save_intent(fresh)
            return fresh, True
        existing = self.ledger.load_intent(fresh.delivery_id)
        if existing.semantic_payload() != fresh.semantic_payload():
            raise DeliveryLedgerConflictError(
                "DELIVERY_LEDGER_CONFLICT: an intent with this delivery identity already "
                "exists with different content"
            )
        return existing, False

    # -- state ----------------------------------------------------------

    def _validate_or_repair_state(
        self,
        intent: MonitoringDeliveryIntentV1,
        derived: MonitoringDeliveryStateV1,
    ) -> None:
        """Fail closed on impossible published state; repair a stale one."""

        published = self.ledger.load_state(intent.delivery_id)
        if published is None or published == derived:
            self.ledger.publish_state(derived)
            return
        behind = published.attempt_count < derived.attempt_count or (
            published.attempt_count == derived.attempt_count
            and published.status is DeliveryStatus.PENDING
            and derived.status is not DeliveryStatus.PENDING
        )
        if not behind:
            raise DeliveryLedgerConflictError(
                "DELIVERY_LEDGER_CONFLICT: published delivery state does not match its "
                "immutable intent/attempt artifacts"
            )
        self.ledger.publish_state(derived)

    # -- delivery -------------------------------------------------------

    def deliver(self, activation_id: str | None = None) -> DeliveryRunOutcome:
        try:
            return self._deliver(activation_id)
        except DeliveryLedgerConflictError:
            raise
        except DeliveryLedgerError as exc:
            raise DeliveryLedgerConflictError(
                f"DELIVERY_LEDGER_CORRUPT: {exc}"
            ) from exc

    def _deliver(self, activation_id: str | None) -> DeliveryRunOutcome:
        if not self.enabled:
            raise DeliveryDisabledError(
                "DELIVERY_DISABLED: notification delivery is not enabled for this "
                "destination"
            )
        if not self.network_allowed:
            raise DeliveryNetworkDeniedError(
                "DELIVERY_NETWORK_DENIED: delivery requires an explicit network opt-in; "
                "no outbound request was attempted"
            )
        receipt = self._load_receipt(activation_id)
        result, alerts = self._load_terminal_pair(receipt)
        intent, created = self._load_or_create_intent(receipt, result, alerts)

        attempts = self.ledger.list_attempts(intent.delivery_id)
        state = derive_delivery_state(intent, attempts)
        self._validate_or_repair_state(intent, state)
        http_requests = 0

        while not state.terminal:
            if state.next_attempt_not_before is not None and (
                normalize_utc(self.clock()) < state.next_attempt_not_before
            ):
                break
            self._perform_attempt(intent, attempt_number=len(attempts) + 1)
            http_requests += 1
            attempts = self.ledger.list_attempts(intent.delivery_id)
            state = derive_delivery_state(intent, attempts)
            self.ledger.publish_state(state)

        return DeliveryRunOutcome(
            delivery_id=intent.delivery_id,
            status=state.status,
            intent=intent,
            state=state,
            http_requests=http_requests,
            reused=not created and http_requests == 0,
            message=_terminal_message(state),
        )

    def _perform_attempt(
        self, intent: MonitoringDeliveryIntentV1, *, attempt_number: int
    ) -> MonitoringDeliveryAttemptV1:
        started_at = normalize_utc(self.clock())
        payload = self._payload_for_intent(intent)
        endpoint = self.endpoint_resolver()
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise DeliveryEndpointUnresolvedError(
                "DELIVERY_ENDPOINT_UNRESOLVED: the configured secret endpoint reference "
                "resolved to nothing; no outbound request was attempted"
            )
        auth_bearer = self.auth_resolver()
        outcome = self.transport.send(
            endpoint=endpoint,
            auth_bearer=auth_bearer,
            request=WebhookRequest(
                body=payload.canonical_bytes(),
                idempotency_key=intent.delivery_id,
                timeout_seconds=float(intent.timeout_seconds),
                max_response_bytes=self.settings.max_response_bytes,
            ),
        )
        finished_at = normalize_utc(self.clock())
        retry_not_before: datetime | None = None
        if outcome.classification == DeliveryStatus.RETRYABLE_FAILURE or (
            outcome.classification == DeliveryStatus.AMBIGUOUS
            and intent.receiver_idempotency_declared
        ):
            retry_not_before = finished_at + timedelta(
                seconds=backoff_seconds(intent, attempt_number)
            )
        attempt = MonitoringDeliveryAttemptV1.build(
            delivery_id=intent.delivery_id,
            attempt_number=attempt_number,
            started_at=started_at,
            finished_at=finished_at,
            classification=outcome.classification.value,
            http_status=outcome.http_status,
            response_body_sha256=outcome.response_body_sha256,
            error_code=None if outcome.error_code is None else outcome.error_code.value,
            retry_not_before=retry_not_before,
        )
        self.ledger.save_attempt(attempt)
        return attempt

    def _payload_for_intent(
        self, intent: MonitoringDeliveryIntentV1
    ) -> MonitoringWebhookPayloadV1:
        """Re-validate the source and prove it still matches the intent."""

        receipt = self._load_receipt(intent.activation_id)
        result, alerts = self._load_terminal_pair(receipt)
        payload = build_webhook_payload(
            settings=self.settings, receipt=receipt, result=result, alerts=alerts
        )
        if (
            canonical_sha256(payload.canonical_payload()) != intent.payload_sha256
            or len(payload.canonical_bytes()) != intent.payload_bytes
        ):
            raise DeliveryLedgerConflictError(
                "DELIVERY_LEDGER_CONFLICT: the validated outbox no longer produces the "
                "intent's canonical payload"
            )
        return payload


def delivery_status_projection(
    ledger: DeliveryLedgerStore,
    *,
    delivery_id: str | None = None,
    activation_id: str | None = None,
) -> dict[str, object]:
    """Read a bounded, secret-free ledger projection.

    The projection reports the state derived from immutable artifacts (with a
    pointer-published flag) instead of trusting the pointer alone, and never
    resolves or contains any secret endpoint or token material.
    """

    ids = [delivery_id] if delivery_id is not None else ledger.list_delivery_ids()
    if delivery_id is not None and not ledger.intent_exists(delivery_id):
        raise MonitoringDeliveryError(f"delivery {delivery_id} was not found in the ledger")
    deliveries: list[dict[str, object]] = []
    for candidate in ids:
        intent = ledger.load_intent(candidate)
        if activation_id is not None and intent.activation_id != activation_id:
            continue
        attempts = ledger.list_attempts(candidate)
        derived = derive_delivery_state(intent, attempts)
        deliveries.append(
            {
                "delivery_id": intent.delivery_id,
                "runner_id": intent.runner_id,
                "activation_id": intent.activation_id,
                "cycle_id": intent.cycle_id,
                "alert_batch_id": intent.alert_batch_id,
                "destination_id": intent.destination_id,
                "transport": intent.transport,
                "payload_contract": intent.payload_contract,
                "payload_sha256": intent.payload_sha256,
                "empty_outbox": intent.empty_outbox,
                "created_at": intent.created_at.isoformat(),
                "state": derived.model_dump(mode="json"),
                "pointer_published": ledger.state_path(candidate).exists(),
                "attempts": [
                    {
                        "attempt_number": attempt.attempt_number,
                        "started_at": attempt.started_at.isoformat(),
                        "finished_at": attempt.finished_at.isoformat(),
                        "classification": attempt.classification,
                        "http_status": attempt.http_status,
                        "response_body_sha256": attempt.response_body_sha256,
                        "error_code": None
                        if attempt.error_code is None
                        else attempt.error_code.value,
                        "retry_not_before": None
                        if attempt.retry_not_before is None
                        else attempt.retry_not_before.isoformat(),
                    }
                    for attempt in attempts
                ],
            }
        )
    return {"delivery_root": str(ledger.root), "deliveries": deliveries}


__all__ = [
    "AuthResolver",
    "DeliveryClock",
    "DeliveryDisabledError",
    "DeliveryEndpointUnresolvedError",
    "DeliveryLedgerConflictError",
    "DeliveryNetworkDeniedError",
    "DeliveryPayloadError",
    "DeliveryRunOutcome",
    "DeliverySourceError",
    "EndpointResolver",
    "MonitoringDeliveryService",
    "backoff_seconds",
    "build_webhook_payload",
    "delivery_status_projection",
    "derive_delivery_state",
]
