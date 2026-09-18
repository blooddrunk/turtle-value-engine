"""Build a deterministic read-only surface from explicit frozen artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from turtle_value_engine.historical import (
    AcquisitionReadinessReportV1,
    HistoricalDatasetManifest,
    HistoricalValidationSummary,
    PrivateAcceptanceReportV1,
)
from turtle_value_engine.models import (
    BusinessQuality,
    Company,
    CompanyAnalysis,
    DataQuality,
    Decision,
    ValuationResult,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.research.report import ResearchReport
from turtle_value_engine.traceability import DecisionTrace, build_decision_trace

from .contracts import (
    ResearchSurfaceSnapshotV1,
    SurfaceAcceptanceStatus,
    SurfaceAnalysisView,
    SurfaceArtifactReference,
    SurfaceCDCMetric,
    SurfaceCoverageRecord,
    SurfaceGate,
    SurfaceGateRule,
    SurfaceGates,
    SurfaceHistoricalStatus,
    SurfaceMetrics,
    SurfaceNetCashMetric,
    SurfaceReadinessStatus,
    SurfaceSourceFreshness,
    SurfaceTargetScope,
    SurfaceThroughReturnMetric,
    SurfaceValidationStatus,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class SurfaceProjectionError(ValueError):
    """Raised when explicit source artifacts cannot form a safe projection."""


def _coerce(value: ModelT | Mapping[str, object], model_type: type[ModelT], name: str) -> ModelT:
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        try:
            return model_type.model_validate(dict(value))
        except Exception as exc:
            raise SurfaceProjectionError(f"invalid {name} artifact: {exc}") from exc
    raise TypeError(f"{name} must be {model_type.__name__} or a JSON object")


def _sha256_model(value: BaseModel) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value.model_dump(mode="json", warnings=False))
    ).hexdigest()


def _copy_company(company: Company) -> Company:
    """Copy only declared identity fields; never copy an arbitrary mapping."""

    return Company(
        name=company.name,
        legal_name=company.legal_name,
        primary_listing=company.primary_listing,
        other_listings=list(company.other_listings),
        sector=company.sector,
        industry=company.industry,
        country_or_region=company.country_or_region,
        reporting_currency=company.reporting_currency,
        accounting_standard=company.accounting_standard,
        accounting_standard_version=company.accounting_standard_version,
        fiscal_year_end=company.fiscal_year_end,
        special_model=company.special_model,
    )


def _copy_metric(
    source: BaseModel,
    target_type: type[BaseModel],
    fields: tuple[str, ...],
) -> BaseModel:
    """Project a metric through an explicit field allowlist."""

    values: dict[str, object] = {}
    for field in fields:
        value = getattr(source, field)
        if isinstance(value, list):
            values[field] = list(value)
        elif isinstance(value, dict):
            values[field] = {
                key: list(child) if isinstance(child, list) else child
                for key, child in value.items()
            }
        else:
            values[field] = value
    return target_type.model_validate(values)


_CDC_FIELDS = (
    "reported_cfo",
    "adjusted_cfo",
    "economic_gross_capex",
    "lease_principal_outside_cfo",
    "core_cdc",
    "parent_core_cdc",
    "normalized_core_cdc",
    "normalized_parent_core_cdc",
    "cdc_yield",
    "positive_years_5y",
    "cumulative_core_cdc_5y",
    "all_in_cdc",
    "all_in_cdc_5y",
    "flags",
    "confidence",
)
_NET_CASH_FIELDS = (
    "book_cash",
    "strict_cash",
    "owner_accessible_cash",
    "financial_debt",
    "lease_debt",
    "debt_equivalent",
    "financial_net_cash",
    "obligation_adjusted_net_cash",
    "owner_debt_equivalent",
    "book_net_cash",
    "strict_net_cash",
    "owner_realizable_net_cash",
    "valuation_net_cash",
    "adjusted_ev",
    "ex_cash_cdc_yield",
    "owner_net_cash_ratio",
    "liquidity_coverage",
    "stress_coverage",
    "net_debt_to_ebitda",
    "interest_coverage",
    "source_evidence_ids",
    "flags",
    "confidence",
)
_THROUGH_RETURN_FIELDS = (
    "normalized_parent_profit",
    "normalized_parent_core_cdc",
    "distributable_base",
    "payout_policy_floor",
    "conservative_payout_ratio",
    "dividend_through_return",
    "normalized_net_share_reduction",
    "through_return",
    "special_return",
    "flags",
    "policy_confidence",
    "confidence",
    "verified_recurring_buyback_cash",
    "buyback_credit_eligible",
    "buyback_history_years",
    "source_evidence_ids",
)


def _copy_metrics(analysis: CompanyAnalysis) -> SurfaceMetrics:
    return SurfaceMetrics(
        cdc=_copy_metric(analysis.metrics.cdc, SurfaceCDCMetric, _CDC_FIELDS),
        net_cash=_copy_metric(analysis.metrics.net_cash, SurfaceNetCashMetric, _NET_CASH_FIELDS),
        through_return=_copy_metric(
            analysis.metrics.through_return,
            SurfaceThroughReturnMetric,
            _THROUGH_RETURN_FIELDS,
        ),
    )


def _copy_gate(source: BaseModel) -> SurfaceGate:
    return SurfaceGate(
        status=source.status.value,
        rules=[
            SurfaceGateRule(
                rule_id=rule.rule_id,
                status=rule.status.value,
                actual=rule.actual,
                threshold=rule.threshold,
                evidence_ids=list(rule.evidence_ids),
                message=rule.message,
            )
            for rule in source.rules
        ],
        blocking_reasons=list(source.blocking_reasons),
        confidence=source.confidence,
    )


def _copy_gates(analysis: CompanyAnalysis) -> SurfaceGates:
    return SurfaceGates(
        universe=_copy_gate(analysis.gates.universe),
        balance_sheet=_copy_gate(analysis.gates.balance_sheet),
        cdc=_copy_gate(analysis.gates.cdc),
        through_return=_copy_gate(analysis.gates.through_return),
        business_quality=_copy_gate(analysis.gates.business_quality),
        governance_data_quality=_copy_gate(analysis.gates.governance_data_quality),
    )


def _copy_strict_model(value: ModelT, model_type: type[ModelT]) -> ModelT:
    """Copy a repository model after its own extra-forbid validation."""

    return model_type.model_validate(value.model_dump(mode="json", warnings=False))


def _analysis_view(analysis: CompanyAnalysis) -> SurfaceAnalysisView:
    business_quality_evaluated = analysis.gates.business_quality.status.value != "NOT_EVALUATED"
    business_quality = (
        None
        if analysis.business_quality is None or not business_quality_evaluated
        else _copy_strict_model(analysis.business_quality, BusinessQuality)
    )
    return SurfaceAnalysisView(
        analysis_id=analysis.analysis_id,
        as_of=analysis.as_of,
        profile_id=analysis.profile_id,
        company=_copy_company(analysis.company),
        data_quality=_copy_strict_model(analysis.data_quality, DataQuality),
        metrics=_copy_metrics(analysis),
        gates=_copy_gates(analysis),
        valuation=_copy_strict_model(analysis.valuation, ValuationResult),
        decision=_copy_strict_model(analysis.decision, Decision),
        business_quality=business_quality,
        business_quality_status=("NOT_EVALUATED" if business_quality is None else "VALIDATED"),
        flags=list(analysis.flags),
        evidence_ids=[item.id for item in analysis.evidence_index],
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _date_boundary_check(analysis: CompanyAnalysis, manifest: HistoricalDatasetManifest) -> None:
    if manifest.target.end_date > analysis.as_of:
        raise SurfaceProjectionError(
            "historical manifest extends beyond analysis as_of: "
            f"{manifest.target.end_date} > {analysis.as_of}"
        )
    for report in manifest.coverage_reports:
        for record in report.records:
            if record.period_end > analysis.as_of:
                raise SurfaceProjectionError(
                    "historical coverage extends beyond analysis as_of: "
                    f"{record.period_end} > {analysis.as_of}"
                )


def _target_scope(manifest: HistoricalDatasetManifest) -> SurfaceTargetScope:
    target = manifest.target
    return SurfaceTargetScope(
        target_id=target.target_id,
        target_name=target.target_name,
        universe_id=target.universe_id,
        markets=[item.value for item in target.markets],
        listing_ids=list(target.listing_ids),
        start_date=target.start_date,
        end_date=target.end_date,
        membership_claim=target.membership_claim,
        coverage_claim=target.coverage_claim.value,
        required_source_kinds=[item.value for item in target.required_source_kinds],
    )


def _coverage_records(manifest: HistoricalDatasetManifest) -> list[SurfaceCoverageRecord]:
    records: list[SurfaceCoverageRecord] = []
    for report in manifest.coverage_reports:
        for record in report.records:
            records.append(
                SurfaceCoverageRecord(
                    source_kind=record.source_kind.value,
                    listing_id=record.listing_id,
                    period_start=record.period_start,
                    period_end=record.period_end,
                    expected_session_count=record.expected_session_count,
                    observed_session_count=record.observed_session_count,
                    missing_date_count=len(record.missing_dates),
                    source_artifact_ids=list(record.source_artifact_ids),
                    status=record.status.value,
                    terminal_outcome=(
                        None
                        if record.terminal_outcome is None
                        else record.terminal_outcome.value
                    ),
                    evidence_basis=(
                        None if record.evidence_basis is None else record.evidence_basis.value
                    ),
                )
            )
    return sorted(
        records,
        key=lambda item: (
            item.source_kind,
            item.listing_id,
            item.period_start,
            item.period_end,
        ),
    )


def _acceptance_status(
    acceptance: PrivateAcceptanceReportV1 | None,
) -> SurfaceAcceptanceStatus:
    if acceptance is None:
        return SurfaceAcceptanceStatus(status="NOT_AVAILABLE")
    return SurfaceAcceptanceStatus(
        status="ACCEPTED" if acceptance.accepted else "BLOCKED",
        plan_id=acceptance.plan_id,
        target_id=acceptance.target_id,
        dataset_id=acceptance.dataset_id,
        probe_report_id=acceptance.probe_report_id,
        probe_network_used=acceptance.probe_network_used,
        offline_replay_verified=acceptance.offline_replay_verified,
        accepted=acceptance.accepted,
        checks=dict(sorted(acceptance.checks.items())),
        blockers=list(acceptance.blockers),
        report_sha256=acceptance.report_sha256,
    )


def _readiness_status(
    readiness: AcquisitionReadinessReportV1 | None,
) -> SurfaceReadinessStatus:
    if readiness is None:
        return SurfaceReadinessStatus(status="NOT_AVAILABLE")
    return SurfaceReadinessStatus(
        status="AVAILABLE",
        report_id=readiness.report_id,
        plan_id=readiness.plan_id,
        generated_at=readiness.generated_at,
        readiness=readiness.readiness,
        network_used=readiness.network_used,
        acquisition_ready=readiness.acquisition_ready,
        personal_research_ready=readiness.personal_research_ready,
        production_eligible=readiness.production_eligible,
        batch_ids=list(readiness.batch_ids),
        compiled_dataset_id=readiness.compiled_dataset_id,
        probe_report_ids=[item.report_id for item in readiness.probe_reports],
        blockers=list(readiness.blockers),
        warnings=list(readiness.warnings),
        report_sha256=readiness.report_sha256,
    )


def _validation_status(
    validation: HistoricalValidationSummary | None,
) -> SurfaceValidationStatus:
    if validation is None:
        return SurfaceValidationStatus(status="NOT_AVAILABLE")
    return SurfaceValidationStatus(
        status="AVAILABLE",
        dataset_id=validation.dataset_id,
        valid=validation.valid,
        production_eligible=validation.production_eligible,
        shard_rows=dict(sorted(validation.shard_rows.items())),
        coverage_status=dict(sorted(validation.coverage_status.items())),
        production_blockers=list(validation.production_blockers),
        errors=list(validation.errors),
        warnings=list(validation.warnings),
        content_sha256=_sha256_model(validation),
    )


def _source_freshness(manifest: HistoricalDatasetManifest) -> list[SurfaceSourceFreshness]:
    return [
        SurfaceSourceFreshness(
            source_id=source.source_id,
            source_kind=source.source_kind.value,
            coverage_start=source.coverage_start,
            coverage_end=source.coverage_end,
            retrieved_at=source.retrieved_at,
            coverage_listing_count=len(source.coverage_listing_ids),
            content_sha256=source.content_sha256,
        )
        for source in sorted(manifest.source_descriptors, key=lambda item: item.source_id)
    ]


def _historical_status(
    analysis: CompanyAnalysis,
    *,
    historical_manifest: HistoricalDatasetManifest | None,
    acceptance: PrivateAcceptanceReportV1 | None,
    readiness: AcquisitionReadinessReportV1 | None,
    validation: HistoricalValidationSummary | None,
) -> SurfaceHistoricalStatus:
    if historical_manifest is not None:
        _date_boundary_check(analysis, historical_manifest)

    dataset_ids = {
        value
        for value in (
            None if historical_manifest is None else historical_manifest.dataset_id,
            None if acceptance is None else acceptance.dataset_id,
            None if readiness is None else readiness.compiled_dataset_id,
            None if validation is None else validation.dataset_id,
        )
        if value is not None
    }
    if len(dataset_ids) > 1:
        raise SurfaceProjectionError(
            "historical artifact dataset identities do not match: "
            + ", ".join(sorted(dataset_ids))
        )
    dataset_id = next(iter(dataset_ids), None)
    if historical_manifest is not None and acceptance is not None:
        if acceptance.target_id != historical_manifest.target.target_id:
            raise SurfaceProjectionError("historical acceptance target does not match manifest")
    if historical_manifest is not None and readiness is not None:
        if readiness.compiled_dataset_id not in {None, historical_manifest.dataset_id}:
            raise SurfaceProjectionError("historical readiness dataset does not match manifest")

    acceptance_view = _acceptance_status(acceptance)
    readiness_view = _readiness_status(readiness)
    validation_view = _validation_status(validation)
    blockers = _unique(
        [
            *([] if acceptance is None else acceptance.blockers),
            *([] if readiness is None else readiness.blockers),
            *([] if validation is None else validation.production_blockers),
            *([] if validation is None else validation.errors),
        ]
    )
    warnings = _unique(
        [
            *([] if readiness is None else readiness.warnings),
            *([] if validation is None else validation.warnings),
        ]
    )
    limitations = [] if historical_manifest is None else list(historical_manifest.limitations)

    if not any((historical_manifest, acceptance, readiness, validation)):
        return SurfaceHistoricalStatus(
            availability="NOT_AVAILABLE",
            claim_state="NOT_AVAILABLE",
            acceptance=acceptance_view,
            readiness=readiness_view,
            validation=validation_view,
        )

    if readiness is not None and readiness.generated_at.date() > analysis.as_of:
        raise SurfaceProjectionError(
            "historical readiness report is newer than analysis as_of: "
            f"{readiness.generated_at.date()} > {analysis.as_of}"
        )

    production_eligible = (
        readiness.production_eligible
        if readiness is not None
        else None if validation is None else validation.production_eligible
    )
    if acceptance is not None and not acceptance.accepted:
        claim_state = "BLOCKED"
    elif blockers:
        claim_state = "BLOCKED"
    elif production_eligible:
        claim_state = "PRODUCTION_ELIGIBLE"
    elif readiness is not None and (
        readiness.personal_research_ready or readiness.acquisition_ready
    ):
        claim_state = "READY"
    elif acceptance is not None and acceptance.accepted:
        claim_state = "READY"
    elif (
        historical_manifest is not None
        and historical_manifest.target.coverage_claim.value == "PARTIAL"
    ):
        claim_state = "PARTIAL"
    else:
        claim_state = "UNKNOWN"

    return SurfaceHistoricalStatus(
        availability="AVAILABLE",
        claim_state=claim_state,
        dataset_id=dataset_id,
        dataset_version=(
            None if historical_manifest is None else historical_manifest.dataset_version
        ),
        manifest_sha256=(
            None if historical_manifest is None else historical_manifest.content_sha256
        ),
        target_scope=None if historical_manifest is None else _target_scope(historical_manifest),
        coverage=[] if historical_manifest is None else _coverage_records(historical_manifest),
        source_freshness=(
            [] if historical_manifest is None else _source_freshness(historical_manifest)
        ),
        acceptance=acceptance_view,
        readiness=readiness_view,
        validation=validation_view,
        production_eligible=production_eligible,
        blockers=blockers,
        warnings=warnings,
        limitations=limitations,
    )


def _reference(
    artifact_type: str,
    artifact_id: str,
    value: BaseModel,
    *,
    as_of: date | None,
) -> SurfaceArtifactReference:
    return SurfaceArtifactReference(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        content_sha256=_sha256_model(value),
        as_of=as_of,
    )


def build_research_surface_snapshot(
    analysis: CompanyAnalysis | Mapping[str, object],
    *,
    decision_trace: DecisionTrace | Mapping[str, object] | None = None,
    research_report: ResearchReport | Mapping[str, object] | None = None,
    historical_manifest: HistoricalDatasetManifest | Mapping[str, object] | None = None,
    historical_acceptance: PrivateAcceptanceReportV1 | Mapping[str, object] | None = None,
    historical_readiness: AcquisitionReadinessReportV1 | Mapping[str, object] | None = None,
    historical_validation: HistoricalValidationSummary | Mapping[str, object] | None = None,
    trace: DecisionTrace | Mapping[str, object] | None = None,
    report: ResearchReport | Mapping[str, object] | None = None,
    acceptance: PrivateAcceptanceReportV1 | Mapping[str, object] | None = None,
) -> ResearchSurfaceSnapshotV1:
    """Project explicit validated artifacts into one deterministic snapshot.

    Mappings are persisted JSON inputs and are immediately validated against
    the existing typed contracts.  This function never searches a workspace,
    opens a store, invokes a provider, or invokes an analyst.
    """

    if decision_trace is not None and trace is not None:
        raise SurfaceProjectionError("supply only one of decision_trace or trace")
    if research_report is not None and report is not None:
        raise SurfaceProjectionError("supply only one of research_report or report")
    if historical_acceptance is not None and acceptance is not None:
        raise SurfaceProjectionError("supply only one of historical_acceptance or acceptance")

    analysis_model = _coerce(analysis, CompanyAnalysis, "CompanyAnalysis")
    trace_input = decision_trace if decision_trace is not None else trace
    trace_model = (
        None
        if trace_input is None
        else _coerce(trace_input, DecisionTrace, "decision trace")
    )
    report_input = research_report if research_report is not None else report
    report_model = (
        None if report_input is None else _coerce(report_input, ResearchReport, "research report")
    )
    manifest_model = (
        None
        if historical_manifest is None
        else _coerce(historical_manifest, HistoricalDatasetManifest, "historical manifest")
    )
    acceptance_input = (
        historical_acceptance if historical_acceptance is not None else acceptance
    )
    acceptance_model = (
        None
        if acceptance_input is None
        else _coerce(acceptance_input, PrivateAcceptanceReportV1, "historical acceptance")
    )
    readiness_model = (
        None
        if historical_readiness is None
        else _coerce(historical_readiness, AcquisitionReadinessReportV1, "historical readiness")
    )
    validation_model = (
        None
        if historical_validation is None
        else _coerce(
            historical_validation, HistoricalValidationSummary, "historical validation"
        )
    )

    expected_trace = build_decision_trace(analysis_model)
    if trace_model is not None:
        if trace_model.analysis_id != analysis_model.analysis_id:
            raise SurfaceProjectionError("decision trace analysis identity does not match")
        if trace_model.model_dump(mode="json", warnings=False) != expected_trace.model_dump(
            mode="json", warnings=False
        ):
            raise SurfaceProjectionError("decision trace content does not match analysis")
    analysis_hash = _sha256_model(analysis_model)
    if report_model is not None:
        if report_model.analysis.analysis_id != analysis_model.analysis_id:
            raise SurfaceProjectionError("research report analysis identity does not match")
        if report_model.analysis.as_of != analysis_model.as_of:
            raise SurfaceProjectionError("research report as_of does not match analysis")
        if report_model.analysis.profile_id != analysis_model.profile_id:
            raise SurfaceProjectionError("research report profile does not match analysis")
        if report_model.analysis_sha256 != analysis_hash:
            raise SurfaceProjectionError("research report analysis hash does not match analysis")
        if report_model.decision_trace.model_dump(
            mode="json", warnings=False
        ) != expected_trace.model_dump(mode="json", warnings=False):
            raise SurfaceProjectionError("research report trace does not match analysis")
        if trace_model is not None and _sha256_model(trace_model) != _sha256_model(
            report_model.decision_trace
        ):
            raise SurfaceProjectionError(
                "decision trace and research report references do not match"
            )

    analysis_view = _analysis_view(analysis_model)
    historical_view = _historical_status(
        analysis_model,
        historical_manifest=manifest_model,
        acceptance=acceptance_model,
        readiness=readiness_model,
        validation=validation_model,
    )

    source_artifacts = [
        _reference(
            "COMPANY_ANALYSIS",
            analysis_model.analysis_id,
            analysis_model,
            as_of=analysis_model.as_of,
        )
    ]
    trace_reference = None
    if trace_model is not None:
        trace_reference = _reference(
            "DECISION_TRACE",
            trace_model.analysis_id,
            trace_model,
            as_of=analysis_model.as_of,
        )
        source_artifacts.append(trace_reference)
    report_reference = None
    if report_model is not None:
        report_reference = _reference(
            "RESEARCH_REPORT",
            report_model.report_id,
            report_model,
            as_of=analysis_model.as_of,
        )
        source_artifacts.append(report_reference)
    if manifest_model is not None:
        source_artifacts.append(
            SurfaceArtifactReference(
                artifact_type="HISTORICAL_MANIFEST",
                artifact_id=manifest_model.dataset_id,
                content_sha256=manifest_model.content_sha256,
                as_of=analysis_model.as_of,
            )
        )
    if acceptance_model is not None:
        source_artifacts.append(
            SurfaceArtifactReference(
                artifact_type="HISTORICAL_ACCEPTANCE",
                artifact_id=f"{acceptance_model.plan_id}:{acceptance_model.target_id}",
                content_sha256=acceptance_model.report_sha256,
                as_of=analysis_model.as_of,
            )
        )
    if readiness_model is not None:
        source_artifacts.append(
            SurfaceArtifactReference(
                artifact_type="HISTORICAL_READINESS",
                artifact_id=readiness_model.report_id,
                content_sha256=readiness_model.report_sha256,
                as_of=analysis_model.as_of,
            )
        )
    if validation_model is not None:
        source_artifacts.append(
            SurfaceArtifactReference(
                artifact_type="HISTORICAL_VALIDATION",
                artifact_id=validation_model.dataset_id,
                content_sha256=_sha256_model(validation_model),
                as_of=analysis_model.as_of,
            )
        )

    return ResearchSurfaceSnapshotV1.build(
        analysis_id=analysis_model.analysis_id,
        as_of=analysis_model.as_of,
        profile_id=analysis_model.profile_id,
        company=_copy_company(analysis_model.company),
        analysis=analysis_view,
        source_artifacts=source_artifacts,
        decision_trace_reference=trace_reference,
        research_report_reference=report_reference,
        accepted_adjustment_ids=sorted(
            adjustment.id
            for adjustment in analysis_model.adjustments
            if adjustment.status.value == "ACCEPTED"
        ),
        historical_status=historical_view,
    )


def build_surface_snapshot(*args: Any, **kwargs: Any) -> ResearchSurfaceSnapshotV1:
    """Short alias for the public surface builder."""

    return build_research_surface_snapshot(*args, **kwargs)


def project_research_surface(*args: Any, **kwargs: Any) -> ResearchSurfaceSnapshotV1:
    """Descriptive alias used by integrations that call this a projection."""

    return build_research_surface_snapshot(*args, **kwargs)


def validate_research_surface_snapshot(
    value: ResearchSurfaceSnapshotV1 | Mapping[str, object],
) -> ResearchSurfaceSnapshotV1:
    """Validate a persisted snapshot and its deterministic identity."""

    if isinstance(value, ResearchSurfaceSnapshotV1):
        return ResearchSurfaceSnapshotV1.model_validate(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return ResearchSurfaceSnapshotV1.model_validate(dict(value))
    raise TypeError("surface snapshot must be ResearchSurfaceSnapshotV1 or a JSON object")


def load_research_surface_snapshot(path: str | Path) -> ResearchSurfaceSnapshotV1:
    """Load one explicit snapshot file; no directory discovery is performed."""

    import json

    file_path = Path(path)
    value = json.loads(file_path.read_text(encoding="utf-8"), parse_constant=_reject_json_number)
    return validate_research_surface_snapshot(value)


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


__all__ = [
    "SurfaceProjectionError",
    "build_research_surface_snapshot",
    "build_surface_snapshot",
    "load_research_surface_snapshot",
    "project_research_surface",
    "validate_research_surface_snapshot",
]
