"""Auditable, deterministic report composition from validated artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from turtle_value_engine.models import (
    Adjustment,
    BusinessQuality,
    CompanyAnalysis,
    DataQuality,
    DecisionState,
    Gates,
    Metrics,
    ValuationResult,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id
from turtle_value_engine.traceability import DecisionTrace, build_decision_trace

from .contracts import AnalystRun, BusinessQualityResearchResult, ResearchSession


class ReportSection(BaseModel):
    """A structured report section with a stable category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "METADATA",
        "DETERMINISTIC_METRICS",
        "DETERMINISTIC_GATES",
        "BUSINESS_QUALITY",
        "ADJUSTMENTS",
        "DATA_QUALITY",
        "VALUATION",
        "DECISION",
        "PROVENANCE",
    ]
    title: StrictStr = Field(min_length=1)
    bullets: list[StrictStr] = Field(default_factory=list, max_length=128)


class ResearchReport(BaseModel):
    """Self-contained report whose embedded analysis is the authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["research_report_v1"] = "research_report_v1"
    report_id: StrictStr = Field(min_length=1)
    analysis: CompanyAnalysis
    decision_trace: DecisionTrace
    deterministic_state: DecisionState
    analysis_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    research_session_id: StrictStr | None = Field(default=None, min_length=1)
    analyst_run_ids: list[StrictStr] = Field(default_factory=list, max_length=1_024)
    proposed_adjustment_ids: list[StrictStr] = Field(default_factory=list, max_length=256)
    evidence_ids: list[StrictStr] = Field(default_factory=list, max_length=4_096)
    filing_ids: list[StrictStr] = Field(default_factory=list, max_length=1_024)
    accepted_adjustments: list[Adjustment] = Field(default_factory=list, max_length=256)
    unresolved_questions: list[StrictStr] = Field(default_factory=list, max_length=256)
    sections: list[ReportSection] = Field(min_length=1, max_length=16)
    text: StrictStr = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def validate_report_integrity(self) -> Self:
        analysis_payload = self.analysis.model_dump(mode="json", warnings=False)
        expected_hash = hashlib.sha256(canonical_json_bytes(analysis_payload)).hexdigest()
        if self.analysis_sha256 != expected_hash:
            raise ValueError("report analysis_sha256 does not match embedded analysis")
        if self.deterministic_state is not self.analysis.decision.state:
            raise ValueError("report deterministic_state contradicts embedded analysis")
        if any(
            adjustment.status.value != "ACCEPTED"
            or adjustment.approved_by is None
            or adjustment.approved_by.value not in {"HUMAN", "RULE_ENGINE"}
            for adjustment in self.accepted_adjustments
        ):
            raise ValueError("report accepted_adjustments contain an unapproved adjustment")
        if self.decision_trace.analysis_id != self.analysis.analysis_id:
            raise ValueError("report decision trace does not match embedded analysis")
        if self.decision_trace.decision_state != self.deterministic_state.value:
            raise ValueError("report decision trace contradicts embedded analysis")
        trace_evidence_ids = {item.id for item in self.decision_trace.evidence}
        if not set(self.evidence_ids).issubset(trace_evidence_ids):
            raise ValueError("report evidence_ids contain IDs absent from decision trace")
        trace_filing_ids = {item.filing_id for item in self.decision_trace.filings}
        if not set(self.filing_ids).issubset(trace_filing_ids):
            raise ValueError("report filing_ids contain IDs absent from decision trace")
        if f"Final deterministic state: {self.deterministic_state.value}" not in self.text:
            raise ValueError("report text must state the validated deterministic final state")
        expected_report_id = deterministic_id(
            "research-report",
            self.analysis.analysis_id,
            self.analysis_sha256,
            self.research_session_id,
            self.analyst_run_ids,
            self.proposed_adjustment_ids,
        )
        if self.report_id != expected_report_id:
            raise ValueError("report_id does not match report content identity")
        return self


    @classmethod
    def build(
        cls,
        *,
        analysis: CompanyAnalysis,
        decision_trace: DecisionTrace,
        sections: list[ReportSection],
        text: str,
        analyst_run_ids: list[str] | None = None,
        proposed_adjustment_ids: list[str] | None = None,
        research_session_id: str | None = None,
        evidence_ids: list[str] | None = None,
        filing_ids: list[str] | None = None,
        unresolved_questions: list[str] | None = None,
    ) -> ResearchReport:
        analysis_sha256 = hashlib.sha256(
            canonical_json_bytes(analysis.model_dump(mode="json", warnings=False))
        ).hexdigest()
        run_ids = list(analyst_run_ids or [])
        proposal_ids = list(proposed_adjustment_ids or [])
        report_id = deterministic_id(
            "research-report",
            analysis.analysis_id,
            analysis_sha256,
            research_session_id,
            run_ids,
            proposal_ids,
        )
        return cls(
            report_id=report_id,
            analysis=analysis,
            decision_trace=decision_trace,
            deterministic_state=analysis.decision.state,
            analysis_sha256=analysis_sha256,
            research_session_id=research_session_id,
            analyst_run_ids=run_ids,
            proposed_adjustment_ids=proposal_ids,
            evidence_ids=list(evidence_ids or []),
            filing_ids=list(filing_ids or []),
            accepted_adjustments=[
                adjustment
                for adjustment in analysis.adjustments
                if adjustment.status.value == "ACCEPTED"
            ],
            unresolved_questions=list(unresolved_questions or []),
            sections=sections,
            text=text,
        )


class ResearchWorkflowResult(BaseModel):
    """Typed aggregate returned by the complete research workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["research_workflow_result_v1"] = "research_workflow_result_v1"
    session: ResearchSession
    business_quality_research: BusinessQualityResearchResult
    analysis: CompanyAnalysis
    decision_trace: DecisionTrace
    report: ResearchReport


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _display(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _metric_bullets(metrics: Metrics) -> list[str]:
    bullets: list[str] = []
    for group_name in ("cdc", "net_cash", "through_return"):
        group = getattr(metrics, group_name)
        values = group.model_dump(mode="json", warnings=False)
        selected = [
            f"{field}={_display(value)}"
            for field, value in values.items()
            if field not in {"flags", "confidence", "source_evidence_ids"} and value is not None
        ]
        bullets.append(
            f"{group_name}: " + (", ".join(selected) if selected else "no scalar result")
        )
        flags = values.get("flags") or []
        if flags:
            bullets.append(f"{group_name} flags: {', '.join(flags)}")
    return bullets


def _gate_bullets(gates: Gates) -> list[str]:
    bullets: list[str] = []
    for name in (
        "universe",
        "balance_sheet",
        "cdc",
        "through_return",
        "business_quality",
        "governance_data_quality",
    ):
        gate = getattr(gates, name)
        bullets.append(f"{name}: {gate.status.value}")
        for reason in gate.blocking_reasons:
            bullets.append(f"{name} reason: {reason}")
    return bullets


def _business_quality_bullets(result: BusinessQuality | None) -> list[str]:
    if result is None:
        return ["Business Quality: NOT_EVALUATED; no agent judgment was supplied."]
    bullets = [
        "validated "
        f"score={_display(result.score)}/40, grade={_display(result.grade)}, "
        f"confidence={_display(result.confidence)}",
        f"evidence coverage={_display(result.evidence_coverage)}",
    ]
    for dimension in result.dimension_results:
        bullets.append(
            f"{dimension.dimension}: score={dimension.score}, "
            f"confidence={dimension.confidence.value}, "
            f"support={','.join(dimension.supporting_evidence_ids) or 'none'}, "
            f"counter={','.join(dimension.counter_evidence_ids) or 'none'}"
        )
    bullets.extend(f"critical weakness: {item}" for item in result.critical_weaknesses)
    bullets.extend(f"unresolved: {item}" for item in result.unresolved_questions)
    return bullets


def _adjustment_bullets(
    adjustments: Sequence[Adjustment], proposed_adjustment_ids: Sequence[str]
) -> list[str]:
    bullets = [
        f"{item.id}: {item.status.value} {item.target_field} ({item.proposed_by.value}"
        + (f", approved by {item.approved_by.value})" if item.approved_by else ")")
        for item in adjustments
    ]
    if proposed_adjustment_ids:
        bullets.append(
            "Agent proposals remain PROPOSED pending explicit review: "
            + ", ".join(proposed_adjustment_ids)
        )
    return bullets or ["No adjustment records were supplied."]


def _data_quality_bullets(data_quality: DataQuality) -> list[str]:
    bullets = [
        f"confidence={data_quality.confidence.value}, "
        f"evidence coverage={data_quality.evidence_coverage:.6g}",
    ]
    bullets.extend(f"critical missing: {item}" for item in data_quality.critical_missing_fields)
    if data_quality.notes:
        bullets.append(f"notes: {data_quality.notes}")
    return bullets


def _valuation_bullets(valuation: ValuationResult) -> list[str]:
    return [
        f"state={valuation.current_valuation_state.value}, "
        f"current price={_display(valuation.current_price)}, "
        f"listing-equivalent market cap={_display(valuation.listing_equivalent_market_cap)}",
        f"adjusted EV={_display(valuation.adjusted_ev)}, "
        f"ex-cash CDC yield={_display(valuation.ex_cash_cdc_yield)}",
        f"acceptable MOS={_display(valuation.mos_acceptable)}, "
        f"turtle MOS={_display(valuation.mos_turtle)}, "
        f"extreme MOS={_display(valuation.mos_extreme)}",
    ]


def compose_report(
    analysis: CompanyAnalysis,
    *,
    analyst_runs: Sequence[AnalystRun] | None = None,
    research_session_id: str | None = None,
) -> ResearchReport:
    """Compose a report without recalculating or mutating ``analysis``."""

    if not isinstance(analysis, CompanyAnalysis):
        raise TypeError("analysis must be a CompanyAnalysis")
    trace = build_decision_trace(analysis)
    runs = list(analyst_runs or [])
    for run in runs:
        if (
            run.analysis_id != analysis.analysis_id
            or run.listing_id != analysis.company.primary_listing
            or run.as_of != analysis.as_of
            or run.profile_id != analysis.profile_id
        ):
            raise ValueError("analyst run scope does not match report analysis")
    run_ids = _unique(run.run_id for run in runs)
    proposed_adjustment_ids = _unique(
        adjustment.id for run in runs for adjustment in run.finding.proposed_adjustments
    )
    evidence_ids = _unique(
        [
            *[item.id for item in analysis.evidence_index],
            *(evidence_id for run in runs for evidence_id in run.finding.evidence_ids),
        ]
    )
    filing_ids = _unique(
        item.provenance.filing_id for item in analysis.evidence_index if item.provenance is not None
    )
    unresolved = _unique(
        [
            *analysis.data_quality.critical_missing_fields,
            *(analysis.business_quality.unresolved_questions if analysis.business_quality else []),
            *analysis.decision.blocking_reasons,
        ]
    )
    sections = [
        ReportSection(
            kind="METADATA",
            title="Scope",
            bullets=[
                f"company={analysis.company.name}",
                f"listing={analysis.company.primary_listing}",
                f"as_of={analysis.as_of.isoformat()}",
                f"rule profile={analysis.profile_id}",
            ],
        ),
        ReportSection(
            kind="DETERMINISTIC_METRICS",
            title="Deterministic metrics",
            bullets=_metric_bullets(analysis.metrics),
        ),
        ReportSection(
            kind="DETERMINISTIC_GATES",
            title="Deterministic gates",
            bullets=_gate_bullets(analysis.gates),
        ),
        ReportSection(
            kind="BUSINESS_QUALITY",
            title="Agent Business Quality judgment (deterministically validated)",
            bullets=_business_quality_bullets(analysis.business_quality),
        ),
        ReportSection(
            kind="ADJUSTMENTS",
            title="Adjustments",
            bullets=_adjustment_bullets(analysis.adjustments, proposed_adjustment_ids),
        ),
        ReportSection(
            kind="DATA_QUALITY",
            title="Missing and unresolved data",
            bullets=_data_quality_bullets(analysis.data_quality),
        ),
        ReportSection(
            kind="VALUATION", title="Valuation", bullets=_valuation_bullets(analysis.valuation)
        ),
        ReportSection(
            kind="DECISION",
            title="Final deterministic decision",
            bullets=[
                f"Final deterministic state: {analysis.decision.state.value}",
                f"automatic decision allowed={analysis.decision.auto_decision_allowed}",
                analysis.decision.summary,
                *analysis.decision.blocking_reasons,
            ],
        ),
        ReportSection(
            kind="PROVENANCE",
            title="Evidence provenance",
            bullets=[
                f"evidence IDs={','.join(evidence_ids) or 'none'}",
                f"filing IDs={','.join(filing_ids) or 'none'}",
                f"analyst run IDs={','.join(run_ids) or 'none'}",
                "The report is a projection of validated artifacts and does not change them.",
            ],
        ),
    ]
    text_lines = [
        "Turtle Value Engine research report",
        f"Company: {analysis.company.name} ({analysis.company.primary_listing})",
        f"As of: {analysis.as_of.isoformat()} | Rule profile: {analysis.profile_id}",
        f"Final deterministic state: {analysis.decision.state.value}",
        "",
    ]
    for section in sections:
        text_lines.append(f"[{section.title}]")
        text_lines.extend(f"- {bullet}" for bullet in section.bullets)
        text_lines.append("")
    return ResearchReport.build(
        analysis=analysis,
        decision_trace=trace,
        sections=sections,
        text="\n".join(text_lines),
        analyst_run_ids=run_ids,
        proposed_adjustment_ids=proposed_adjustment_ids,
        research_session_id=research_session_id,
        evidence_ids=evidence_ids,
        filing_ids=filing_ids,
        unresolved_questions=unresolved,
    )


class ReportComposer:
    """Stable report-composition facade for external runtimes."""

    def compose(
        self,
        analysis: CompanyAnalysis,
        *,
        analyst_runs: Sequence[AnalystRun] | None = None,
        research_session_id: str | None = None,
    ) -> ResearchReport:
        return compose_report(
            analysis,
            analyst_runs=analyst_runs,
            research_session_id=research_session_id,
        )


__all__ = [
    "ReportComposer",
    "ReportSection",
    "ResearchReport",
    "ResearchWorkflowResult",
    "compose_report",
]
