"""Deterministic bounded evidence-packet assembly."""

from __future__ import annotations

import math
import re
from calendar import monthrange
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from turtle_value_engine.models import (
    CompanyAnalysis,
    Evidence,
    Fact,
    NormalizedCompanyInput,
)
from turtle_value_engine.providers.normalization import deterministic_id

from .contracts import (
    RESEARCH_PROTOCOL_VERSION,
    AnalystRole,
    DeterministicMetric,
    EvidencePacket,
    PacketFact,
    ResearchIntent,
    ResearchQuestion,
)


class EvidencePacketError(ValueError):
    """Raised when a bounded packet cannot be assembled safely."""


_EXPECTED_INTENTS = {
    AnalystRole.QUALITY_ANALYST: ResearchIntent.THESIS,
    AnalystRole.SKEPTIC: ResearchIntent.FALSIFICATION,
    AnalystRole.ADJUDICATOR: ResearchIntent.ADJUDICATION,
}

_DIMENSION_FIELDS: dict[str, frozenset[str]] = {
    "demand_durability": frozenset(
        {
            "revenue",
            "core_revenue",
            "revenue_cagr_5y",
            "recurring_revenue_ratio",
            "demand_classification",
            "structural_demand_decline",
            "replacement_earnings_engine",
            "structural_disruption",
            "structural_disruption_revenue_ratio",
        }
    ),
    "cyclicality": frozenset(
        {
            "operating_profit",
            "profit_cv",
            "core_cdc",
            "core_cdc_cv",
            "cycle_phase",
            "gross_margin",
            "ebit_margin",
        }
    ),
    "pricing_power": frozenset(
        {
            "asp",
            "asp_change",
            "volume",
            "volume_change",
            "market_share",
            "gross_margin",
            "input_cost_change",
        }
    ),
    "moat": frozenset(
        {
            "roic",
            "market_share",
            "recurring_revenue_ratio",
            "customer_retention",
            "customer_acquisition_cost",
            "unit_cost",
        }
    ),
    "capital_efficiency": frozenset(
        {
            "capex_intensity",
            "normalized_operating_nwc",
            "invested_capital",
            "nopat",
            "roic",
            "core_cdc",
            "m_and_a_cash",
            "goodwill",
            "impairment",
        }
    ),
    "dependency": frozenset(
        {
            "largest_customer_ratio",
            "top5_customer_ratio",
            "channel_concentration",
            "critical_supplier_concentration",
            "single_point_dependency_ratio",
            "single_point_survival_dependency",
        }
    ),
    "regulatory_risk": frozenset(
        {
            "structural_disruption",
            "structural_disruption_revenue_ratio",
            "governance_risk_level",
            "single_point_dependency_ratio",
            "replacement_earnings_engine",
        }
    ),
    "predictability": frozenset(
        {
            "revenue",
            "core_revenue",
            "operating_profit",
            "gross_margin",
            "ebit_margin",
            "core_cdc",
            "profit_cv",
            "core_cdc_cv",
            "m_and_a_cash",
            "goodwill",
            "impairment",
        }
    ),
}

_DIMENSION_TERMS: dict[str, tuple[str, ...]] = {
    "demand_durability": ("demand", "customer", "renew", "repeat", "volume", "market"),
    "cyclicality": ("cycle", "cyclic", "recession", "margin", "profit", "downturn"),
    "pricing_power": ("price", "pricing", "asp", "cost", "margin", "volume"),
    "moat": ("moat", "competition", "share", "brand", "switch", "network", "license"),
    "capital_efficiency": ("capex", "capital", "roic", "return", "cash", "investment"),
    "dependency": ("customer", "supplier", "channel", "platform", "concentration"),
    "regulatory_risk": ("regulat", "policy", "license", "government", "export", "sanction"),
    "predictability": ("predict", "segment", "acquisition", "account", "margin", "cash"),
}

_PERIOD_PATTERNS = (
    re.compile(r"^AS_OF_(\d{4})-(\d{2})-(\d{2})$"),
    re.compile(r"^FY(\d{4})(?:-FY(\d{4}))?$"),
    re.compile(r"^(\d{4})[-_]?Q([1-4])$", re.IGNORECASE),
    re.compile(r"^(\d{4})-(\d{2})$"),
    re.compile(r"^(\d{4})$"),
)


def _period_end(period: str) -> date | None:
    """Parse only common period forms; unknown labels remain explicitly unresolved."""

    for index, pattern in enumerate(_PERIOD_PATTERNS):
        match = pattern.fullmatch(period.strip())
        if match is None:
            continue
        if index == 0:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
        if index == 1:
            return date(int(match.group(2) or match.group(1)), 12, 31)
        if index == 2:
            year = int(match.group(1))
            quarter = int(match.group(2))
            month = quarter * 3
            return date(year, month, monthrange(year, month)[1])
        if index == 3:
            year = int(match.group(1))
            month = int(match.group(2))
            if not 1 <= month <= 12:
                return None
            if month == 12:
                return date(year, 12, 31)
            return date(year, month + 1, 1) - date.resolution
        return date(int(match.group(1)), 12, 31)
    return None


