"""Automatic Phase 6-D2B notification-delivery and ledger matrix.

Every test drives the delivery boundary through its public service/CLI
surfaces over genuine terminal Phase 6-D1/D2A artifacts produced by injected
fakes, a loopback HTTP receiver or an injected transport.  No public
Internet, live provider, model or real sleep is used anywhere in this
module.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import socket
import subprocess
import sys
import threading
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
    DeliveryNetworkDeniedError,
    DeliverySettingsV1,
    DeliverySourceError,
    MonitoringDeliveryAttemptV1,
    MonitoringDeliveryIntentV1,
    MonitoringDeliveryService,
    MonitoringDeliveryStateV1,
    MonitoringWebhookPayloadV1,
    TransportOutcome,
    WebhookEndpointError,
    WebhookHttpTransport,
    WebhookRequest,
    backoff_seconds,
    build_webhook_payload,
    delivery_identity,
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


def test_crash_after_intent_before_request_resumes_same_delivery(tmp_path):
    stack = _terminal_stack(tmp_path)

    class CrashBeforeRequest(FakeTransport):
        def send(self, **kwargs):
            raise RuntimeError("simulated crash before the outbound request")

    service = _service(stack, CrashBeforeRequest([]), tmp_path=tmp_path)
    with pytest.raises(RuntimeError, match="crash before the outbound request"):
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
