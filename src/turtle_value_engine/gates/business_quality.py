"""Deterministic Business Quality hard gates and score gate."""

import math
from collections.abc import Iterable

from turtle_value_engine.calculations.business_quality import BUSINESS_QUALITY_DIMENSIONS
from turtle_value_engine.calculations.facts import FactBook, boolean_value, numeric_value
from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import (
    BusinessQuality,
    ConfidenceLevel,
    GateResult,
    GateRule,
    GateStatus,
    NormalizedCompanyInput,
)

from .common import make_gate_result, result_or_not_evaluated, unique_strings


def _valid_ratio(value: float | None) -> bool:
    """Accept only finite proportions in the normalized [0, 1] domain."""

    return value is not None and math.isfinite(value) and 0 <= value <= 1


def _reference_value(
    book: FactBook,
    fields: Iterable[str],
    period: str,
    *,
    numeric: bool,
) -> tuple[object | None, list[str], bool]:
    """Read the first available alias while retaining whether it was supplied."""

    for field in fields:
        reference = book.get(field, period)
        if reference is None:
            continue
        value = (
            numeric_value(reference, field=field)
            if numeric
            else boolean_value(reference, field=field)
        )
        return value, list(reference.evidence_ids), True
    return None, [], False


def _latest_numeric(
    book: FactBook,
    fields: Iterable[str],
    as_of_period: str,
) -> tuple[float | None, list[str], bool]:
    """Read an AS_OF value, or the latest non-AS_OF annual value as a fallback."""

    field_list = tuple(fields)
    value, evidence_ids, present = _reference_value(book, field_list, as_of_period, numeric=True)
    if present:
        return (
            value if isinstance(value, (int, float)) and math.isfinite(value) else None,
            evidence_ids,
            True,
        )

    for field in field_list:
        periods = [period for period in book.periods([field]) if not period.startswith("AS_OF_")]
        for period in reversed(periods):
            reference = book.get(field, period)
            if reference is None:
                continue
            value = numeric_value(reference, field=field)
            return (
                value if value is not None and math.isfinite(value) else None,
                list(reference.evidence_ids),
                True,
            )
    return None, [], False


def _core_revenue_cagr(
    book: FactBook,
    as_of_period: str,
) -> tuple[float | None, list[str], bool]:
    """Use an explicit 5Y CAGR or derive it from the latest five core revenues."""

    explicit, evidence_ids, present = _reference_value(
        book, ("revenue_cagr_5y",), as_of_period, numeric=True
    )
    if present:
        return (
            explicit if isinstance(explicit, (int, float)) and math.isfinite(explicit) else None,
            evidence_ids,
            True,
        )

    periods = [
        period for period in book.periods(["core_revenue"]) if not period.startswith("AS_OF_")
    ]
    if len(periods) < 5:
        return None, [], False
    periods = periods[-5:]
    values: list[float] = []
    source_ids: list[str] = []
    for period in periods:
        reference = book.get("core_revenue", period)
        value = numeric_value(reference, field="core_revenue")
        if value is None or not math.isfinite(value):
            return None, unique_strings(source_ids), True
        values.append(value)
        source_ids.extend(reference.evidence_ids)
    if values[0] <= 0 or values[-1] <= 0:
        return None, unique_strings(source_ids), True
    cagr = math.pow(values[-1] / values[0], 1 / 4) - 1
    return cagr, unique_strings(source_ids), True


def _core_profit_ratio(
    book: FactBook,
    as_of_period: str,
) -> tuple[float | None, list[str], bool]:
    """Resolve an explicitly normalized core-profit share without guessing from revenue."""

    ratio, evidence_ids, present = _latest_numeric(
        book,
        (
            "sustainable_core_profit_ratio",
            "core_profit_ratio",
            "core_profit_to_normalized_total_profit",
        ),
        as_of_period,
    )
    if present:
        return ratio if _valid_ratio(ratio) else None, evidence_ids, True

    non_core_ratio, evidence_ids, present = _latest_numeric(
        book, ("non_core_profit_ratio",), as_of_period
    )
    if present:
        return (
            None
            if non_core_ratio is None or not _valid_ratio(non_core_ratio)
            else 1 - non_core_ratio,
            evidence_ids,
            True,
        )

    core_profit, core_ids, core_present = _latest_numeric(
        book, ("normalized_core_profit", "core_operating_profit"), as_of_period
    )
    total_profit, total_ids, total_present = _latest_numeric(
        book,
        ("normalized_total_profit", "normalized_parent_profit", "parent_net_profit"),
        as_of_period,
    )
    if not core_present or not total_present or core_profit is None or total_profit in (None, 0):
        return None, unique_strings([*core_ids, *total_ids]), core_present or total_present
    ratio = core_profit / total_profit
    return (
        ratio if _valid_ratio(ratio) else None,
        unique_strings([*core_ids, *total_ids]),
        True,
    )


