"""Deterministic decision trace projection for completed analyses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from turtle_value_engine.models import CompanyAnalysis
from turtle_value_engine.models.common import FactValue


class TraceMetric(BaseModel):
    """One metric group and the source-side lineage it can reach."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: dict[str, object]
    fact_ids: list[str] = Field(default_factory=list)
    adjustment_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class TraceGate(BaseModel):
    """One gate with its deterministic rule IDs."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    rule_ids: list[str]


class TraceAdjustment(BaseModel):
    """Adjustment node retained in the final trace."""

    model_config = ConfigDict(extra="forbid")

    id: str
    target_field: str
    target_period: str | None = None
    status: str
    proposed_by: str
    approved_by: str | None = None
    source_evidence_ids: list[str]


class TraceFact(BaseModel):
    """Fact node, including effective-fact lineage when present."""

    model_config = ConfigDict(extra="forbid")

    id: str
    field: str
    period: str
    value: FactValue
    source_fact_id: str | None = None
    source_value: FactValue = None
    applied_adjustment_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str]


class TraceEvidence(BaseModel):
    """Evidence node and optional official-filing identity."""

    model_config = ConfigDict(extra="forbid")

    id: str
    direction: str
    strength: str
    source_type: str
    source_title: str
    source_url: str | None = None
    filing_id: str | None = None
    filing_source: str | None = None
    source_document_id: str | None = None
    block_sequence: int | None = None


class TraceFiling(BaseModel):
    """Official filing node inferred only from filing evidence provenance."""

    model_config = ConfigDict(extra="forbid")

    filing_id: str
    filing_source: str
    title: str
    url: str | None = None
    source_document_id: str | None = None
    evidence_ids: list[str]


class TraceLink(BaseModel):
    """One explicit edge along Decision→...→Filing."""

    model_config = ConfigDict(extra="forbid")

    decision_state: str
    gate: str
    gate_status: str
    rule_id: str
    metric: str
    evidence_id: str | None = None
    fact_id: str | None = None
    adjustment_ids: list[str] = Field(default_factory=list)
    filing_id: str | None = None


class DecisionTrace(BaseModel):
    """Complete deterministic trace projection; no new investment judgment."""

    model_config = ConfigDict(extra="forbid")

    contract: Literal["decision_trace_v1"] = "decision_trace_v1"
    analysis_id: str
    decision_state: str
    gates: list[TraceGate]
    metrics: list[TraceMetric]
    adjustments: list[TraceAdjustment]
    facts: list[TraceFact]
    evidence: list[TraceEvidence]
    filings: list[TraceFiling]
    links: list[TraceLink]


_GATE_TO_METRIC = {
    "universe": "eligibility",
    "balance_sheet": "net_cash",
    "cdc": "cdc",
    "through_return": "through_return",
    "business_quality": "business_quality",
    "governance_data_quality": "data_quality",
}
_GATE_NAMES = tuple(_GATE_TO_METRIC)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _source_url(evidence: object) -> str | None:
    source = getattr(evidence, "source", None)
    url = getattr(source, "url", None)
    return None if url is None else str(url)


def build_decision_trace(analysis: CompanyAnalysis) -> DecisionTrace:
    """Build a stable graph-like projection from one validated analysis.

    Gate rules already carry evidence IDs and effective facts carry accepted
    adjustment IDs.  The trace joins those existing references; it does not
    re-run metrics, gates or valuation and cannot change the decision.
    """

    if not isinstance(analysis, CompanyAnalysis):
        raise TypeError("analysis must be a CompanyAnalysis")
    facts = [
        TraceFact(
            id=fact.id,
            field=fact.field,
            period=fact.period,
            value=fact.value,
            source_fact_id=fact.source_fact_id,
            source_value=fact.source_value,
            applied_adjustment_ids=list(fact.applied_adjustment_ids),
            source_evidence_ids=list(fact.source_evidence_ids),
        )
        for fact in analysis.facts
    ]
    facts_by_evidence: dict[str, list[TraceFact]] = {}
    for fact in facts:
        for evidence_id in fact.source_evidence_ids:
            facts_by_evidence.setdefault(evidence_id, []).append(fact)

    adjustments = [
        TraceAdjustment(
            id=adjustment.id,
            target_field=adjustment.target_field,
            target_period=adjustment.target_period,
            status=adjustment.status.value,
            proposed_by=adjustment.proposed_by.value,
            approved_by=(
                None if adjustment.approved_by is None else adjustment.approved_by.value
            ),
            source_evidence_ids=list(adjustment.source_evidence_ids),
        )
        for adjustment in analysis.adjustments
    ]

    evidence_nodes: list[TraceEvidence] = []
    filing_evidence: dict[str, list[TraceEvidence]] = {}
    for evidence in analysis.evidence_index:
        provenance = evidence.provenance
        node = TraceEvidence(
            id=evidence.id,
            direction=evidence.direction.value,
            strength=evidence.strength.value,
            source_type=evidence.source.type.value,
            source_title=evidence.source.title,
            source_url=_source_url(evidence),
            filing_id=None if provenance is None else provenance.filing_id,
            filing_source=None if provenance is None else provenance.filing_source,
            source_document_id=(
                None if provenance is None else provenance.source_document_id
            ),
            block_sequence=None if provenance is None else provenance.block_sequence,
        )
        evidence_nodes.append(node)
        if node.filing_id is not None:
            filing_evidence.setdefault(node.filing_id, []).append(node)

    filings = [
        TraceFiling(
            filing_id=filing_id,
            filing_source=nodes[0].filing_source or "UNKNOWN",
            title=nodes[0].source_title,
            url=nodes[0].source_url,
            source_document_id=nodes[0].source_document_id,
            evidence_ids=[node.id for node in nodes],
        )
        for filing_id, nodes in sorted(filing_evidence.items())
    ]

    metric_nodes: list[TraceMetric] = []
    for metric_name, metric in (
        ("cdc", analysis.metrics.cdc),
        ("net_cash", analysis.metrics.net_cash),
        ("through_return", analysis.metrics.through_return),
    ):
        metric_evidence: list[str] = []
        source_evidence = getattr(metric, "source_evidence_ids", {})
        if isinstance(source_evidence, Mapping):
            metric_evidence = _unique(
                evidence_id
                for values in source_evidence.values()
                if isinstance(values, Iterable) and not isinstance(values, (str, bytes))
                for evidence_id in values
                if isinstance(evidence_id, str)
            )
        metric_facts = [
            fact
            for fact in facts
            if any(evidence_id in metric_evidence for evidence_id in fact.source_evidence_ids)
        ]
        metric_nodes.append(
            TraceMetric(
                name=metric_name,
                value=metric.model_dump(mode="json"),
                fact_ids=[fact.id for fact in metric_facts],
                adjustment_ids=_unique(
                    adjustment_id
                    for fact in metric_facts
                    for adjustment_id in fact.applied_adjustment_ids
                ),
                evidence_ids=metric_evidence,
            )
        )
    metric_nodes.append(
        TraceMetric(
            name="valuation",
            value=analysis.valuation.model_dump(mode="json"),
            fact_ids=[],
            adjustment_ids=[],
            evidence_ids=[],
        )
    )

    gate_nodes: list[TraceGate] = []
    links: list[TraceLink] = []
    for gate_name in _GATE_NAMES:
        gate = getattr(analysis.gates, gate_name)
        metric_name = _GATE_TO_METRIC[gate_name]
        gate_nodes.append(
            TraceGate(
                name=gate_name,
                status=gate.status.value,
                rule_ids=[rule.rule_id for rule in gate.rules],
            )
        )
        for rule in gate.rules:
            evidence_ids = list(rule.evidence_ids) or [None]
            for evidence_id in evidence_ids:
                linked_facts = (
                    facts_by_evidence.get(evidence_id, [])
                    if evidence_id is not None
                    else []
                ) or [None]
                for fact in linked_facts:
                    links.append(
                        TraceLink(
                            decision_state=analysis.decision.state.value,
                            gate=gate_name,
                            gate_status=gate.status.value,
                            rule_id=rule.rule_id,
                            metric=metric_name,
                            evidence_id=evidence_id,
                            fact_id=None if fact is None else fact.id,
                            adjustment_ids=(
                                [] if fact is None else list(fact.applied_adjustment_ids)
                            ),
                            filing_id=(
                                None
                                if evidence_id is None
                                else next(
                                    (
                                        node.filing_id
                                        for node in evidence_nodes
                                        if node.id == evidence_id
                                    ),
                                    None,
                                )
                            ),
                        )
                    )

    return DecisionTrace(
        analysis_id=analysis.analysis_id,
        decision_state=analysis.decision.state.value,
        gates=gate_nodes,
        metrics=metric_nodes,
        adjustments=adjustments,
        facts=facts,
        evidence=evidence_nodes,
        filings=filings,
        links=links,
    )


def trace_analysis(analysis: CompanyAnalysis) -> DecisionTrace:
    """Public alias for callers that use the analysis-centric vocabulary."""

    return build_decision_trace(analysis)


def trace_decision(analysis: CompanyAnalysis) -> DecisionTrace:
    """Public alias for callers that start at the final decision."""

    return build_decision_trace(analysis)


__all__ = [
    "DecisionTrace",
    "TraceAdjustment",
    "TraceEvidence",
    "TraceFact",
    "TraceFiling",
    "TraceGate",
    "TraceLink",
    "TraceMetric",
    "build_decision_trace",
    "trace_analysis",
    "trace_decision",
]
