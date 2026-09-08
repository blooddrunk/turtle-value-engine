"""Deterministic, offline validation of evidence-backed business quality.

The business-quality analyst supplies the eight structured dimension scores.
This module is the rule-engine boundary: it resolves evidence references,
enforces the strict-v1 high-score caps, calculates coverage/confidence and
recomputes the aggregate grade.  It deliberately does not infer a score from
company facts or generate an investment recommendation.
"""

from collections.abc import Iterable, Sequence

from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import (
    BusinessQuality,
    BusinessQualityDimension,
    BusinessQualityInput,
    ConfidenceLevel,
    Evidence,
    NormalizedCompanyInput,
)


class BusinessQualityCalculationError(ValueError):
    """Raised when a structured business-quality assessment is ambiguous."""


BUSINESS_QUALITY_DIMENSIONS = (
    "demand_durability",
    "cyclicality",
    "pricing_power",
    "moat",
    "capital_efficiency",
    "dependency",
    "regulatory_risk",
    "predictability",
)

_RELIABLE_STRENGTHS = frozenset({"E1", "E2", "E3"})
_STRONG_STRENGTHS = frozenset({"E2", "E3"})
_CONFIDENCE_ORDER = {
    ConfidenceLevel.HIGH: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.LOW: 2,
}


def _unique(items: Iterable[str]) -> list[str]:
    """Return stable first-seen values without duplicate audit messages."""

    return list(dict.fromkeys(items))


def _worst_confidence(levels: Iterable[ConfidenceLevel]) -> ConfidenceLevel:
    values = list(levels)
    return max(values, key=_CONFIDENCE_ORDER.__getitem__) if values else ConfidenceLevel.LOW


def _source_key(evidence: Evidence) -> str:
    """Identify a source conservatively for the independence check."""

    source = evidence.source
    if source.document_id:
        return f"document:{source.document_id}"
    if source.url:
        return f"url:{source.url}"
    published = "" if source.published_date is None else source.published_date.isoformat()
    return f"source:{source.type.value}:{source.title}:{published}"


def _has_explicit_counter_check(dimension: BusinessQualityDimension) -> bool:
    """Allow an empty counter list only with a clear analyst audit statement."""

    summary = (dimension.reasoning_summary or "").lower()
    return any(
        phrase in summary
        for phrase in (
            "counter-evidence checked",
            "counter evidence checked",
            "no material contradiction",
            "no material counter-evidence",
            "no material counter evidence",
        )
    )


def _ordered_dimensions(
    dimensions: Sequence[BusinessQualityDimension],
) -> list[BusinessQualityDimension]:
    by_name: dict[str, BusinessQualityDimension] = {}
    for dimension in dimensions:
        name = dimension.dimension
        if name in by_name:
            raise BusinessQualityCalculationError(f"duplicate business-quality dimension: {name}")
        by_name[name] = dimension

    missing = [name for name in BUSINESS_QUALITY_DIMENSIONS if name not in by_name]
    if missing:
        raise BusinessQualityCalculationError(
            "business-quality assessment is missing dimensions: " + ", ".join(missing)
        )
    unknown = sorted(set(by_name) - set(BUSINESS_QUALITY_DIMENSIONS))
    if unknown:
        raise BusinessQualityCalculationError(
            "unknown business-quality dimension(s): " + ", ".join(unknown)
        )
    return [by_name[name] for name in BUSINESS_QUALITY_DIMENSIONS]


def _evidence_map(evidence_index: Sequence[Evidence]) -> dict[str, Evidence]:
    evidence_by_id: dict[str, Evidence] = {}
    for evidence in evidence_index:
        if evidence.id in evidence_by_id:
            raise BusinessQualityCalculationError(
                f"duplicate evidence ID in business-quality input: {evidence.id}"
            )
        evidence_by_id[evidence.id] = evidence
    return evidence_by_id


def build_business_quality_input_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    dimension_results: Sequence[BusinessQualityDimension],
    *,
    confidence: ConfidenceLevel | None = None,
) -> BusinessQualityInput:
    """Join structured dimension judgments to the normalized evidence index."""

    return BusinessQualityInput(
        dimension_results=list(dimension_results),
        evidence_index=list(normalized_input.evidence_index),
        confidence=confidence,
    )