def _non_core_profit_is_non_recurring(
    book: FactBook,
    as_of_period: str,
) -> tuple[object | None, list[str], bool]:
    return _reference_value(
        book,
        (
            "non_core_profit_non_recurring",
            "non_recurring_profit_dependence",
            "non_core_profit_is_non_recurring",
        ),
        as_of_period,
        numeric=False,
    )


def _core_cash_generation(
    book: FactBook,
    as_of_period: str,
    failure_years: int,
) -> tuple[bool | None, list[str], bool, int | None]:
    value, evidence_ids, present = _reference_value(
        book, ("core_business_cash_generation",), as_of_period, numeric=False
    )
    if present:
        return value if isinstance(value, bool) else None, evidence_ids, True, None

    periods = [period for period in book.periods(["core_cdc"]) if not period.startswith("AS_OF_")]
    values: list[float] = []
    source_ids: list[str] = []
    for period in periods[-max(failure_years, 3) :]:
        reference = book.get("core_cdc", period)
        value = numeric_value(reference, field="core_cdc")
        if value is None or not math.isfinite(value):
            return None, unique_strings(source_ids), bool(source_ids), None
        values.append(value)
        source_ids.extend(reference.evidence_ids)
    if len(values) < failure_years:
        return None, unique_strings(source_ids), bool(source_ids), None
    negative_years = sum(value <= 0 for value in values)
    if negative_years >= failure_years:
        return False, unique_strings(source_ids), True, negative_years
    return True, unique_strings(source_ids), True, negative_years


def _structural_disruption(
    book: FactBook,
    as_of_period: str,
    ratio_above: float,
) -> GateRule:
    disruption, disruption_ids, present = _reference_value(
        book, ("structural_disruption",), as_of_period, numeric=False
    )
    ratio, ratio_ids, ratio_present = _latest_numeric(
        book,
        (
            "structural_disruption_revenue_ratio",
            "displaced_product_revenue_ratio",
            "rapidly_displaced_revenue_ratio",
        ),
        as_of_period,
    )
    evidence_ids = unique_strings([*disruption_ids, *ratio_ids])
    if ratio_present and ratio is not None and not _valid_ratio(ratio):
        return GateRule(
            rule_id="BUSINESS.STRUCTURAL_DISRUPTION",
            status=GateStatus.SPECIAL_REVIEW,
            actual=ratio,
            threshold=ratio_above,
            evidence_ids=evidence_ids,
            message="Structural-disruption revenue exposure is outside the [0, 1] range.",
        )
    if ratio_present and ratio is not None and ratio <= ratio_above:
        return GateRule(
            rule_id="BUSINESS.STRUCTURAL_DISRUPTION",
            status=GateStatus.PASS,
            actual=ratio,
            threshold=ratio_above,
            evidence_ids=evidence_ids,
            message="The disclosed disruption exposure is not above the configured trigger.",
        )

    if ratio_present and ratio is not None and ratio > ratio_above:
        replacement, replacement_ids, _ = _reference_value(
            book, ("replacement_earnings_engine",), as_of_period, numeric=False
        )
        evidence_ids = unique_strings([*evidence_ids, *replacement_ids])
        if replacement is True:
            status = GateStatus.PASS
            message = None
        elif replacement is False:
            status = GateStatus.FAIL
            message = "Structural disruption lacks a credible replacement earnings engine."
        else:
            status = GateStatus.SPECIAL_REVIEW
            message = "Replacement earnings path is unresolved."
        return GateRule(
            rule_id="BUSINESS.STRUCTURAL_DISRUPTION",
            status=status,
            actual=ratio,
            threshold=ratio_above,
            evidence_ids=evidence_ids,
            message=message,
        )

    if disruption is False:
        return GateRule(
            rule_id="BUSINESS.STRUCTURAL_DISRUPTION",
            status=GateStatus.PASS,
            actual=False,
            threshold=True,
            evidence_ids=evidence_ids,
        )

    if not present or not isinstance(disruption, bool):
        return GateRule(
            rule_id="BUSINESS.STRUCTURAL_DISRUPTION",
            status=GateStatus.NOT_EVALUATED,
            evidence_ids=evidence_ids,
            message="Structural-disruption status and revenue exposure are unavailable.",
        )

    _, replacement_ids, replacement_present = _reference_value(
        book, ("replacement_earnings_engine",), as_of_period, numeric=False
    )
    evidence_ids = unique_strings([*evidence_ids, *replacement_ids])
    status = GateStatus.SPECIAL_REVIEW if replacement_present else GateStatus.NOT_EVALUATED
    message = (
        "Structural disruption is disclosed, but the revenue exposure ratio is unavailable."
        if status is GateStatus.SPECIAL_REVIEW
        else "Structural-disruption status and revenue exposure are unavailable."
    )
    return GateRule(
        rule_id="BUSINESS.STRUCTURAL_DISRUPTION",
        status=status,
        actual=ratio if ratio is not None else disruption,
        threshold=ratio_above,
        evidence_ids=evidence_ids,
        message=message,
    )


