"""Automatic Phase 6-D2B notification-delivery and ledger matrix.

Every test drives the delivery boundary through its public service/CLI
surfaces over genuine terminal Phase 6-D1/D2A artifacts produced by injected
fakes, a loopback HTTP receiver or an injected transport.  No public
Internet, live provider, model or real sleep is used anywhere in this
module.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from turtle_value_engine.monitoring import (
    MonitoringEventBatchV1,
    MonitoringWorkspace,
    WatchlistSpecV1,
    build_event_batch,
)
from turtle_value_engine.monitoring_cycle import (
    CycleAcquisitionOutcome,
    MonitoringCycleRunner,
    MonitoringCycleSpecV1,
    MonitoringCycleStore,
    MonitoringExecutionCatalogV1,
)
from turtle_value_engine.monitoring_delivery import (
    DeliveryDisabledError,
    DeliveryEndpointUnresolvedError,
    DeliveryLedgerConflictError,
    DeliveryLedgerError,
    DeliveryLedgerStore,
    DeliveryLockBusyError,
    DeliveryLockError,
    DeliveryNetworkDeniedError,
    DeliverySettingsV1,
    DeliverySourceError,
    MonitoringDeliveryAttemptV1,
    MonitoringDeliveryIntentV1,
    MonitoringDeliveryService,
    MonitoringDeliveryStateV1,
    MonitoringDispatchClaimV1,
    MonitoringWebhookPayloadV1,
    TransportOutcome,
    WebhookEndpointError,
    WebhookHttpTransport,
    WebhookRequest,
    backoff_seconds,
    build_webhook_payload,
    delivery_identity,
    delivery_single_flight,
    delivery_status_projection,
    derive_delivery_state,
)
from turtle_value_engine.monitoring_execution import ReanalysisJobStore
from turtle_value_engine.monitoring_runner import RunnerReceiptV1, RunnerStore

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 8, tzinfo=UTC)
RUNNER_ID = "turtle-test"
ACTIVATION_ID = "ab" * 32
URL_SENTINEL = "webhook-path-secret-sentinel-7f31"
TOKEN_SENTINEL = "webhook-bearer-secret-sentinel-9c2d"

# --- shared fixtures -----------------------------------------------------


class FakeClock:
    def __init__(self, start: datetime = AS_OF) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


class FakeAcquisition:
    def __init__(self, batch: MonitoringEventBatchV1) -> None:
        self.batch = batch
        self.calls = 0

    def acquire(self, request):
        self.calls += 1
        return CycleAcquisitionOutcome(batch=self.batch)


class CountingD1:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def run(self, spec, watchlist):
        self.calls += 1
        return self.delegate.run(spec, watchlist)


def _watchlist() -> WatchlistSpecV1:
    return WatchlistSpecV1.build(
        watchlist_id="phase6d2b-test",
        profile_id="strict-v1",
        entries=[{"listing_id": "SH600001", "company_display_name": "fixture"}],
    )


def _batch(event_type: str | None) -> MonitoringEventBatchV1:
    if event_type is None:
        return MonitoringEventBatchV1.build([])
    return build_event_batch(
        [
            {
                "event_id": "event-1",
                "listing_id": "SH600001",
                "event_type": event_type,
                "source_id": "fixture-source",
                "source_event_id": "fixture:event-1",
                "available_at": "2026-06-01T00:00:00Z",
            }
        ]
    )


def _spec(tmp_path: Path, watchlist: WatchlistSpecV1) -> MonitoringCycleSpecV1:
    return MonitoringCycleSpecV1.build(
        watchlist_id=watchlist.watchlist_id,
        watchlist_content_sha256=watchlist.content_sha256,
        as_of=AS_OF,
        acquisition_policy_id="monitoring-acquisition-v1",
        source_id="CNINFO",
        adapter_version="fixture-adapter-v1",
        published_from=date(2026, 6, 1),
        published_to=date(2026, 9, 8),
        acquisition_limit=30,
        network_allowed=False,
        offline_replay=True,
        monitoring_workspace_root=str(tmp_path / "monitoring"),
        reanalysis_job_root=str(tmp_path / "jobs"),
        cycle_store_root=str(tmp_path / "cycles"),
        execution_catalog=MonitoringExecutionCatalogV1.build(),
    )


def _terminal_stack(tmp_path: Path, *, event_type: str | None = "ANNUAL_REPORT"):
    """Produce genuine terminal D1 + D2A artifacts through public boundaries."""

    watchlist = _watchlist()
    spec = _spec(tmp_path, watchlist)
    acquisition = FakeAcquisition(_batch(event_type))
    cycles = MonitoringCycleStore(tmp_path / "cycles")
    d1 = CountingD1(
        MonitoringCycleRunner(
            MonitoringWorkspace(tmp_path / "monitoring"),
            ReanalysisJobStore(tmp_path / "jobs"),
            cycles,
            acquisition=acquisition,
            model_allowed=False,
        )
    )
    outcome = d1.run(spec, watchlist)
    runner_store = RunnerStore(tmp_path / "runner")
    receipt = RunnerReceiptV1.build(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        cycle_id=spec.cycle_id,
        d1_status=outcome.result.status.value,
        d1_failure_code=None
        if outcome.result.failure_code is None
        else outcome.result.failure_code.value,
        result_content_sha256=outcome.result.content_sha256,
        alert_batch_id=outcome.alert_batch.alert_batch_id,
        alert_batch_content_sha256=outcome.alert_batch.content_sha256,
        completed_at=AS_OF,
    )
    runner_store.publish_receipt(receipt)
    return SimpleNamespace(
        watchlist=watchlist,
        spec=spec,
        acquisition=acquisition,
        d1=d1,
        cycles=cycles,
        runner_store=runner_store,
        receipt=receipt,
        result=outcome.result,
        alerts=outcome.alert_batch,
    )


class FakeTransport:
    """Injected transport with scripted outcomes and full call accounting."""

    def __init__(self, script: list[TransportOutcome | Exception]) -> None:
        self.script = list(script)
        self.requests: list[WebhookRequest] = []
        self.endpoints: list[str] = []
        self.auths: list[str | None] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def send(self, *, endpoint, auth_bearer, request):
        self.endpoints.append(endpoint)
        self.auths.append(auth_bearer)
        self.requests.append(request)
        if not self.script:
            raise AssertionError("FakeTransport received an unexpected request")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _delivered(status: int = 200) -> TransportOutcome:
    from turtle_value_engine.monitoring_delivery import DeliveryStatus

    return TransportOutcome(DeliveryStatus.DELIVERED, status, "ff" * 32, None)


def _retryable(status: int = 503) -> TransportOutcome:
    from turtle_value_engine.monitoring_delivery import DeliveryFailureCode, DeliveryStatus

    return TransportOutcome(
        DeliveryStatus.RETRYABLE_FAILURE, status, None, DeliveryFailureCode.HTTP_RETRYABLE_STATUS
    )


def _permanent(status: int = 404) -> TransportOutcome:
    from turtle_value_engine.monitoring_delivery import DeliveryFailureCode, DeliveryStatus

    return TransportOutcome(
        DeliveryStatus.PERMANENT_FAILURE,
        status,
        None,
        DeliveryFailureCode.HTTP_PERMANENT_STATUS,
    )


def _ambiguous(code: str = "TIMEOUT_AFTER_DISPATCH") -> TransportOutcome:
    from turtle_value_engine.monitoring_delivery import DeliveryFailureCode, DeliveryStatus

    return TransportOutcome(
        DeliveryStatus.AMBIGUOUS, None, None, DeliveryFailureCode(code)
    )


def _settings(**overrides) -> DeliverySettingsV1:
    values = {
        "destination_id": "owner-primary",
        "max_attempts": 3,
        "timeout_seconds": 5.0,
        "backoff_base_seconds": 0,
        "backoff_cap_seconds": 3600,
        "receiver_idempotency_declared": False,
    }
    values.update(overrides)
    return DeliverySettingsV1(**values)


def _service(
    stack,
    transport,
    *,
    tmp_path: Path | None = None,
    settings: DeliverySettingsV1 | None = None,
    clock: FakeClock | None = None,
    network_allowed: bool = True,
    enabled: bool = True,
    failure_injector=None,
    endpoint: str = f"https://example.invalid/hook?key={URL_SENTINEL}",
    auth: str | None = TOKEN_SENTINEL,
    runner_id: str = RUNNER_ID,
):
    clock = clock or FakeClock()
    return MonitoringDeliveryService(
        settings=settings or _settings(),
        ledger=DeliveryLedgerStore(
            (tmp_path or Path(stack.runner_store.root).parent) / "delivery",
            failure_injector=failure_injector,
        ),
        runner_store=stack.runner_store,
        cycle_store=stack.cycles,
        transport=transport,
        endpoint_resolver=lambda: endpoint,
        auth_resolver=lambda: auth,
        clock=clock,
        runner_id=runner_id,
        network_allowed=network_allowed,
        enabled=enabled,
    )


class LoopbackWebhook:
    """Real in-process HTTP webhook receiver on 127.0.0.1."""

    def __init__(self, script: list[tuple[str, bytes]]) -> None:
        self.script = list(script)
        self.records: list[tuple[str, dict[str, str], bytes]] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.records.append((self.path, dict(self.headers), body))
                mode, payload = outer.script.pop(0) if outer.script else ("respond", b"{}")
                if mode == "close":
                    self.connection.close()
                    return
                if mode == "oversize":
                    blob = b"x" * 8192
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(blob)))
                    self.end_headers()
                    self.wfile.write(blob)
                    return
                status = int(mode)
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):  # noqa: A002 - http.server API
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.url = f"http://127.0.0.1:{port}/hook?key={URL_SENTINEL}"

    @property
    def requests(self) -> int:
        return len(self.records)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def loopback_factory():
    servers: list[LoopbackWebhook] = []

    def _make(script):
        server = LoopbackWebhook(script)
        servers.append(server)
        return server

    yield _make
    for server in servers:
        server.close()


def _all_ledger_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --- schema drift --------------------------------------------------------


def test_delivery_schema_snapshots_are_stable():
    models = (
        ("monitoring-delivery-settings.schema.json", DeliverySettingsV1),
        ("monitoring-delivery-intent.schema.json", MonitoringDeliveryIntentV1),
        ("monitoring-delivery-attempt.schema.json", MonitoringDeliveryAttemptV1),
        ("monitoring-delivery-state.schema.json", MonitoringDeliveryStateV1),
        ("monitoring-delivery-dispatch-claim.schema.json", MonitoringDispatchClaimV1),
        ("monitoring-delivery-webhook-payload.schema.json", MonitoringWebhookPayloadV1),
    )
    for filename, model in models:
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert model.model_json_schema() == checked_in


def test_delivery_identity_binds_destination_and_payload_contract():
    base = dict(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id="cd" * 32,
    )
    first = delivery_identity(destination_id="owner-primary", **base)
    assert first == delivery_identity(destination_id="owner-primary", **base)
    assert first != delivery_identity(destination_id="owner-backup", **base)
    assert first != delivery_identity(
        destination_id="owner-primary", payload_contract="future-payload-v2", **base
    )


# --- source binding ------------------------------------------------------


def test_alert_batch_hash_mismatch_fails_before_any_transport_call(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([])
    service = _service(stack, transport, tmp_path=tmp_path)
    path = stack.cycles.alert_batch_path(stack.alerts.alert_batch_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["watchlist_id"] = "tampered"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with pytest.raises(DeliverySourceError, match="MISMATCH|CORRUPT"):
        service.deliver()
    assert transport.calls == 0
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls
    assert not (Path(stack.runner_store.root).parent / "delivery").exists()


def test_missing_d1_terminal_pair_fails_before_transport(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([])
    stack.cycles.result_path(stack.spec.cycle_id).unlink()
    with pytest.raises(DeliverySourceError, match="DELIVERY_SOURCE"):
        _service(stack, transport, tmp_path=tmp_path).deliver()
    assert transport.calls == 0


def test_foreign_runner_receipt_is_rejected(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([])
    with pytest.raises(DeliverySourceError, match="another runner identity"):
        _service(
            stack, transport, tmp_path=tmp_path, runner_id="runner-b"
        ).deliver(ACTIVATION_ID)
    assert transport.calls == 0
    with pytest.raises(DeliverySourceError, match="no terminal runner activation"):
        _service(
            stack, FakeTransport([]), tmp_path=tmp_path, runner_id="runner-b"
        ).deliver()
    assert transport.calls == 0


def test_specific_activation_id_is_loaded(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver(ACTIVATION_ID)
    assert outcome.status.value == "DELIVERED"
    assert transport.calls == 1
    with pytest.raises(DeliverySourceError, match="not found"):
        _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver("99" * 32)


# --- deny-by-default and disabled ----------------------------------------


def test_network_denied_performs_zero_socket_io(tmp_path, monkeypatch):
    stack = _terminal_stack(tmp_path)

    class SocketBlocked:
        def __init__(self, *args, **kwargs):
            raise AssertionError("denied delivery attempted a socket")

    monkeypatch.setattr(socket, "socket", SocketBlocked)
    transport = FakeTransport([])
    with pytest.raises(DeliveryNetworkDeniedError):
        _service(stack, transport, tmp_path=tmp_path, network_allowed=False).deliver()
    assert transport.calls == 0
    assert not (Path(stack.runner_store.root).parent / "delivery").exists()


def test_disabled_delivery_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([])
    with pytest.raises(DeliveryDisabledError):
        _service(stack, transport, tmp_path=tmp_path, enabled=False).deliver()
    assert transport.calls == 0


def test_unresolved_endpoint_fails_before_any_request(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([])
    service = _service(stack, transport, tmp_path=tmp_path, endpoint="")
    with pytest.raises(DeliveryEndpointUnresolvedError):
        service.deliver()
    assert transport.calls == 0
    # The immutable intent is persisted before the endpoint is resolved.
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    delivery_id = delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )
    assert ledger.intent_exists(delivery_id)


# --- empty outbox NOOP ----------------------------------------------------


def test_empty_outbox_is_noop_with_zero_requests(tmp_path):
    stack = _terminal_stack(tmp_path, event_type=None)
    assert stack.alerts.alerts == []
    transport = FakeTransport([])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert outcome.status.value == "NOOP"
    assert outcome.state.terminal is True
    assert outcome.state.attempt_count == 0
    assert transport.calls == 0
    again = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert again.status.value == "NOOP"
    assert again.http_requests == 0
    assert transport.calls == 0


# --- loopback success -----------------------------------------------------


def test_loopback_webhook_success_exact_body_and_idempotency_header(
    tmp_path, loopback_factory
):
    stack = _terminal_stack(tmp_path)
    server = loopback_factory([("200", b'{"ok":true}')])
    transport = WebhookHttpTransport(allow_loopback_http=True)
    service = _service(
        stack,
        transport,
        tmp_path=tmp_path,
        endpoint=server.url,
        settings=_settings(max_response_bytes=4096),
    )
    outcome = service.deliver()
    assert outcome.status.value == "DELIVERED"
    assert outcome.http_requests == 1
    assert server.requests == 1
    path, headers, body = server.records[0]
    assert path == f"/hook?key={URL_SENTINEL}"
    assert headers["Content-Type"] == "application/json"
    assert headers["Idempotency-Key"] == outcome.delivery_id
    assert headers["X-TVE-Delivery-Id"] == outcome.delivery_id
    assert headers["Authorization"] == f"Bearer {TOKEN_SENTINEL}"
    assert headers["User-Agent"].startswith("turtle-value-engine")
    expected = build_webhook_payload(
        settings=_settings(),
        receipt=stack.receipt,
        result=stack.result,
        alerts=stack.alerts,
    )
    assert bytes(body) == expected.canonical_bytes()
    parsed = MonitoringWebhookPayloadV1.model_validate(json.loads(body))
    assert parsed.delivery_id == outcome.delivery_id
    assert parsed.alert_count == len(stack.alerts.alerts)

    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    state = ledger.load_state(outcome.delivery_id)
    assert state is not None and state.terminal
    assert state.terminal_attempt_number == 1
    attempt = ledger.load_attempt(outcome.delivery_id, 1)
    assert attempt.classification == "DELIVERED"
    assert attempt.http_status == 200
    assert attempt.response_body_sha256 == hashlib.sha256(b'{"ok":true}').hexdigest()


def test_rerun_after_delivered_performs_zero_requests(tmp_path, loopback_factory):
    stack = _terminal_stack(tmp_path)
    server = loopback_factory([("200", b"{}")])
    transport = WebhookHttpTransport(allow_loopback_http=True)
    service = _service(stack, transport, tmp_path=tmp_path, endpoint=server.url)
    first = service.deliver()
    assert first.status.value == "DELIVERED"
    assert server.requests == 1
    second = service.deliver()
    assert second.status.value == "DELIVERED"
    assert second.http_requests == 0
    assert second.reused is True
    assert server.requests == 1
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls


# --- retry semantics ------------------------------------------------------


def test_503_then_success_bounded_retry_with_monotonic_attempts(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_retryable(503), _retryable(429), _delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    outcome = service.deliver()
    assert outcome.status.value == "DELIVERED"
    assert outcome.http_requests == 3
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    attempts = ledger.list_attempts(outcome.delivery_id)
    assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3]
    assert [attempt.http_status for attempt in attempts] == [503, 429, 200]
    assert attempts[0].classification == "RETRYABLE_FAILURE"


def test_backoff_scheduling_uses_clock_without_sleeping(tmp_path):
    stack = _terminal_stack(tmp_path)
    clock = FakeClock()
    transport = FakeTransport([_retryable(503), _delivered()])
    service = _service(
        stack, transport, tmp_path=tmp_path, clock=clock, settings=_settings(
            backoff_base_seconds=120
        )
    )
    first = service.deliver()
    assert first.status.value == "RETRYABLE_FAILURE"
    assert first.http_requests == 1
    assert first.state.next_attempt_not_before == clock.now + timedelta(seconds=120)
    # Not due yet: a second wake must not perform any request.
    second = _service(
        stack, transport, tmp_path=tmp_path, clock=clock, settings=_settings(
            backoff_base_seconds=120
        )
    ).deliver()
    assert second.http_requests == 0
    assert second.status.value == "RETRYABLE_FAILURE"
    assert transport.calls == 1
    clock.advance(timedelta(seconds=120))
    third = _service(
        stack, transport, tmp_path=tmp_path, clock=clock, settings=_settings(
            backoff_base_seconds=120
        )
    ).deliver()
    assert third.status.value == "DELIVERED"
    assert third.http_requests == 1
    assert transport.calls == 2


def test_backoff_is_bounded_by_policy():
    intent = MonitoringDeliveryIntentV1.build(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        cycle_id="cd" * 32,
        d1_status="ALERTS_EMITTED",
        result_content_sha256="ce" * 32,
        alert_batch_id="cf" * 32,
        alert_batch_content_sha256="d0" * 32,
        destination_id="owner-primary",
        payload_sha256="d1" * 32,
        payload_bytes=32,
        empty_outbox=False,
        max_attempts=20,
        timeout_seconds=5.0,
        backoff_base_seconds=60,
        backoff_cap_seconds=3600,
        receiver_idempotency_declared=False,
        created_at=AS_OF,
    )
    assert backoff_seconds(intent, 1) == 60
    assert backoff_seconds(intent, 5) == 960
    assert backoff_seconds(intent, 20) == 3600


def test_retry_budget_exhaustion_is_terminal_permanent(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_retryable(503)] * 5)
    service = _service(stack, transport, tmp_path=tmp_path)
    outcome = service.deliver()
    assert outcome.status.value == "PERMANENT_FAILURE"
    assert outcome.state.last_error_code.value == "RETRIES_EXHAUSTED"
    assert outcome.http_requests == 3
    later = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    assert later.status.value == "PERMANENT_FAILURE"
    assert later.http_requests == 0


def test_permanent_4xx_has_no_retry_storm(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_permanent(404)] + [_permanent(404)] * 3)
    service = _service(stack, transport, tmp_path=tmp_path)
    outcome = service.deliver()
    assert outcome.status.value == "PERMANENT_FAILURE"
    assert outcome.state.last_error_code.value == "HTTP_PERMANENT_STATUS"
    assert transport.calls == 1
    again = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert again.http_requests == 0
    assert transport.calls == 1


def test_post_dispatch_timeout_is_ambiguous_and_never_resent_by_default(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_ambiguous("TIMEOUT_AFTER_DISPATCH"), _delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    outcome = service.deliver()
    assert outcome.status.value == "AMBIGUOUS"
    assert outcome.state.terminal is True
    assert outcome.state.next_attempt_not_before is None
    later = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert later.status.value == "AMBIGUOUS"
    assert later.http_requests == 0
    assert transport.calls == 1
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls


def test_ambiguous_is_retried_only_with_declared_receiver_idempotency(tmp_path):
    stack = _terminal_stack(tmp_path)
    clock = FakeClock()
    settings = _settings(receiver_idempotency_declared=True, backoff_base_seconds=30)
    transport = FakeTransport([_ambiguous(), _delivered()])
    service = _service(stack, transport, tmp_path=tmp_path, clock=clock, settings=settings)
    first = service.deliver()
    assert first.status.value == "AMBIGUOUS"
    assert first.state.terminal is False
    assert first.state.next_attempt_not_before == clock.now + timedelta(seconds=30)
    clock.advance(timedelta(seconds=30))
    second = _service(
        stack, transport, tmp_path=tmp_path, clock=clock, settings=settings
    ).deliver()
    assert second.status.value == "DELIVERED"
    assert transport.calls == 2


def test_loopback_remote_disconnect_is_ambiguous(tmp_path, loopback_factory):
    stack = _terminal_stack(tmp_path)
    server = loopback_factory([("close", b"")])
    transport = WebhookHttpTransport(allow_loopback_http=True)
    service = _service(
        stack, transport, tmp_path=tmp_path, endpoint=server.url, settings=_settings(
            timeout_seconds=5.0
        )
    )
    outcome = service.deliver()
    assert outcome.status.value == "AMBIGUOUS"
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    attempt = ledger.load_attempt(outcome.delivery_id, 1)
    assert attempt.error_code.value == "CONNECTION_LOST_AFTER_DISPATCH"
    assert server.requests == 1


def test_loopback_oversize_response_is_bounded(tmp_path, loopback_factory):
    stack = _terminal_stack(tmp_path)
    server = loopback_factory([("oversize", b"")])
    transport = WebhookHttpTransport(allow_loopback_http=True)
    service = _service(
        stack, transport, tmp_path=tmp_path, endpoint=server.url, settings=_settings(
            max_response_bytes=1024
        )
    )
    outcome = service.deliver()
    assert outcome.status.value == "DELIVERED"
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    attempt = ledger.load_attempt(outcome.delivery_id, 1)
    assert attempt.response_body_sha256 is None
    assert attempt.error_code.value == "RESPONSE_BYTES_EXCEEDED"


def test_loopback_redirect_is_not_followed(tmp_path, loopback_factory):
    stack = _terminal_stack(tmp_path)
    server = loopback_factory([("301", b"")])
    transport = WebhookHttpTransport(allow_loopback_http=True)
    service = _service(stack, transport, tmp_path=tmp_path, endpoint=server.url)
    outcome = service.deliver()
    assert outcome.status.value == "PERMANENT_FAILURE"
    assert outcome.state.last_error_code.value == "HTTP_REDIRECT_NOT_FOLLOWED"
    assert server.requests == 1


def test_pre_dispatch_connect_failure_is_retryable():
    transport = WebhookHttpTransport(allow_loopback_http=True)
    outcome = transport.send(
        endpoint="http://127.0.0.1:1/hook",
        auth_bearer=None,
        request=WebhookRequest(body=b"{}", idempotency_key="k", timeout_seconds=1.0,
                               max_response_bytes=1024),
    )
    assert outcome.classification.value == "RETRYABLE_FAILURE"
    assert outcome.error_code.value == "CONNECT_FAILED_PRE_DISPATCH"


def test_live_transport_requires_https_and_valid_endpoints(tmp_path, monkeypatch):
    class SocketBlocked:
        def __init__(self, *args, **kwargs):
            raise AssertionError("endpoint validation attempted a socket")

    monkeypatch.setattr(socket, "socket", SocketBlocked)
    transport = WebhookHttpTransport()
    with pytest.raises(WebhookEndpointError, match="https"):
        transport.send(
            endpoint="http://example.com/hook",
            auth_bearer=None,
            request=WebhookRequest(b"{}", "k", 1.0, 1024),
        )
    with pytest.raises(WebhookEndpointError, match="userinfo"):
        transport.send(
            endpoint="https://user:pass@example.com/hook",
            auth_bearer=None,
            request=WebhookRequest(b"{}", "k", 1.0, 1024),
        )
    with pytest.raises(WebhookEndpointError, match="scheme"):
        transport.send(
            endpoint="ftp://example.com/hook",
            auth_bearer=None,
            request=WebhookRequest(b"{}", "k", 1.0, 1024),
        )
    with pytest.raises(WebhookEndpointError, match="empty"):
        transport.send(
            endpoint="  ",
            auth_bearer=None,
            request=WebhookRequest(b"{}", "k", 1.0, 1024),
        )
    loopback_transport = WebhookHttpTransport(allow_loopback_http=True)
    with pytest.raises(WebhookEndpointError, match="loopback-test-only"):
        loopback_transport.send(
            endpoint="http://example.com/hook",
            auth_bearer=None,
            request=WebhookRequest(b"{}", "k", 1.0, 1024),
        )


# --- crash / repair -------------------------------------------------------


class _PointerFailAfter:
    """Fail the Nth pointer write to simulate a crash at publication time."""

    def __init__(self, fail_on: int) -> None:
        self.fail_on = fail_on
        self.pointer_writes = 0

    def __call__(self, path: Path, kind: str) -> None:
        if kind == "pointer":
            self.pointer_writes += 1
            if self.pointer_writes == self.fail_on:
                raise RuntimeError("simulated crash before pointer publication")


def test_crash_after_intent_before_claim_resumes_same_delivery(tmp_path):
    stack = _terminal_stack(tmp_path)

    class CrashBeforeClaim:
        """Simulate a crash after the intent write but before the claim."""

        def __call__(self, path: Path, kind: str) -> None:
            if kind == "artifact" and "claims" in path.parts:
                raise RuntimeError("simulated crash before the dispatch claim")

    service = _service(
        stack, FakeTransport([]), tmp_path=tmp_path, failure_injector=CrashBeforeClaim()
    )
    with pytest.raises(DeliveryLedgerConflictError, match="delivery ledger write failed"):
        service.deliver()
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    delivery_id = delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )
    intent = ledger.load_intent(delivery_id)
    assert ledger.list_attempts(delivery_id) == []
    assert ledger.list_claims(delivery_id) == []
    assert derive_delivery_state(intent, []).status.value == "PENDING"

    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert outcome.status.value == "DELIVERED"
    assert transport.calls == 1
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls
    assert stack.acquisition.calls == 1


def test_crash_after_response_before_pointer_publish_repairs_deterministically(tmp_path):
    stack = _terminal_stack(tmp_path)
    injector = _PointerFailAfter(fail_on=2)
    transport = FakeTransport([_delivered()])
    service = _service(
        stack, transport, tmp_path=tmp_path, failure_injector=injector
    )
    with pytest.raises(DeliveryLedgerConflictError, match="delivery ledger write failed"):
        service.deliver()
    assert transport.calls == 1

    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    delivery_id = delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )
    # The immutable successful attempt exists while the published pointer is
    # still the stale PENDING state written before the request.
    attempts = ledger.list_attempts(delivery_id)
    assert [attempt.classification for attempt in attempts] == ["DELIVERED"]
    stale = ledger.load_state(delivery_id)
    assert stale is not None and stale.status.value == "PENDING"

    repaired = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    assert repaired.status.value == "DELIVERED"
    assert repaired.http_requests == 0
    expected = derive_delivery_state(
        ledger.load_intent(delivery_id), ledger.list_attempts(delivery_id)
    )
    assert ledger.state_path(delivery_id).read_bytes() == expected.canonical_bytes() + b"\n"
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls


def test_repair_after_state_pointer_loss_is_byte_identical(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    outcome = service.deliver()
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    published = ledger.state_path(outcome.delivery_id).read_bytes()
    ledger.state_path(outcome.delivery_id).unlink()
    again = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    assert again.status.value == "DELIVERED"
    assert again.http_requests == 0
    assert ledger.state_path(outcome.delivery_id).read_bytes() == published


def test_delivery_failures_never_rerun_d1_provider_or_reanalysis(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_retryable(503)] * 6)
    settings = _settings(max_attempts=3, backoff_base_seconds=10)
    clock = FakeClock()
    for _ in range(4):
        _service(
            stack, transport, tmp_path=tmp_path, clock=clock, settings=settings
        ).deliver()
        clock.advance(timedelta(seconds=600))
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls
    assert stack.acquisition.calls == 1
    assert transport.calls == 3


# --- Phase 6-D2B-R1: durable dispatch claims -------------------------------


class _CrashAfterClaimTransport:
    """Transport that raises before recording anything (claim is durable)."""

    def __init__(self) -> None:
        self.calls = 0

    def send(self, *, endpoint, auth_bearer, request):
        self.calls += 1
        raise RuntimeError("simulated crash after the durable claim, before send")


class _CrashAfterDispatchTransport:
    """Transport that may have written request bytes, then dies."""

    def __init__(self) -> None:
        self.calls = 0
        self.keys: list[str] = []

    def send(self, *, endpoint, auth_bearer, request):
        self.calls += 1
        self.keys.append(request.idempotency_key)
        # Request bytes may already have reached the receiver here.
        raise RuntimeError("simulated crash after possible dispatch, before save")


def _ledger_for(stack) -> DeliveryLedgerStore:
    return DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")


def _delivery_id_for(stack) -> str:
    return delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )


def test_crash_after_claim_before_send_is_conservative_ambiguous_zero_resend(tmp_path):
    stack = _terminal_stack(tmp_path)
    crashing = _CrashAfterClaimTransport()
    with pytest.raises(RuntimeError, match="after the durable claim"):
        _service(stack, crashing, tmp_path=tmp_path).deliver()
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)
    claims = ledger.list_claims(delivery_id)
    assert [claim.attempt_number for claim in claims] == [1]
    assert ledger.list_attempts(delivery_id) == []

    # Restart: the orphaned claim is conservatively AMBIGUOUS, zero resend.
    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert outcome.status.value == "AMBIGUOUS"
    assert outcome.state.terminal is True
    assert outcome.state.last_error_code.value == "ORPHANED_DISPATCH"
    assert outcome.http_requests == 0
    assert transport.calls == 0
    # Further wakes still resend nothing by default.
    again = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    assert again.status.value == "AMBIGUOUS"
    assert again.http_requests == 0
    assert stack.d1.calls == 1  # setup only; delivery performed zero D1 calls


def test_crash_after_possible_dispatch_before_outcome_save_is_ambiguous(tmp_path):
    stack = _terminal_stack(tmp_path)
    crashing = _CrashAfterDispatchTransport()
    with pytest.raises(RuntimeError, match="after possible dispatch"):
        _service(stack, crashing, tmp_path=tmp_path).deliver()
    assert crashing.calls == 1

    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver()
    assert outcome.status.value == "AMBIGUOUS"
    assert outcome.state.last_error_code.value == "ORPHANED_DISPATCH"
    assert outcome.http_requests == 0
    assert transport.calls == 0
    # Exactly one outbound request ever happened in this ledger's lifetime.
    assert crashing.calls == 1


def test_orphaned_claim_retries_only_under_declared_receiver_idempotency(tmp_path):
    stack = _terminal_stack(tmp_path)
    settings = _settings(receiver_idempotency_declared=True)

    class RetryThenCrashTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.keys: list[str] = []

        def send(self, *, endpoint, auth_bearer, request):
            self.calls += 1
            self.keys.append(request.idempotency_key)
            if self.calls == 1:
                return _retryable(503)
            raise RuntimeError("simulated crash on the second dispatch")

    crashing = RetryThenCrashTransport()
    with pytest.raises(RuntimeError):
        _service(stack, crashing, tmp_path=tmp_path, settings=settings).deliver()
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)
    assert [attempt.attempt_number for attempt in ledger.list_attempts(delivery_id)] == [1]
    assert [claim.attempt_number for claim in ledger.list_claims(delivery_id)] == [1, 2]
    claim_two_before = ledger.claim_path(delivery_id, 2).read_bytes()

    # Restart under the explicit receiver-idempotency policy: the resend is
    # authorized by a NEW monotonic dispatch-budget slot (claim 3), never by
    # reusing the orphaned claim 2, and the receiver-facing idempotency key
    # stays byte-identical (6-D2B-R2).
    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path, settings=settings).deliver()
    assert outcome.status.value == "DELIVERED"
    assert outcome.http_requests == 1
    assert transport.requests[0].idempotency_key == delivery_id
    assert crashing.keys + [request.idempotency_key for request in transport.requests] == [
        delivery_id,
        delivery_id,
        delivery_id,
    ]
    # Slot 2 was skipped by the retry: its claim stays untouched, its attempt
    # never exists, and the resend lives in slot 3.
    claims = ledger.list_claims(delivery_id)
    assert [claim.attempt_number for claim in claims] == [1, 2, 3]
    assert ledger.claim_path(delivery_id, 2).read_bytes() == claim_two_before
    assert claims[2].content_sha256 != claims[1].content_sha256
    assert claims[2].attempt_number == 3
    attempts = ledger.list_attempts(delivery_id)
    assert [attempt.attempt_number for attempt in attempts] == [1, 3]
    assert attempts[-1].classification == "DELIVERED"


def test_orphaned_claim_with_exhausted_budget_stays_terminal_ambiguous():
    """A durable claim always consumes budget; derivation stays terminal.

    These are direct derivations of the F5 boundary the R2 post-closure
    review selected: remaining budget is decided by durable dispatch slots,
    never by ``len(attempts)`` alone.
    """

    def _intent(**overrides):
        values = {
            "runner_id": RUNNER_ID,
            "activation_id": ACTIVATION_ID,
            "cycle_id": "cd" * 32,
            "d1_status": "ALERTS_EMITTED",
            "result_content_sha256": "ce" * 32,
            "alert_batch_id": "cf" * 32,
            "alert_batch_content_sha256": "d0" * 32,
            "destination_id": "owner-primary",
            "payload_sha256": "d1" * 32,
            "payload_bytes": 32,
            "empty_outbox": False,
            "max_attempts": 1,
            "timeout_seconds": 5.0,
            "backoff_base_seconds": 0,
            "backoff_cap_seconds": 3600,
            "receiver_idempotency_declared": True,
            "created_at": AS_OF,
        }
        values.update(overrides)
        return MonitoringDeliveryIntentV1.build(**values)

    def _claim(intent, number):
        return MonitoringDispatchClaimV1.build(
            delivery_id=intent.delivery_id,
            attempt_number=number,
            intent_content_sha256=intent.content_sha256,
            payload_sha256=intent.payload_sha256,
            idempotency_key=intent.delivery_id,
        )

    def _attempt(intent, number):
        return MonitoringDeliveryAttemptV1.build(
            delivery_id=intent.delivery_id,
            attempt_number=number,
            started_at=AS_OF,
            finished_at=AS_OF,
            classification="RETRYABLE_FAILURE",
            http_status=503,
            response_body_sha256=None,
            error_code="HTTP_RETRYABLE_STATUS",
            retry_not_before=AS_OF,
        )

    # max_attempts=1 with zero persisted outcomes but one durable dispatch
    # slot: the orphan consumed the whole budget, so even a receiver-
    # idempotent policy may not send again (the R1 defect sent twice).
    max_one = _intent(max_attempts=1)
    state = derive_delivery_state(max_one, [], claims=[_claim(max_one, 1)])
    assert state.status.value == "AMBIGUOUS"
    assert state.terminal is True
    assert state.last_error_code.value == "ORPHANED_DISPATCH"
    assert state.next_attempt_not_before is None

    # One completed retryable outcome plus a later orphaned slot inside a
    # max_attempts=3 budget leaves exactly one slot: retry is permitted.
    max_three = _intent(max_attempts=3)
    pending = derive_delivery_state(
        max_three, [_attempt(max_three, 1)], claims=[_claim(max_three, 1), _claim(max_three, 2)]
    )
    assert pending.status.value == "PENDING"
    assert pending.terminal is False

    # A third durable slot consumes the last position: terminal ambiguous.
    exhausted = derive_delivery_state(
        max_three,
        [_attempt(max_three, 1)],
        claims=[_claim(max_three, n) for n in (1, 2, 3)],
    )
    assert exhausted.status.value == "AMBIGUOUS"
    assert exhausted.terminal is True
    assert exhausted.last_error_code.value == "ORPHANED_DISPATCH"
    assert exhausted.next_attempt_not_before is None


def test_unresolved_claim_conflicts_fail_closed(tmp_path):
    first = _terminal_stack(tmp_path / "a")
    _service(
        first,
        FakeTransport([_retryable(503)]),
        tmp_path=tmp_path / "a",
        settings=_settings(backoff_base_seconds=120),
    ).deliver()
    ledger = _ledger_for(first)
    delivery_id = _delivery_id_for(first)
    intent = ledger.load_intent(delivery_id)

    def _claim(number: int, *, intent_hash: str | None = None):
        return MonitoringDispatchClaimV1.build(
            delivery_id=delivery_id,
            attempt_number=number,
            intent_content_sha256=intent_hash or intent.content_sha256,
            payload_sha256=intent.payload_sha256,
            idempotency_key=delivery_id,
        )

    def _attempt(number: int):
        return MonitoringDeliveryAttemptV1.build(
            delivery_id=delivery_id,
            attempt_number=number,
            started_at=AS_OF,
            finished_at=AS_OF,
            classification="RETRYABLE_FAILURE",
            http_status=503,
            response_body_sha256=None,
            error_code="HTTP_RETRYABLE_STATUS",
            retry_not_before=AS_OF,
        )

    # Multiple unresolved claims within the budget are the legitimate
    # repeated-crash state under R2 (each consumed one slot); with the
    # default non-idempotent policy they stay terminal AMBIGUOUS with zero
    # resend instead of raising.
    ledger.save_claim(_claim(2))
    ledger.save_claim(_claim(3))
    bounded = _service(
        first,
        FakeTransport([]),
        tmp_path=tmp_path / "a",
        settings=_settings(backoff_base_seconds=120),
    ).deliver()
    assert bounded.status.value == "AMBIGUOUS"
    assert bounded.state.last_error_code.value == "ORPHANED_DISPATCH"
    assert bounded.http_requests == 0

    # More authorized dispatch slots than the configured maximum is
    # over-budget evidence and fails closed before transport.
    ledger.save_claim(_claim(4))
    with pytest.raises(DeliveryLedgerConflictError, match="exceed the configured retry"):
        _service(
            first,
            FakeTransport([]),
            tmp_path=tmp_path / "a",
            settings=_settings(backoff_base_seconds=120),
        ).deliver()

    # A non-monotonic (gapped) claim sequence is impossible budget evidence.
    ledger.claim_path(delivery_id, 4).unlink()
    ledger.save_claim(_claim(5))
    with pytest.raises(DeliveryLedgerConflictError, match="contiguous from one"):
        _service(
            first,
            FakeTransport([]),
            tmp_path=tmp_path / "a",
            settings=_settings(backoff_base_seconds=120),
        ).deliver()

    # An attempt outcome whose durable dispatch slot is missing is bound to
    # the wrong slot and fails closed before transport.
    ledger.claim_path(delivery_id, 5).unlink()
    ledger.save_attempt(_attempt(4))
    with pytest.raises(DeliveryLedgerConflictError, match="no durable dispatch slot"):
        _service(
            first,
            FakeTransport([]),
            tmp_path=tmp_path / "a",
            settings=_settings(backoff_base_seconds=120),
        ).deliver()

    # A claim bound to a different intent is foreign evidence.
    second = _terminal_stack(tmp_path / "b")
    _service(
        second,
        FakeTransport([_retryable(503)]),
        tmp_path=tmp_path / "b",
        settings=_settings(backoff_base_seconds=120),
    ).deliver()
    ledger_b = _ledger_for(second)
    delivery_b = _delivery_id_for(second)
    intent_b = ledger_b.load_intent(delivery_b)
    ledger_b.save_claim(
        MonitoringDispatchClaimV1.build(
            delivery_id=delivery_b,
            attempt_number=2,
            intent_content_sha256="0" * 64,
            payload_sha256=intent_b.payload_sha256,
            idempotency_key=delivery_b,
        )
    )
    with pytest.raises(DeliveryLedgerConflictError, match="not bound to this intent"):
        _service(
            second,
            FakeTransport([]),
            tmp_path=tmp_path / "b",
            settings=_settings(backoff_base_seconds=120),
        ).deliver()


# --- Phase 6-D2B-R2: orphan retry-budget accounting -------------------------


def test_r2_max_attempts_one_orphan_restart_sends_zero(tmp_path):
    """max_attempts=1 + declared idempotency + orphaned claim 1.

    The R1 defect let a crash between the durable claim and the attempt-outcome
    save buy a second transport entry.  Under R2 the durable claim consumed
    the only budget position, so the restart performs zero new transport
    calls and exposes the truthful terminal exhausted/ambiguous state.
    """

    stack = _terminal_stack(tmp_path)
    settings = _settings(max_attempts=1, receiver_idempotency_declared=True)
    crashing = _CrashAfterDispatchTransport()
    with pytest.raises(RuntimeError, match="after possible dispatch"):
        _service(stack, crashing, tmp_path=tmp_path, settings=settings).deliver()
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)
    assert [claim.attempt_number for claim in ledger.list_claims(delivery_id)] == [1]
    assert ledger.list_attempts(delivery_id) == []

    # A crashing transport proves by construction that no resend happened.
    guard = _CrashAfterDispatchTransport()
    outcome = _service(stack, guard, tmp_path=tmp_path, settings=settings).deliver()
    assert outcome.status.value == "AMBIGUOUS"
    assert outcome.state.terminal is True
    assert outcome.state.last_error_code.value == "ORPHANED_DISPATCH"
    assert outcome.http_requests == 0
    assert guard.calls == 0
    # Exactly one transport entry ever happened in this ledger's lifetime.
    assert crashing.calls == 1
    assert len(ledger.list_claims(delivery_id)) == 1


def test_r2_repeated_crash_after_dispatch_loop_is_bounded(tmp_path):
    """Repeated crash-after-possible-dispatch never exceeds max_attempts=3."""

    stack = _terminal_stack(tmp_path)
    settings = _settings(max_attempts=3, receiver_idempotency_declared=True)
    crashes: list[_CrashAfterDispatchTransport] = []
    for _ in range(3):
        crashing = _CrashAfterDispatchTransport()
        crashes.append(crashing)
        with pytest.raises(RuntimeError, match="after possible dispatch"):
            _service(stack, crashing, tmp_path=tmp_path, settings=settings).deliver()
        assert crashing.calls == 1
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)
    assert [claim.attempt_number for claim in ledger.list_claims(delivery_id)] == [1, 2, 3]
    assert ledger.list_attempts(delivery_id) == []

    # Every later wake performs zero transport entries and exposes the
    # truthful terminal exhausted/ambiguous state.
    for _ in range(2):
        guard = _CrashAfterDispatchTransport()
        outcome = _service(stack, guard, tmp_path=tmp_path, settings=settings).deliver()
        assert outcome.status.value == "AMBIGUOUS"
        assert outcome.state.terminal is True
        assert outcome.state.last_error_code.value == "ORPHANED_DISPATCH"
        assert outcome.http_requests == 0
        assert guard.calls == 0

    # Hard bound: total outbound transport entries never exceed max_attempts.
    assert sum(transport.calls for transport in crashes) == 3
    projection = delivery_status_projection(ledger)
    entry = projection["deliveries"][0]
    assert entry["dispatch_claim_count"] == 3
    assert entry["unresolved_claim_numbers"] == [1, 2, 3]
    assert entry["state"]["status"] == "AMBIGUOUS"
    assert entry["unresolved_dispatch_claim"]["attempt_number"] == 3


def test_r2_recovery_retry_persists_new_slot_before_transport(tmp_path):
    """An allowed orphan-recovery retry enters transport only under a NEW slot."""

    stack = _terminal_stack(tmp_path)
    settings = _settings(max_attempts=3, receiver_idempotency_declared=True)
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)

    class SlotAwareCrashTransport:
        """Records which claim slots are durable when a send starts."""

        def __init__(self) -> None:
            self.calls = 0
            self.claims_at_send: list[list[int]] = []
            self.keys: list[str] = []

        def send(self, *, endpoint, auth_bearer, request):
            self.calls += 1
            self.keys.append(request.idempotency_key)
            self.claims_at_send.append(
                [claim.attempt_number for claim in ledger.list_claims(delivery_id)]
            )
            raise RuntimeError("simulated crash after possible dispatch")

    crashing = SlotAwareCrashTransport()
    with pytest.raises(RuntimeError):
        _service(stack, crashing, tmp_path=tmp_path, settings=settings).deliver()
    assert crashing.claims_at_send == [[1]]

    retrying = SlotAwareCrashTransport()
    with pytest.raises(RuntimeError):
        _service(stack, retrying, tmp_path=tmp_path, settings=settings).deliver()
    # The retry's transport entry was already covered by a NEW monotonic
    # durable slot 2 persisted before the send; the orphaned slot 1 was never
    # reused as a budget token, and the receiver key stayed byte-identical.
    assert retrying.claims_at_send == [[1, 2]]
    assert crashing.keys == retrying.keys == [delivery_id]
    assert [claim.attempt_number for claim in ledger.list_claims(delivery_id)] == [1, 2]


def test_r2_completed_attempts_and_orphan_slots_share_one_budget(tmp_path):
    """Completed attempts and orphaned slots consume the same budget exactly once."""

    stack = _terminal_stack(tmp_path)
    settings = _settings(max_attempts=3, receiver_idempotency_declared=True)
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)

    class FirstRetryThenCrashTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.keys: list[str] = []

        def send(self, *, endpoint, auth_bearer, request):
            self.calls += 1
            self.keys.append(request.idempotency_key)
            if self.calls == 1:
                return _retryable(503)
            raise RuntimeError("simulated crash on the second dispatch")

    crashing = FirstRetryThenCrashTransport()
    with pytest.raises(RuntimeError):
        _service(stack, crashing, tmp_path=tmp_path, settings=settings).deliver()
    assert [attempt.attempt_number for attempt in ledger.list_attempts(delivery_id)] == [1]
    assert [claim.attempt_number for claim in ledger.list_claims(delivery_id)] == [1, 2]

    recovery = FakeTransport([_delivered()])
    outcome = _service(
        stack, recovery, tmp_path=tmp_path, settings=settings
    ).deliver()
    # The completed retryable attempt (slot 1), the orphaned slot 2 and the
    # successful recovery slot 3 each consumed exactly one of the three
    # budget positions: no double spending, no skipped position.
    claims = ledger.list_claims(delivery_id)
    attempts = ledger.list_attempts(delivery_id)
    assert [claim.attempt_number for claim in claims] == [1, 2, 3]
    assert [attempt.attempt_number for attempt in attempts] == [1, 3]
    assert crashing.calls == 2 and recovery.calls == 1
    assert outcome.status.value == "DELIVERED"
    assert outcome.state.terminal is True
    assert outcome.state.attempt_count == 2
    assert outcome.state.terminal_attempt_number == 3
    assert crashing.keys + [r.idempotency_key for r in recovery.requests] == [
        delivery_id,
        delivery_id,
        delivery_id,
    ]


# --- Phase 6-D2B-R1: per-delivery OS single-flight --------------------------


_SINGLE_FLIGHT_CHILD = r"""
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, sys.argv[2])

