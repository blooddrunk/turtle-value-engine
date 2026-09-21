"""Automatic Phase 6-D1 monitoring-cycle and alert-outbox matrix."""

from __future__ import annotations

import json
import socket
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_monitoring_acquisition import ADAPTER_VERSION, FakeDiscoveryClient, _acquire
from tests.test_monitoring_execution import _normalized
from turtle_value_engine.cli import main
from turtle_value_engine.monitoring import (
    MonitoringEventBatchV1,
    MonitoringWorkspace,
    WatchlistSpecV1,
    build_event_batch,
    run_monitoring,
)
from turtle_value_engine.monitoring_cycle import (
    AlertKind,
    CninfoCycleAcquisition,
    CycleAcquisitionOutcome,
    CycleFailureCode,
    CycleStatus,
    MonitoringAlertBatchV1,
    MonitoringAlertV1,
    MonitoringCycleAcquisitionV1,
    MonitoringCycleExecutionDispositionV1,
    MonitoringCyclePlanV1,
    MonitoringCyclePointerV1,
    MonitoringCycleResultV1,
    MonitoringCycleRunner,
    MonitoringCycleSpecV1,
    MonitoringCycleStore,
    MonitoringCycleStoreError,
    MonitoringExecutionBindingV1,
    MonitoringExecutionCatalogV1,
    ResolvedExecutionBinding,
)
from turtle_value_engine.monitoring_execution import (
    ReanalysisJobStatus,
    ReanalysisJobStore,
)

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 8, tzinfo=UTC)


def _watchlist(listing: str = "SH600001") -> WatchlistSpecV1:
    return WatchlistSpecV1.build(
        watchlist_id="phase6d1-test",
        profile_id="strict-v1",
        entries=[{"listing_id": listing, "company_display_name": "fixture"}],
    )


def _batch(
    event_type: str,
    *,
    listing: str = "SH600001",
    event_id: str = "event-1",
    available_at: str = "2026-06-01T00:00:00Z",
) -> MonitoringEventBatchV1:
    return build_event_batch(
        [
            {
                "event_id": event_id,
                "listing_id": listing,
                "event_type": event_type,
                "source_id": "fixture-source",
                "source_event_id": f"fixture:{event_id}",
                "available_at": available_at,
            }
        ]
    )


class FakeAcquisition:
    def __init__(self, batch: MonitoringEventBatchV1, *, error: Exception | None = None):
        self.batch = batch
        self.error = error
        self.calls = 0
        self.as_ofs: list[datetime] = []

    def acquire(self, request):
        self.calls += 1
        self.as_ofs.append(request.spec.as_of)
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


def _catalog(listing: str = "SH600001") -> MonitoringExecutionCatalogV1:
    return MonitoringExecutionCatalogV1.build(
        [MonitoringExecutionBindingV1(listing_id=listing, resolver_key="fixture")]
    )


def _spec(
    tmp_path: Path,
    watchlist: WatchlistSpecV1,
    *,
    catalog: MonitoringExecutionCatalogV1 | None = None,
    as_of: datetime = AS_OF,
    published_from: date = date(2026, 6, 1),
    published_to: date = date(2026, 9, 8),
    adapter_version: str = "fixture-adapter-v1",
    network_allowed: bool = False,
    offline_replay: bool = True,
) -> MonitoringCycleSpecV1:
    workspace = tmp_path / "monitoring"
    jobs = tmp_path / "jobs"
    cycles = tmp_path / "cycles"
    return MonitoringCycleSpecV1.build(
        watchlist_id=watchlist.watchlist_id,
        watchlist_content_sha256=watchlist.content_sha256,
        as_of=as_of,
        acquisition_policy_id="monitoring-acquisition-v1",
        source_id="CNINFO",
        adapter_version=adapter_version,
        published_from=published_from,
        published_to=published_to,
        acquisition_limit=30,
        network_allowed=network_allowed,
        offline_replay=offline_replay,
        monitoring_workspace_root=str(workspace),
        reanalysis_job_root=str(jobs),
        cycle_store_root=str(cycles),
        execution_catalog=catalog or MonitoringExecutionCatalogV1.build(),
    )


