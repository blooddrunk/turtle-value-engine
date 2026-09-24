"""Automatic Phase 6-D3 read-only monitoring operations projection/API matrix.

Every test drives the D3 projection and API through their public boundaries
over genuine Phase 6-A/6-C/D1/D2A/D2B/R1/R2 artifacts produced by injected or
already-proven fakes.  No provider, acquisition, model, research, cycle
execution, delivery transport, retry/resend, repair or mutation path is
invoked by the projection itself anywhere in this module.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_monitoring_delivery import (
    TOKEN_SENTINEL,
    URL_SENTINEL,
    FakeTransport,
    _ambiguous,
    _CrashAfterDispatchTransport,
    _delivered,
    _permanent,
    _PointerFailAfter,
    _retryable,
    _settings,
)
from tests.test_monitoring_delivery import (
    _service as _delivery_service,
)
from tests.test_monitoring_runner import (
    RUNNER_ID,
    CountingBindingResolver,
    CrashingD1,
    FakeAcquisition,
    RealD1,
    RunnerCompletion,
    RunnerLease,
    RunnerLeaseBusyError,
    _batch,
    _config,
    _config_payload,
    _watchlist,
    _write_watchlist,
)
from tests.test_monitoring_runner import (
    _service as _runner_service,
)
from tests.test_surface_api import _snapshot
from turtle_value_engine.monitoring import MonitoringEventBatchV1, WatchlistSpecV1
from turtle_value_engine.monitoring_cycle import (
    MonitoringCycleStore,
    MonitoringExecutionBindingV1,
    MonitoringExecutionCatalogV1,
)
from turtle_value_engine.monitoring_delivery import (
    DeliveryLedgerConflictError,
    DeliveryLedgerStore,
    MonitoringDeliveryStateV1,
)
from turtle_value_engine.monitoring_operations import (
    MonitoringOperationsConflictError,
    MonitoringOperationsProjectionV1,
    MonitoringOperationsReadService,
    MonitoringOperationsSourcesError,
    build_monitoring_operations_projection,
    sources_from_runner_config,
)
from turtle_value_engine.monitoring_runner import RunnerStore
from turtle_value_engine.monitoring_runner import lease as lease_module
from turtle_value_engine.surface import SurfaceRegistry, create_surface_app

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 8, tzinfo=UTC)
WATCHLIST_ID = "phase6d2a-test"


# --- shared fixtures -------------------------------------------------------


def _write_catalog(tmp_path: Path) -> str:
    catalog = MonitoringExecutionCatalogV1.build(
        [MonitoringExecutionBindingV1(listing_id="SH600001", resolver_key="fixture")]
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog.model_dump(mode="json")), encoding="utf-8")
    return str(path)


def _run_chain(
    tmp_path: Path,
    *,
    event_type: str | None = None,
    binding: bool = False,
    d1=None,
) -> SimpleNamespace:
    """Run one genuine D2A activation over injected fakes inside ``tmp_path``."""

    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    overrides: dict[str, object] = {}
    if binding:
        overrides["execution_catalog_path"] = _write_catalog(tmp_path)
    config = _config(tmp_path, **overrides)
    if d1 is None:
        batch = (
            MonitoringEventBatchV1.build([]) if event_type is None else _batch(event_type)
        )
        resolver = CountingBindingResolver() if binding else None
        d1 = RealD1(tmp_path, FakeAcquisition(batch), resolver=resolver)
    outcome = _runner_service(config, d1).run()
    return SimpleNamespace(config=config, d1=d1, outcome=outcome)


def _sources(chain: SimpleNamespace, tmp_path: Path, *, delivery: bool = True):
    return sources_from_runner_config(
        chain.config,
        delivery_root=str(tmp_path / "delivery") if delivery else None,
    )


def _projection(
    chain: SimpleNamespace, tmp_path: Path, *, delivery: bool = True
) -> MonitoringOperationsProjectionV1:
    return build_monitoring_operations_projection(_sources(chain, tmp_path, delivery=delivery))


def _delivery_stack(chain: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        runner_store=RunnerStore(chain.config.runner_root),
        cycles=MonitoringCycleStore(chain.config.cycle_store_root),
    )


def _deliver(
    chain: SimpleNamespace,
    tmp_path: Path,
    transport,
    *,
    settings=None,
    failure_injector=None,
):
    return _delivery_service(
        _delivery_stack(chain),
        transport,
        tmp_path=tmp_path,
        settings=settings,
        failure_injector=failure_injector,
    ).deliver()


def _inventory(root: Path) -> dict[str, bytes | None]:
    """Full recursive file/dir inventory used for zero-mutation proofs."""

    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): (None if path.is_dir() else path.read_bytes())
        for path in sorted(root.rglob("*"))
    }


def _client(app):
    testclient = pytest.importorskip("fastapi.testclient")
    return testclient.TestClient(app)


def _monitoring_app(chain: SimpleNamespace, tmp_path: Path):
    service = MonitoringOperationsReadService(_sources(chain, tmp_path))
    return create_surface_app(
        SurfaceRegistry.from_snapshots([_snapshot()]), monitoring_service=service
    )


# --- 9.1 projection/service tests ------------------------------------------


def test_empty_configured_stores_produce_honest_empty_projection(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    chain = SimpleNamespace(config=_config(tmp_path))
    before = _inventory(tmp_path)

    projection = _projection(chain, tmp_path)

    assert projection.contract == "monitoring_operations_projection_v1"
    assert projection.runner_id == RUNNER_ID
    assert projection.watchlist.watchlist_id == WATCHLIST_ID
    assert projection.watchlist.availability == "NOT_AVAILABLE"
    assert projection.runner.lease_state == "FREE"
    assert projection.runner.lease_corrupt is False
    assert projection.runner.lease_record is None
    assert projection.runner.unfinished_activation_ids == []
    assert projection.runner.latest_terminal_activation_id is None
    assert projection.activation is None
    assert projection.cycle is None
    assert projection.jobs == []
    assert projection.deliveries_configured is True
    assert projection.deliveries == []
    # Reading empty stores created nothing.
    assert _inventory(tmp_path) == before


def test_committed_chain_projects_exact_end_to_end_identities(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    outcome = chain.outcome
    delivery_outcome = _deliver(chain, tmp_path, FakeTransport([_delivered(200)]))

    projection = _projection(chain, tmp_path)

    assert projection.watchlist.availability == "AVAILABLE"
    assert projection.watchlist.watchlist_id == WATCHLIST_ID
    assert projection.watchlist.entries[0].listing_id == "SH600001"
    assert projection.watchlist.entries[0].processed_event_count == 1

    runner = projection.runner
    assert runner.lease_state == "ABANDONED"
    assert runner.lease_corrupt is False
    assert runner.lease_record is not None
    assert runner.lease_record.runner_id == RUNNER_ID
    assert runner.lease_record.activation_id == outcome.activation.activation_id
    assert runner.unfinished_activation_ids == []
    assert runner.latest_terminal_activation_id == outcome.activation.activation_id

    activation = projection.activation
    assert activation is not None
    assert activation.kind == "LATEST_TERMINAL"
    assert activation.activation_id == outcome.activation.activation_id
    assert activation.runner_id == RUNNER_ID
    assert activation.cycle_id == outcome.result.cycle_id
    assert activation.as_of == AS_OF
    assert activation.intent_content_sha256 == outcome.activation.content_sha256
    assert activation.request_fingerprint == outcome.activation.request_fingerprint
    assert activation.receipt is not None
    assert activation.receipt.classification == "CYCLE_TERMINAL"
    assert activation.receipt.content_sha256 == outcome.receipt.content_sha256
    assert activation.receipt.d1_status == outcome.result.status.value
    assert activation.receipt.result_content_sha256 == outcome.result.content_sha256
    assert activation.receipt.alert_batch_id == outcome.alert_batch.alert_batch_id

    cycle = projection.cycle
    assert cycle is not None
    assert cycle.cycle_id == outcome.result.cycle_id
    assert cycle.status.value == "ALERTS_EMITTED"
    assert cycle.failure_code is None
    assert cycle.watchlist_id == WATCHLIST_ID
    assert cycle.pointer_published is True
    assert cycle.alert_count == len(outcome.alert_batch.alerts) > 0
    assert len(cycle.alerts) == cycle.alert_count
    assert cycle.result_content_sha256 == outcome.result.content_sha256
    assert cycle.alert_batch_id == outcome.alert_batch.alert_batch_id
    assert cycle.alert_batch_content_sha256 == outcome.alert_batch.content_sha256

    assert len(projection.jobs) == 1
    disposition = outcome.result.execution[0]
    job = projection.jobs[0]
    assert job.request_id == disposition.request_id
    assert job.job_id == disposition.job_id
    assert job.job_content_sha256 == disposition.job_content_sha256
    assert job.listing_id == "SH600001"
    assert job.impact.value == disposition.impact.value
    assert job.resolution == "RESOLVED"
    assert job.disposition_status.value == "SUCCEEDED"
    assert job.disposition_failure_code is None
    assert job.job is not None
    assert job.job.status.value == "SUCCEEDED"
    assert job.job.attempt_number == 1

    assert projection.deliveries_configured is True
    assert len(projection.deliveries) == 1
    delivery = projection.deliveries[0]
    assert delivery.delivery_id == delivery_outcome.delivery_id
    assert delivery.runner_id == RUNNER_ID
    assert delivery.activation_id == activation.activation_id
    assert delivery.cycle_id == cycle.cycle_id
    assert delivery.alert_batch_id == outcome.alert_batch.alert_batch_id
    assert delivery.destination_id == "owner-primary"
    assert delivery.empty_outbox is False
    assert delivery.state.status.value == "DELIVERED"
    assert delivery.state.terminal is True
    assert delivery.state.attempt_count == 1
    assert delivery.dispatch_claim_count == 1
    assert delivery.unresolved_claim_numbers == []
    assert delivery.unresolved_dispatch_claim is None
    assert delivery.pointer_published is True
    assert delivery.pointer_status == "CURRENT"
    assert [attempt.attempt_number for attempt in delivery.attempts] == [1]
    assert delivery.attempts[0].classification == "DELIVERED"
    assert delivery.attempts[0].http_status == 200


def test_active_unfinished_activation_is_not_confused_with_terminal(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    crashing = CrashingD1(
        RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    )
    with pytest.raises(RuntimeError, match="simulated crash inside the D1 boundary"):
        _runner_service(config, crashing).run()
    chain = SimpleNamespace(config=config)

    projection = _projection(chain, tmp_path)

    activation = projection.activation
    assert activation is not None
    assert activation.kind == "ACTIVE"
    assert activation.receipt is None
    assert projection.runner.unfinished_activation_ids == [activation.activation_id]
    # The unfinished activation is never presented as a terminal receipt.
    assert projection.runner.latest_terminal_activation_id is None
    assert projection.cycle is None
    assert projection.jobs == []
    assert projection.deliveries == []


@pytest.mark.parametrize(
    ("event_type", "binding", "expected_job_status", "expected_resolution"),
    [
        ("ANNUAL_REPORT", True, "BLOCKED", "UNRESOLVED"),
        ("PROFIT_WARNING", False, "MANUAL_REVIEW_REQUIRED", "RESOLVED"),
        ("INTERIM_REPORT", False, "FAILED", "UNRESOLVED"),
    ],
    ids=["blocked", "manual-review", "failed"],
)
def test_d1_attention_states_remain_distinct(
    tmp_path, event_type, binding, expected_job_status, expected_resolution
):
    chain = _run_chain(tmp_path, event_type=event_type, binding=binding)

    projection = _projection(chain, tmp_path, delivery=False)

    cycle = projection.cycle
    assert cycle is not None
    # All three are committed terminal D1 attention cycles, never a generic ok
    # and never the D1-level FAILED state.
    assert cycle.status.value == "ATTENTION_REQUIRED"
    assert len(projection.jobs) == 1
    job = projection.jobs[0]
    assert job.disposition_status is not None
    assert job.disposition_status.value == expected_job_status
    assert job.resolution == expected_resolution
    if expected_job_status == "BLOCKED":
        assert job.disposition_failure_code == "BLOCKED_RESEARCH_RUNTIME"
    assert projection.deliveries_configured is False
    assert projection.deliveries == []


def test_job_terminal_facts_are_exact(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=False)

    projection = _projection(chain, tmp_path, delivery=False)

    job = projection.jobs[0]
    assert job.disposition_status is not None
    assert job.disposition_status.value == "FAILED"
    assert job.job is not None
    stored = chain.d1.jobs.load_latest(job.job_id)
    assert stored is not None
    detail = job.job
    assert detail.status is stored.job.status
    assert detail.failure_code == (
        None if stored.job.failure_code is None else stored.job.failure_code.value
    )
    assert detail.message == stored.job.message
    assert detail.attempt_number == stored.attempt_number
    assert detail.evidence_codes == list(stored.job.evidence_codes)


@pytest.mark.parametrize(
    "case", ["delivered", "retryable", "permanent", "ambiguous", "noop"]
)
def test_delivery_terminal_states_remain_exact(tmp_path, case):
    case_dir = tmp_path / case
    case_dir.mkdir()
    if case == "noop":
        chain = _run_chain(case_dir, event_type=None, binding=False)
        transport = FakeTransport([])
        _deliver(chain, case_dir, transport)
        assert transport.calls == 0
    elif case == "retryable":
        chain = _run_chain(case_dir, event_type="INTERIM_REPORT", binding=True)
        _deliver(
            chain,
            case_dir,
            FakeTransport([_retryable(503)]),
            settings=_settings(backoff_base_seconds=120),
        )
    else:
        chain = _run_chain(case_dir, event_type="INTERIM_REPORT", binding=True)
        script = {
            "delivered": [_delivered(200)],
            "permanent": [_permanent(404)],
            "ambiguous": [_ambiguous()],
        }[case]
        _deliver(chain, case_dir, FakeTransport(script))

    delivery = _projection(chain, case_dir).deliveries[0]

    expected = {
        "delivered": ("DELIVERED", True, 1),
        "retryable": ("RETRYABLE_FAILURE", False, 1),
        "permanent": ("PERMANENT_FAILURE", True, 1),
        "ambiguous": ("AMBIGUOUS", True, 1),
        "noop": ("NOOP", True, 0),
    }[case]
    assert delivery.state.status.value == expected[0]
    assert delivery.state.terminal is expected[1]
    assert delivery.state.attempt_count == expected[2]
    assert delivery.dispatch_claim_count == expected[2]
    assert delivery.empty_outbox is (case == "noop")
    assert [attempt.attempt_number for attempt in delivery.attempts] == list(
        range(1, expected[2] + 1)
    )
    assert delivery.unresolved_claim_numbers == []
    assert delivery.unresolved_dispatch_claim is None
    assert delivery.pointer_status == "CURRENT"
    if case == "delivered":
        assert delivery.state.last_http_status == 200
    if case == "retryable":
        assert delivery.state.next_attempt_not_before is not None
        assert delivery.state.last_error_code.value == "HTTP_RETRYABLE_STATUS"
    if case == "permanent":
        assert delivery.state.last_error_code.value == "HTTP_PERMANENT_STATUS"
    if case == "ambiguous":
        assert delivery.state.last_error_code.value == "TIMEOUT_AFTER_DISPATCH"


def test_r2_orphan_proves_outcome_count_differs_from_consumed_slots(tmp_path):
    """max_attempts=1 + declared idempotency + crash after possible dispatch.

    The durable dispatch claim consumed the only authorized outbound slot
    while no attempt outcome ever became durable: the projection must expose
    the two counts as distinct facts and keep the unresolved slot number.
    """

    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    settings = _settings(max_attempts=1, receiver_idempotency_declared=True)
    crashing = _CrashAfterDispatchTransport()
    with pytest.raises(RuntimeError, match="after possible dispatch"):
        _deliver(chain, tmp_path, crashing, settings=settings)

    delivery = _projection(chain, tmp_path).deliveries[0]

    assert delivery.state.status.value == "AMBIGUOUS"
    assert delivery.state.last_error_code.value == "ORPHANED_DISPATCH"
    # Persisted delivery outcomes: none. Consumed authorized slots: one.
    assert delivery.state.attempt_count == 0
    assert delivery.attempts == []
    assert delivery.dispatch_claim_count == 1
    assert delivery.unresolved_claim_numbers == [1]
    assert delivery.unresolved_dispatch_claim is not None
    assert delivery.unresolved_dispatch_claim.attempt_number == 1
    assert delivery.unresolved_dispatch_claim.idempotency_key == delivery.delivery_id
    # Exactly one transport entry ever happened in this ledger's lifetime.
    assert crashing.calls == 1


def test_delivery_pointer_missing_and_stale_repairable_are_visible(tmp_path):
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()
    chain = _run_chain(missing_dir, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, missing_dir, FakeTransport([_delivered()]))
    delivery = _projection(chain, missing_dir).deliveries[0]
    assert delivery.pointer_status == "CURRENT"
    ledger = DeliveryLedgerStore(missing_dir / "delivery")
    state_path = ledger.state_path(delivery.delivery_id)
    state_path.unlink()

    repaired = _projection(chain, missing_dir).deliveries[0]
    assert repaired.pointer_status == "MISSING"
    assert repaired.pointer_published is False
    # The derived terminal truth stays visible and nothing was repaired.
    assert repaired.state.status.value == "DELIVERED"
    assert not state_path.exists()

    stale_dir = tmp_path / "stale"
    stale_dir.mkdir()
    chain = _run_chain(stale_dir, event_type="INTERIM_REPORT", binding=True)
    injector = _PointerFailAfter(fail_on=2)
    with pytest.raises(DeliveryLedgerConflictError, match="delivery ledger write failed"):
        _deliver(
            chain,
            stale_dir,
            FakeTransport([_delivered()]),
            failure_injector=injector,
        )

    stale = _projection(chain, stale_dir).deliveries[0]
    assert stale.pointer_status == "STALE_REPAIRABLE"
    assert stale.pointer_published is True
    assert stale.state.status.value == "DELIVERED"
    assert stale.state.attempt_count == 1


def test_corrupt_foreign_contradictory_evidence_fails_closed(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, tmp_path, FakeTransport([_delivered()]))
    delivery = _projection(chain, tmp_path).deliveries[0]
    ledger = DeliveryLedgerStore(tmp_path / "delivery")
    state_path = ledger.state_path(delivery.delivery_id)
    original = state_path.read_bytes()

    def assert_conflict() -> None:
        with pytest.raises(MonitoringOperationsConflictError) as exc_info:
            _projection(chain, tmp_path)
        assert exc_info.value.code == "MONITORING_OPERATIONS_CONFLICT"
        # The stable error never leaks local absolute paths.
        assert str(tmp_path) not in str(exc_info.value)

    # Corrupt bytes.
    state_path.write_bytes(b'{"contract": "monitoring_delivery_state_v1"')
    assert_conflict()

    # Valid JSON but non-canonical.
    payload = json.loads(original.decode("utf-8"))
    state_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    assert_conflict()

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
    assert_conflict()

    # Contradictory: terminal published pointer outruns its attempt set.
    state_path.write_bytes(original)
    ledger.attempt_path(delivery.delivery_id, 1).unlink()
    assert_conflict()


def test_invalid_configured_sources_fail_closed_without_path_leak(tmp_path):
    chain = SimpleNamespace(config=_config(tmp_path))  # watchlist never written

    with pytest.raises(MonitoringOperationsSourcesError) as exc_info:
        _projection(chain, tmp_path)

    assert exc_info.value.code == "MONITORING_OPERATIONS_SOURCES_INVALID"
    assert str(tmp_path) not in str(exc_info.value)


def test_projection_invokes_no_provider_model_cycle_or_transport(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path, execution_catalog_path=_write_catalog(tmp_path))
    acquisition = FakeAcquisition(_batch("INTERIM_REPORT"))
    resolver = CountingBindingResolver()
    d1 = RealD1(tmp_path, acquisition, resolver=resolver)
    _runner_service(config, d1).run()
    chain = SimpleNamespace(config=config)
    transport = FakeTransport([_delivered()])
    _deliver(chain, tmp_path, transport)
    counters = (acquisition.calls, len(resolver.calls), d1.calls, transport.calls)

    for _ in range(3):
        _projection(chain, tmp_path)

    # Projection reads never re-enter acquisition, binding resolution, D1
    # cycle execution or the delivery transport.
    assert (acquisition.calls, len(resolver.calls), d1.calls, transport.calls) == counters


def test_projection_reads_leave_every_source_store_byte_identical(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, tmp_path, FakeTransport([_delivered()]))
    before = _inventory(tmp_path)

    for _ in range(2):
        _projection(chain, tmp_path)

    assert _inventory(tmp_path) == before


def test_serialized_projection_contains_no_secret_or_local_root(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, tmp_path, FakeTransport([_delivered()]))

    projection = _projection(chain, tmp_path)
    payload = json.dumps(projection.model_dump(mode="json"), ensure_ascii=False)

    for sentinel in (URL_SENTINEL, TOKEN_SENTINEL, str(tmp_path), "delivery_root"):
        assert sentinel not in payload


def test_projection_schema_snapshot_is_stable():
    checked_in = json.loads(
        (ROOT / "schemas" / "monitoring-operations-projection.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert MonitoringOperationsProjectionV1.model_json_schema() == checked_in


# --- 9.2 API tests -----------------------------------------------------------


def test_monitoring_endpoint_returns_generated_typed_response(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, tmp_path, FakeTransport([_delivered(200)]))
    client = _client(_monitoring_app(chain, tmp_path))

    response = client.get("/v1/monitoring/operations")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    typed = MonitoringOperationsProjectionV1.model_validate(response.json())
    assert typed.activation is not None
    assert typed.activation.activation_id == chain.outcome.activation.activation_id
    assert typed.activation.kind == "LATEST_TERMINAL"
    assert typed.cycle is not None
    assert typed.cycle.status.value == "ALERTS_EMITTED"
    assert len(typed.deliveries) == 1
    # The R2 pair survives the API boundary as distinct values.
    assert response.json()["deliveries"][0]["state"]["attempt_count"] == 1
    assert response.json()["deliveries"][0]["dispatch_claim_count"] == 1
    assert str(tmp_path) not in response.text

    rejected = client.get("/v1/monitoring/operations", params={"runner_id": "x"})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "INVALID_QUERY_PARAMETER"


def test_surface_only_app_construction_still_works_without_monitoring():
    app = create_surface_app(SurfaceRegistry.from_snapshots([_snapshot()]))
    client = _client(app)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    missing = client.get("/v1/monitoring/operations")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MONITORING_OPERATIONS_NOT_FOUND"


def test_no_monitoring_mutation_endpoint_exists(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, tmp_path, FakeTransport([_delivered()]))
    client = _client(_monitoring_app(chain, tmp_path))
    before = _inventory(tmp_path)

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, "/v1/monitoring/operations", json={})
        assert response.status_code == 405
        assert response.json()["error"]["code"] == "READ_ONLY_METHOD_NOT_ALLOWED"
        assert response.headers["Cache-Control"] == "no-store"

    assert _inventory(tmp_path) == before


def test_unknown_monitoring_subpaths_fail_closed(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    client = _client(_monitoring_app(chain, tmp_path))

    for path in (
        "/v1/monitoring",
        "/v1/monitoring/other",
        "/v1/monitoring/operations/retry",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MONITORING_OPERATIONS_NOT_FOUND"
        assert response.headers["Cache-Control"] == "no-store"


def test_fail_closed_api_error_contains_no_path_or_secret(tmp_path):
    chain = _run_chain(tmp_path, event_type="INTERIM_REPORT", binding=True)
    _deliver(chain, tmp_path, FakeTransport([_delivered()]))
    delivery = _projection(chain, tmp_path).deliveries[0]
    ledger = DeliveryLedgerStore(tmp_path / "delivery")
    ledger.state_path(delivery.delivery_id).write_bytes(
        b'{"contract": "monitoring_delivery_state_v1"'
    )
    client = _client(_monitoring_app(chain, tmp_path))

    response = client.get("/v1/monitoring/operations")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MONITORING_OPERATIONS_CONFLICT"
    assert response.headers["Cache-Control"] == "no-store"
    assert str(tmp_path) not in response.text
    assert URL_SENTINEL not in response.text
    assert TOKEN_SENTINEL not in response.text


def test_openapi_export_is_deterministic_and_drift_checked():
    result = subprocess.run(
        [sys.executable, "scripts/export_surface_openapi.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- 9.6 Phase 6-D3-R1: non-interfering observation under real concurrency ---

_BARRIER_DEADLINE_SECONDS = 60.0


def _wait_for_marker(path: Path, *, what: str) -> None:
    deadline = time.monotonic() + _BARRIER_DEADLINE_SECONDS
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"the {what} never signalled {path}")
        time.sleep(0.01)


_D3_OBSERVER_CHILD = r"""
import fcntl
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[2])