from turtle_value_engine.monitoring_delivery import (
    DeliverySettingsV1,
    DeliveryLedgerStore,
    MonitoringDeliveryService,
    TransportOutcome,
)
from turtle_value_engine.monitoring_delivery.contracts import DeliveryStatus
from turtle_value_engine.monitoring_cycle import MonitoringCycleStore
from turtle_value_engine.monitoring_runner import RunnerStore

spec = json.loads(sys.argv[1])
entered = Path(spec["entered"])
release = Path(spec["release"])
result = Path(spec["result"])


class BlockingTransport:
    def __init__(self) -> None:
        self.request_count = 0

    def send(self, *, endpoint, auth_bearer, request):
        self.request_count += 1
        entered.write_text("entered", encoding="utf-8")
        deadline = time.monotonic() + 60.0
        while not release.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("release barrier timeout")
            time.sleep(0.01)
        return TransportOutcome(DeliveryStatus.DELIVERED, 200, "cd" * 32, None)


service = MonitoringDeliveryService(
    settings=DeliverySettingsV1(
        destination_id="owner-primary",
        max_attempts=3,
        timeout_seconds=5.0,
        backoff_base_seconds=0,
        backoff_cap_seconds=3600,
        receiver_idempotency_declared=False,
    ),
    ledger=DeliveryLedgerStore(spec["delivery_root"]),
    runner_store=RunnerStore(spec["runner_root"]),
    cycle_store=MonitoringCycleStore(spec["cycle_store_root"]),
    transport=BlockingTransport(),
    endpoint_resolver=lambda: "https://example.invalid/hook",
    auth_resolver=lambda: None,
    clock=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    runner_id=spec["runner_id"],
    network_allowed=True,
    enabled=True,
)
try:
    outcome = service.deliver(spec["activation_id"])
    payload = {
        "classification": outcome.status.value,
        "http_requests": outcome.http_requests,
    }