def evaluate_business_quality_hard_rules(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile,
) -> list[GateRule]:
    """Evaluate BG01--BG05 without using any narrative or external data."""

    book = FactBook(normalized_input.facts)
    period = book.as_of_period(normalized_input.as_of)
    config = profile.business_quality.hard_gates
    rules: list[GateRule] = []

    cagr, cagr_ids, _ = _core_revenue_cagr(book, period)
    structural, structural_ids, structural_present = _reference_value(
        book, ("structural_demand_decline",), period, numeric=False
    )
    replacement, replacement_ids, replacement_present = _reference_value(
        book, ("replacement_earnings_engine",), period, numeric=False
    )
    evidence_ids = unique_strings([*cagr_ids, *structural_ids, *replacement_ids])
    if cagr is None:
        status = GateStatus.NOT_EVALUATED
        message = "Five-year core-revenue CAGR is unavailable."
    elif cagr >= config.structural_revenue_cagr_below:
        status = GateStatus.PASS
        message = None
    elif structural is False or replacement is True:
        status = GateStatus.PASS
        message = None
    elif structural is True and replacement is False:
        status = GateStatus.FAIL
        message = "Core revenue is structurally declining without a replacement earnings engine."
    else:
        status = (
            GateStatus.SPECIAL_REVIEW
            if structural_present or replacement_present
            else GateStatus.NOT_EVALUATED
        )
        message = "Structural decline and replacement-earnings evidence is incomplete."
    rules.append(
        GateRule(
            rule_id="BUSINESS.STRUCTURAL_REVENUE_DECLINE",
            status=status,
            actual=cagr,
            threshold=config.structural_revenue_cagr_below,
            evidence_ids=evidence_ids,
            message=message,
        )
    )

    core_ratio, ratio_ids, ratio_present = _core_profit_ratio(book, period)
    non_recurring, non_recurring_ids, non_recurring_present = _non_core_profit_is_non_recurring(
        book, period
    )
    evidence_ids = unique_strings([*ratio_ids, *non_recurring_ids])
    if core_ratio is None:
        status = (
            GateStatus.SPECIAL_REVIEW
            if non_recurring is True or ratio_present or non_recurring_present
            else GateStatus.NOT_EVALUATED
        )
        message = (
            "Sustainable core-profit share is unavailable while non-core profit dependence "
            "is indicated."
            if status is GateStatus.SPECIAL_REVIEW
            else "Sustainable core-profit share is unavailable."
        )
    elif core_ratio >= config.non_core_profit_ratio_below:
        status = GateStatus.PASS
        message = None
    elif non_recurring is False:
        status = GateStatus.PASS
        message = None
    elif non_recurring is True:
        status = GateStatus.SPECIAL_REVIEW
        message = (
            "Sustainable core profit is below half of normalized profit and depends on "
            "non-recurring sources."
        )
    else:
        status = (
            GateStatus.SPECIAL_REVIEW
            if ratio_present or non_recurring_present
            else GateStatus.NOT_EVALUATED
        )
        message = "Non-core profit dependence is unresolved."
    rules.append(
        GateRule(
            rule_id="BUSINESS.NON_CORE_PROFIT_DEPENDENCE",
            status=status,
            actual=core_ratio,
            threshold=config.non_core_profit_ratio_below,
            evidence_ids=evidence_ids,
            message=message,
        )
    )

    cash_generation, cash_ids, _, negative_years = _core_cash_generation(
        book, period, config.core_cash_failure_years
    )
    if cash_generation is True:
        cash_status = GateStatus.PASS
        cash_message = None
    elif cash_generation is False:
        cash_status = GateStatus.SPECIAL_REVIEW
        cash_message = "Core business cash generation fails the persistent-cash test."
    else:
        cash_status = GateStatus.NOT_EVALUATED
        cash_message = "Core business cash-generation evidence is unavailable."
    rules.append(
        GateRule(
            rule_id="BUSINESS.CORE_CASH_GENERATION",
            status=cash_status,
            actual=negative_years if negative_years is not None else cash_generation,
            threshold=config.core_cash_failure_years,
            evidence_ids=cash_ids,
            message=cash_message,
        )
    )

    rules.append(
        _structural_disruption(book, period, config.structural_disruption_revenue_ratio_above)
    )

    dependency, dependency_ids, _ = _reference_value(
        book, ("single_point_survival_dependency",), period, numeric=False
    )
    ratio, ratio_ids, ratio_present = _latest_numeric(
        book,
        (
            "single_point_dependency_ratio",
            "largest_customer_ratio",
            "critical_supplier_concentration",
            "channel_concentration",
        ),
        period,
    )
    evidence_ids = unique_strings([*dependency_ids, *ratio_ids])
    if ratio is not None and not _valid_ratio(ratio):
        dependency_status = GateStatus.SPECIAL_REVIEW
        dependency_message = "Single-point dependency ratio is outside the [0, 1] range."
    elif dependency is True or (
        ratio is not None and ratio > config.single_point_dependency_ratio_above
    ):
        dependency_status = GateStatus.SPECIAL_REVIEW
        dependency_message = (
            "A single customer, channel, supplier or other dependency may threaten more "
            "than half of economics."
        )
    elif dependency is False or ratio is not None:
        dependency_status = GateStatus.PASS
        dependency_message = None
    else:
        dependency_status = GateStatus.NOT_EVALUATED
        dependency_message = "Single-point dependency evidence is unavailable."
    rules.append(
        GateRule(
            rule_id="BUSINESS.SINGLE_POINT_DEPENDENCY",
            status=dependency_status,
            actual=ratio if ratio is not None else dependency,
            threshold=config.single_point_dependency_ratio_above,
            evidence_ids=evidence_ids,
            message=dependency_message,
        )
    )

    return rules


