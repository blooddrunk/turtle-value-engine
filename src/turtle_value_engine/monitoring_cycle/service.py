"""Synchronous, scheduler-neutral Phase 6-D1 monitoring-cycle service."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.input_loader import parse_normalized_input
from turtle_value_engine.models import Company, CompanyAnalysis, NormalizedCompanyInput
from turtle_value_engine.monitoring import (
    ImpactClass,
    MonitoringEventBatchV1,
    MonitoringRunV1,
    MonitoringWorkspace,
    MonitoringWorkspaceError,
    ReanalysisRequestV1,
    WatchlistSpecV1,
    WatchlistStateV1,
    run_monitoring,
)
from turtle_value_engine.monitoring_execution import (
    ReanalysisExecutionResult,
    ReanalysisExecutor,
    ReanalysisJobStatus,
    ReanalysisJobStore,
    ReanalysisJobStoreError,
    reanalysis_job_id,
)
from turtle_value_engine.preparation import AcquisitionRequest

from .contracts import (
    AlertKind,
    CycleFailureCode,
    CycleStatus,
    MonitoringAlertBatchV1,
    MonitoringAlertV1,
    MonitoringCycleAcquisitionV1,
    MonitoringCycleExecutionDispositionV1,
    MonitoringCyclePlanV1,
    MonitoringCycleResultV1,
    MonitoringCycleSpecV1,
    MonitoringExecutionBindingV1,
)
from .store import MonitoringCycleStore, MonitoringCycleStoreError


class MonitoringCycleError(ValueError):
    """Base class for D1 cycle failures."""


class MonitoringCycleBindingError(MonitoringCycleError):
    """Raised when explicit execution context cannot be resolved."""


@dataclass(frozen=True, slots=True)
class CycleAcquisitionRequest:
    """Typed input supplied to the injected Phase 6-B acquisition boundary."""

    spec: MonitoringCycleSpecV1
    watchlist: WatchlistSpecV1
    prior_state: WatchlistStateV1 | None


@dataclass(frozen=True, slots=True)
class CycleAcquisitionOutcome:
    """Minimal normalized return from an existing acquisition service."""

    batch: MonitoringEventBatchV1
    retrieval_mode: str = "INJECTED"


class MonitoringAcquisitionBoundary(Protocol):
    def acquire(self, request: CycleAcquisitionRequest) -> CycleAcquisitionOutcome:
        """Acquire one canonical event batch under the explicit cycle policy."""


@dataclass(frozen=True, slots=True)
class ResolvedExecutionBinding:
    """Runtime-only result of resolving one non-secret execution binding."""

    company: Company | None = None
    prepared_input: NormalizedCompanyInput | None = None
    prior_analysis: CompanyAnalysis | None = None


BindingResolver = Callable[
    [MonitoringExecutionBindingV1, ReanalysisRequestV1, MonitoringCycleSpecV1],
    ResolvedExecutionBinding,
]


class PathExecutionBindingResolver:
    """Resolve only the exact explicit paths in a binding; never scan a folder."""

    def resolve(
        self,
        binding: MonitoringExecutionBindingV1,
        request: ReanalysisRequestV1,
        spec: MonitoringCycleSpecV1,
    ) -> ResolvedExecutionBinding:
        if binding.resolver_key is not None:
            raise MonitoringCycleBindingError(
                "D1_MISSING_EXECUTION_BINDING: resolver_key requires an injected resolver"
            )
        prepared = None
        if binding.prepared_input_path is not None:
            path = Path(binding.prepared_input_path)
            try:
                prepared = parse_normalized_input(path.read_bytes())
            except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
                raise MonitoringCycleBindingError(
                    "D1_MISSING_EXECUTION_BINDING: prepared-input artifact could not be resolved"
                ) from exc
        prior = None
        if binding.prior_analysis_path is not None:
            path = Path(binding.prior_analysis_path)
            try:
                prior = CompanyAnalysis.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
                ValidationError,
            ) as exc:
                raise MonitoringCycleBindingError(
                    "D1_MISSING_EXECUTION_BINDING: prior-analysis artifact could not be resolved"
                ) from exc
        if prepared is None and prior is None and binding.company is None:
            raise MonitoringCycleBindingError(
                "D1_MISSING_EXECUTION_BINDING: company, prepared input or "
                "prior artifact is required"
            )
        del request, spec
        return ResolvedExecutionBinding(
            company=binding.company,
            prepared_input=prepared,
            prior_analysis=prior,
        )


class _CyclePreparationBoundary:
    """Prevent 6-C preparation from running without an explicit company bind."""

    def __init__(
        self,
        delegate: object | Callable[..., object] | None,
        resolved: Mapping[str, ResolvedExecutionBinding | None],
    ) -> None:
        self.delegate = delegate
        self.resolved = resolved

    def prepare(self, request: AcquisitionRequest, **kwargs: object) -> object:
        binding = self.resolved.get(request.listing_id)
        if binding is None or binding.company is None:
            raise MonitoringCycleBindingError(
                "D1_MISSING_EXECUTION_BINDING: preparation requires explicit company context"
            )
        if self.delegate is None:
            raise MonitoringCycleBindingError(
                "D1_MISSING_EXECUTION_BINDING: no preparation boundary is configured"
            )
        kwargs.setdefault("company", binding.company)
        prepare = getattr(self.delegate, "prepare", self.delegate)
        return prepare(request, **kwargs)


@dataclass(frozen=True, slots=True)
class MonitoringCycleOutcome:
    result: MonitoringCycleResultV1
    alert_batch: MonitoringAlertBatchV1
    reused: bool = False


class MonitoringCycleRunner:
    """Compose Phase 6-B acquisition, Phase 6-A commit and Phase 6-C execution."""

    def __init__(
        self,
        workspace: MonitoringWorkspace,
        job_store: ReanalysisJobStore,
        cycle_store: MonitoringCycleStore,
        *,
        acquisition: MonitoringAcquisitionBoundary | Callable[[CycleAcquisitionRequest], object],
        preparation: object | Callable[..., object] | None = None,
        research_orchestrator: object | None = None,
        analyst_clients: Sequence[object] | None = None,
        profile_loader: Callable[[str], RuleProfile] = load_profile,
        model_allowed: bool | None = None,
        binding_resolver: BindingResolver | object | None = None,
    ) -> None:
        if not isinstance(workspace, MonitoringWorkspace):
            raise TypeError("workspace must be a MonitoringWorkspace")
        if not isinstance(job_store, ReanalysisJobStore):
            raise TypeError("job_store must be a ReanalysisJobStore")
        if not isinstance(cycle_store, MonitoringCycleStore):
            raise TypeError("cycle_store must be a MonitoringCycleStore")
        self.workspace = workspace
        self.job_store = job_store
        self.cycle_store = cycle_store
        self.acquisition = acquisition
        self.preparation = preparation
        self.research_orchestrator = research_orchestrator
        self.analyst_clients = analyst_clients
        self.profile_loader = profile_loader
        self.model_allowed = model_allowed
        self.binding_resolver = binding_resolver or PathExecutionBindingResolver()

    def run(
        self,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
    ) -> MonitoringCycleOutcome:
        self._validate_scope(spec, watchlist)
        self.cycle_store.save_spec(spec)

        existing = self.cycle_store.load_terminal(spec.cycle_id)
        if existing is not None:
            result, alerts = existing
            self._validate_existing(result, spec, watchlist)
            return MonitoringCycleOutcome(result=result, alert_batch=alerts, reused=True)

        current_state = self.workspace.load_current_state(watchlist.watchlist_id)
        staged_plan = self.cycle_store.load_plan(spec.cycle_id)
        staged_acquisition = self.cycle_store.load_acquisition(spec.cycle_id)
        self._validate_staged_artifacts(
            spec, watchlist, current_state, staged_acquisition, staged_plan
        )

        committed_run: MonitoringRunV1 | None = None
        batch: MonitoringEventBatchV1 | None = None
        prior_state = current_state
        if (
            staged_plan is not None
            and current_state is not None
            and current_state.state_id == staged_plan.next_state_id
        ):
            try:
                _proof, _stored_watchlist, stored_batch, committed_run, _state = (
                    self.workspace.load_committed_run(staged_plan.monitoring_run_id)
                )
            except (MonitoringWorkspaceError, OSError, ValidationError, ValueError) as exc:
                del exc
                return self._publish_failure(
                    spec,
                    watchlist,
                    current_state,
                    CycleFailureCode.LOWER_LEVEL_INELIGIBLE,
                    "The staged monitoring commit cannot be proven from its lower-level artifacts.",
                    listing_ids=(),
                    event_batch=staged_acquisition.batch if staged_acquisition else None,
                )
            batch = stored_batch
            prior_state = (
                self.workspace.load_state(staged_plan.prior_state_id)
                if staged_plan.prior_state_id
                else None
            )
        else:
            try:
                gate = self._unresolved_current_run(
                    current_state, watchlist.watchlist_id, spec.cycle_id
                )
            except MonitoringCycleError:
                return self._publish_failure(
                    spec,
                    watchlist,
                    current_state,
                    CycleFailureCode.LOWER_LEVEL_INELIGIBLE,
                    "The current monitoring commit cannot be proven before advancing.",
                    listing_ids=(),
                    event_batch=None,
                )
            if gate is not None:
                dispositions, alerts = gate
                return self._publish_attention(
                    spec,
                    watchlist,
                    current_state,
                    dispositions,
                    alerts,
                    failure_code=CycleFailureCode.UNRESOLVED_CURRENT_RUN,
                )

        if staged_acquisition is None:
            try:
                acquisition = self._call_acquisition(
                    CycleAcquisitionRequest(spec=spec, watchlist=watchlist, prior_state=prior_state)
                )
                if not isinstance(acquisition.batch, MonitoringEventBatchV1):
                    raise MonitoringCycleError(
                        "acquisition boundary did not return a canonical event batch"
                    )
                batch = acquisition.batch
                staged_acquisition = MonitoringCycleAcquisitionV1.build(
                    cycle_id=spec.cycle_id,
                    spec_content_sha256=spec.content_sha256,
                    watchlist_id=watchlist.watchlist_id,
                    watchlist_content_sha256=watchlist.content_sha256,
                    prior_state_id=None if prior_state is None else prior_state.state_id,
                    source_id=spec.source_id,
                    adapter_version=spec.adapter_version,
                    published_from=spec.published_from,
                    published_to=spec.published_to,
                    network_allowed=spec.network_allowed,
                    offline_replay=spec.offline_replay,
                    retrieval_mode=acquisition.retrieval_mode,
                    batch=batch,
                )
                self.cycle_store.save_acquisition(staged_acquisition)
            except Exception as exc:
                del exc
                return self._publish_failure(
                    spec,
                    watchlist,
                    current_state,
                    CycleFailureCode.ACQUISITION_FAILED,
                    "The explicit Phase 6-B acquisition boundary failed before monitoring commit.",
                    listing_ids=(),
                    event_batch=None,
                )
        else:
            batch = staged_acquisition.batch

        if committed_run is None:
            if batch is None:
                raise MonitoringCycleError("cycle has no canonical acquisition batch")
            try:
                committed_run = run_monitoring(
                    watchlist,
                    batch,
                    prior_state,
                    spec.as_of,
                    policy_id=spec.event_impact_policy_id,
                )
                staged_plan = MonitoringCyclePlanV1.build(
                    cycle_id=spec.cycle_id,
                    spec_content_sha256=spec.content_sha256,
                    prior_state_id=None if prior_state is None else prior_state.state_id,
                    next_state_id=committed_run.next_state.state_id,
                    event_batch_id=batch.batch_id,
                    monitoring_run_id=committed_run.run_id,
                    monitoring_run_content_sha256=committed_run.content_sha256,
                    request_ids=[request.request_id for request in committed_run.plan.requests],
                )
                self.cycle_store.save_plan(staged_plan)
                self.workspace.commit_run(committed_run, watchlist=watchlist, batch=batch)
            except Exception as exc:
                del exc
                return self._publish_failure(
                    spec,
                    watchlist,
                    current_state,
                    CycleFailureCode.MONITORING_COMMIT_FAILED,
                    "The Phase 6-A monitoring commit failed; the prior pointer "
                    "remains authoritative.",
                    listing_ids=(),
                    event_batch=batch,
                )

        assert committed_run is not None
        assert batch is not None
        try:
            dispositions, execution_results, missing_bindings = self._execute_requests(
                spec, watchlist, batch, committed_run
            )
        except (
            MonitoringCycleError,
            ReanalysisJobStoreError,
            OSError,
            ValidationError,
            ValueError,
        ) as exc:
            del exc
            return self._publish_failure(
                spec,
                watchlist,
                current_state,
                CycleFailureCode.EXECUTION_ATTENTION_REQUIRED,
                "The committed monitoring plan could not be completed at the Phase 6-C boundary.",
                listing_ids=[request.listing_id for request in committed_run.plan.requests],
                event_batch=batch,
                run=committed_run,
            )

        alerts = self._alerts_for_execution(
            spec,
            watchlist,
            batch,
            committed_run,
            execution_results,
            missing_bindings,
        )
        unresolved = any(item.resolution == "UNRESOLVED" for item in dispositions)
        status = (
            CycleStatus.ATTENTION_REQUIRED
            if unresolved
            or any(
                item.status is ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED for item in dispositions
            )
            else CycleStatus.ALERTS_EMITTED
            if alerts
            else CycleStatus.NO_CHANGE
        )
        failure_code = CycleFailureCode.EXECUTION_ATTENTION_REQUIRED if unresolved else None
        return self._publish_result(
            spec,
            watchlist,
            status=status,
            failure_code=failure_code,
            message=None,
            prior_state=prior_state,
            batch=batch,
            run=committed_run,
            dispositions=dispositions,
            alerts=alerts,
        )

    def _validate_scope(self, spec: MonitoringCycleSpecV1, watchlist: WatchlistSpecV1) -> None:
        if (
            spec.watchlist_id != watchlist.watchlist_id
            or spec.watchlist_content_sha256 != watchlist.content_sha256
        ):
            raise MonitoringCycleError("cycle spec does not bind the supplied watchlist identity")
        for declared, actual, label in (
            (spec.monitoring_workspace_root, self.workspace.root, "monitoring workspace"),
            (spec.reanalysis_job_root, self.job_store.root, "re-analysis job store"),
            (spec.cycle_store_root, self.cycle_store.root, "cycle store"),
        ):
            if Path(declared).resolve() != Path(actual).resolve():
                raise MonitoringCycleError(
                    f"cycle spec {label} root does not match the injected store"
                )

    @staticmethod
    def _validate_existing(
        result: MonitoringCycleResultV1,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
    ) -> None:
        if (
            result.spec_content_sha256 != spec.content_sha256
            or result.watchlist_id != watchlist.watchlist_id
            or result.watchlist_content_sha256 != watchlist.content_sha256
        ):
            raise MonitoringCycleError(
                "existing cycle artifact conflicts with the explicit request"
            )

    @staticmethod
    def _validate_staged_artifacts(
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
        current_state: WatchlistStateV1 | None,
        acquisition: MonitoringCycleAcquisitionV1 | None,
        plan: MonitoringCyclePlanV1 | None,
    ) -> None:
        plan_committed = (
            plan is not None
            and current_state is not None
            and current_state.state_id == plan.next_state_id
        )
        if acquisition is not None and (
            acquisition.cycle_id != spec.cycle_id
            or acquisition.spec_content_sha256 != spec.content_sha256
            or acquisition.watchlist_id != watchlist.watchlist_id
            or acquisition.watchlist_content_sha256 != watchlist.content_sha256
            or (
                not plan_committed
                and current_state is not None
                and acquisition.prior_state_id != current_state.state_id
            )
        ):
            raise MonitoringCycleError(
                "staged acquisition receipt conflicts with current cycle state"
            )
        if plan is not None and (
            plan.cycle_id != spec.cycle_id or plan.spec_content_sha256 != spec.content_sha256
        ):
            raise MonitoringCycleError("staged cycle plan conflicts with explicit cycle spec")

    def _call_acquisition(self, request: CycleAcquisitionRequest) -> CycleAcquisitionOutcome:
        acquire = getattr(self.acquisition, "acquire", self.acquisition)
        outcome = acquire(request)
        if isinstance(outcome, CycleAcquisitionOutcome):
            return outcome
        if isinstance(outcome, MonitoringEventBatchV1):
            return CycleAcquisitionOutcome(batch=outcome)
        if isinstance(outcome, Mapping) and isinstance(
            outcome.get("batch"), MonitoringEventBatchV1
        ):
            return CycleAcquisitionOutcome(
                batch=outcome["batch"],
                retrieval_mode=str(outcome.get("retrieval_mode", "INJECTED")),
            )
        raise MonitoringCycleError("acquisition boundary returned an unsupported result")

    def _unresolved_current_run(
        self, state: WatchlistStateV1 | None, watchlist_id: str, cycle_id: str
    ) -> tuple[list[MonitoringCycleExecutionDispositionV1], list[MonitoringAlertV1]] | None:
        if state is None or state.last_committed_run_id is None:
            return None
        try:
            _proof, watchlist, batch, run, _state = self.workspace.load_committed_run(
                state.last_committed_run_id
            )
        except (MonitoringWorkspaceError, OSError, ValidationError, ValueError) as exc:
            raise MonitoringCycleError(
                "current committed monitoring run cannot be proven before advancing"
            ) from exc
        if watchlist.watchlist_id != watchlist_id:
            raise MonitoringCycleError("current monitoring run belongs to another watchlist")
        dispositions: list[MonitoringCycleExecutionDispositionV1] = []
        alerts: list[MonitoringAlertV1] = []
        event_map = {(event.listing_id, event.event_id): event for event in batch.events}
        for request in sorted(run.plan.requests, key=lambda item: item.request_id):
            job_id = reanalysis_job_id(run.run_id, request.request_id, run.as_of)
            attempt = None
            try:
                attempt = self.job_store.load_latest(job_id)
            except ReanalysisJobStoreError:
                attempt = None
            if attempt is None:
                disposition = MonitoringCycleExecutionDispositionV1(
                    request_id=request.request_id,
                    listing_id=request.listing_id,
                    impact=request.impact,
                    job_id=job_id,
                    status=None,
                    resolution="MISSING",
                    failure_code=CycleFailureCode.MISSING_EXECUTION_DISPOSITION.value,
                )
                alerts.append(
                    self._build_alert(
                        cycle_id=cycle_id,
                        watchlist_id=watchlist_id,
                        monitoring_run_id=run.run_id,
                        event_batch_id=batch.batch_id,
                        kind=AlertKind.REANALYSIS_BLOCKED,
                        listing_id=request.listing_id,
                        request=request,
                        events=[
                            event_map[(request.listing_id, event_id)]
                            for event_id in request.event_ids
                        ],
                        job_id=job_id,
                        failure_code=CycleFailureCode.MISSING_EXECUTION_DISPOSITION.value,
                        reason_code=CycleFailureCode.MISSING_EXECUTION_DISPOSITION.value,
                        message=(
                            "A required prior re-analysis disposition is missing; "
                            "the next monitoring run is blocked."
                        ),
                    )
                )
                dispositions.append(disposition)
                continue
            status = attempt.job.status
            resolution = (
                "RESOLVED"
                if status
                in {
                    ReanalysisJobStatus.SUCCEEDED,
                    ReanalysisJobStatus.NO_ACTION,
                    ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
                }
                else "UNRESOLVED"
            )
            disposition = MonitoringCycleExecutionDispositionV1(
                request_id=request.request_id,
                listing_id=request.listing_id,
                impact=request.impact,
                job_id=job_id,
                job_content_sha256=attempt.job.content_sha256,
                status=status,
                resolution=resolution,
                failure_code=None
                if attempt.job.failure_code is None
                else attempt.job.failure_code.value,
            )
            dispositions.append(disposition)
            if resolution == "UNRESOLVED":
                kind = (
                    AlertKind.REANALYSIS_BLOCKED
                    if status is ReanalysisJobStatus.BLOCKED
                    else AlertKind.REANALYSIS_FAILED
                )
                alerts.append(
                    self._build_alert(
                        cycle_id=cycle_id,
                        watchlist_id=watchlist_id,
                        monitoring_run_id=run.run_id,
                        event_batch_id=batch.batch_id,
                        kind=kind,
                        listing_id=request.listing_id,
                        request=request,
                        events=[
                            event_map[(request.listing_id, event_id)]
                            for event_id in request.event_ids
                        ],
                        job_id=job_id,
                        job_status=status,
                        failure_code=None
                        if attempt.job.failure_code is None
                        else attempt.job.failure_code.value,
                        reason_code=CycleFailureCode.UNRESOLVED_CURRENT_RUN.value,
                        message=(
                            "The current committed re-analysis remains unresolved; "
                            "no newer monitoring pointer may be advanced."
                        ),
                    )
                )
        return (
            (dispositions, alerts)
            if any(item.resolution != "RESOLVED" for item in dispositions)
            else None
        )

    def _execute_requests(
        self,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
        batch: MonitoringEventBatchV1,
        run: MonitoringRunV1,
    ) -> tuple[
        list[MonitoringCycleExecutionDispositionV1], list[ReanalysisExecutionResult], set[str]
    ]:
        resolved: dict[str, ResolvedExecutionBinding | None] = {}
        missing_bindings: set[str] = set()
        requests = tuple(sorted(run.plan.requests, key=lambda item: item.request_id))
        for request in requests:
            binding = spec.execution_catalog.for_listing(request.listing_id)
            if (
                request.impact in {ImpactClass.NO_REANALYSIS, ImpactClass.URGENT_MANUAL_REVIEW}
                and binding is None
            ):
                resolved[request.listing_id] = ResolvedExecutionBinding()
                continue
            if binding is None:
                missing_bindings.add(request.listing_id)
                resolved[request.listing_id] = None
                continue
            try:
                resolver = getattr(self.binding_resolver, "resolve", self.binding_resolver)
                value = resolver(binding, request, spec)
                if not isinstance(value, ResolvedExecutionBinding):
                    raise MonitoringCycleBindingError(
                        "D1_MISSING_EXECUTION_BINDING: resolver returned an invalid type"
                    )
                resolved[request.listing_id] = value
            except MonitoringCycleBindingError:
                missing_bindings.add(request.listing_id)
                resolved[request.listing_id] = None

        executor = ReanalysisExecutor(
            self.workspace,
            self.job_store,
            preparation=_CyclePreparationBoundary(self.preparation, resolved),
            research_orchestrator=self.research_orchestrator,
            analyst_clients=self.analyst_clients,
            profile_loader=self.profile_loader,
            model_allowed=self.model_allowed,
        )
        results: list[ReanalysisExecutionResult] = []
        for request in requests:
            binding = resolved.get(request.listing_id)
            results.extend(
                executor.execute(
                    run.run_id,
                    listing_id=request.listing_id,
                    request_id=request.request_id,
                    network_allowed=spec.network_allowed,
                    prepared_input=None if binding is None else binding.prepared_input,
                    prior_analysis=None if binding is None else binding.prior_analysis,
                    company=None if binding is None else binding.company,
                )
            )
        by_request = {result.job.request_id: result for result in results}
        dispositions: list[MonitoringCycleExecutionDispositionV1] = []
        for request in requests:
            result = by_request.get(request.request_id)
            if result is None:
                raise MonitoringCycleError(
                    "Phase 6-C did not return a result for every committed request"
                )
            disposition = MonitoringCycleExecutionDispositionV1(
                request_id=request.request_id,
                listing_id=request.listing_id,
                impact=request.impact,
                job_id=result.job.job_id,
                job_content_sha256=result.job.content_sha256,
                status=result.job.status,
                failure_code=None
                if result.job.failure_code is None
                else result.job.failure_code.value,
                resolution=(
                    "RESOLVED"
                    if result.job.status
                    in {
                        ReanalysisJobStatus.SUCCEEDED,
                        ReanalysisJobStatus.NO_ACTION,
                        ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
                    }
                    else "UNRESOLVED"
                ),
            )
            dispositions.append(disposition)
        return dispositions, results, missing_bindings

    def _alerts_for_execution(
        self,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
        batch: MonitoringEventBatchV1,
        run: MonitoringRunV1,
        results: Sequence[ReanalysisExecutionResult],
        missing_bindings: set[str],
    ) -> list[MonitoringAlertV1]:
        event_map = {(event.listing_id, event.event_id): event for event in batch.events}
        result_map = {result.job.request_id: result for result in results}
        alerts: list[MonitoringAlertV1] = []
        for request in sorted(run.plan.requests, key=lambda item: item.request_id):
            events = [event_map[(request.listing_id, event_id)] for event_id in request.event_ids]
            if request.impact is not ImpactClass.NO_REANALYSIS:
                alerts.append(
                    self._build_alert(
                        cycle_id=spec.cycle_id,
                        watchlist_id=watchlist.watchlist_id,
                        monitoring_run_id=run.run_id,
                        event_batch_id=batch.batch_id,
                        kind=AlertKind.MATERIAL_EVENT,
                        listing_id=request.listing_id,
                        request=request,
                        events=events,
                        impact=request.impact,
                        reason_code="MATERIAL_EVENT_PROCESSED",
                        message=(
                            "A committed material monitoring event was processed at "
                            "the explicit point-in-time boundary."
                        ),
                    )
                )
            result = result_map[request.request_id]
            job = result.job
            if job.status is ReanalysisJobStatus.NO_ACTION:
                continue
            if job.status is ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED:
                kind = AlertKind.MANUAL_REVIEW_REQUIRED
                reason = "URGENT_MANUAL_REVIEW"
                message = (
                    "The committed event requires manual investment review; no "
                    "analysis conclusion was generated."
                )
            elif job.status is ReanalysisJobStatus.BLOCKED:
                kind = AlertKind.REANALYSIS_BLOCKED
                reason = (
                    CycleFailureCode.MISSING_EXECUTION_BINDING.value
                    if request.listing_id in missing_bindings
                    else (job.failure_code.value if job.failure_code else "REANALYSIS_BLOCKED")
                )
                message = (
                    "Explicit execution context is missing; re-analysis was "
                    "blocked without guessing company facts."
                    if request.listing_id in missing_bindings
                    else "The committed re-analysis was blocked at its existing "
                    "fail-closed execution boundary."
                )
            elif job.status is ReanalysisJobStatus.FAILED:
                kind = AlertKind.REANALYSIS_FAILED
                reason = (
                    CycleFailureCode.MISSING_EXECUTION_BINDING.value
                    if request.listing_id in missing_bindings
                    else (job.failure_code.value if job.failure_code else "REANALYSIS_FAILED")
                )
                message = (
                    "Explicit execution context is missing; re-analysis failed "
                    "closed without guessing company facts."
                    if request.listing_id in missing_bindings
                    else "The committed re-analysis failed at an existing typed execution boundary."
                )
            else:
                kind = AlertKind.REANALYSIS_SUCCEEDED
                reason = "REANALYSIS_SUCCEEDED"
                message = (
                    "The committed re-analysis succeeded and produced a validated "
                    "read-only surface reference."
                )
            alerts.append(
                self._build_alert(
                    cycle_id=spec.cycle_id,
                    watchlist_id=watchlist.watchlist_id,
                    monitoring_run_id=run.run_id,
                    event_batch_id=batch.batch_id,
                    kind=kind,
                    listing_id=request.listing_id,
                    request=request,
                    events=events,
                    impact=request.impact,
                    job_id=job.job_id,
                    job_status=job.status,
                    failure_code=None if job.failure_code is None else job.failure_code.value,
                    analysis_id=job.analysis_id,
                    surface_id=job.surface_id,
                    reason_code=reason,
                    message=message,
                )
            )
        return alerts

    @staticmethod
    def _build_alert(
        *,
        cycle_id: str,
        watchlist_id: str,
        monitoring_run_id: str | None = None,
        event_batch_id: str | None = None,
        kind: AlertKind,
        listing_id: str | None,
        request: ReanalysisRequestV1 | None = None,
        events: Sequence[object] = (),
        impact: ImpactClass | None = None,
        job_id: str | None = None,
        job_status: ReanalysisJobStatus | None = None,
        failure_code: str | None = None,
        analysis_id: str | None = None,
        surface_id: str | None = None,
        reason_code: str,
        message: str,
    ) -> MonitoringAlertV1:
        event_list = list(events)
        return MonitoringAlertV1.build(
            cycle_id=cycle_id,
            watchlist_id=watchlist_id,
            monitoring_run_id=monitoring_run_id,
            event_batch_id=event_batch_id,
            kind=kind,
            listing_id=listing_id,
            event_ids=[] if request is None else list(request.event_ids),
            event_types=[event.event_type for event in event_list],
            impact=impact if impact is not None else (None if request is None else request.impact),
            available_at=(max(event.available_at for event in event_list) if event_list else None),
            job_id=job_id,
            job_status=job_status,
            failure_code=failure_code,
            analysis_id=analysis_id,
            surface_id=surface_id,
            reason_code=reason_code,
            message=message,
        )

    def _publish_attention(
        self,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
        state: WatchlistStateV1 | None,
        dispositions: list[MonitoringCycleExecutionDispositionV1],
        alerts: list[MonitoringAlertV1],
        *,
        failure_code: CycleFailureCode,
    ) -> MonitoringCycleOutcome:
        return self._publish_result(
            spec,
            watchlist,
            status=CycleStatus.ATTENTION_REQUIRED,
            failure_code=failure_code,
            message=(
                "The current committed run contains unresolved execution work; no "
                "new monitoring run was committed."
            ),
            prior_state=state,
            batch=None,
            run=None,
            dispositions=dispositions,
            alerts=alerts,
        )

    def _publish_failure(
        self,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
        state: WatchlistStateV1 | None,
        failure_code: CycleFailureCode,
        message: str,
        *,
        listing_ids: Sequence[str],
        event_batch: MonitoringEventBatchV1 | None,
        run: MonitoringRunV1 | None = None,
    ) -> MonitoringCycleOutcome:
        del listing_ids
        alert = MonitoringAlertV1.build(
            cycle_id=spec.cycle_id,
            watchlist_id=watchlist.watchlist_id,
            kind=AlertKind.CYCLE_FAILED,
            listing_id=None,
            event_ids=[],
            event_types=[],
            reason_code=failure_code.value,
            failure_code=failure_code.value,
            message=message,
        )
        return self._publish_result(
            spec,
            watchlist,
            status=CycleStatus.FAILED,
            failure_code=failure_code,
            message=message,
            prior_state=state,
            batch=event_batch,
            run=run,
            dispositions=[],
            alerts=[alert],
        )

    def _publish_result(
        self,
        spec: MonitoringCycleSpecV1,
        watchlist: WatchlistSpecV1,
        *,
        status: CycleStatus,
        failure_code: CycleFailureCode | None,
        message: str | None,
        prior_state: WatchlistStateV1 | None,
        batch: MonitoringEventBatchV1 | None,
        run: MonitoringRunV1 | None,
        dispositions: Sequence[MonitoringCycleExecutionDispositionV1],
        alerts: Sequence[MonitoringAlertV1],
    ) -> MonitoringCycleOutcome:
        alert_batch = MonitoringAlertBatchV1.build(
            cycle_id=spec.cycle_id,
            watchlist_id=watchlist.watchlist_id,
            alerts=list(alerts),
        )
        result = MonitoringCycleResultV1.build(
            cycle_id=spec.cycle_id,
            spec_content_sha256=spec.content_sha256,
            watchlist_id=watchlist.watchlist_id,
            watchlist_content_sha256=watchlist.content_sha256,
            as_of=spec.as_of,
            status=status,
            failure_code=failure_code,
            message=message,
            prior_state_id=None if prior_state is None else prior_state.state_id,
            event_batch_id=None if batch is None else batch.batch_id,
            event_batch_content_sha256=None if batch is None else batch.content_sha256,
            monitoring_run_id=None if run is None else run.run_id,
            monitoring_run_content_sha256=None if run is None else run.content_sha256,
            next_state_id=None if run is None else run.next_state.state_id,
            alert_batch_id=alert_batch.alert_batch_id,
            alert_batch_content_sha256=alert_batch.content_sha256,
            execution=sorted(dispositions, key=lambda item: item.request_id),
        )
        try:
            self.cycle_store.publish(result, alert_batch)
        except MonitoringCycleStoreError:
            raise
        return MonitoringCycleOutcome(result=result, alert_batch=alert_batch)


__all__ = [
    "BindingResolver",
    "CycleAcquisitionOutcome",
    "CycleAcquisitionRequest",
    "MonitoringAcquisitionBoundary",
    "MonitoringCycleBindingError",
    "MonitoringCycleError",
    "MonitoringCycleOutcome",
    "MonitoringCycleRunner",
    "PathExecutionBindingResolver",
    "ResolvedExecutionBinding",
]