from turtle_value_engine.monitoring_operations import (
    build_monitoring_operations_projection,
    sources_from_runner_config,
)
from turtle_value_engine.monitoring_runner import RunnerConfigV1
from turtle_value_engine.monitoring_runner import lease as lease_module

spec = json.loads(sys.argv[1])
entered = Path(spec["entered"])
release = Path(spec["release"])
result = Path(spec["result"])


def forbidden_flock(descriptor, operation):
    raise AssertionError("D3 observation attempted to take an OS lock")


fcntl.flock = forbidden_flock

real_scan = lease_module._scan_flock_holder


def pausing_scan(*args, **kwargs):
    outcome = real_scan(*args, **kwargs)
    entered.write_text("1", encoding="utf-8")
    deadline = time.monotonic() + 60.0
    while not release.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("observation release barrier timeout")
        time.sleep(0.01)
    return outcome


lease_module._scan_flock_holder = pausing_scan

config = RunnerConfigV1.model_validate(
    json.loads(Path(spec["config"]).read_text(encoding="utf-8"))
)
sources = sources_from_runner_config(
    config, delivery_root=spec.get("delivery_root")
)
try:
    projection = build_monitoring_operations_projection(sources)
    payload = {
        "error": None,
        "lease_state": projection.runner.lease_state,
        "lease_corrupt": projection.runner.lease_corrupt,
        "lease_record_activation_id": (
            None
            if projection.runner.lease_record is None
            else projection.runner.lease_record.activation_id
        ),
    }