def _fact_available(fact: Fact, as_of: date) -> bool:
    period_end = _period_end(fact.period)
    # An unknown/ambiguous period cannot be proven to be point-in-time safe.
    # Leave it out of the packet rather than allowing an analyst to treat it as
    # historical evidence.
    return period_end is not None and period_end <= as_of


def _evidence_available(evidence: Evidence, as_of: date) -> bool:
    published_date = evidence.source.published_date
    return published_date is None or published_date <= as_of


def _validated_input(value: NormalizedCompanyInput) -> NormalizedCompanyInput:
    if not isinstance(value, NormalizedCompanyInput):
        raise TypeError("normalized_input must be a NormalizedCompanyInput")
    return value


def _metric_values(analysis: CompanyAnalysis | None) -> list[DeterministicMetric]:
    """Project only scalar output metrics; never recalculate them here."""

    if analysis is None:
        return []
    result: list[DeterministicMetric] = []
    for group_name in ("cdc", "net_cash", "through_return"):
        group = getattr(analysis.metrics, group_name)
        raw = group.model_dump(mode="python", warnings=False)
        source_map = raw.get("source_evidence_ids", {})
        if not isinstance(source_map, Mapping):
            source_map = {}
        for field_name, value in raw.items():
            if field_name in {"flags", "confidence", "year_results", "source_evidence_ids"}:
                continue
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not math.isfinite(float(value)):
                continue
            evidence_ids = source_map.get(field_name, [])
            if not isinstance(evidence_ids, Iterable) or isinstance(evidence_ids, (str, bytes)):
                evidence_ids = []
            clean_evidence_ids = [item for item in evidence_ids if isinstance(item, str)]
            name = f"{group_name}.{field_name}"
            result.append(
                DeterministicMetric(
                    id=deterministic_id(
                        "deterministic-metric",
                        analysis.analysis_id,
                        analysis.as_of.isoformat(),
                        name,
                    ),
                    name=name,
                    value=float(value),
                    period=f"AS_OF_{analysis.as_of.isoformat()}",
                    source_evidence_ids=list(dict.fromkeys(clean_evidence_ids)),
                )
            )
    return sorted(result, key=lambda item: item.id)


def _candidate_score(
    evidence: Evidence,
    *,
    dimension: str | None,
    fact_evidence_ids: set[str],
) -> int:
    score = 0
    if evidence.id in fact_evidence_ids:
        score += 100
    if dimension is not None:
        statement = f"{evidence.source.title} {evidence.statement}".lower()
        score += sum(3 for term in _DIMENSION_TERMS.get(dimension, ()) if term in statement)
    if evidence.direction.value == "COUNTER":
        score += 1
    return score


def _select_evidence(
    normalized_input: NormalizedCompanyInput,
    *,
    as_of: date,
    dimension: str | None,
    explicit_ids: Sequence[str] | None,
    required_ids: Iterable[str],
    max_evidence_items: int,
) -> tuple[list[Evidence], list[str]]:
    by_id = {item.id: item for item in normalized_input.evidence_index}
    if len(by_id) != len(normalized_input.evidence_index):
        raise EvidencePacketError("normalized input contains duplicate evidence IDs")

    required = list(dict.fromkeys(required_ids))
    if explicit_ids is not None:
        selected_ids = list(dict.fromkeys(explicit_ids))
        unknown = sorted(set(selected_ids) - set(by_id))
        if unknown:
            raise EvidencePacketError(
                "packet requested undefined evidence ID(s): " + ", ".join(unknown)
            )
        if len(selected_ids) > max_evidence_items:
            raise EvidencePacketError("explicit packet evidence exceeds max_evidence_items")
    else:
        fact_evidence_ids = {
            evidence_id
            for fact in normalized_input.facts
            if dimension is None or fact.field in _DIMENSION_FIELDS.get(dimension, frozenset())
            for evidence_id in fact.source_evidence_ids
        }
        candidates = [
            item for item in normalized_input.evidence_index if _evidence_available(item, as_of)
        ]
        candidates.sort(
            key=lambda item: (
                -_candidate_score(item, dimension=dimension, fact_evidence_ids=fact_evidence_ids),
                item.id,
            )
        )
        selected_ids = [item.id for item in candidates[:max_evidence_items]]
        if required:
            missing_required = [item for item in required if item not in selected_ids]
            if len(selected_ids) + len(missing_required) > max_evidence_items:
                raise EvidencePacketError(
                    "required metric provenance cannot fit in the bounded evidence packet"
                )
            selected_ids.extend(missing_required)

    future = [
        evidence_id
        for evidence_id in selected_ids
        if not _evidence_available(by_id[evidence_id], as_of)
    ]
    if future:
        raise EvidencePacketError(
            "packet contains evidence published after as_of: " + ", ".join(future)
        )
    return [by_id[evidence_id] for evidence_id in selected_ids], [
        item.id for item in normalized_input.evidence_index if item.id not in selected_ids
    ]