def _runner(
    tmp_path: Path,
    acquisition: FakeAcquisition,
    *,
    catalog: MonitoringExecutionCatalogV1 | None = None,
    resolver: CountingBindingResolver | None = None,
    model_allowed: bool | None = False,
    workspace_failure_injector=None,
    cycle_failure_injector=None,
):
    workspace = MonitoringWorkspace(
        tmp_path / "monitoring", failure_injector=workspace_failure_injector
    )
    jobs = ReanalysisJobStore(tmp_path / "jobs")
    cycles = MonitoringCycleStore(tmp_path / "cycles", failure_injector=cycle_failure_injector)
    return (
        MonitoringCycleRunner(
            workspace,
            jobs,
            cycles,
            acquisition=acquisition,
            binding_resolver=resolver,
            model_allowed=model_allowed,
        ),
        workspace,
        jobs,
        cycles,
    )


def _json_tree(root: Path) -> dict[str, bytes]:
    return (
        {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*.json"))}
        if root.exists()
        else {}
    )


def test_cycle_schema_snapshots_and_contract_hashes_are_stable():
    models = (
        ("monitoring-execution-binding.schema.json", MonitoringExecutionBindingV1),
        ("monitoring-execution-catalog.schema.json", MonitoringExecutionCatalogV1),
        ("monitoring-cycle-spec.schema.json", MonitoringCycleSpecV1),
        ("monitoring-cycle-acquisition.schema.json", MonitoringCycleAcquisitionV1),
        ("monitoring-cycle-plan.schema.json", MonitoringCyclePlanV1),
        ("monitoring-alert.schema.json", MonitoringAlertV1),
        ("monitoring-alert-batch.schema.json", MonitoringAlertBatchV1),
        (
            "monitoring-cycle-execution-disposition.schema.json",
            MonitoringCycleExecutionDispositionV1,
        ),
        ("monitoring-cycle-result.schema.json", MonitoringCycleResultV1),
        ("monitoring-cycle-pointer.schema.json", MonitoringCyclePointerV1),
    )
    for filename, model in models:
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert model.model_json_schema() == checked_in

    watchlist = _watchlist()
    catalog = _catalog()
    first = MonitoringCycleSpecV1.build(
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
        monitoring_workspace_root="/tmp/monitoring",
        reanalysis_job_root="/tmp/jobs",
        cycle_store_root="/tmp/cycles",
        execution_catalog=catalog,
    )
    second = first.model_copy(deep=True)
    assert first.cycle_id == second.cycle_id
    assert first.content_sha256 == second.content_sha256
    with pytest.raises(ValidationError):
        MonitoringCycleSpecV1.model_validate(
            first.model_dump(mode="json") | {"as_of": "2026-09-09T00:00:00Z"}
        )


def test_fake_acquisition_commits_6a_executes_6c_and_emits_outbox(tmp_path):
    watchlist = _watchlist()
    acquisition = FakeAcquisition(_batch("INTERIM_REPORT"))
    resolver = CountingBindingResolver()
    runner, workspace, jobs, cycles = _runner(
        tmp_path, acquisition, catalog=_catalog(), resolver=resolver
    )
    outcome = runner.run(_spec(tmp_path, watchlist, catalog=_catalog()), watchlist)

    assert outcome.result.status is CycleStatus.ALERTS_EMITTED
    assert outcome.result.as_of == AS_OF
    assert outcome.result.monitoring_run_id is not None
    assert outcome.result.execution[0].status is ReanalysisJobStatus.SUCCEEDED
    assert outcome.result.execution[0].resolution == "RESOLVED"
    assert outcome.result.execution[0].job_content_sha256 is not None
    assert {alert.kind for alert in outcome.alert_batch.alerts} == {
        AlertKind.MATERIAL_EVENT,
        AlertKind.REANALYSIS_SUCCEEDED,
    }
    success = next(
        alert
        for alert in outcome.alert_batch.alerts
        if alert.kind is AlertKind.REANALYSIS_SUCCEEDED
    )
    assert success.surface_id is not None
    assert acquisition.as_ofs == [AS_OF]
    assert len(resolver.calls) == 1
    assert jobs.load_latest(outcome.result.execution[0].job_id) is not None
    assert cycles.load_terminal(outcome.result.cycle_id) is not None
    assert workspace.load_committed_run(outcome.result.monitoring_run_id)[3].as_of == AS_OF


def test_fake_phase6b_source_composes_through_6a_6c_and_outbox(tmp_path):
    from turtle_value_engine.monitoring_acquisition import (
        AcquisitionWindow,
        acquire_filing_events,
    )
    from turtle_value_engine.providers.cache import FilesystemRawResponseCache
    from turtle_value_engine.providers.filings import (
        FilingDescriptor,
        FilingDiscoverySourceClient,
        FilingSource,
        OfficialFilingDiscoveryProvider,
    )

    class Phase6BFakeAcquisition:
        def __init__(self):
            self.calls = 0
            self.client = FakeDiscoveryClient(
                {
                    "SH600001": [
                        FilingDescriptor(
                            title="2026年半年度报告",
                            document_type="010303",
                            published_date=date(2026, 6, 17),
                            url="https://static.cninfo.com.cn/finalpage/2026-06-17/fake.PDF",
                            source_document_id="fake-2026-interim",
                            issuer_name="fixture",
                        )
                    ]
                }
            )
            self.cache = FilesystemRawResponseCache(tmp_path / "raw-cache")
            self.provider = OfficialFilingDiscoveryProvider(
                {
                    FilingSource.CNINFO: FilingDiscoverySourceClient(
                        source=FilingSource.CNINFO,
                        source_uri="https://www.cninfo.com.cn/new/hisAnnouncement/query",
                        discover=self.client.discover,
                    )
                },
                provider_version=ADAPTER_VERSION,
            )

        def acquire(self, request):
            self.calls += 1
            outcome = acquire_filing_events(
                provider=self.provider,
                listings=[entry.listing_id for entry in request.watchlist.entries if entry.enabled],
                window=AcquisitionWindow(request.spec.published_from, request.spec.published_to),
                source_id=request.spec.source_id,
                adapter_version=request.spec.adapter_version,
                cache=self.cache,
                limit=request.spec.acquisition_limit,
                as_of=request.spec.as_of,
                network_allowed=request.spec.network_allowed,
                offline=request.spec.offline_replay,
            )
            return CycleAcquisitionOutcome(batch=outcome.batch, retrieval_mode="LIVE")

    watchlist = _watchlist()
    acquisition = Phase6BFakeAcquisition()
    resolver = CountingBindingResolver()
    runner, workspace, jobs, _cycles = _runner(
        tmp_path,
        acquisition,
        catalog=_catalog(),
        resolver=resolver,
    )
    spec = _spec(
        tmp_path,
        watchlist,
        catalog=_catalog(),
        adapter_version=ADAPTER_VERSION,
        network_allowed=True,
        offline_replay=False,
    )
    outcome = runner.run(spec, watchlist)

    assert acquisition.calls == 1
    assert acquisition.client.calls == ["SH600001"]
    assert outcome.result.status is CycleStatus.ALERTS_EMITTED
    assert outcome.result.execution[0].status is ReanalysisJobStatus.SUCCEEDED
    assert (
        workspace.load_committed_run(outcome.result.monitoring_run_id)[2].events[0].event_type.value
        == "INTERIM_REPORT"
    )
    assert (
        jobs.load_latest(outcome.result.execution[0].job_id).job.status
        is ReanalysisJobStatus.SUCCEEDED
    )


def test_no_event_cycle_makes_zero_reanalysis_calls(tmp_path):
    watchlist = _watchlist()
    acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    resolver = CountingBindingResolver()
    runner, workspace, jobs, _cycles = _runner(
        tmp_path, acquisition, catalog=_catalog(), resolver=resolver
    )
    outcome = runner.run(_spec(tmp_path, watchlist, catalog=_catalog()), watchlist)

    assert outcome.result.status is CycleStatus.NO_CHANGE
    assert outcome.alert_batch.alerts == []
    assert outcome.result.execution == []
    assert resolver.calls == []
    assert _json_tree(jobs.root) == {}
    assert workspace.load_current_state(watchlist.watchlist_id) is not None


@pytest.mark.parametrize(
    ("event_type", "expected_status", "expected_job_status", "needs_binding"),
    [
        ("INFORMATIONAL_DISCLOSURE", CycleStatus.NO_CHANGE, ReanalysisJobStatus.NO_ACTION, False),
        ("INTERIM_REPORT", CycleStatus.ALERTS_EMITTED, ReanalysisJobStatus.SUCCEEDED, True),
        ("ANNUAL_REPORT", CycleStatus.ATTENTION_REQUIRED, ReanalysisJobStatus.BLOCKED, True),
        (
            "PROFIT_WARNING",
            CycleStatus.ATTENTION_REQUIRED,
            ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
            False,
        ),
    ],
)
def test_all_four_impact_classes_keep_phase_6c_semantics(
    tmp_path, event_type, expected_status, expected_job_status, needs_binding
):
    watchlist = _watchlist()
    acquisition = FakeAcquisition(_batch(event_type))
    resolver = CountingBindingResolver() if needs_binding else None
    catalog = _catalog() if needs_binding else MonitoringExecutionCatalogV1.build()
    runner, _workspace, jobs, _cycles = _runner(
        tmp_path,
        acquisition,
        catalog=catalog,
        resolver=resolver,
        model_allowed=False,
    )
    outcome = runner.run(_spec(tmp_path, watchlist, catalog=catalog), watchlist)

    assert outcome.result.status is expected_status
    assert len(outcome.result.execution) == 1
    disposition = outcome.result.execution[0]
    assert disposition.status is expected_job_status
    if expected_job_status is ReanalysisJobStatus.BLOCKED:
        assert disposition.failure_code == "BLOCKED_RESEARCH_RUNTIME"
        assert any(
            alert.kind is AlertKind.REANALYSIS_BLOCKED for alert in outcome.alert_batch.alerts
        )
    elif expected_job_status is ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED:
        assert any(
            alert.kind is AlertKind.MANUAL_REVIEW_REQUIRED for alert in outcome.alert_batch.alerts
        )
        assert resolver is None
    elif expected_job_status is ReanalysisJobStatus.SUCCEEDED:
        job = jobs.load_latest(disposition.job_id).job
        assert job.capabilities.accepted_adjustments_supplied is False
        assert job.surface_id is not None
    else:
        assert outcome.alert_batch.alerts == []


def test_missing_binding_is_stable_fail_closed_blocker_without_guessed_context(tmp_path):
    watchlist = _watchlist()
    acquisition = FakeAcquisition(_batch("INTERIM_REPORT"))
    runner, _workspace, jobs, _cycles = _runner(tmp_path, acquisition)
    outcome = runner.run(_spec(tmp_path, watchlist), watchlist)

    assert outcome.result.status is CycleStatus.ATTENTION_REQUIRED
    job = jobs.load_latest(outcome.result.execution[0].job_id).job
    assert job.status is ReanalysisJobStatus.FAILED
    assert any(
        alert.reason_code == CycleFailureCode.MISSING_EXECUTION_BINDING.value
        for alert in outcome.alert_batch.alerts
    )
    assert "company" not in json.dumps(job.model_dump(mode="json"), ensure_ascii=False)


def test_cache_replay_with_sockets_blocked_makes_no_source_call(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    # Reuse the already-tested Phase 6-B fake source to create the exact cache
    # record; D1 only consumes it through the existing acquisition boundary.
    from turtle_value_engine.monitoring_acquisition import AcquisitionWindow
    from turtle_value_engine.providers.cache import FilesystemRawResponseCache
    from turtle_value_engine.providers.filings import FilingDescriptor

    fake_source = FakeDiscoveryClient(
        {
            "SH600519": [
                FilingDescriptor(
                    title="2025年年度报告",
                    document_type="010301",
                    published_date=date(2026, 4, 17),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                    source_document_id="1225114741",
                    issuer_name="fixture",
                )
            ]
        }
    )
    cache = FilesystemRawResponseCache(cache_dir)
    _acquire(
        fake_source,
        cache,
        listings=("SH600519",),
        window=AcquisitionWindow(date(2026, 4, 10), date(2026, 4, 30)),
        as_of=AS_OF,
    )
    fake_source.calls.clear()

    class SocketBlocked:
        def __init__(self, *args, **kwargs):
            raise AssertionError("cache replay attempted a socket")

    monkeypatch.setattr(socket, "socket", SocketBlocked)
    watchlist = _watchlist("SH600519")
    workspace = MonitoringWorkspace(tmp_path / "monitoring")
    jobs = ReanalysisJobStore(tmp_path / "jobs")
    cycles = MonitoringCycleStore(tmp_path / "cycles")
    spec = _spec(
        tmp_path,
        watchlist,
        adapter_version=ADAPTER_VERSION,
        published_from=date(2026, 4, 10),
        published_to=date(2026, 4, 30),
    )
    runner = MonitoringCycleRunner(
        workspace,
        jobs,
        cycles,
        acquisition=CninfoCycleAcquisition(cache_dir),
        model_allowed=False,
    )
    outcome = runner.run(spec, watchlist)
    assert outcome.result.status is CycleStatus.ATTENTION_REQUIRED
    assert fake_source.calls == []


def test_acquisition_failure_is_atomic_and_does_not_create_execution_job(tmp_path):
    watchlist = _watchlist()
    baseline = FakeAcquisition(MonitoringEventBatchV1.build([]))
    runner, workspace, _jobs, _cycles = _runner(tmp_path, baseline)
    baseline_spec = _spec(tmp_path, watchlist)
    runner.run(baseline_spec, watchlist)
    before_state = _json_tree(workspace.root)

    failing = FakeAcquisition(MonitoringEventBatchV1.build([]), error=RuntimeError("secret"))
    runner2, workspace2, jobs2, _cycles2 = _runner(tmp_path, failing)
    spec = _spec(
        tmp_path,
        watchlist,
        as_of=AS_OF + timedelta(days=1),
        published_to=date(2026, 9, 9),
    )
    outcome = runner2.run(spec, watchlist)

    assert outcome.result.status is CycleStatus.FAILED
    assert outcome.result.failure_code is CycleFailureCode.ACQUISITION_FAILED
    assert _json_tree(workspace.root) == before_state
    assert _json_tree(jobs2.root) == {}


def test_monitoring_commit_failure_preserves_previous_pointer_and_state(tmp_path):
    watchlist = _watchlist()
    initial = FakeAcquisition(MonitoringEventBatchV1.build([]))
    runner, workspace, _jobs, _cycles = _runner(tmp_path, initial)
    runner.run(_spec(tmp_path, watchlist), watchlist)
    pointer_before = workspace.pointer_path(watchlist.watchlist_id).read_bytes()
    state_before = workspace.load_current_state(watchlist.watchlist_id).content_sha256

    def fail_pointer(path, kind):
        if kind == "pointer":
            raise OSError("injected pointer failure")

    event = FakeAcquisition(_batch("INTERIM_REPORT"))
    workspace._failure_injector = fail_pointer
    failing_runner = MonitoringCycleRunner(
        workspace,
        ReanalysisJobStore(tmp_path / "jobs"),
        MonitoringCycleStore(tmp_path / "cycles"),
        acquisition=event,
        binding_resolver=CountingBindingResolver(),
        model_allowed=False,
    )
    outcome = failing_runner.run(
        _spec(
            tmp_path,
            watchlist,
            catalog=_catalog(),
            as_of=AS_OF + timedelta(days=1),
            published_to=date(2026, 9, 9),
        ),
        watchlist,
    )

    assert outcome.result.status is CycleStatus.FAILED
    assert outcome.result.failure_code is CycleFailureCode.MONITORING_COMMIT_FAILED
    assert workspace.pointer_path(watchlist.watchlist_id).read_bytes() == pointer_before
    assert workspace.load_current_state(watchlist.watchlist_id).content_sha256 == state_before


@pytest.mark.parametrize("event_type", ["INTERIM_REPORT", "ANNUAL_REPORT"])
def test_unresolved_current_run_blocks_new_monitoring_pointer(tmp_path, event_type):
    watchlist = _watchlist()
    first_catalog = _catalog() if event_type == "ANNUAL_REPORT" else None
    first = FakeAcquisition(_batch(event_type))
    first_runner, workspace, _jobs, _cycles = _runner(
        tmp_path,
        first,
        catalog=first_catalog,
        resolver=CountingBindingResolver() if first_catalog else None,
    )
    first_outcome = first_runner.run(_spec(tmp_path, watchlist, catalog=first_catalog), watchlist)
    pointer_before = workspace.pointer_path(watchlist.watchlist_id).read_bytes()
    state_before = workspace.load_current_state(watchlist.watchlist_id).state_id
    assert first_outcome.result.execution[0].status in {
        ReanalysisJobStatus.BLOCKED,
        ReanalysisJobStatus.FAILED,
    }

    second_acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    second_runner, second_workspace, _jobs2, _cycles2 = _runner(tmp_path, second_acquisition)
    assert second_workspace.root == workspace.root
    second_spec = _spec(
        tmp_path,
        watchlist,
        as_of=AS_OF + timedelta(days=1),
        published_to=date(2026, 9, 9),
    )
    outcome = second_runner.run(second_spec, watchlist)

    assert second_acquisition.calls == 0
    assert outcome.result.failure_code is CycleFailureCode.UNRESOLVED_CURRENT_RUN
    assert workspace.pointer_path(watchlist.watchlist_id).read_bytes() == pointer_before
    assert workspace.load_current_state(watchlist.watchlist_id).state_id == state_before


@pytest.mark.parametrize(
    "event_type", ["INFORMATIONAL_DISCLOSURE", "INTERIM_REPORT", "PROFIT_WARNING"]
)
def test_resolved_no_action_success_and_manual_dispositions_permit_next_cycle(tmp_path, event_type):
    watchlist = _watchlist()
    first_catalog = _catalog() if event_type == "INTERIM_REPORT" else None
    first = FakeAcquisition(_batch(event_type))
    first_runner, workspace, _jobs, _cycles = _runner(
        tmp_path,
        first,
        catalog=first_catalog,
        resolver=CountingBindingResolver() if first_catalog else None,
    )
    first_runner.run(_spec(tmp_path, watchlist, catalog=first_catalog), watchlist)
    second = FakeAcquisition(MonitoringEventBatchV1.build([]))
    second_runner, _workspace, _jobs2, _cycles2 = _runner(tmp_path, second)
    second_spec = _spec(
        tmp_path,
        watchlist,
        as_of=AS_OF + timedelta(days=1),
        published_to=date(2026, 9, 9),
    )
    second_outcome = second_runner.run(second_spec, watchlist)
    assert second.calls == 1
    assert second_outcome.result.failure_code is None


def test_missing_prior_disposition_is_unresolved_before_acquisition(tmp_path):
    watchlist = _watchlist()
    batch = _batch("INTERIM_REPORT")
    run = run_monitoring(watchlist, batch, None, AS_OF)
    workspace = MonitoringWorkspace(tmp_path / "monitoring")
    workspace.commit_run(run, watchlist=watchlist, batch=batch)
    acquisition = FakeAcquisition(MonitoringEventBatchV1.build([]))
    runner, _workspace, _jobs, _cycles = _runner(tmp_path, acquisition)

    outcome = runner.run(
        _spec(tmp_path, watchlist, as_of=AS_OF + timedelta(days=1), published_to=date(2026, 9, 9)),
        watchlist,
    )
    assert acquisition.calls == 0
    assert outcome.result.failure_code is CycleFailureCode.UNRESOLVED_CURRENT_RUN
    assert any(
        alert.reason_code == CycleFailureCode.MISSING_EXECUTION_DISPOSITION.value
        for alert in outcome.alert_batch.alerts
    )


def test_cycle_artifact_and_pointer_crash_recovery_is_idempotent(tmp_path):
    watchlist = _watchlist()
    acquisition = FakeAcquisition(_batch("INTERIM_REPORT"))
    resolver = CountingBindingResolver()
    failed_once = {"value": False}

    def fail_alert_artifact(path, kind):
        if kind == "artifact" and path.parent.name == "alerts" and not failed_once["value"]:
            failed_once["value"] = True
            raise OSError("injected immutable outbox failure")

    runner, workspace, jobs, cycles = _runner(
        tmp_path,
        acquisition,
        catalog=_catalog(),
        resolver=resolver,
        cycle_failure_injector=fail_alert_artifact,
    )
    spec = _spec(tmp_path, watchlist, catalog=_catalog())
    with pytest.raises(MonitoringCycleStoreError):
        runner.run(spec, watchlist)
    attempts_before = _json_tree(jobs.root)
    retry = MonitoringCycleRunner(
        workspace,
        jobs,
        MonitoringCycleStore(cycles.root),
        acquisition=acquisition,
        binding_resolver=resolver,
        model_allowed=False,
    ).run(spec, watchlist)
    assert retry.result.status is CycleStatus.ALERTS_EMITTED
    assert acquisition.calls == 1
    assert _json_tree(jobs.root) == attempts_before

    pointer_fail = {"value": False}

    def fail_cycle_pointer(path, kind):
        if kind == "pointer" and not pointer_fail["value"]:
            pointer_fail["value"] = True
            raise OSError("injected latest-pointer failure")

    second_cycle_store = MonitoringCycleStore(cycles.root, failure_injector=fail_cycle_pointer)
    with pytest.raises(MonitoringCycleStoreError):
        second_cycle_store.publish(retry.result, retry.alert_batch)
    repaired = MonitoringCycleStore(cycles.root).load_terminal(spec.cycle_id)
    assert repaired is not None
    assert repaired[0].content_sha256 == retry.result.content_sha256


def test_cycle_store_conflict_and_tamper_rejects_existing_identity(tmp_path):
    watchlist = _watchlist()
    spec = _spec(tmp_path, watchlist)
    store = MonitoringCycleStore(tmp_path / "cycles")
    store.save_spec(spec)
    conflicting = spec.model_copy(update={"content_sha256": "0" * 64})
    with pytest.raises(MonitoringCycleStoreError):
        store.save_spec(conflicting)
    path = store.spec_path(spec.cycle_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["adapter_version"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MonitoringCycleStoreError):
        store.load_spec(spec.cycle_id)


def test_duplicate_alerts_are_suppressed_and_outbox_is_bounded_secret_free(tmp_path, capsys):
    watchlist = _watchlist()
    acquisition = FakeAcquisition(_batch("INTERIM_REPORT"))
    spec = _spec(tmp_path, watchlist, catalog=_catalog())
    runner, _workspace, _jobs, cycles = _runner(
        tmp_path,
        acquisition,
        catalog=_catalog(),
        resolver=CountingBindingResolver(),
    )
    first = runner.run(spec, watchlist)
    second = runner.run(spec, watchlist)
    assert second.reused is True
    assert [item.alert_id for item in first.alert_batch.alerts] == [
        item.alert_id for item in second.alert_batch.alerts
    ]
    assert len(list((cycles.root / "alerts").glob("*.json"))) == 1
    assert all(len(item.message) <= 512 for item in first.alert_batch.alerts)
    assert "secret" not in json.dumps(first.alert_batch.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        MonitoringAlertBatchV1.build(
            cycle_id=first.result.cycle_id,
            watchlist_id=watchlist.watchlist_id,
            alerts=[first.alert_batch.alerts[0], first.alert_batch.alerts[0]],
        )

    rc = main(
        [
            "watch",
            "cycle-status",
            "--cycle-root",
            str(cycles.root),
            "--cycle-id",
            spec.cycle_id,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert len(captured.out.encode()) < 64 * 1024
    assert "secret" not in captured.out
    assert json.loads(captured.out)["cycle"]["cycle_id"] == spec.cycle_id


def test_orphan_lower_level_artifacts_do_not_create_a_terminal_cycle(tmp_path):
    watchlist = _watchlist()
    batch = _batch("INFORMATIONAL_DISCLOSURE")
    run = run_monitoring(watchlist, batch, None, AS_OF)
    workspace = MonitoringWorkspace(tmp_path / "monitoring")
    workspace._commit_bytes(workspace.run_path(run.run_id), run.canonical_bytes(), "artifact")
    cycle_store = MonitoringCycleStore(tmp_path / "cycles")
    assert cycle_store.load_terminal("0" * 64) is None
    assert not list(cycle_store.root.rglob("*.json"))