def _score_dimension(
    dimension: BusinessQualityDimension,
    evidence_by_id: dict[str, Evidence],
    profile: RuleProfile,
    flags: list[str],
    unresolved_questions: list[str],
) -> tuple[BusinessQualityDimension, bool]:
    """Validate one dimension and apply evidence-dependent score caps."""

    name = dimension.dimension
    support_ids = list(dimension.supporting_evidence_ids)
    counter_ids = list(dimension.counter_evidence_ids)
    all_ids = support_ids + counter_ids
    missing_ids = [evidence_id for evidence_id in all_ids if evidence_id not in evidence_by_id]
    if missing_ids:
        raise BusinessQualityCalculationError(
            f"undefined evidence ID reference(s) for {name}: " + ", ".join(_unique(missing_ids))
        )

    overlap = set(support_ids) & set(counter_ids)
    if overlap:
        flags.append(
            f"EVIDENCE_REFERENCED_AS_SUPPORT_AND_COUNTER:{name}:" + ",".join(sorted(overlap))
        )

    support_evidence = [evidence_by_id[evidence_id] for evidence_id in support_ids]
    counter_evidence = [evidence_by_id[evidence_id] for evidence_id in counter_ids]

    valid_support = [
        evidence for evidence in support_evidence if evidence.direction.value == "SUPPORT"
    ]
    valid_counter = [
        evidence for evidence in counter_evidence if evidence.direction.value == "COUNTER"
    ]
    if len(valid_support) != len(support_evidence):
        flags.append(f"SUPPORT_EVIDENCE_DIRECTION_MISMATCH:{name}")
        unresolved_questions.append(f"Confirm supporting evidence direction for {name}.")
    if len(valid_counter) != len(counter_evidence):
        flags.append(f"COUNTER_EVIDENCE_DIRECTION_MISMATCH:{name}")
        unresolved_questions.append(f"Confirm counter-evidence direction for {name}.")

    counter_checked = bool(counter_ids) or _has_explicit_counter_check(dimension)
    if not counter_checked:
        flags.append(f"MISSING_COUNTER_EVIDENCE:{name}")
        unresolved_questions.append(f"Provide counter-evidence or record checks for {name}.")

    score = dimension.score
    if not valid_support:
        if score > 0:
            score = 0
            flags.append(f"SCORE_CAPPED_NO_SUPPORTING_EVIDENCE:{name}")
        else:
            flags.append(f"NO_SUPPORTING_EVIDENCE:{name}")
        unresolved_questions.append(f"Provide valid supporting evidence for {name}.")

    requirements = profile.business_quality.evidence_requirements
    strong_support = [
        evidence for evidence in valid_support if evidence.strength.value in _STRONG_STRENGTHS
    ]
    has_primary_support = any(evidence.strength.value == "E3" for evidence in valid_support)
    score_4_supported = (
        len(strong_support) >= requirements.score_4_min_strong_evidence and has_primary_support
    )
    if score == 4 and not score_4_supported:
        score = min(score, requirements.score_without_strong_evidence_max)
        flags.append(f"SCORE_CAPPED_INSUFFICIENT_STRONG_EVIDENCE:{name}")
        unresolved_questions.append(
            f"Add independent E3/E2 support before relying on a high {name} score."
        )
    elif score == 5:
        independent_sources = {_source_key(evidence) for evidence in strong_support}
        score_5_supported = (
            len(strong_support) >= requirements.score_5_min_strong_evidence
            and len(independent_sources) >= requirements.score_5_min_strong_evidence
        )
        if score_5_supported:
            pass
        elif score_4_supported:
            score = min(score, 4)
            flags.append(f"SCORE_CAPPED_NON_INDEPENDENT_STRONG_EVIDENCE:{name}")
            unresolved_questions.append(
                f"Add independent strong evidence before assigning a 5 to {name}."
            )
        else:
            score = min(score, requirements.score_without_strong_evidence_max)
            flags.append(f"SCORE_CAPPED_INSUFFICIENT_STRONG_EVIDENCE:{name}")
            unresolved_questions.append(
                f"Add independent E3/E2 support before relying on a high {name} score."
            )

    if score >= 5 and any(
        evidence.strength.value in _STRONG_STRENGTHS for evidence in valid_counter
    ):
        score = (
            4 if score_4_supported else min(score, requirements.score_without_strong_evidence_max)
        )
        flags.append(f"SCORE_CAPPED_SEVERE_COUNTER_EVIDENCE:{name}")
        unresolved_questions.append(f"Resolve strong counter-evidence for {name}.")

    reliable_evidence_present = any(
        evidence.strength.value in _RELIABLE_STRENGTHS
        for evidence in (*valid_support, *valid_counter)
    )
    if not reliable_evidence_present:
        flags.append(f"NO_RELIABLE_EVIDENCE:{name}")
        unresolved_questions.append(f"Obtain E1/E2/E3 evidence for {name}.")

    if score != dimension.score:
        flags.append(f"SCORE_ADJUSTED:{name}:{dimension.score}->{score}")

    adjusted = dimension.model_copy(update={"score": score})
    return adjusted, reliable_evidence_present