except BaseException as exc:  # noqa: BLE001 - the failure IS the observation result
    payload = {"error": f"{type(exc).__name__}: {exc}"}
result.write_text(json.dumps(payload), encoding="utf-8")
"""

_REAL_HOLDER_CHILD = r"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[2])

from turtle_value_engine.monitoring_runner import RunnerLease

spec = json.loads(sys.argv[1])
entered = Path(spec["entered"])
release = Path(spec["release"])

lease = RunnerLease(spec["runner_root"], spec["runner_id"])
with lease.held() as handle:
    handle.record(None)
    entered.write_text("1", encoding="utf-8")
    deadline = time.monotonic() + 60.0
    while not release.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("holder release barrier timeout")
        time.sleep(0.01)
"""


def _spawn_child(script: str, spec: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script, json.dumps(spec), str(ROOT / "src")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_d3_observation_paused_mid_probe_cannot_busy_real_runner(tmp_path):
    """Case 1: no real holder, the D3 read is held inside its critical
    observation section, and the real runner must still enter D1 exactly
    once and reach its terminal result (6-D3-R1)."""

    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    # The lease slot exists with no live holder, so the observation enters
    # its real critical section instead of exiting early as FREE.
    lease = RunnerLease(config.runner_root, RUNNER_ID)
    lease.path.parent.mkdir(parents=True, exist_ok=True)
    lease.path.touch()

    config_path = tmp_path / "runner-config.json"
    config_path.write_text(
        json.dumps(_config_payload(tmp_path), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    entered = tmp_path / "observer-entered"
    release = tmp_path / "observer-release"
    result = tmp_path / "observer-result.json"
    observer = _spawn_child(
        _D3_OBSERVER_CHILD,
        {
            "entered": str(entered),
            "release": str(release),
            "result": str(result),
            "config": str(config_path),
            "delivery_root": str(tmp_path / "delivery"),
        },
    )
    try:
        _wait_for_marker(entered, what="D3 observer")

        # While the observation is provably inside its critical section, the
        # real unattended runner must run to its terminal result.
        acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
        d1 = RealD1(tmp_path, acquisition)
        outcome = _runner_service(config, d1).run()

        assert outcome.classification is RunnerCompletion.COMPLETED_NEW
        assert d1.calls == 1
        assert acquisition.calls == 1

        release.write_text("1", encoding="utf-8")
        stdout, stderr = observer.communicate(timeout=_BARRIER_DEADLINE_SECONDS)
        assert observer.returncode == 0, f"observer failed: {stderr}\n{stdout}"
        payload = json.loads(result.read_text(encoding="utf-8"))

        # The observer finished cleanly, took zero OS locks (any attempt
        # raised inside the child), and converged on the post-run record.
        assert payload["error"] is None, payload["error"]
        assert payload["lease_state"] == "ABANDONED"
        assert payload["lease_corrupt"] is False
        assert payload["lease_record_activation_id"] == outcome.activation.activation_id
    finally:
        if observer.poll() is None:
            observer.kill()
            observer.communicate()


def test_real_holder_remains_authoritative_while_d3_observes(tmp_path, monkeypatch):
    """Case 2: a genuine live holder still wins; the D3 read takes no
    conflicting authority and reports only kernel-proven truth."""

    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    chain = SimpleNamespace(config=config)

    entered = tmp_path / "holder-entered"
    release = tmp_path / "holder-release"
    holder = _spawn_child(
        _REAL_HOLDER_CHILD,
        {
            "entered": str(entered),
            "release": str(release),
            "runner_root": config.runner_root,
            "runner_id": RUNNER_ID,
        },
    )
    try:
        _wait_for_marker(entered, what="real lease holder")

        # The D3 observation runs while the holder owns the kernel lock.  It
        # must take no OS lock itself (any flock attempt raises here) and
        # must prove LIVE from the passive kernel lock table.
        def forbidden_flock(descriptor, operation):
            raise AssertionError("D3 observation attempted to take an OS lock")

        monkeypatch.setattr(fcntl, "flock", forbidden_flock)
        projection = build_monitoring_operations_projection(
            sources_from_runner_config(chain.config, delivery_root=None)
        )
        monkeypatch.undo()
        assert projection.runner.lease_state == "LIVE"
        assert projection.runner.lease_record is not None
        assert projection.runner.lease_record.runner_id == RUNNER_ID

        # A competing real runner still fails fast with zero work.
        acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
        d1 = RealD1(tmp_path, acquisition)
        with pytest.raises(RunnerLeaseBusyError):
            _runner_service(config, d1).run()
        assert d1.calls == 0
        assert acquisition.calls == 0

        release.write_text("1", encoding="utf-8")
        stdout, stderr = holder.communicate(timeout=_BARRIER_DEADLINE_SECONDS)
        assert holder.returncode == 0, f"holder failed: {stderr}\n{stdout}"

        # After the genuine holder exits, the slot is usable again.
        outcome = _runner_service(config, d1).run()
        assert outcome.classification is RunnerCompletion.COMPLETED_NEW
        assert d1.calls == 1
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate()


def test_bounded_observer_runner_matrix_has_zero_observer_induced_busy(
    tmp_path, monkeypatch
):
    """Case 3: a tightly coordinated repeated observer+runner matrix with no
    real holder produces exactly zero observer-induced LEASE_BUSY outcomes."""

    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    lease = RunnerLease(config.runner_root, RUNNER_ID)
    lease.path.parent.mkdir(parents=True, exist_ok=True)
    lease.path.touch()

    acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    d1 = RealD1(tmp_path, acquisition)
    sources = sources_from_runner_config(config, delivery_root=None)

    real_scan = lease_module._scan_flock_holder
    real_flock = fcntl.flock
    observer_thread: list[threading.Thread] = []
    violations: list[int] = []

    def recording_flock(descriptor, operation):
        if observer_thread and threading.current_thread() is observer_thread[0]:
            violations.append(operation)
        return real_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", recording_flock)

    iterations = 10
    for index in range(iterations):
        # A unique watchlist identity gives every invocation a fresh
        # activation fingerprint, so each run performs real D1 work.
        _write_watchlist(
            tmp_path / "watchlist.json",
            WatchlistSpecV1.build(
                watchlist_id=f"phase6d3r1-matrix-{index}",
                profile_id="strict-v1",
                entries=[{"listing_id": "SH600001", "company_display_name": "fixture"}],
            ),
        )
        inside = threading.Event()
        release = threading.Event()
        box: dict[str, object] = {}

        def pausing_scan(*args, **kwargs):
            outcome_scan = real_scan(*args, **kwargs)
            inside.set()
            if not release.wait(timeout=_BARRIER_DEADLINE_SECONDS):
                raise RuntimeError("observation release barrier timeout")
            return outcome_scan

        monkeypatch.setattr(lease_module, "_scan_flock_holder", pausing_scan)

        def observe() -> None:
            try:
                box["projection"] = build_monitoring_operations_projection(sources)
            except BaseException as exc:  # noqa: BLE001 - recorded for the assert
                box["error"] = f"{type(exc).__name__}: {exc}"

        observer = threading.Thread(target=observe, name=f"d3-observer-{index}")
        observer_thread[:] = [observer]
        observer.start()
        try:
            assert inside.wait(timeout=_BARRIER_DEADLINE_SECONDS), (
                "the observer never entered its critical observation section"
            )
            outcome = _runner_service(config, d1).run()
            release.set()
        finally:
            observer.join(timeout=_BARRIER_DEADLINE_SECONDS)
            observer_thread.clear()
        assert not observer.is_alive()
        assert "error" not in box, box.get("error")
        projection = box["projection"]
        assert projection.runner.lease_state == "ABANDONED"
        assert projection.runner.lease_record is not None
        assert projection.runner.lease_record.activation_id == (
            outcome.activation.activation_id
        )
        assert outcome.classification is RunnerCompletion.COMPLETED_NEW

    assert d1.calls == iterations
    assert violations == []
