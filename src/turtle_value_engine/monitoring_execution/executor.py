"""Controlled, provider/model-neutral Phase 6-C re-analysis execution."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.effective_input import (
    AdjustmentInput,
    materialize_effective_input,
)
from turtle_value_engine.models import (
    Company,
    CompanyAnalysis,
    NormalizedCompanyInput,
)
from turtle_value_engine.monitoring import (
    ImpactClass,
    MonitoringEventBatchV1,
    MonitoringRunV1,
    MonitoringWorkspace,
    MonitoringWorkspaceError,
    ReanalysisRequestV1,
    WatchlistSpecV1,
    WatchlistStateV1,
)
from turtle_value_engine.monitoring.canonical import canonical_json_bytes, normalize_utc
from turtle_value_engine.pipeline import (
    run_analyze,
    run_analyze_with_accepted_adjustments,
)
from turtle_value_engine.preparation import AcquisitionRequest
from turtle_value_engine.research import (
    AnalystClient,
    ResearchOrchestrator,
    ResearchReport,
    ResearchSession,
    ResearchWorkspace,
)
from turtle_value_engine.surface import (
    build_research_surface_snapshot,
    validate_research_surface_snapshot,
)
from turtle_value_engine.traceability import DecisionTrace, build_decision_trace

from .contracts import (
    ReanalysisCapabilitySummaryV1,
    ReanalysisFailureCode,
    ReanalysisJobAttemptV1,
    ReanalysisJobStatus,
    ReanalysisJobV1,
    reanalysis_job_id,
)
from .store import ReanalysisArtifactBundle, ReanalysisJobStore


class ReanalysisExecutionError(ValueError):
    """Base error for an invalid or unsuccessful execution request."""


class ReanalysisEligibilityError(ReanalysisExecutionError):
    """Raised when a run is not a fully proven committed execution source."""


class PriorAnalysisError(ReanalysisExecutionError):
    """Raised when an explicitly supplied prior analysis is not reusable."""


class PreparationBoundary(Protocol):
    """Minimal injected preparation surface used by the executor."""

    def prepare(self, request: AcquisitionRequest, **kwargs: object) -> object:
        """Return an acquisition bundle plus a NormalizedCompanyInput."""


PriorAnalysisResolver = Callable[[ReanalysisRequestV1], CompanyAnalysis | None]


@dataclass(frozen=True, slots=True)
class PriorAnalysisArtifact:
    """An explicitly resolved prior analysis and its canonical content hash."""

    analysis: CompanyAnalysis
    content_sha256: str

    @classmethod
    def build(cls, analysis: CompanyAnalysis) -> PriorAnalysisArtifact:
        return cls(analysis=analysis, content_sha256=_model_sha256(analysis))


@dataclass(frozen=True, slots=True)
class ReanalysisExecutionResult:
    """Non-persisted result envelope returned by the executor API."""

    job: ReanalysisJobV1
    attempt: ReanalysisJobAttemptV1
    reused: bool
    artifacts: ReanalysisArtifactBundle | None = None

    @property
    def status(self) -> ReanalysisJobStatus:
        return self.job.status


@dataclass(frozen=True, slots=True)
class _CommittedRunContext:
    proof: Any
    watchlist: WatchlistSpecV1
    batch: MonitoringEventBatchV1
    run: MonitoringRunV1
    state: WatchlistStateV1
    requests: tuple[ReanalysisRequestV1, ...]


def _model_sha256(value: BaseModel) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value.model_dump(mode="json", warnings=False))
    ).hexdigest()


def _safe_message(code: ReanalysisFailureCode) -> str:
    return {
        ReanalysisFailureCode.PREPARATION_FAILED: (
            "Fresh normalized-input preparation failed at the explicit preparation boundary."
        ),
        ReanalysisFailureCode.RESEARCH_FAILED: (
            "Injected Business Quality research failed at the explicit research boundary."
        ),
        ReanalysisFailureCode.ANALYSIS_FAILED: (
            "Deterministic analysis failed at the existing calculation boundary."
        ),
        ReanalysisFailureCode.SURFACE_FAILED: (
            "Research surface projection failed validation."
        ),
        ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS: (
            "The explicitly supplied prior analysis failed listing, profile or "
            "point-in-time validation."
        ),
        ReanalysisFailureCode.BLOCKED_RESEARCH_RUNTIME: (
            "FULL_REANALYSIS is blocked because an independent research runtime "
            "and model permission are required."
        ),
        ReanalysisFailureCode.JOB_STORE_WRITE_FAILED: (
            "The re-analysis result could not be durably persisted."
        ),
    }[code]


class ReanalysisExecutor:
    """Execute only validated requests from an explicitly committed run.

    The executor has no scheduler and no hidden provider or model client.  A
    preparation boundary and, for FULL jobs, an injected research boundary are
    supplied by the caller.  The synchronous implementation persists only
    terminal records, so a process restart cannot expose a false RUNNING job.
    """

    def __init__(
        self,
        workspace: MonitoringWorkspace,
        job_store: ReanalysisJobStore,
        *,
        preparation: PreparationBoundary | Callable[..., object] | None = None,
        research_orchestrator: ResearchOrchestrator | None = None,
        analyst_clients: Sequence[AnalystClient] | None = None,
        profile_loader: Callable[[str], RuleProfile] = load_profile,
        provider: str = "akshare",
        company: Company | None = None,
        research_root: str | Path | None = None,
        model_allowed: bool | None = None,
    ) -> None:
        if not isinstance(workspace, MonitoringWorkspace):
            raise TypeError("workspace must be a MonitoringWorkspace")
        if not isinstance(job_store, ReanalysisJobStore):
            raise TypeError("job_store must be a ReanalysisJobStore")
        if not provider.strip():
            raise ValueError("provider must not be blank")
        if research_orchestrator is not None and analyst_clients is not None:
            raise ValueError("supply research_orchestrator or analyst_clients, not both")
        clients = None if analyst_clients is None else tuple(analyst_clients)
        if clients is not None and len(clients) != 3:
            raise ValueError("analyst_clients must contain quality, skeptic and adjudicator")
        if clients is not None and any(
            not callable(getattr(client, "analyze", None)) for client in clients
        ):
            raise TypeError("every analyst client must implement analyze()")
        self.workspace = workspace
        self.job_store = job_store
        self.preparation = preparation
        self.research_orchestrator = research_orchestrator
        self.analyst_clients = clients
        self.profile_loader = profile_loader
        self.provider = provider.strip()
        self.company = company
        self.research_root = None if research_root is None else Path(research_root)
        self.model_allowed = (
            bool(model_allowed)
            if model_allowed is not None
            else research_orchestrator is not None or clients is not None
        )

    def execute(
        self,
        run_id: str,
        *,
        listing_id: str | None = None,
        request_id: str | None = None,
        network_allowed: bool = False,
        model_allowed: bool | None = None,
        prepared_input: NormalizedCompanyInput | None = None,
        prepared_inputs: Mapping[str, NormalizedCompanyInput] | None = None,
        prior_analysis: CompanyAnalysis | None = None,
        prior_resolver: PriorAnalysisResolver | None = None,
        accepted_adjustments: Sequence[AdjustmentInput] | None = None,
        company: Company | None = None,
        provider: str | None = None,
    ) -> tuple[ReanalysisExecutionResult, ...]:
        """Execute all committed requests, or the selected listing/request."""

        context = self._load_committed_context(run_id)
        selected = self._select_requests(
            context.requests, listing_id=listing_id, request_id=request_id
        )
        if prepared_input is not None and len(selected) != 1:
            raise ReanalysisExecutionError(
                "prepared_input can only be supplied when exactly one request is selected"
            )
        if prepared_inputs is not None:
            unknown = set(prepared_inputs) - {request.listing_id for request in selected}
            if unknown:
                raise ReanalysisExecutionError(
                    "prepared_inputs contains an unselected listing"
                )
        results: list[ReanalysisExecutionResult] = []
        for request in selected:
            current_input = prepared_input
            if prepared_inputs is not None:
                current_input = prepared_inputs.get(request.listing_id)
            current_prior = prior_analysis
            if prior_resolver is not None:
                if prior_analysis is not None:
                    raise ReanalysisExecutionError(
                        "supply prior_analysis or prior_resolver, not both"
                    )
                try:
                    current_prior = prior_resolver(request)
                except Exception as exc:
                    results.append(
                        self._persist_terminal(
                            context,
                            request,
                            capabilities=self._capabilities(
                                network_allowed,
                                self._effective_model_allowed(model_allowed),
                                accepted_adjustments,
                            ),
                            status=ReanalysisJobStatus.FAILED,
                            failure_code=ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS,
                            message=_safe_message(ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS),
                            evidence_codes=["INVALID_PRIOR_ANALYSIS"],
                        )
                    )
                    del exc
                    continue
            results.append(
                self._execute_one(
                    context,
                    request,
                    network_allowed=network_allowed,
                    model_allowed=self._effective_model_allowed(model_allowed),
                    prepared_input=current_input,
                    prior_analysis=current_prior,
                    accepted_adjustments=accepted_adjustments,
                    company=company or self.company,
                    provider=provider or self.provider,
                )
            )
        return tuple(results)

    def execute_run(self, *args: Any, **kwargs: Any) -> tuple[ReanalysisExecutionResult, ...]:
        """Descriptive alias for callers that execute one monitoring run."""

        return self.execute(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> tuple[ReanalysisExecutionResult, ...]:
        """Compatibility alias for injected runtimes."""

        return self.execute(*args, **kwargs)

    def _effective_model_allowed(self, override: bool | None) -> bool:
        return self.model_allowed if override is None else bool(override)

    def _capabilities(
        self,
        network_allowed: bool,
        model_allowed: bool,
        accepted_adjustments: Sequence[AdjustmentInput] | None,
    ) -> ReanalysisCapabilitySummaryV1:
        return ReanalysisCapabilitySummaryV1(
            network_allowed=network_allowed,
            preparation_mode="LIVE" if network_allowed else "CACHE_ONLY",
            model_allowed=model_allowed,
            research_runtime_available=(
                self.research_orchestrator is not None or self.analyst_clients is not None
            ),
            accepted_adjustments_supplied=bool(accepted_adjustments),
        )

    @staticmethod
    def _select_requests(
        requests: Sequence[ReanalysisRequestV1],
        *,
        listing_id: str | None,
        request_id: str | None,
    ) -> tuple[ReanalysisRequestV1, ...]:
        selected = [
            request
            for request in requests
            if (listing_id is None or request.listing_id == listing_id)
            and (request_id is None or request.request_id == request_id)
        ]
        if (listing_id is not None or request_id is not None) and not selected:
            raise ReanalysisExecutionError("selected committed re-analysis request was not found")
        return tuple(selected)

    def _load_committed_context(self, run_id: str) -> _CommittedRunContext:
        try:
            proof, watchlist, batch, run, state = self.workspace.load_committed_run(run_id)
        except (MonitoringWorkspaceError, OSError, ValidationError, ValueError) as exc:
            raise ReanalysisEligibilityError(
                "monitoring run is not a fully proven committed execution source"
            ) from exc
        self._validate_run_relationships(proof, watchlist, batch, run, state)
        requests = self._validate_plan_requests(watchlist, batch, run)
        return _CommittedRunContext(
            proof=proof,
            watchlist=watchlist,
            batch=batch,
            run=run,
            state=state,
            requests=requests,
        )

    @staticmethod
    def _validate_run_relationships(
        proof: Any,
        watchlist: WatchlistSpecV1,
        batch: MonitoringEventBatchV1,
        run: MonitoringRunV1,
        state: WatchlistStateV1,
    ) -> None:
        if proof.run_id != run.run_id:
            raise ReanalysisEligibilityError("commit proof run identity mismatch")
        if proof.commit_id != proof.content_sha256:
            raise ReanalysisEligibilityError("commit proof identity is invalid")
        if run.plan.run_id != run.run_id or run.plan.watchlist_id != watchlist.watchlist_id:
            raise ReanalysisEligibilityError("monitoring run plan identity mismatch")
        if run.watchlist_id != watchlist.watchlist_id:
            raise ReanalysisEligibilityError("monitoring run watchlist identity mismatch")
        if run.watchlist_content_sha256 != watchlist.content_sha256:
            raise ReanalysisEligibilityError("monitoring run watchlist hash mismatch")
        if run.event_batch_id != batch.batch_id or state.watchlist_id != watchlist.watchlist_id:
            raise ReanalysisEligibilityError("monitoring run event/state identity mismatch")

    @staticmethod
    def _validate_plan_requests(
        watchlist: WatchlistSpecV1,
        batch: MonitoringEventBatchV1,
        run: MonitoringRunV1,
    ) -> tuple[ReanalysisRequestV1, ...]:
        if run.as_of is None:
            raise ReanalysisEligibilityError("monitoring run has no point-in-time boundary")
        enabled = {
            entry.listing_id for entry in watchlist.entries if entry.enabled
        }
        events = {(event.listing_id, event.event_id): event for event in batch.events}
        decisions: dict[tuple[str, str], Any] = {}
        for decision in run.decisions:
            key = (decision.listing_id, decision.event_id)
            if key in decisions:
                raise ReanalysisEligibilityError("monitoring run contains duplicate decisions")
            decisions[key] = decision
            event = events.get(key)
            if event is None:
                raise ReanalysisEligibilityError("monitoring decision references a missing event")
            if (
                event.event_type != decision.event_type
                or event.available_at != decision.available_at
                or event.available_at > run.as_of
                or decision.policy_id != run.policy_id
            ):
                raise ReanalysisEligibilityError("monitoring decision/event identity mismatch")

        expected: dict[str, ReanalysisRequestV1] = {}
        for listing in sorted(enabled):
            listing_decisions = sorted(
                (item for item in decisions.values() if item.listing_id == listing),
                key=lambda item: (item.available_at, item.event_id),
            )
            if not listing_decisions:
                continue
            expected[listing] = ReanalysisRequestV1.build(
                watchlist_id=watchlist.watchlist_id,
                listing_id=listing,
                impact=_combine_decision_impacts(listing_decisions),
                event_ids=[item.event_id for item in listing_decisions],
                available_through=max(item.available_at for item in listing_decisions),
            )

        actual: dict[str, ReanalysisRequestV1] = {}
        for request in run.plan.requests:
            if (
                request.watchlist_id != watchlist.watchlist_id
                or request.listing_id not in enabled
            ):
                raise ReanalysisEligibilityError(
                    "re-analysis request is outside the enabled watchlist"
                )
            if request.listing_id in actual:
                raise ReanalysisEligibilityError(
                    "monitoring plan contains duplicate listing requests"
                )
            actual[request.listing_id] = request
            for event_id in request.event_ids:
                event = events.get((request.listing_id, event_id))
                decision = decisions.get((request.listing_id, event_id))
                if event is None or decision is None:
                    raise ReanalysisEligibilityError(
                        "re-analysis request references a missing event"
                    )
                if event.listing_id != request.listing_id:
                    raise ReanalysisEligibilityError(
                        "re-analysis request crosses listing boundaries"
                    )
                if event.available_at > run.as_of:
                    raise ReanalysisEligibilityError("re-analysis request contains a future event")
        if set(actual) != set(expected):
            raise ReanalysisEligibilityError(
                "monitoring plan does not cover exactly the committed decisions"
            )
        for listing, expected_request in expected.items():
            if actual[listing].model_dump(mode="json") != expected_request.model_dump(
                mode="json"
            ):
                raise ReanalysisEligibilityError("monitoring plan/request content mismatch")
        return tuple(run.plan.requests)

    def _execute_one(
        self,
        context: _CommittedRunContext,
        request: ReanalysisRequestV1,
        *,
        network_allowed: bool,
        model_allowed: bool,
        prepared_input: NormalizedCompanyInput | None,
        prior_analysis: CompanyAnalysis | None,
        accepted_adjustments: Sequence[AdjustmentInput] | None,
        company: Company | None,
        provider: str,
    ) -> ReanalysisExecutionResult:
        capabilities = self._capabilities(
            network_allowed, model_allowed, accepted_adjustments
        )
        runtime_available = capabilities.research_runtime_available
        job_id = reanalysis_job_id(context.run.run_id, request.request_id, context.run.as_of)
        existing = self.job_store.load_latest(job_id)
        if existing is not None:
            if existing.job.status is ReanalysisJobStatus.SUCCEEDED:
                # A crash after the immutable attempt but before the pointer
                # leaves an orphaned successful attempt.  Re-publish only the
                # pointer; never repeat preparation, research or analysis.
                self.job_store.save(existing.job)
                return ReanalysisExecutionResult(
                    job=existing.job,
                    attempt=existing,
                    reused=True,
                    artifacts=self.job_store.load_success_artifacts(existing.job),
                )
            if existing.job.status in {
                ReanalysisJobStatus.NO_ACTION,
                ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
            }:
                return ReanalysisExecutionResult(job=existing.job, attempt=existing, reused=True)
            if (
                existing.job.status is ReanalysisJobStatus.BLOCKED
                and existing.job.capabilities == capabilities
            ):
                return ReanalysisExecutionResult(job=existing.job, attempt=existing, reused=True)

        if request.impact is ImpactClass.NO_REANALYSIS:
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.NO_ACTION,
                message="The committed event-impact policy requires no re-analysis.",
                evidence_codes=["NO_REANALYSIS"],
            )
        if request.impact is ImpactClass.URGENT_MANUAL_REVIEW:
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
                message="The committed event-impact policy requires manual investment review.",
                evidence_codes=["URGENT_MANUAL_REVIEW"],
            )
        if request.impact is ImpactClass.FULL_REANALYSIS and (
            not runtime_available or not model_allowed
        ):
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.BLOCKED,
                failure_code=ReanalysisFailureCode.BLOCKED_RESEARCH_RUNTIME,
                message=_safe_message(ReanalysisFailureCode.BLOCKED_RESEARCH_RUNTIME),
                evidence_codes=["BLOCKED_RESEARCH_RUNTIME"],
            )

        prior = None
        prior_error: PriorAnalysisError | None = None
        if prior_analysis is not None:
            try:
                prior = self._validate_prior_analysis(
                    prior_analysis,
                    listing_id=request.listing_id,
                    profile_id=context.watchlist.profile_id,
                    execution_as_of=context.run.as_of,
                )
            except PriorAnalysisError as exc:
                prior_error = exc
        if prior_error is not None:
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.FAILED,
                failure_code=ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS,
                message=_safe_message(ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS),
                evidence_codes=["INVALID_PRIOR_ANALYSIS"],
            )

        try:
            normalized = self._prepare(
                context,
                request,
                prepared_input=prepared_input,
                network_allowed=network_allowed,
                provider=provider,
                company=company,
            )
        except Exception as exc:
            del exc
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.FAILED,
                failure_code=ReanalysisFailureCode.PREPARATION_FAILED,
                message=_safe_message(ReanalysisFailureCode.PREPARATION_FAILED),
                evidence_codes=["PREPARATION_FAILED"],
            )

        business_quality = None
        prior_ref: PriorAnalysisArtifact | None = None
        evidence_codes: list[str] = []
        if request.impact is ImpactClass.PARTIAL_REANALYSIS:
            if prior is not None and prior.analysis.business_quality is not None:
                try:
                    known_evidence = {item.id for item in normalized.evidence_index}
                    cited = {
                        evidence_id
                        for dimension in prior.analysis.business_quality.dimension_results
                        for evidence_id in (
                            *dimension.supporting_evidence_ids,
                            *dimension.counter_evidence_ids,
                        )
                    }
                    if not cited.issubset(known_evidence):
                        raise PriorAnalysisError(
                            "prior business-quality evidence is outside fresh input"
                        )
                    business_quality = prior.analysis.business_quality
                    prior_ref = prior
                    evidence_codes.append("REUSED_PRIOR_BQ")
                except PriorAnalysisError:
                    return self._persist_terminal(
                        context,
                        request,
                        capabilities=capabilities,
                        status=ReanalysisJobStatus.FAILED,
                        failure_code=ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS,
                        message=_safe_message(ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS),
                        evidence_codes=["INVALID_PRIOR_ANALYSIS"],
                    )
            else:
                evidence_codes.append("BUSINESS_QUALITY_NOT_REFRESHED")

        try:
            profile = self.profile_loader(context.watchlist.profile_id)
            effective_input = self._effective_input(normalized, accepted_adjustments)
            if request.impact is ImpactClass.PARTIAL_REANALYSIS:
                analysis = self._run_deterministic(
                    normalized,
                    profile,
                    accepted_adjustments=accepted_adjustments,
                    business_quality=business_quality,
                )
                trace = build_decision_trace(analysis)
                session = None
                report = None
            else:
                workflow = self._research_orchestrator(profile).research(
                    normalized,
                    accepted_adjustments=accepted_adjustments,
                )
                analysis = _required_attr(workflow, "analysis", CompanyAnalysis)
                trace = _required_attr(workflow, "decision_trace", DecisionTrace)
                session = _required_attr(workflow, "session", ResearchSession)
                report = _required_attr(workflow, "report", ResearchReport)
        except Exception as exc:
            failure_code = (
                ReanalysisFailureCode.RESEARCH_FAILED
                if request.impact is ImpactClass.FULL_REANALYSIS
                else ReanalysisFailureCode.ANALYSIS_FAILED
            )
            del exc
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.FAILED,
                failure_code=failure_code,
                message=_safe_message(failure_code),
                evidence_codes=evidence_codes or [failure_code.value],
                prior=prior_ref,
            )

        try:
            if analysis.analysis_id != effective_input.analysis_id:
                raise ReanalysisExecutionError("analysis identity does not match prepared input")
            if (
                _listing_identity(analysis.company.primary_listing)
                != _listing_identity(effective_input.company.primary_listing)
                or analysis.company != effective_input.company
                or analysis.facts != effective_input.facts
                or analysis.adjustments != effective_input.adjustments
                or analysis.evidence_index != effective_input.evidence_index
            ):
                raise ReanalysisExecutionError(
                    "analysis input lineage does not match the prepared input"
                )
            if analysis.as_of != context.run.as_of.date():
                raise ReanalysisExecutionError("analysis as_of does not match committed run")
            if analysis.profile_id != context.watchlist.profile_id:
                raise ReanalysisExecutionError("analysis profile does not match watchlist")
            if trace.analysis_id != analysis.analysis_id:
                raise ReanalysisExecutionError("trace analysis identity does not match analysis")
            surface = build_research_surface_snapshot(
                analysis,
                decision_trace=trace,
                research_report=report,
            )
            surface = validate_research_surface_snapshot(surface)
        except Exception as exc:
            del exc
            return self._persist_terminal(
                context,
                request,
                capabilities=capabilities,
                status=ReanalysisJobStatus.FAILED,
                failure_code=ReanalysisFailureCode.SURFACE_FAILED,
                message=_safe_message(ReanalysisFailureCode.SURFACE_FAILED),
                evidence_codes=evidence_codes or ["SURFACE_FAILED"],
                prior=prior_ref,
            )

        bundle = ReanalysisArtifactBundle(
            normalized_input=effective_input,
            analysis=analysis,
            trace=trace,
            surface=surface,
            research_session=session,
            report=report,
        )
        job = self._build_job(
            context,
            request,
            capabilities=capabilities,
            status=ReanalysisJobStatus.SUCCEEDED,
            evidence_codes=evidence_codes,
            prior=prior_ref,
            artifacts=bundle,
        )
        attempt = self.job_store.save(job, artifacts=bundle)
        return ReanalysisExecutionResult(
            job=attempt.job,
            attempt=attempt,
            reused=attempt is not None and existing is not None,
            artifacts=bundle,
        )

    def _prepare(
        self,
        context: _CommittedRunContext,
        request: ReanalysisRequestV1,
        *,
        prepared_input: NormalizedCompanyInput | None,
        network_allowed: bool,
        provider: str,
        company: Company | None,
    ) -> NormalizedCompanyInput:
        if prepared_input is not None:
            normalized = prepared_input
        else:
            if self.preparation is None:
                raise ReanalysisExecutionError("no preparation boundary is configured")
            acquisition = AcquisitionRequest(
                listing_id=request.listing_id,
                as_of=context.run.as_of.date(),
                provider=provider,
                profile_id=context.watchlist.profile_id,
            )
            active_company = company
            if company is not None:
                if _listing_identity(company.primary_listing) != _listing_identity(
                    request.listing_id
                ):
                    raise ReanalysisExecutionError(
                        "company context does not match committed listing"
                    )
                active_company = company.model_copy(
                    update={"primary_listing": acquisition.listing_id}
                )
                acquisition = acquisition.model_copy(update={"company": active_company})
            prepare = getattr(self.preparation, "prepare", self.preparation)
            kwargs = _supported_kwargs(
                prepare,
                {
                    "company": active_company,
                    "offline": not network_allowed,
                    "allow_stale": False,
                },
            )
            result = prepare(acquisition, **kwargs)
            if isinstance(result, NormalizedCompanyInput):
                normalized = result
            elif isinstance(result, tuple) and len(result) == 2:
                normalized = result[1]
            else:
                raise ReanalysisExecutionError(
                    "preparation boundary must return NormalizedCompanyInput or (bundle, input)"
                )
        if not isinstance(normalized, NormalizedCompanyInput):
            raise ReanalysisExecutionError("preparation did not return NormalizedCompanyInput")
        if (
            _listing_identity(normalized.company.primary_listing)
            != _listing_identity(request.listing_id)
            or normalized.as_of != context.run.as_of.date()
            or normalized.profile_id != context.watchlist.profile_id
        ):
            raise ReanalysisExecutionError(
                "prepared input does not match committed listing/profile/as_of"
            )
        if any(fact.applied_adjustment_ids for fact in normalized.facts):
            raise ReanalysisExecutionError(
                "fresh input contains prior materialized adjustment lineage"
            )
        # A fresh preparation is not allowed to carry a prior accepted proposal
        # implicitly.  Explicit caller-supplied adjustments are materialized
        # below through the existing effective-input boundary.
        return normalized.model_copy(update={"adjustments": []})

    @staticmethod
    def _effective_input(
        normalized: NormalizedCompanyInput,
        accepted_adjustments: Sequence[AdjustmentInput] | None,
    ) -> NormalizedCompanyInput:
        if not accepted_adjustments:
            return normalized
        return materialize_effective_input(normalized, accepted_adjustments)

    @staticmethod
    def _run_deterministic(
        normalized: NormalizedCompanyInput,
        profile: RuleProfile,
        *,
        accepted_adjustments: Sequence[AdjustmentInput] | None,
        business_quality: Any,
    ) -> CompanyAnalysis:
        if accepted_adjustments:
            return run_analyze_with_accepted_adjustments(
                normalized,
                accepted_adjustments,
                profile,
                business_quality=business_quality,
            )
        return run_analyze(normalized, profile, business_quality=business_quality)

    def _research_orchestrator(self, profile: RuleProfile) -> ResearchOrchestrator:
        if self.research_orchestrator is not None:
            return self.research_orchestrator
        if self.analyst_clients is None:
            raise ReanalysisExecutionError("no research runtime is configured")
        return ResearchOrchestrator(
            *self.analyst_clients,
            profile=profile,
            workspace=(
                None
                if self.research_root is None
                else ResearchWorkspace(self.research_root)
            ),
        )

    @staticmethod
    def _validate_prior_analysis(
        analysis: CompanyAnalysis,
        *,
        listing_id: str,
        profile_id: str,
        execution_as_of: datetime,
    ) -> PriorAnalysisArtifact:
        if not isinstance(analysis, CompanyAnalysis):
            raise PriorAnalysisError("prior analysis has an invalid type")
        if _listing_identity(analysis.company.primary_listing) != _listing_identity(
            listing_id
        ):
            raise PriorAnalysisError("prior analysis listing does not match request")
        if analysis.profile_id != profile_id:
            raise PriorAnalysisError("prior analysis profile does not match request")
        if analysis.as_of > normalize_utc(execution_as_of).date():
            raise PriorAnalysisError("prior analysis is later than execution point in time")
        return PriorAnalysisArtifact.build(analysis)

    def _build_job(
        self,
        context: _CommittedRunContext,
        request: ReanalysisRequestV1,
        *,
        capabilities: ReanalysisCapabilitySummaryV1,
        status: ReanalysisJobStatus,
        evidence_codes: Sequence[str] = (),
        message: str | None = None,
        failure_code: ReanalysisFailureCode | None = None,
        prior: PriorAnalysisArtifact | None = None,
        artifacts: ReanalysisArtifactBundle | None = None,
    ) -> ReanalysisJobV1:
        normalized_hash = None if artifacts is None else _model_sha256(artifacts.normalized_input)
        analysis_hash = None if artifacts is None else _model_sha256(artifacts.analysis)
        trace_hash = None if artifacts is None else _model_sha256(artifacts.trace)
        surface_hash = None if artifacts is None else _model_sha256(artifacts.surface)
        session_hash = (
            None
            if artifacts is None or artifacts.research_session is None
            else _model_sha256(artifacts.research_session)
        )
        report_hash = (
            None
            if artifacts is None or artifacts.report is None
            else _model_sha256(artifacts.report)
        )
        return ReanalysisJobV1.build(
            source_run_id=context.run.run_id,
            request_id=request.request_id,
            watchlist_id=request.watchlist_id,
            listing_id=request.listing_id,
            profile_id=context.watchlist.profile_id,
            impact=request.impact,
            event_ids=list(request.event_ids),
            event_types=[
                next(
                    event.event_type
                    for event in context.batch.events
                    if event.listing_id == request.listing_id and event.event_id == event_id
                )
                for event_id in request.event_ids
            ],
            source_watchlist_content_sha256=context.watchlist.content_sha256,
            event_batch_id=context.batch.batch_id,
            committed_run_proof_id=context.proof.commit_id,
            execution_as_of=context.run.as_of,
            capabilities=capabilities,
            status=status,
            failure_code=failure_code,
            message=message,
            evidence_codes=list(dict.fromkeys(evidence_codes)),
            prior_analysis_id=None if prior is None else prior.analysis.analysis_id,
            prior_analysis_sha256=None if prior is None else prior.content_sha256,
            normalized_input_sha256=normalized_hash,
            analysis_id=None if artifacts is None else artifacts.analysis.analysis_id,
            analysis_sha256=analysis_hash,
            trace_id=None if artifacts is None else artifacts.trace.analysis_id,
            trace_sha256=trace_hash,
            research_session_id=(
                None
                if artifacts is None or artifacts.research_session is None
                else artifacts.research_session.session_id
            ),
            research_session_sha256=session_hash,
            report_id=(
                None
                if artifacts is None or artifacts.report is None
                else artifacts.report.report_id
            ),
            report_sha256=report_hash,
            surface_id=None if artifacts is None else artifacts.surface.surface_id,
            surface_sha256=surface_hash,
        )

    def _persist_terminal(
        self,
        context: _CommittedRunContext,
        request: ReanalysisRequestV1,
        *,
        capabilities: ReanalysisCapabilitySummaryV1,
        status: ReanalysisJobStatus,
        message: str | None = None,
        evidence_codes: Sequence[str] = (),
        failure_code: ReanalysisFailureCode | None = None,
        prior: PriorAnalysisArtifact | None = None,
    ) -> ReanalysisExecutionResult:
        job = self._build_job(
            context,
            request,
            capabilities=capabilities,
            status=status,
            evidence_codes=evidence_codes,
            message=message,
            failure_code=failure_code,
            prior=prior,
        )
        attempt = self.job_store.save(job)
        return ReanalysisExecutionResult(
            job=attempt.job,
            attempt=attempt,
            reused=attempt.job.content_sha256 != job.content_sha256,
        )


def _combine_decision_impacts(decisions: Sequence[Any]) -> ImpactClass:
    rank = {
        ImpactClass.NO_REANALYSIS: 0,
        ImpactClass.PARTIAL_REANALYSIS: 1,
        ImpactClass.FULL_REANALYSIS: 2,
        ImpactClass.URGENT_MANUAL_REVIEW: 3,
    }
    return max((decision.impact for decision in decisions), key=rank.__getitem__)


def _listing_identity(value: str) -> str:
    """Compare common A/H listing spellings without merging different issues."""

    text = value.strip().upper()
    if "." in text:
        code, market = text.rsplit(".", 1)
        if market in {"SH", "SZ", "HK"}:
            return f"{market}{code}"
    return text


def _required_attr(value: object, name: str, expected_type: type[Any]) -> Any:
    result = getattr(value, name, None)
    if not isinstance(result, expected_type):
        raise ReanalysisExecutionError(
            f"research runtime result is missing typed {name} output"
        )
    return result


def _supported_kwargs(
    callable_value: Callable[..., object], candidates: Mapping[str, object]
) -> dict[str, object]:
    try:
        parameters = inspect.signature(callable_value).parameters
    except (TypeError, ValueError):
        return dict(candidates)
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(candidates)
    return {name: value for name, value in candidates.items() if name in parameters}


__all__ = [
    "PreparationBoundary",
    "PriorAnalysisArtifact",
    "PriorAnalysisError",
    "ReanalysisEligibilityError",
    "ReanalysisExecutionError",
    "ReanalysisExecutionResult",
    "ReanalysisExecutor",
]