def calculate_business_quality(
    inputs: BusinessQualityInput, profile: RuleProfile
) -> BusinessQuality:
    """Recompute an auditable business-quality assessment deterministically."""

    evidence_by_id = _evidence_map(inputs.evidence_index)
    flags: list[str] = []
    unresolved_questions: list[str] = []
    scored_dimensions: list[BusinessQualityDimension] = []
    covered_dimensions = 0

    for dimension in _ordered_dimensions(inputs.dimension_results):
        scored, covered = _score_dimension(
            dimension,
            evidence_by_id,
            profile,
            flags,
            unresolved_questions,
        )
        scored_dimensions.append(scored)
        covered_dimensions += int(covered)

    evidence_coverage = covered_dimensions / len(BUSINESS_QUALITY_DIMENSIONS)
    coverage_config = profile.business_quality.evidence_coverage
    if evidence_coverage < coverage_config.medium:
        flags.append("EVIDENCE_COVERAGE_BELOW_MEDIUM")
        unresolved_questions.append("Increase reliable evidence coverage before an automatic pass.")

    score = sum(dimension.score for dimension in scored_dimensions)
    score_bands = profile.business_quality.score_bands
    if score >= score_bands.s:
        grade = "S"
    elif score >= score_bands.a:
        grade = "A"
    elif score >= score_bands.pass_:
        grade = "B"
    elif score >= score_bands.watch:
        grade = "WATCH"
    else:
        grade = "FAIL"

    critical_limit = profile.business_quality.critical_dimension_fail_at_or_below
    critical_weaknesses = [
        dimension.dimension
        for dimension in scored_dimensions
        if dimension.dimension in profile.business_quality.critical_dimensions
        and dimension.score <= critical_limit
    ]

    coverage_confidence = (
        ConfidenceLevel.HIGH
        if evidence_coverage >= coverage_config.high
        else ConfidenceLevel.MEDIUM
        if evidence_coverage >= coverage_config.medium
        else ConfidenceLevel.LOW
    )
    confidence_levels = [dimension.confidence for dimension in scored_dimensions]
    confidence_levels.append(coverage_confidence)
    if inputs.confidence is not None:
        confidence_levels.append(inputs.confidence)
    confidence = _worst_confidence(confidence_levels)

    review_prefixes = (
        "MISSING_COUNTER_EVIDENCE:",
        "NO_SUPPORTING_EVIDENCE:",
        "SUPPORT_EVIDENCE_DIRECTION_MISMATCH:",
        "COUNTER_EVIDENCE_DIRECTION_MISMATCH:",
        "SCORE_CAPPED_NO_SUPPORTING_EVIDENCE:",
    )
    if any(flag.startswith(review_prefixes) for flag in flags):
        confidence = ConfidenceLevel.LOW
    if critical_weaknesses:
        flags.append("CRITICAL_DIMENSION_WEAKNESS")

    return BusinessQuality(
        score=score,
        grade=grade,
        confidence=confidence,
        evidence_coverage=evidence_coverage,
        critical_weaknesses=_unique(critical_weaknesses),
        unresolved_questions=_unique(unresolved_questions),
        flags=_unique(flags),
        dimension_results=scored_dimensions,
    )


def score_business_quality(
    dimension_results: Sequence[BusinessQualityDimension],
    evidence_index: Sequence[Evidence],
    profile: RuleProfile,
    *,
    confidence: ConfidenceLevel | None = None,
) -> BusinessQuality:
    """Convenience wrapper for callers with separate dimension/evidence lists."""

    return calculate_business_quality(
        BusinessQualityInput(
            dimension_results=list(dimension_results),
            evidence_index=list(evidence_index),
            confidence=confidence,
        ),
        profile,
    )


def calculate_business_quality_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    dimension_results: Sequence[BusinessQualityDimension],
    profile: RuleProfile,
    *,
    confidence: ConfidenceLevel | None = None,
) -> BusinessQuality:
    """Score manual/offline judgments using evidence from normalized input."""

    return calculate_business_quality(
        build_business_quality_input_from_normalized_input(
            normalized_input,
            dimension_results,
            confidence=confidence,
        ),
        profile,
    )


__all__ = [
    "BUSINESS_QUALITY_DIMENSIONS",
    "BusinessQualityCalculationError",
    "build_business_quality_input_from_normalized_input",
    "calculate_business_quality",
    "calculate_business_quality_from_normalized_input",
    "score_business_quality",
]