def build_evidence_packet(
    normalized_input: NormalizedCompanyInput,
    *,
    question: ResearchQuestion,
    role: AnalystRole,
    analysis: CompanyAnalysis | None = None,
    evidence_ids: Sequence[str] | None = None,
    max_evidence_items: int = 32,
    max_fact_items: int = 128,
    max_metric_items: int = 64,
    protocol_version: str = RESEARCH_PROTOCOL_VERSION,
) -> EvidencePacket:
    """Build a reproducible packet with strict point-in-time and size bounds."""

    normalized_input = _validated_input(normalized_input)
    if analysis is not None and (
        analysis.analysis_id != normalized_input.analysis_id
        or analysis.as_of != normalized_input.as_of
        or analysis.profile_id != normalized_input.profile_id
        or analysis.company.primary_listing != normalized_input.company.primary_listing
    ):
        raise EvidencePacketError(
            "deterministic analysis and normalized input must have identical scope"
        )
    if max_evidence_items <= 0 or max_evidence_items > 128:
        raise ValueError("max_evidence_items must be between 1 and 128")
    if max_fact_items <= 0 or max_fact_items > 256:
        raise ValueError("max_fact_items must be between 1 and 256")
    if max_metric_items <= 0 or max_metric_items > 128:
        raise ValueError("max_metric_items must be between 1 and 128")
    expected_intent = _EXPECTED_INTENTS.get(role)
    if expected_intent is not None and question.intent is not expected_intent:
        raise EvidencePacketError(f"{role.value} packets require {expected_intent.value} intent")
    if question.dimension is not None and question.dimension not in _DIMENSION_FIELDS:
        raise EvidencePacketError(f"unknown business-quality dimension: {question.dimension}")

    metrics = _metric_values(analysis)[:max_metric_items]
    metric_evidence_ids = [
        evidence_id for metric in metrics for evidence_id in metric.source_evidence_ids
    ]
    explicit = None if evidence_ids is None else list(evidence_ids)
    if explicit is not None:
        missing_metric_evidence = [
            evidence_id for evidence_id in metric_evidence_ids if evidence_id not in explicit
        ]
        if missing_metric_evidence:
            explicit.extend(missing_metric_evidence)
    evidence, excluded_evidence_ids = _select_evidence(
        normalized_input,
        as_of=normalized_input.as_of,
        dimension=question.dimension,
        explicit_ids=explicit,
        required_ids=metric_evidence_ids,
        max_evidence_items=max_evidence_items,
    )
    available_ids = {item.id for item in evidence}
    facts = [
        PacketFact.from_fact(fact)
        for fact in normalized_input.facts
        if _fact_available(fact, normalized_input.as_of)
        and set(fact.source_evidence_ids).issubset(available_ids)
        and (
            question.dimension is None
            or fact.field in _DIMENSION_FIELDS.get(question.dimension, frozenset())
        )
    ][:max_fact_items]
    undated_ids = [item.id for item in evidence if item.source.published_date is None]
    metrics = [
        metric for metric in metrics if set(metric.source_evidence_ids).issubset(available_ids)
    ]
    packet = EvidencePacket.build(
        analysis_id=normalized_input.analysis_id,
        listing_id=normalized_input.company.primary_listing,
        as_of=normalized_input.as_of,
        profile_id=normalized_input.profile_id,
        role=role,
        question=question,
        evidence=evidence,
        facts=facts,
        deterministic_metrics=metrics,
        undated_evidence_ids=undated_ids,
        protocol_version=protocol_version,
    )
    # ``excluded_evidence_ids`` is intentionally not passed through as a
    # second unbounded corpus.  It is returned by the builder through the
    # packet's deterministic available-ID list only; callers can inspect the
    # normalized input if they need the omitted corpus.
    _ = excluded_evidence_ids
    return packet


class EvidencePacketBuilder:
    """Reusable configured wrapper around :func:`build_evidence_packet`."""

    def __init__(
        self,
        *,
        max_evidence_items: int = 32,
        max_fact_items: int = 128,
        max_metric_items: int = 64,
        protocol_version: str = RESEARCH_PROTOCOL_VERSION,
    ) -> None:
        self.max_evidence_items = max_evidence_items
        self.max_fact_items = max_fact_items
        self.max_metric_items = max_metric_items
        self.protocol_version = protocol_version

    def build(
        self,
        normalized_input: NormalizedCompanyInput,
        *,
        question: ResearchQuestion,
        role: AnalystRole,
        analysis: CompanyAnalysis | None = None,
        evidence_ids: Sequence[str] | None = None,
    ) -> EvidencePacket:
        return build_evidence_packet(
            normalized_input,
            question=question,
            role=role,
            analysis=analysis,
            evidence_ids=evidence_ids,
            max_evidence_items=self.max_evidence_items,
            max_fact_items=self.max_fact_items,
            max_metric_items=self.max_metric_items,
            protocol_version=self.protocol_version,
        )


__all__ = [
    "EvidencePacketBuilder",
    "EvidencePacketError",
    "build_evidence_packet",
]
