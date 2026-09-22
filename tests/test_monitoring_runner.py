"""Automatic Phase 6-D2A durable unattended-runner matrix.

Every test drives the runner through its public service/CLI boundaries with
injected or already-proven fake Phase 6-B/D1 components; no live provider,
model or network access occurs anywhere in this module.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tests.test_monitoring_acquisition import ADAPTER_VERSION, FakeDiscoveryClient, _acquire
from tests.test_monitoring_execution import _normalized
from turtle_value_engine.monitoring import (
    MonitoringEventBatchV1,
    MonitoringWorkspace,
    WatchlistSpecV1,
    build_event_batch,
)
from turtle_value_engine.monitoring_cycle import (
    CninfoCycleAcquisition,
    CycleAcquisitionOutcome,
    CycleStatus,
    MonitoringCycleRunner,
    MonitoringCycleSpecV1,
    MonitoringCycleStore,
    MonitoringExecutionBindingV1,
    MonitoringExecutionCatalogV1,
    ResolvedExecutionBinding,
)
from turtle_value_engine.monitoring_execution import ReanalysisJobStore
from turtle_value_engine.monitoring_runner import (
    ActivationRequestConflictError,
    LeaseState,
    MonitoringRunnerService,
    RunnerActivationIntentV1,
    RunnerArtifactCorruptError,
    RunnerCompletion,
    RunnerConfigV1,
    RunnerLatestPointerV1,
    RunnerLease,
    RunnerLeaseBusyError,
    RunnerLeaseError,
    RunnerStateConflictError,
    RunnerStore,
)
from turtle_value_engine.monitoring_runner.contracts import (
    RunnerActivePointerV1,
    RunnerLeaseV1,
    RunnerReceiptV1,
)

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 8, tzinfo=UTC)
RUNNER_ID = "turtle-test"


class FakeClock:
    def __init__(self, start: datetime = AS_OF) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def _watchlist(listing: str = "SH600001") -> WatchlistSpecV1:
    return WatchlistSpecV1.build(
        watchlist_id="phase6d2a-test",
        profile_id="strict-v1",
        entries=[{"listing_id": listing, "company_display_name": "fixture"}],
    )


def _write_watchlist(path: Path, watchlist: WatchlistSpecV1) -> None:
    path.write_text(
        json.dumps(watchlist.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_watchlist_file(path: Path) -> WatchlistSpecV1:
    return WatchlistSpecV1.build(**json.loads(path.read_text(encoding="utf-8")))


def _batch(event_type: str, *, listing: str = "SH600001") -> MonitoringEventBatchV1:
    return build_event_batch(
        [
            {
                "event_id": "event-1",
                "listing_id": listing,
                "event_type": event_type,
                "source_id": "fixture-source",
                "source_event_id": "fixture:event-1",
                "available_at": "2026-06-01T00:00:00Z",
            }
        ]
    )


class FakeAcquisition:
    def __init__(self, batch: MonitoringEventBatchV1, *, error: Exception | None = None):
        self.batch = batch
        self.error = error
        self.calls = 0

    def acquire(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CycleAcquisitionOutcome(batch=self.batch)


class CountingBindingResolver:
    def __init__(self, listing: str = "SH600001"):
        self.listing = listing
        self.calls: list[str] = []
        self.normalized = _normalized(listing)

    def resolve(self, binding, request, spec):
        self.calls.append(request.request_id)
        return ResolvedExecutionBinding(prepared_input=self.normalized)


class RealD1:
    """Compose the service with the real D1 runner over injected fakes."""

    def __init__(self, tmp_path: Path, acquisition, *, resolver=None):
        self.workspace = MonitoringWorkspace(tmp_path / "monitoring")
        self.jobs = ReanalysisJobStore(tmp_path / "jobs")
        self.cycles = MonitoringCycleStore(tmp_path / "cycles")
        self.acquisition_obj = acquisition
        self.runner = MonitoringCycleRunner(
            self.workspace,
            self.jobs,
            self.cycles,
            acquisition=acquisition,
            binding_resolver=resolver,
            model_allowed=False,
        )
        self.calls = 0
        self.specs: list[MonitoringCycleSpecV1] = []

    def run_cycle(self, spec, watchlist):
        self.calls += 1
        self.specs.append(spec)
        return self.runner.run(spec, watchlist)


class CrashingD1:
    def __init__(self, delegate, *, fail_calls: int = 1):
        self.delegate = delegate
        self.fail_calls = fail_calls
        self.calls = 0
        self.specs: list[MonitoringCycleSpecV1] = []

    def run_cycle(self, spec, watchlist):
        self.specs.append(spec)
        self.calls += 1
        if self.calls <= self.fail_calls:
            raise RuntimeError("simulated crash inside the D1 boundary")
        return self.delegate.run_cycle(spec, watchlist)


def _config_payload(tmp_path: Path, **overrides) -> dict:
    payload = {
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
    payload.update(overrides)
    return payload


def _config(tmp_path: Path, **overrides) -> RunnerConfigV1:
    return RunnerConfigV1.model_validate(_config_payload(tmp_path, **overrides))


def _service(
    config: RunnerConfigV1,
    d1,
    *,
    clock=None,
    failure_injector=None,
) -> MonitoringRunnerService:
    clock = clock or FakeClock()
    store = RunnerStore(config.runner_root, failure_injector=failure_injector)
    lease = RunnerLease(
        config.runner_root,
        config.runner_id,
        ttl_seconds=config.lease_ttl_seconds,
        clock=clock,
    )
    return MonitoringRunnerService(
        config=config,
        store=store,
        cycle_store=MonitoringCycleStore(config.cycle_store_root),
        lease=lease,
        d1=d1,
        watchlist_loader=lambda: _load_watchlist_file(Path(config.watchlist_path)),
        adapter_version=config.adapter_version,
        clock=clock,
    )


def _json_tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
        if path.is_file()
    }


def test_runner_schema_snapshots_and_contract_hashes_are_stable(tmp_path):
    models = (
        ("monitoring-runner-config.schema.json", RunnerConfigV1),
        ("monitoring-runner-activation.schema.json", RunnerActivationIntentV1),
        ("monitoring-runner-lease.schema.json", RunnerLeaseV1),
        ("monitoring-runner-receipt.schema.json", RunnerReceiptV1),
        ("monitoring-runner-latest-pointer.schema.json", RunnerLatestPointerV1),
        ("monitoring-runner-active-pointer.schema.json", RunnerActivePointerV1),
    )
    for filename, model in models:
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert model.model_json_schema() == checked_in

    config = _config(tmp_path)
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    outcome = _service(config, d1).run()
    store = RunnerStore(config.runner_root)
    first = store.load_intent(outcome.activation.activation_id)
    assert first.content_sha256 == outcome.activation.content_sha256
    tampered = json.loads(first.canonical_bytes().decode("utf-8"))
    tampered["spec"]["acquisition_limit"] = 1
    store.intent_path(first.activation_id).write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(Exception):
        store.load_intent(first.activation_id)


def test_first_activation_one_d1_call_terminal_receipt_and_pointers(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    d1 = RealD1(tmp_path, acquisition)
    outcome = _service(config, d1).run()

    assert outcome.classification is RunnerCompletion.COMPLETED_NEW
    assert d1.calls == 1
    assert acquisition.calls == 1
    store = RunnerStore(config.runner_root)
    receipt = store.load_receipt(outcome.activation.activation_id)
    assert receipt is not None
    assert receipt.classification == "CYCLE_TERMINAL"
    assert receipt.d1_status == CycleStatus.NO_CHANGE.value
    assert receipt.d1_failure_code is None
    assert receipt.result_content_sha256 == outcome.result.content_sha256
    assert receipt.alert_batch_id == outcome.alert_batch.alert_batch_id
    assert receipt.alert_batch_content_sha256 == outcome.alert_batch.content_sha256
    latest = store.load_latest(RUNNER_ID)
    assert latest is not None
    assert latest.activation_id == outcome.activation.activation_id
    assert latest.receipt_content_sha256 == receipt.content_sha256
    assert store.load_active(RUNNER_ID) is None
    lease = RunnerLease(config.runner_root, RUNNER_ID)
    probe = lease.probe()
    assert probe["state"] == LeaseState.ABANDONED.value
    assert probe["record"]["activation_id"] == outcome.activation.activation_id


def test_overlapping_invocation_loser_performs_zero_work(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    d1 = RealD1(tmp_path, acquisition)
    service = _service(config, d1)

    with RunnerLease(config.runner_root, RUNNER_ID).held():
        with pytest.raises(RunnerLeaseBusyError):
            service.run()
    assert d1.calls == 0
    assert acquisition.calls == 0
    assert not (Path(config.runner_root) / "activations").exists()

    outcome = service.run()
    assert outcome.classification is RunnerCompletion.COMPLETED_NEW
    assert d1.calls == 1


def test_abandoned_lease_record_is_recovered(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    lease = RunnerLease(config.runner_root, RUNNER_ID)
    with lease.held() as handle:
        assert handle.acquired_stale_record is False
        handle.record(None)
    # The record now exists with no live holder: an abandoned lease.
    assert lease.probe()["state"] == LeaseState.ABANDONED.value

    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    outcome = _service(config, d1).run()
    assert outcome.classification is RunnerCompletion.COMPLETED_NEW
    assert d1.calls == 1
    record = lease.probe()["record"]
    assert record["activation_id"] == outcome.activation.activation_id


def test_crash_after_intent_before_d1_terminal_resumes_same_activation_and_pit(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    clock = FakeClock()
    config = _config(tmp_path, as_of=None, published_from=None, published_to=None, window_days=3)
    delegate = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    crashing = CrashingD1(delegate)

    with pytest.raises(RuntimeError):
        _service(config, crashing, clock=clock).run()
    store = RunnerStore(config.runner_root)
    unfinished = store.list_unfinished_activations(RUNNER_ID)
    assert len(unfinished) == 1
    frozen = unfinished[0]
    frozen_as_of = frozen.spec.as_of
    frozen_cycle = frozen.spec.cycle_id

    clock.advance(timedelta(days=5))
    outcome = _service(config, delegate, clock=clock).run()

    assert outcome.classification is RunnerCompletion.COMPLETED_RESUMED
    assert outcome.activation.activation_id == frozen.activation_id
    assert outcome.activation.spec.cycle_id == frozen_cycle
    assert outcome.activation.spec.as_of == frozen_as_of
    assert outcome.receipt.d1_status == CycleStatus.NO_CHANGE.value
    assert delegate.calls == 1
    assert delegate.specs[0].as_of == frozen_as_of
    assert delegate.specs[0].cycle_id == frozen_cycle
    assert store.list_unfinished_activations(RUNNER_ID) == []


def test_crash_after_d1_terminal_before_receipt_repairs_without_repeating_work(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    catalog = MonitoringExecutionCatalogV1.build(
        [MonitoringExecutionBindingV1(listing_id="SH600001", resolver_key="fixture")]
    )
    (tmp_path / "catalog.json").write_text(
        json.dumps(catalog.model_dump(mode="json")), encoding="utf-8"
    )
    config = _config(tmp_path, execution_catalog_path=str(tmp_path / "catalog.json"))
    acquisition = FakeAcquisition(_batch("INTERIM_REPORT"))
    resolver = CountingBindingResolver()
    d1 = RealD1(tmp_path, acquisition, resolver=resolver)

    failed = {"value": False}

    def fail_receipt_artifact(path, kind):
        if kind == "artifact" and path.parent.name == "receipts" and not failed["value"]:
            failed["value"] = True
            raise OSError("injected receipt failure")

    with pytest.raises(RunnerArtifactCorruptError):
        _service(config, d1, failure_injector=fail_receipt_artifact).run()

    cycle_id = d1.specs[0].cycle_id
    assert d1.cycles.load_terminal(cycle_id) is not None
    monitoring_before = _json_tree(d1.workspace.root)
    jobs_before = _json_tree(d1.jobs.root)
    cycles_before = _json_tree(d1.cycles.root)
    assert acquisition.calls == 1
    assert len(resolver.calls) == 1

    outcome = _service(config, d1).run()

    assert outcome.classification is RunnerCompletion.COMPLETED_REPAIRED
    assert outcome.reused_terminal is True
    assert d1.calls == 1
    assert acquisition.calls == 1
    assert len(resolver.calls) == 1
    assert _json_tree(d1.workspace.root) == monitoring_before
    assert _json_tree(d1.jobs.root) == jobs_before
    assert _json_tree(d1.cycles.root) == cycles_before
    store = RunnerStore(config.runner_root)
    assert store.load_receipt(outcome.activation.activation_id) is not None
    assert store.load_latest(RUNNER_ID).activation_id == outcome.activation.activation_id
    assert store.load_active(RUNNER_ID) is None
    assert store.list_unfinished_activations(RUNNER_ID) == []


def test_crash_between_intent_and_active_pointer_adopts_unfinished(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))

    failed = {"value": False}

    def fail_active_pointer(path, kind):
        if kind == "pointer" and path.parent.name == "active" and not failed["value"]:
            failed["value"] = True
            raise OSError("injected active pointer failure")

    with pytest.raises(RunnerArtifactCorruptError):
        _service(config, d1, failure_injector=fail_active_pointer).run()

    store = RunnerStore(config.runner_root)
    unfinished = store.list_unfinished_activations(RUNNER_ID)
    assert len(unfinished) == 1
    assert d1.calls == 0  # the crash happened before entering D1

    outcome = _service(config, d1).run()
    assert outcome.classification is RunnerCompletion.COMPLETED_RESUMED
    assert outcome.activation.activation_id == unfinished[0].activation_id
    assert d1.calls == 1


def test_crash_before_clear_active_settles_then_creates_new_activation(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    clock = FakeClock()
    config = _config(tmp_path, as_of=None, published_from=None, published_to=None, window_days=1)
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    first = _service(config, d1, clock=clock).run()

    # Simulate a crash between publishing the receipt and clearing the slot.
    store = RunnerStore(config.runner_root)
    store.set_active(first.activation)

    clock.advance(timedelta(days=1))
    second = _service(config, d1, clock=clock).run()

    assert second.classification is RunnerCompletion.COMPLETED_NEW
    assert second.activation.activation_id != first.activation.activation_id
    assert store.load_latest(RUNNER_ID).activation_id == second.activation.activation_id
    assert store.load_active(RUNNER_ID) is None
    assert d1.calls == 2


def test_repeated_wake_identical_request_reuses_terminal_activation(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    first = _service(config, d1).run()
    second = _service(config, d1).run()

    assert second.classification is RunnerCompletion.COMPLETED_REUSED
    assert second.activation.activation_id == first.activation.activation_id
    assert second.reused_terminal is True
    assert d1.calls == 1


def _crashed_intent(
    tmp_path: Path, *, as_of: str, published_to: str
) -> RunnerActivationIntentV1:
    """Persist one receipt-less intent, simulating a pre-D1 crash."""

    config = _config(tmp_path, as_of=as_of, published_to=published_to)
    crashing = CrashingD1(RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([]))))
    with pytest.raises(RuntimeError):
        _service(config, crashing).run()
    store = RunnerStore(config.runner_root)
    unfinished = store.list_unfinished_activations(RUNNER_ID)
    assert len(unfinished) == 1
    return unfinished[0]


@pytest.mark.parametrize(
    "case",
    [
        "tampered_intent",
        "corrupt_lease_record",
        "tampered_latest_pointer",
        "tampered_latest_receipt",
        "conflicting_latest_pointer",
    ],
)
def test_corrupt_or_conflicting_state_fails_closed(tmp_path, case):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    _service(config, d1).run()
    store = RunnerStore(config.runner_root)
    latest = store.load_latest(RUNNER_ID)

    if case == "tampered_intent":
        crashed = _crashed_intent(
            tmp_path, as_of="2026-09-09T00:00:00Z", published_to="2026-09-09"
        )
        path = store.intent_path(crashed.activation_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec"]["source_id"] = "tampered"
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif case == "corrupt_lease_record":
        RunnerLease(config.runner_root, RUNNER_ID).path.write_text(
            "{not canonical json", encoding="utf-8"
        )
    elif case == "tampered_latest_pointer":
        path = store.latest_path(RUNNER_ID)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["activation_id"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif case == "tampered_latest_receipt":
        store.receipt_path(latest.activation_id).write_text("{}", encoding="utf-8")
    elif case == "conflicting_latest_pointer":
        conflicting = RunnerLatestPointerV1.build(
            runner_id=RUNNER_ID,
            activation_id=latest.activation_id,
            cycle_id=latest.cycle_id,
            receipt_content_sha256="0" * 64,
        )
        store._write_pointer(store.latest_path(RUNNER_ID), conflicting.canonical_bytes())

    with pytest.raises(
        (RunnerArtifactCorruptError, RunnerStateConflictError, RunnerLeaseError)
    ):
        _service(config, d1).run()
    assert d1.calls == 1  # fail-closed checks performed zero additional D1 work


def test_two_unfinished_activations_are_an_ambiguous_conflict(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    _service(config, d1).run()

    crashed = _crashed_intent(
        tmp_path, as_of="2026-09-09T00:00:00Z", published_to="2026-09-09"
    )
    store = RunnerStore(config.runner_root)
    finished = store.load_intent(store.load_latest(RUNNER_ID).activation_id)
    forged_spec = MonitoringCycleSpecV1.build(
        watchlist_id=finished.spec.watchlist_id,
        watchlist_content_sha256=finished.spec.watchlist_content_sha256,
        as_of=datetime(2026, 9, 10, tzinfo=UTC),
        acquisition_policy_id=finished.spec.acquisition_policy_id,
        source_id=finished.spec.source_id,
        adapter_version=finished.spec.adapter_version,
        published_from=finished.spec.published_from,
        published_to=finished.spec.published_to,
        acquisition_limit=finished.spec.acquisition_limit,
        network_allowed=finished.spec.network_allowed,
        offline_replay=finished.spec.offline_replay,
        monitoring_workspace_root=finished.spec.monitoring_workspace_root,
        reanalysis_job_root=finished.spec.reanalysis_job_root,
        cycle_store_root=finished.spec.cycle_store_root,
        execution_catalog=finished.spec.execution_catalog,
    )
    forged = RunnerActivationIntentV1.build(
        runner_id=RUNNER_ID,
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
        request_fingerprint=crashed.request_fingerprint,
        spec=forged_spec,
    )
    store.save_intent(forged)
    assert len(store.list_unfinished_activations(RUNNER_ID)) == 2

    with pytest.raises(RunnerStateConflictError):
        _service(config, d1).run()


def test_changed_inputs_under_unfinished_activation_fail_closed(tmp_path):
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path, _watchlist())
    config = _config(tmp_path)
    crashing = CrashingD1(RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([]))))
    with pytest.raises(RuntimeError):
        _service(config, crashing).run()
    assert len(RunnerStore(config.runner_root).list_unfinished_activations(RUNNER_ID)) == 1

    changed = WatchlistSpecV1.build(
        watchlist_id="phase6d2a-test",
        profile_id="strict-v1",
        entries=[
            {"listing_id": "SH600001", "company_display_name": "fixture"},
            {"listing_id": "SH600002", "company_display_name": "fixture-2"},
        ],
    )
    _write_watchlist(watchlist_path, changed)
    with pytest.raises(ActivationRequestConflictError):
        _service(config, RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))).run()

    _write_watchlist(watchlist_path, _watchlist())
    changed_config = _config(tmp_path, cache_dir=str(tmp_path / "cache-moved"))
    with pytest.raises(ActivationRequestConflictError):
        _service(
            changed_config, RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
        ).run()


def test_unresolved_current_run_blocker_is_recorded_factually(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    clock = FakeClock()
    config = _config(tmp_path, as_of=None, published_from=None, published_to=None, window_days=1)
    # ANNUAL_REPORT without model permission produces an unresolved BLOCKED
    # disposition, which D1 already gates the next cycle on.
    d1 = RealD1(tmp_path, FakeAcquisition(_batch("ANNUAL_REPORT")))
    first = _service(config, d1, clock=clock).run()
    assert first.receipt.d1_status == CycleStatus.ATTENTION_REQUIRED.value

    workspace = d1.workspace
    pointer_before = workspace.pointer_path(_watchlist().watchlist_id).read_bytes()
    state_before = workspace.load_current_state(_watchlist().watchlist_id).state_id

    clock.advance(timedelta(days=1))
    acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    second_d1 = RealD1(tmp_path, acquisition)
    second = _service(config, second_d1, clock=clock).run()

    assert second.receipt.d1_status == CycleStatus.ATTENTION_REQUIRED.value
    assert second.receipt.d1_failure_code == "UNRESOLVED_CURRENT_RUN"
    assert second.classification is RunnerCompletion.COMPLETED_NEW
    assert acquisition.calls == 0  # D1 blocked before any acquisition
    assert workspace.pointer_path(_watchlist().watchlist_id).read_bytes() == pointer_before
    assert workspace.load_current_state(_watchlist().watchlist_id).state_id == state_before


def test_no_event_cycle_makes_zero_reanalysis_or_model_calls(tmp_path):
    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    resolver = CountingBindingResolver()
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])), resolver=resolver)
    outcome = _service(config, d1).run()

    assert outcome.receipt.d1_status == CycleStatus.NO_CHANGE.value
    assert outcome.alert_batch.alerts == []
    assert resolver.calls == []
    assert _json_tree(d1.jobs.root) == {}


def test_config_requires_explicit_acquisition_mode():
    with pytest.raises(ValidationError):
        RunnerConfigV1.model_validate(
            _config_payload(Path("/tmp/x"), network_allowed=False, offline_replay=False)
        )
    with pytest.raises(ValidationError):
        RunnerConfigV1.model_validate(
            _config_payload(Path("/tmp/x"), network_allowed=True, offline_replay=True)
        )
    with pytest.raises(ValidationError):
        RunnerConfigV1.model_validate(
            _config_payload(Path("/tmp/x"), published_from=None, window_days=None)
        )


def _filing_descriptor(published: date, document_type: str, document_id: str):
    from turtle_value_engine.providers.filings import FilingDescriptor

    return FilingDescriptor(
        title="2025年年度报告",
        document_type=document_type,
        published_date=published,
        url=f"https://static.cninfo.com.cn/finalpage/2026-04-17/{document_id}.PDF",
        source_document_id=document_id,
        issuer_name="fixture",
    )


def _seeded_raw_cache(tmp_path: Path, cache_dir: Path) -> FakeDiscoveryClient:
    from turtle_value_engine.monitoring_acquisition import AcquisitionWindow
    from turtle_value_engine.providers.cache import FilesystemRawResponseCache

    fake_source = FakeDiscoveryClient(
        {"SH600519": [_filing_descriptor(date(2026, 4, 17), "010301", "1225114741")]}
    )
    _acquire(
        fake_source,
        FilesystemRawResponseCache(cache_dir),
        listings=("SH600519",),
        window=AcquisitionWindow(date(2026, 4, 10), date(2026, 4, 30)),
        as_of=AS_OF,
    )
    fake_source.calls.clear()
    return fake_source


def test_cache_replay_through_runner_needs_no_sockets(tmp_path, monkeypatch):
    cache_dir = tmp_path / "raw-cache"
    fake_source = _seeded_raw_cache(tmp_path, cache_dir)

    class SocketBlocked:
        def __init__(self, *args, **kwargs):
            raise AssertionError("runner cache replay attempted a socket")

    monkeypatch.setattr(socket, "socket", SocketBlocked)

    _write_watchlist(tmp_path / "watchlist.json", _watchlist("SH600519"))
    config = _config(
        tmp_path,
        adapter_version=ADAPTER_VERSION,
        published_from="2026-04-10",
        published_to="2026-04-30",
    )
    d1 = RealD1(tmp_path, CninfoCycleAcquisition(cache_dir))
    outcome = _service(config, d1).run()

    assert outcome.classification is RunnerCompletion.COMPLETED_NEW
    # ANNUAL_REPORT without an execution binding is a factual attention state.
    assert outcome.receipt.d1_status == CycleStatus.ATTENTION_REQUIRED.value
    assert fake_source.calls == []


def test_cli_status_is_bounded_and_secret_free(tmp_path, capsys):
    from turtle_value_engine.cli import main

    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    d1 = RealD1(tmp_path, FakeAcquisition(MonitoringEventBatchV1.build([])))
    outcome = _service(config, d1).run()

    rc = main(
        [
            "watch",
            "unattended-status",
            "--runner-root",
            str(Path(config.runner_root)),
            "--runner-id",
            RUNNER_ID,
            "--activation-id",
            outcome.activation.activation_id,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert len(captured.out.encode()) < 64 * 1024
    assert "secret" not in captured.out
    payload = json.loads(captured.out)
    assert payload["runners"][0]["runner_id"] == RUNNER_ID
    assert payload["activation"]["intent"]["activation_id"] == outcome.activation.activation_id
    assert payload["activation"]["receipt"]["d1_status"] == "NO_CHANGE"

    lease_record = json.loads(
        RunnerLease(config.runner_root, RUNNER_ID).path.read_text(encoding="utf-8")
    )
    assert lease_record["holder_token"] not in captured.out


def test_cli_run_reports_lease_busy_with_exit_code_three(tmp_path, capsys):
    from turtle_value_engine.cli import main

    _write_watchlist(tmp_path / "watchlist.json", _watchlist())
    config = _config(tmp_path)
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(_config_payload(tmp_path), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with RunnerLease(config.runner_root, RUNNER_ID).held():
        rc = main(["watch", "unattended-run", "--runner-config", str(config_path)])
    captured = capsys.readouterr()
    assert rc == 3
    payload = json.loads(captured.out)
    assert payload["classification"] == "LEASE_BUSY"
    assert payload["runner_id"] == RUNNER_ID
    assert not (Path(config.runner_root) / "activations").exists()


def test_subprocess_black_box_run_status_reuse_and_busy(tmp_path):
    cache_dir = tmp_path / "raw-cache"
    _seeded_raw_cache(tmp_path, cache_dir)

    _write_watchlist(tmp_path / "watchlist.json", _watchlist("SH600519"))
    config_payload = _config_payload(
        tmp_path,
        cache_dir=str(cache_dir),
        adapter_version=ADAPTER_VERSION,
        published_from="2026-04-10",
        published_to="2026-04-30",
    )
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    base = [sys.executable, "-m", "turtle_value_engine"]

    completed = subprocess.run(
        base + ["watch", "unattended-run", "--runner-config", str(config_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    first_payload = json.loads(completed.stdout)
    assert first_payload["classification"] == "COMPLETED_NEW"
    assert first_payload["d1_status"] in {
        CycleStatus.ATTENTION_REQUIRED.value,
        CycleStatus.ALERTS_EMITTED.value,
    }
    store = RunnerStore(config_payload["runner_root"])
    assert store.load_receipt(first_payload["activation_id"]) is not None
    assert len(first_payload["as_of"]) > 0

    status = subprocess.run(
        base
        + [
            "watch",
            "unattended-status",
            "--runner-root",
            config_payload["runner_root"],
            "--runner-id",
            RUNNER_ID,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["runners"][0]["runner_id"] == RUNNER_ID

    reused = subprocess.run(
        base + ["watch", "unattended-run", "--runner-config", str(config_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=300,
    )
    assert reused.returncode == 0, reused.stderr
    assert json.loads(reused.stdout)["classification"] == "COMPLETED_REUSED"

    with RunnerLease(config_payload["runner_root"], RUNNER_ID).held():
        busy = subprocess.run(
            base + ["watch", "unattended-run", "--runner-config", str(config_path)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
            timeout=300,
        )
    assert busy.returncode == 3
    assert json.loads(busy.stdout)["classification"] == "LEASE_BUSY"


def test_systemd_reference_units_pass_systemd_analyze_verify():
    tool = shutil.which("systemd-analyze")
    if tool is None:  # pragma: no cover - ordinary CI and dev hosts provide it
        pytest.skip("systemd-analyze is not available on this host")
    units = [
        ROOT / "deploy" / "monitoring" / "turtle-value-monitor.service",
        ROOT / "deploy" / "monitoring" / "turtle-value-monitor.timer",
    ]
    completed = subprocess.run(
        [tool, "verify", *[str(unit) for unit in units]],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_no_scheduled_github_actions_monitoring_workflow_exists():
    workflows_dir = ROOT / ".github" / "workflows"
    assert workflows_dir.exists()
    for path in sorted(workflows_dir.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
        triggers = document.get("on", document.get(True))
        if triggers is None:
            continue
        assert "schedule" not in triggers, f"{path.name} declares a scheduled trigger"
    document_text = "\n".join(
        path.read_text(encoding="utf-8") for path in workflows_dir.glob("*.yml")
    )
    assert "cron" not in document_text