def _business_quality_evidence_ids(result: BusinessQuality) -> list[str]:
    return unique_strings(
        evidence_id
        for dimension in result.dimension_results
        for evidence_id in (
            *dimension.supporting_evidence_ids,
            *dimension.counter_evidence_ids,
        )
    )


def evaluate_business_quality_gate(
    result: BusinessQuality | None,
    profile: RuleProfile,
    *,
    normalized_input: NormalizedCompanyInput | None = None,
) -> GateResult:
    """Evaluate business hard triggers and the deterministic score constraints."""

    if result is None:
        return result_or_not_evaluated("Business-quality evidence scoring has not been supplied.")

    rules: list[GateRule] = []
    evidence_ids = _business_quality_evidence_ids(result)
    if normalized_input is None:
        rules.append(
            GateRule(
                rule_id="BUSINESS.HARD_GATES",
                status=GateStatus.NOT_EVALUATED,
                evidence_ids=evidence_ids,
                message="Business hard-gate facts are not available.",
            )
        )
    else:
        rules.extend(evaluate_business_quality_hard_rules(normalized_input, profile))

    complete = [dimension.dimension for dimension in result.dimension_results]
    complete_status = (
        GateStatus.PASS
        if len(complete) == len(BUSINESS_QUALITY_DIMENSIONS)
        and len(set(complete)) == len(BUSINESS_QUALITY_DIMENSIONS)
        and set(complete) == set(BUSINESS_QUALITY_DIMENSIONS)
        else GateStatus.SPECIAL_REVIEW
    )
    rules.append(
        GateRule(
            rule_id="BUSINESS.DIMENSIONS_COMPLETE",
            status=complete_status,
            actual=len(complete),
            threshold=len(BUSINESS_QUALITY_DIMENSIONS),
            evidence_ids=evidence_ids,
            message=(
                "All eight business-quality dimensions are required."
                if complete_status is not GateStatus.PASS
                else None
            ),
        )
    )

    score = result.score
    score_bands = profile.business_quality.score_bands
    if score is None:
        score_status = GateStatus.SPECIAL_REVIEW
        score_message = "Business-quality score is unavailable."
    elif score < score_bands.fail_below:
        score_status = GateStatus.FAIL
        score_message = "Business-quality score is below the configured failure floor."
    elif score < score_bands.pass_:
        score_status = GateStatus.WATCH
        score_message = "Business-quality score is below the configured pass threshold."
    else:
        score_status = GateStatus.PASS
        score_message = None
    rules.append(
        GateRule(
            rule_id="BUSINESS.SCORE",
            status=score_status,
            actual=score,
            threshold=score_bands.pass_,
            evidence_ids=evidence_ids,
            message=score_message,
        )
    )

    limit = profile.business_quality.critical_dimension_fail_at_or_below
    computed_critical = [
        dimension.dimension
        for dimension in result.dimension_results
        if dimension.dimension in profile.business_quality.critical_dimensions
        and dimension.score <= limit
    ]
    critical = unique_strings([*result.critical_weaknesses, *computed_critical])
    critical_status = GateStatus.SPECIAL_REVIEW if critical else GateStatus.PASS
    rules.append(
        GateRule(
            rule_id="BUSINESS.CRITICAL_DIMENSIONS",
            status=critical_status,
            actual=",".join(critical) if critical else None,
            threshold=profile.business_quality.critical_dimension_fail_at_or_below,
            evidence_ids=evidence_ids,
            message=(
                "A critical business-quality dimension is at or below the failure boundary."
                if critical
                else None
            ),
        )
    )

    coverage = result.evidence_coverage
    medium_coverage = profile.business_quality.evidence_coverage.medium
    coverage_status = (
        GateStatus.PASS
        if coverage is not None and coverage >= medium_coverage
        else GateStatus.SPECIAL_REVIEW
    )
    rules.append(
        GateRule(
            rule_id="BUSINESS.EVIDENCE_COVERAGE",
            status=coverage_status,
            actual=coverage,
            threshold=medium_coverage,
            evidence_ids=evidence_ids,
            message=(
                "Reliable evidence coverage is below the configured medium threshold."
                if coverage_status is not GateStatus.PASS
                else None
            ),
        )
    )

    confidence_status = (
        GateStatus.PASS
        if result.confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
        else GateStatus.SPECIAL_REVIEW
    )
    rules.append(
        GateRule(
            rule_id="BUSINESS.EVIDENCE_CONFIDENCE",
            status=confidence_status,
            actual=None if result.confidence is None else result.confidence.value,
            threshold=ConfidenceLevel.MEDIUM.value,
            evidence_ids=evidence_ids,
            message=(
                "Business-quality evidence confidence is LOW."
                if confidence_status is not GateStatus.PASS
                else None
            ),
        )
    )

    review_flags = [
        flag
        for flag in result.flags
        if flag.startswith(
            (
                "MISSING_COUNTER_EVIDENCE:",
                "NO_SUPPORTING_EVIDENCE:",
                "SCORE_CAPPED_NO_SUPPORTING_EVIDENCE:",
                "SUPPORT_EVIDENCE_DIRECTION_MISMATCH:",
                "COUNTER_EVIDENCE_DIRECTION_MISMATCH:",
                "EVIDENCE_REFERENCED_AS_SUPPORT_AND_COUNTER:",
            )
        )
    ]
    rules.append(
        GateRule(
            rule_id="BUSINESS.EVIDENCE_REQUIREMENTS",
            status=GateStatus.SPECIAL_REVIEW if review_flags else GateStatus.PASS,
            actual=len(review_flags),
            threshold=0,
            evidence_ids=evidence_ids,
            message=(
                "Mandatory evidence or counter-evidence requirements are unresolved."
                if review_flags
                else None
            ),
        )
    )

    confidence = result.confidence
    if any(rule.status in {GateStatus.FAIL, GateStatus.SPECIAL_REVIEW} for rule in rules):
        confidence = ConfidenceLevel.LOW
    return make_gate_result(rules, confidence=confidence)


__all__ = [
    "evaluate_business_quality_gate",
    "evaluate_business_quality_hard_rules",
]