except Exception as exc:
    payload = {"error": type(exc).__name__, "message": str(exc)}
result.write_text(json.dumps(payload), encoding="utf-8")
"""


def test_two_processes_single_flight_only_one_enters_transport(tmp_path):
    """Real cross-process proof: a second process cannot enter the transport."""

    stack = _terminal_stack(tmp_path)
    delivery_root = Path(stack.runner_store.root).parent / "delivery"
    entered = tmp_path / "child-entered"
    release = tmp_path / "child-release"
    result = tmp_path / "child-result.json"
    spec = {
        "entered": str(entered),
        "release": str(release),
        "result": str(result),
        "delivery_root": str(delivery_root),
        "runner_root": str(stack.runner_store.root),
        "cycle_store_root": str(stack.cycles.root),
        "runner_id": RUNNER_ID,
        "activation_id": ACTIVATION_ID,
    }
    child = subprocess.Popen(
        [sys.executable, "-c", _SINGLE_FLIGHT_CHILD, json.dumps(spec), str(ROOT / "src")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30.0
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered.exists(), "the child process never entered the transport"

        # While the child holds the OS lock inside the transport, this real
        # second process must fail fast as busy with zero transport calls.
        losing = FakeTransport([])
        with pytest.raises(DeliveryLockBusyError):
            _service(stack, losing, tmp_path=tmp_path).deliver()
        assert losing.calls == 0

        release.write_text("1", encoding="utf-8")
        stdout, stderr = child.communicate(timeout=60)
        assert child.returncode == 0, f"child failed: {stderr}\n{stdout}"
        payload = json.loads(result.read_text(encoding="utf-8"))
        assert payload == {"classification": "DELIVERED", "http_requests": 1}

        # After the winner finished, another wake replays with zero requests.
        replay = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
        assert replay.status.value == "DELIVERED"
        assert replay.http_requests == 0
    finally:
        if child.poll() is None:
            release.write_text("1", encoding="utf-8")
            child.communicate(timeout=60)


def test_real_contention_is_classified_busy_not_fail_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    delivery_id = _delivery_id_for(stack)
    ledger = _ledger_for(stack)
    with delivery_single_flight(ledger.lock_path(delivery_id), delivery_id):
        with pytest.raises(DeliveryLockBusyError):
            _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    # After the holder released, the same invocation delivers normally.
    outcome = service.deliver()
    assert outcome.status.value == "DELIVERED"
    assert transport.calls == 1


def test_non_contention_lock_failure_fails_closed_not_busy(tmp_path, monkeypatch):
    stack = _terminal_stack(tmp_path)
    service = _service(stack, FakeTransport([]), tmp_path=tmp_path)

    def enolck(descriptor, operation):
        raise OSError(errno.ENOLCK, "no record locks available")

    monkeypatch.setattr(fcntl, "flock", enolck)
    with pytest.raises(DeliveryLockError) as excinfo:
        service.deliver()
    assert type(excinfo.value) is DeliveryLockError  # never disguised as busy
    assert "ENOLCK" in str(excinfo.value) or "no record locks" in str(excinfo.value)
    monkeypatch.undo()

    real_open = os.open

    def eio_open(path, flags, *args, **kwargs):
        if str(path).endswith(".lock"):
            raise OSError(errno.EIO, "I/O error")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", eio_open)
    with pytest.raises(DeliveryLockError) as excinfo:
        service.deliver()
    assert type(excinfo.value) is DeliveryLockError
    assert "cannot open delivery lock" in str(excinfo.value)


def test_cli_deliver_busy_exits_three_with_zero_requests(tmp_path, monkeypatch, capsys):
    import turtle_value_engine.cli as cli_module

    stack = _terminal_stack(tmp_path)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://hook.invalid/x")
    runner_config = tmp_path / "runner.json"
    runner_config.write_text(json.dumps(_runner_config_payload(tmp_path)), encoding="utf-8")
    project_config = _write_project_config(tmp_path, enabled=True)
    transport = FakeTransport([])
    monkeypatch.setattr(cli_module, "WebhookHttpTransport", lambda: transport)

    delivery_root = tmp_path / ".tve-private" / "monitoring" / "delivery"
    lock_path = delivery_root / "locks" / f"{_delivery_id_for(stack)}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc = cli_module.main(
            [
                "watch",
                "deliver",
                "--runner-config",
                str(runner_config),
                "--project-config",
                str(project_config),
                "--network",
                "allow",
            ]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert rc == 3
        assert payload["classification"] == "DELIVERY_BUSY"
        assert transport.calls == 0
    finally:
        os.close(descriptor)


# --- Phase 6-D2B-R1: one monotonic overall deadline -------------------------


class _FakeMonotonic:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeSock:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _FakeResponse:
    status = 200

    def __init__(self, clock: _FakeMonotonic, read_cost: float, chunks: list[bytes]) -> None:
        self._clock = clock
        self._read_cost = read_cost
        self._chunks = list(chunks)
        self.reads = 0

    def getheader(self, name):
        return None

    def read(self, amount):
        self.reads += 1
        self._clock.advance(self._read_cost)
        return self._chunks.pop(0) if self._chunks else b""


class _FakeConnection:
    def __init__(
        self,
        sock: _FakeSock,
        clock: _FakeMonotonic,
        *,
        connect_cost: float,
        request_cost: float,
        read_cost: float,
        chunks: list[bytes],
    ) -> None:
        self.sock = sock
        self._clock = clock
        self._connect_cost = connect_cost
        self._request_cost = request_cost
        self._read_cost = read_cost
        self._chunks = chunks
        self.connected = False
        self.closed = False
        self.requests: list[tuple[object, ...]] = []

    def connect(self):
        self._clock.advance(self._connect_cost)
        self.connected = True

    def request(self, method, path, body=None, headers=None):
        self._clock.advance(self._request_cost)
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return _FakeResponse(self._clock, self._read_cost, self._chunks)

    def close(self):
        self.closed = True


def _fake_transport_with_clock(connection: _FakeConnection, clock: _FakeMonotonic):
    factory_calls: list[dict] = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return connection

    transport = WebhookHttpTransport(monotonic_clock=clock, connection_factory=factory)
    return transport, factory_calls


def test_overall_deadline_bounds_connect_request_and_reads_from_one_budget():
    clock = _FakeMonotonic()
    sock = _FakeSock()
    connection = _FakeConnection(
        sock,
        clock,
        connect_cost=3.0,
        request_cost=4.0,
        read_cost=2.0,
        chunks=[b"a", b"b", b"c"],
    )
    transport, factory_calls = _fake_transport_with_clock(connection, clock)
    outcome = transport.send(
        endpoint="https://example.invalid/hook",
        auth_bearer=None,
        request=WebhookRequest(b"{}", "k", 10.0, 1024),
    )
    # The connect phase received the full budget; the request/header phase
    # and each repeated response read received only the *remaining* budget.
    assert factory_calls[0]["timeout"] == 10.0
    assert sock.timeouts == [7.0, 3.0, 1.0]
    assert connection.requests and connection.requests[0][0] == "POST"
    assert outcome.classification.value == "AMBIGUOUS"
    assert outcome.error_code.value == "TIMEOUT_AFTER_DISPATCH"
    assert connection.closed is True


def test_deadline_expiry_after_connect_before_request_is_proven_unsent():
    clock = _FakeMonotonic()
    sock = _FakeSock()
    connection = _FakeConnection(
        sock, clock, connect_cost=20.0, request_cost=0.0, read_cost=0.0, chunks=[b"x"]
    )
    transport, factory_calls = _fake_transport_with_clock(connection, clock)
    outcome = transport.send(
        endpoint="https://example.invalid/hook",
        auth_bearer=None,
        request=WebhookRequest(b"{}", "k", 10.0, 1024),
    )
    assert outcome.classification.value == "RETRYABLE_FAILURE"
    assert outcome.error_code.value == "DEADLINE_EXHAUSTED_PRE_DISPATCH"
    assert factory_calls[0]["timeout"] == 10.0
    assert connection.requests == []  # no request byte was ever written
    assert sock.timeouts == []


def test_post_dispatch_deadline_expiry_is_ambiguous():
    clock = _FakeMonotonic()
    sock = _FakeSock()
    connection = _FakeConnection(
        sock, clock, connect_cost=0.0, request_cost=20.0, read_cost=0.0, chunks=[b"x"]
    )
    transport, _ = _fake_transport_with_clock(connection, clock)
    outcome = transport.send(
        endpoint="https://example.invalid/hook",
        auth_bearer=None,
        request=WebhookRequest(b"{}", "k", 10.0, 1024),
    )
    assert connection.requests  # request bytes may have been dispatched
    assert outcome.classification.value == "AMBIGUOUS"
    assert outcome.error_code.value == "TIMEOUT_AFTER_DISPATCH"


def test_body_read_timeout_after_dispatch_is_ambiguous():
    clock = _FakeMonotonic()
    sock = _FakeSock()
    connection = _FakeConnection(
        sock, clock, connect_cost=0.0, request_cost=0.0, read_cost=0.0, chunks=[b"x"]
    )
    transport, _ = _fake_transport_with_clock(connection, clock)
    response = connection.getresponse()
    read_attempts = {"count": 0}

    def timing_out_read(amount):
        read_attempts["count"] += 1
        raise TimeoutError("socket timeout during body read")

    response.read = timing_out_read  # type: ignore[method-assign]
    connection.getresponse = lambda: response  # type: ignore[method-assign]
    outcome = transport.send(
        endpoint="https://example.invalid/hook",
        auth_bearer=None,
        request=WebhookRequest(b"{}", "k", 10.0, 1024),
    )
    assert read_attempts["count"] == 1
    assert outcome.classification.value == "AMBIGUOUS"
    assert outcome.error_code.value == "TIMEOUT_AFTER_DISPATCH"


# --- Phase 6-D2B-R1: truthful read-only pointer status ----------------------


def test_status_pointer_is_current_after_delivered_run(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver()
    projection = delivery_status_projection(_ledger_for(stack))
    entry = projection["deliveries"][0]
    assert entry["delivery_id"] == outcome.delivery_id
    assert entry["pointer_status"] == "CURRENT"
    assert entry["pointer_published"] is True
    assert entry["unresolved_dispatch_claim"] is None


def test_status_pointer_missing_is_reported_and_not_repaired(tmp_path):
    stack = _terminal_stack(tmp_path)
    outcome = _service(stack, FakeTransport([_delivered()]), tmp_path=tmp_path).deliver()
    ledger = _ledger_for(stack)
    state_path = ledger.state_path(outcome.delivery_id)
    state_path.unlink()
    projection = delivery_status_projection(ledger)
    entry = projection["deliveries"][0]
    assert entry["pointer_status"] == "MISSING"
    assert entry["pointer_published"] is False
    assert entry["state"]["status"] == "DELIVERED"  # derived from artifacts
    # The read-only status command did not silently repair anything.
    assert not state_path.exists()


def test_status_pointer_stale_after_attempt_is_repairable(tmp_path):
    stack = _terminal_stack(tmp_path)
    injector = _PointerFailAfter(fail_on=2)
    service = _service(
        stack, FakeTransport([_delivered()]), tmp_path=tmp_path, failure_injector=injector
    )
    with pytest.raises(DeliveryLedgerConflictError, match="delivery ledger write failed"):
        service.deliver()
    ledger = _ledger_for(stack)
    projection = delivery_status_projection(ledger)
    entry = projection["deliveries"][0]
    assert entry["pointer_status"] == "STALE_REPAIRABLE"
    assert entry["pointer_published"] is True
    assert entry["state"]["status"] == "DELIVERED"
    # Status stayed read-only: the mutating path still repairs it afterwards.
    assert ledger.load_state(entry["delivery_id"]).status.value == "PENDING"
    repaired = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    assert repaired.status.value == "DELIVERED"
    assert delivery_status_projection(ledger)["deliveries"][0]["pointer_status"] == "CURRENT"


def test_status_pointer_corrupt_noncanonical_foreign_contradictory_fail_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    outcome = _service(stack, FakeTransport([_delivered()]), tmp_path=tmp_path).deliver()
    ledger = _ledger_for(stack)
    delivery_id = outcome.delivery_id
    state_path = ledger.state_path(delivery_id)

    # Corrupt bytes.
    original = state_path.read_bytes()
    state_path.write_bytes(b'{"contract": "monitoring_delivery_state_v1"')
    with pytest.raises(Exception, match="DELIVERY_POINTER_CONFLICT"):
        delivery_status_projection(ledger)

    # Valid JSON but non-canonical.
    payload = json.loads(original.decode("utf-8"))
    state_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    with pytest.raises(Exception, match="DELIVERY_POINTER_CONFLICT"):
        delivery_status_projection(ledger)

    # Canonical but foreign delivery identity in this slot.
    foreign = MonitoringDeliveryStateV1.build(
        delivery_id="ee" * 32,
        status="PENDING",
        terminal=False,
        attempt_count=0,
        intent_content_sha256="ef" * 32,
        updated_at=AS_OF,
    )
    state_path.write_bytes(foreign.canonical_bytes() + b"\n")
    with pytest.raises(Exception, match="DELIVERY_POINTER_CONFLICT"):
        delivery_status_projection(ledger)

    # Contradictory: terminal published pointer outruns its attempt set.
    state_path.write_bytes(original)
    ledger.attempt_path(delivery_id, 1).unlink()
    with pytest.raises(Exception, match="DELIVERY_POINTER_CONFLICT"):
        delivery_status_projection(ledger)


def test_status_reports_unresolved_dispatch_claim_read_only(tmp_path):
    stack = _terminal_stack(tmp_path)
    with pytest.raises(RuntimeError):
        _service(stack, _CrashAfterClaimTransport(), tmp_path=tmp_path).deliver()
    ledger = _ledger_for(stack)
    delivery_id = _delivery_id_for(stack)
    published_before = ledger.load_state(delivery_id)
    projection = delivery_status_projection(ledger)
    entry = projection["deliveries"][0]
    assert entry["state"]["status"] == "AMBIGUOUS"
    assert entry["state"]["last_error_code"] == "ORPHANED_DISPATCH"
    assert entry["unresolved_dispatch_claim"] == {
        "attempt_number": 1,
        "idempotency_key": delivery_id,
        "content_sha256": ledger.load_claim(delivery_id, 1).content_sha256,
    }
    assert entry["pointer_status"] == "STALE_REPAIRABLE"
    # Read-only: the on-disk pointer is untouched by the status projection.
    assert ledger.load_state(delivery_id) == published_before


def test_cli_delivery_status_corrupt_pointer_exits_two(tmp_path, capsys):
    from turtle_value_engine.cli import main

    stack = _terminal_stack(tmp_path)
    outcome = _service(stack, FakeTransport([_delivered()]), tmp_path=tmp_path).deliver()
    delivery_root = Path(stack.runner_store.root).parent / "delivery"
    (delivery_root / "state" / f"{outcome.delivery_id}.json").write_bytes(b"not json")
    rc = main(
        ["watch", "delivery-status", "--delivery-root", str(delivery_root)]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "DELIVERY_POINTER_CONFLICT" in captured.err


# --- corrupt / foreign / conflicting ledger -------------------------------


def test_corrupt_state_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    service.deliver()
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    path = ledger.state_path(delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    ))
    path.write_bytes(b'{"contract": "monitoring_delivery_state_v1"')
    with pytest.raises(DeliveryLedgerConflictError):
        _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()


def test_non_canonical_state_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    outcome = service.deliver()
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    path = ledger.state_path(outcome.delivery_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    with pytest.raises(DeliveryLedgerConflictError):
        _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()


def test_foreign_state_in_wrong_slot_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    delivery_id = delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )
    foreign = MonitoringDeliveryStateV1.build(
        delivery_id="ee" * 32,
        status="PENDING",
        terminal=False,
        attempt_count=0,
        intent_content_sha256="ef" * 32,
        updated_at=AS_OF,
    )
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    ledger.state_path(delivery_id).parent.mkdir(parents=True, exist_ok=True)
    ledger.state_path(delivery_id).write_bytes(foreign.canonical_bytes() + b"\n")
    with pytest.raises(DeliveryLedgerError, match="ledger slot"):
        ledger.load_state(delivery_id)
    with pytest.raises(DeliveryLedgerConflictError):
        _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()


def test_conflicting_published_state_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    service = _service(stack, transport, tmp_path=tmp_path)
    service.deliver()
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    delivery_id = delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )
    # A published terminal state that outruns the immutable attempt set
    # (attempt artifact removed) is impossible and must fail closed.
    ledger.attempt_path(delivery_id, 1).unlink()
    with pytest.raises(DeliveryLedgerConflictError):
        _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()


def test_conflicting_intent_content_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    first = _service(stack, transport, tmp_path=tmp_path, settings=_settings())
    first.deliver()
    with pytest.raises(DeliveryLedgerConflictError, match="different content"):
        _service(
            stack,
            FakeTransport([]),
            tmp_path=tmp_path,
            settings=_settings(max_attempts=9),
        ).deliver()


def test_corrupt_attempt_fails_closed(tmp_path):
    stack = _terminal_stack(tmp_path)
    delivery_id = delivery_identity(
        runner_id=RUNNER_ID,
        activation_id=ACTIVATION_ID,
        alert_batch_id=stack.alerts.alert_batch_id,
        destination_id="owner-primary",
    )
    ledger = DeliveryLedgerStore(Path(stack.runner_store.root).parent / "delivery")
    attempt = MonitoringDeliveryAttemptV1.build(
        delivery_id=delivery_id,
        attempt_number=1,
        started_at=AS_OF,
        finished_at=AS_OF,
        classification="RETRYABLE_FAILURE",
        http_status=503,
        response_body_sha256=None,
        error_code="HTTP_RETRYABLE_STATUS",
        retry_not_before=AS_OF,
    )
    ledger.save_attempt(attempt)
    path = ledger.attempt_path(delivery_id, 1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["http_status"] = 200
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    with pytest.raises(DeliveryLedgerConflictError):
        _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()


# --- secret hygiene --------------------------------------------------------


def test_secret_canaries_never_persist_or_leak(tmp_path, loopback_factory, capsys):
    from turtle_value_engine.cli import main

    stack = _terminal_stack(tmp_path)
    server = loopback_factory([("200", b"{}")])
    delivery_root = Path(stack.runner_store.root).parent / "delivery"

    transport = WebhookHttpTransport(allow_loopback_http=True)
    service = _service(
        stack, transport, tmp_path=tmp_path, endpoint=server.url,
        settings=_settings(),
    )
    outcome = service.deliver()
    assert outcome.status.value == "DELIVERED"

    all_files = _all_ledger_files(delivery_root)
    assert all_files
    status = _service(stack, FakeTransport([]), tmp_path=tmp_path).deliver()
    status_payload = {
        "delivery_id": status.delivery_id,
        "state": status.state.model_dump(mode="json"),
        "intent": status.intent.model_dump(mode="json"),
    }
    sources = {
        "ledger files": b"".join(all_files.values()),
        "status payload": json.dumps(status_payload).encode(),
        "outcome message": outcome.message.encode(),
    }
    for name, blob in sources.items():
        assert URL_SENTINEL.encode() not in blob, f"endpoint secret leaked into {name}"
        assert TOKEN_SENTINEL.encode() not in blob, f"bearer secret leaked into {name}"

    # Exception text from endpoint misconfiguration stays secret-free.  The
    # plain-http form is rejected by validation before any socket is created.
    with pytest.raises(WebhookEndpointError) as excinfo:
        WebhookHttpTransport().send(
            endpoint=f"http://example.invalid/hook?key={URL_SENTINEL}",
            auth_bearer=TOKEN_SENTINEL,
            request=WebhookRequest(b"{}", "k", 1.0, 1024),
        )
    assert URL_SENTINEL not in str(excinfo.value)
    assert TOKEN_SENTINEL not in str(excinfo.value)

    # CLI delivery-status output stays secret-free.
    rc = main(
        [
            "watch",
            "delivery-status",
            "--delivery-root",
            str(delivery_root),
            "--delivery-id",
            outcome.delivery_id,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert URL_SENTINEL not in captured.out
    assert TOKEN_SENTINEL not in captured.out


def test_project_config_safe_summary_shows_reference_names_only(tmp_path, monkeypatch):
    from turtle_value_engine.config import load_project_config

    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", f"https://example.invalid/{URL_SENTINEL}")
    source = Path("config/project.example.toml").read_text(encoding="utf-8")
    configured = source.replace("enabled = false\ntransport = \"webhook-v1\"",
                                "enabled = true\ntransport = \"webhook-v1\"")
    path = tmp_path / ".tve-private" / "project.toml"
    path.parent.mkdir()
    path.write_text(configured, encoding="utf-8")
    config = load_project_config(path)
    summary = repr(config.safe_summary())
    assert "TVE_MONITORING_WEBHOOK_URL" in summary
    assert URL_SENTINEL not in summary
    delivery = config.monitoring.delivery
    assert delivery.enabled is True
    assert delivery.endpoint_ref is not None
    assert delivery.endpoint_ref.env == "TVE_MONITORING_WEBHOOK_URL"
    assert delivery.max_attempts == 5


# --- CLI -------------------------------------------------------------------


def _runner_config_payload(tmp_path: Path) -> dict:
    return {
        "contract": "monitoring_runner_config_v1",
        "schema_version": "1.0.0",
        "runner_id": RUNNER_ID,
        "watchlist_path": str(tmp_path / "watchlist.json"),
        "monitoring_workspace_root": str(tmp_path / "monitoring"),
        "reanalysis_job_root": str(tmp_path / "jobs"),
        "cycle_store_root": str(tmp_path / "cycles"),
        "runner_root": str(tmp_path / "runner"),
        "cache_dir": str(tmp_path / "cache"),
        "source_id": "CNINFO",
        "adapter_version": "fixture-adapter-v1",
        "acquisition_policy_id": "monitoring-acquisition-v1",
        "acquisition_limit": 30,
        "network_allowed": False,
        "offline_replay": True,
        "timeout_seconds": 15.0,
        "max_response_bytes": 524288,
        "execution_catalog_path": None,
        "as_of": "2026-09-08T00:00:00Z",
        "published_from": "2026-06-01",
        "published_to": "2026-09-08",
        "window_days": None,
        "lease_ttl_seconds": 900,
    }


def _write_project_config(tmp_path: Path, *, enabled: bool) -> Path:
    source = Path("config/project.example.toml").read_text(encoding="utf-8")
    if enabled:
        source = source.replace(
            'enabled = false\ntransport = "webhook-v1"',
            'enabled = true\ntransport = "webhook-v1"',
        )
    path = tmp_path / "project.toml"
    path.write_text(source, encoding="utf-8")
    return path


def test_cli_deliver_requires_explicit_network_allow(tmp_path, monkeypatch, capsys):
    from turtle_value_engine.cli import main

    _terminal_stack(tmp_path)

    class SocketBlocked:
        def __init__(self, *args, **kwargs):
            raise AssertionError("denied CLI delivery attempted a socket")

    monkeypatch.setattr(socket, "socket", SocketBlocked)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://example.invalid/hook")
    runner_config = tmp_path / "runner.json"
    runner_config.write_text(
        json.dumps(_runner_config_payload(tmp_path)), encoding="utf-8"
    )
    project_config = _write_project_config(tmp_path, enabled=True)
    rc = main(
        [
            "watch",
            "deliver",
            "--runner-config",
            str(runner_config),
            "--project-config",
            str(project_config),
            "--network",
            "deny",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "DELIVERY_NETWORK_DENIED" in captured.err
    assert not (tmp_path / ".tve-private" / "monitoring" / "delivery").exists()


def test_cli_deliver_disabled_fails_closed(tmp_path, monkeypatch, capsys):
    from turtle_value_engine.cli import main

    _terminal_stack(tmp_path)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://example.invalid/hook")
    runner_config = tmp_path / "runner.json"
    runner_config.write_text(
        json.dumps(_runner_config_payload(tmp_path)), encoding="utf-8"
    )
    project_config = _write_project_config(tmp_path, enabled=False)
    rc = main(
        [
            "watch",
            "deliver",
            "--runner-config",
            str(runner_config),
            "--project-config",
            str(project_config),
            "--network",
            "allow",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "DELIVERY_DISABLED" in captured.err


def test_cli_deliver_success_payload_and_exit_zero(tmp_path, monkeypatch, capsys):
    import turtle_value_engine.cli as cli_module

    stack = _terminal_stack(tmp_path)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", f"https://hook.invalid/{URL_SENTINEL}")
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_TOKEN", TOKEN_SENTINEL)
    runner_config = tmp_path / "runner.json"
    runner_config.write_text(
        json.dumps(_runner_config_payload(tmp_path)), encoding="utf-8"
    )
    project_config = _write_project_config(tmp_path, enabled=True)
    transport = FakeTransport([_delivered()])
    monkeypatch.setattr(
        cli_module, "WebhookHttpTransport", lambda: transport
    )
    rc = cli_module.main(
        [
            "watch",
            "deliver",
            "--runner-config",
            str(runner_config),
            "--project-config",
            str(project_config),
            "--network",
            "allow",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0
    assert payload["classification"] == "DELIVERED"
    assert payload["http_requests"] == 1
    assert payload["attempt_count"] == 1
    assert payload["destination_id"] == "owner-primary"
    assert payload["alert_batch_id"] == stack.alerts.alert_batch_id
    assert URL_SENTINEL not in captured.out
    assert TOKEN_SENTINEL not in captured.out

    # A second CLI run performs zero additional requests.
    transport.script.append(_delivered())
    rc = cli_module.main(
        [
            "watch",
            "deliver",
            "--runner-config",
            str(runner_config),
            "--project-config",
            str(project_config),
            "--network",
            "allow",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["http_requests"] == 0
    assert payload["reused"] is True
    assert transport.calls == 1


def test_cli_deliver_reports_failure_states_with_exit_four(tmp_path, monkeypatch, capsys):
    import turtle_value_engine.cli as cli_module

    _terminal_stack(tmp_path)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://hook.invalid/x")
    runner_config = tmp_path / "runner.json"
    runner_config.write_text(
        json.dumps(_runner_config_payload(tmp_path)), encoding="utf-8"
    )
    project_config = _write_project_config(tmp_path, enabled=True)
    transport = FakeTransport([_permanent(410)])
    monkeypatch.setattr(cli_module, "WebhookHttpTransport", lambda: transport)
    rc = cli_module.main(
        [
            "watch",
            "deliver",
            "--runner-config",
            str(runner_config),
            "--project-config",
            str(project_config),
            "--network",
            "allow",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 4
    assert payload["classification"] == "PERMANENT_FAILURE"
    assert payload["last_http_status"] == 410


def test_cli_delivery_status_is_bounded_and_secret_free(tmp_path, capsys):
    from turtle_value_engine.cli import main

    stack = _terminal_stack(tmp_path)
    transport = FakeTransport([_delivered()])
    outcome = _service(stack, transport, tmp_path=tmp_path).deliver()
    delivery_root = Path(stack.runner_store.root).parent / "delivery"
    rc = main(
        [
            "watch",
            "delivery-status",
            "--delivery-root",
            str(delivery_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert len(payload["deliveries"]) == 1
    entry = payload["deliveries"][0]
    assert entry["delivery_id"] == outcome.delivery_id
    assert entry["state"]["status"] == "DELIVERED"
    assert entry["attempts"][0]["http_status"] == 200
    assert entry["pointer_published"] is True
    assert len(captured.out.encode()) < 64 * 1024

    rc = main(
        [
            "watch",
            "delivery-status",
            "--delivery-root",
            str(delivery_root),
            "--delivery-id",
            outcome.delivery_id,
            "--activation-id",
            ACTIVATION_ID,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(payload["deliveries"]) == 1

    rc = main(
        [
            "watch",
            "delivery-status",
            "--delivery-root",
            str(delivery_root),
            "--delivery-id",
            outcome.delivery_id,
            "--activation-id",
            "99" * 32,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["deliveries"] == []


# --- import isolation -------------------------------------------------------


def _run_isolated(code: str) -> None:
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=ROOT,
        capture_output=True,
    )


def test_delivery_package_modules_import_no_provider_research_or_pipeline():
    """Static check: the delivery package never imports those layers directly.

    Importing the Phase 6-D1 ``monitoring_cycle`` package transitively loads
    the D1 runner's own dependencies, so the meaningful invariant is that no
    delivery module itself imports a provider, research, pipeline or
    preparation module.
    """

    import ast

    forbidden_prefixes = (
        "turtle_value_engine.providers",
        "turtle_value_engine.research",
        "turtle_value_engine.pipeline",
        "turtle_value_engine.preparation",
    )
    package_root = ROOT / "src" / "turtle_value_engine" / "monitoring_delivery"
    assert package_root.is_dir()
    for module_path in sorted(package_root.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(forbidden_prefixes), (
                    f"{module_path.name} imports forbidden module {name}"
                )


def test_lower_monitoring_packages_do_not_import_delivery():
    _run_isolated(
        "import sys, turtle_value_engine.monitoring_runner; "
        "sys.exit(1 if 'turtle_value_engine.monitoring_delivery' in sys.modules else 0)"
    )
