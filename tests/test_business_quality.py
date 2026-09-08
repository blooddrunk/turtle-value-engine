from pathlib import Path

import pytest

from turtle_value_engine import load_normalized_input
from turtle_value_engine.calculations import (
    BUSINESS_QUALITY_DIMENSIONS,
    BusinessQualityCalculationError,
    calculate_business_quality_from_normalized_input,
)
from turtle_value_engine.config import load_profile
from turtle_value_engine.gates import (
    evaluate_business_quality_gate,
    evaluate_business_quality_hard_rules,
)
from turtle_value_engine.models import BusinessQuality, BusinessQualityDimension, Evidence, Fact


def _evidence(identifier: str, direction: str, strength: str, title: str | None = None) -> Evidence:
    return Evidence(
        id=identifier,
        direction=direction,
        strength=strength,
        statement=f"Synthetic evidence {identifier}.",
        source={"type": "ANNUAL_REPORT", "title": title or identifier},
        confidence=1,
    )


def _dimensions(
    *,
    score: int = 5,
    support_ids: list[str] | None = None,
    counter_ids: list[str] | None = None,
    counter_checked: bool = False,
) -> list[BusinessQualityDimension]:
    return [
        BusinessQualityDimension(
            dimension=dimension,
            score=score,
            supporting_evidence_ids=support_ids or [],
            counter_evidence_ids=counter_ids or [],
            confidence="HIGH",
            reasoning_summary=(
                "Counter-evidence checked; no material counter-evidence found."
                if counter_checked
                else None
            ),
        )
        for dimension in BUSINESS_QUALITY_DIMENSIONS
    ]


def _input_with_evidence(evidence: list[Evidence]):
    normalized_input = load_normalized_input(Path("fixtures/healthy_cash_cow.json"))
    return normalized_input.model_copy(
        update={"evidence_index": [*normalized_input.evidence_index, *evidence]}
    )


def _fact(identifier: str, field: str, value: object, period: str, evidence_id: str) -> Fact:
    return Fact(
        id=identifier,
        field=field,
        value=value,
        period=period,
        source_evidence_ids=[evidence_id],
        confidence=1,
    )


def _input_with_facts(facts: list[Fact], evidence: list[Evidence]):
    normalized_input = load_normalized_input(Path("fixtures/healthy_cash_cow.json"))
    return normalized_input.model_copy(
        update={
            "facts": [*normalized_input.facts, *facts],
            "evidence_index": [*normalized_input.evidence_index, *evidence],
        }
    )


def test_business_quality_recomputes_score_grade_coverage_and_lineage():
    evidence = []
    dimensions = []
    for dimension in BUSINESS_QUALITY_DIMENSIONS:
        primary = f"{dimension}-primary"
        operating = f"{dimension}-operating"
        counter = f"{dimension}-counter"
        evidence.extend(
            [
                _evidence(primary, "SUPPORT", "E3", f"Annual report {dimension}"),
                _evidence(operating, "SUPPORT", "E2", f"Operating disclosure {dimension}"),
                _evidence(counter, "COUNTER", "E1", f"Risk review {dimension}"),
            ]
        )
        dimensions.append(
            BusinessQualityDimension(
                dimension=dimension,
                score=5,
                supporting_evidence_ids=[primary, operating],
                counter_evidence_ids=[counter],
                confidence="HIGH",
            )
        )

    result = calculate_business_quality_from_normalized_input(
        _input_with_evidence(evidence),
        dimensions,
        load_profile("strict-v1"),
    )

    assert result.score == 40
    assert result.grade == "S"
    assert result.evidence_coverage == 1
    assert result.confidence.value == "HIGH"
    assert result.flags == []
    assert [item.dimension for item in result.dimension_results] == list(
        BUSINESS_QUALITY_DIMENSIONS
    )
    assert result.dimension_results[0].supporting_evidence_ids == [
        "demand_durability-primary",
        "demand_durability-operating",
    ]


def test_inference_only_high_scores_are_capped_and_cannot_pass():
    evidence = [
        _evidence("support", "SUPPORT", "E0"),
        _evidence("counter", "COUNTER", "E0"),
    ]
    result = calculate_business_quality_from_normalized_input(
        _input_with_evidence(evidence),
        _dimensions(support_ids=["support"], counter_ids=["counter"]),
        load_profile("strict-v1"),
    )

    assert result.score == 24
    assert result.grade == "WATCH"
    assert result.evidence_coverage == 0
    assert result.confidence.value == "LOW"
    assert "SCORE_CAPPED_INSUFFICIENT_STRONG_EVIDENCE:demand_durability" in result.flags

    gate = evaluate_business_quality_gate(result, load_profile("strict-v1"))
    assert gate.status.value == "SPECIAL_REVIEW"
    assert any(rule.rule_id == "BUSINESS.EVIDENCE_COVERAGE" for rule in gate.rules)


def test_business_quality_rejects_missing_dimensions_and_unresolved_evidence():
    profile = load_profile("strict-v1")
    normalized_input = load_normalized_input(Path("fixtures/healthy_cash_cow.json"))

    with pytest.raises(BusinessQualityCalculationError, match="missing dimensions"):
        calculate_business_quality_from_normalized_input(
            normalized_input,
            _dimensions()[:-1],
            profile,
        )

    dimensions = _dimensions(support_ids=["not-defined"], counter_checked=True)
    with pytest.raises(BusinessQualityCalculationError, match="undefined evidence ID"):
        calculate_business_quality_from_normalized_input(normalized_input, dimensions, profile)


def test_structural_revenue_decline_is_a_hard_business_failure():
    normalized_input = load_normalized_input(Path("fixtures/cash_rich_dying_business.json"))
    assessment = BusinessQuality(
        score=40,
        grade="S",
        confidence="HIGH",
        evidence_coverage=1,
        dimension_results=_dimensions(score=5, counter_checked=True),
    )

    gate = evaluate_business_quality_gate(
        assessment,
        load_profile("strict-v1"),
        normalized_input=normalized_input,
    )

    assert gate.status.value == "FAIL"
    decline = next(
        rule for rule in gate.rules if rule.rule_id == "BUSINESS.STRUCTURAL_REVENUE_DECLINE"
    )
    assert decline.status.value == "FAIL"
    assert decline.actual == pytest.approx((520 / 1000) ** (1 / 4) - 1)


def test_business_hard_rules_keep_each_trigger_explicit_and_traceable():
    evidence = [
        _evidence("hard-profit", "SUPPORT", "E3"),
        _evidence("hard-cash-2023", "SUPPORT", "E3"),
        _evidence("hard-cash-2024", "SUPPORT", "E3"),
        _evidence("hard-cash-2025", "SUPPORT", "E3"),
        _evidence("hard-disruption", "SUPPORT", "E3"),
        _evidence("hard-disruption-ratio", "SUPPORT", "E3"),
        _evidence("hard-replacement", "COUNTER", "E2"),
        _evidence("hard-dependency", "SUPPORT", "E3"),
    ]
    as_of = "AS_OF_2026-09-08"
    normalized_input = _input_with_facts(
        [
            _fact("hard-profit-fact", "sustainable_core_profit_ratio", 0.4, as_of, "hard-profit"),
            _fact(
                "hard-profit-non-recurring",
                "non_core_profit_non_recurring",
                True,
                as_of,
                "hard-profit",
            ),
            _fact("hard-cash-2023-fact", "core_cdc", -1, "FY2023", "hard-cash-2023"),
            _fact("hard-cash-2024-fact", "core_cdc", -2, "FY2024", "hard-cash-2024"),
            _fact("hard-cash-2025-fact", "core_cdc", -3, "FY2025", "hard-cash-2025"),
            _fact("hard-disruption-fact", "structural_disruption", True, as_of, "hard-disruption"),
            _fact(
                "hard-disruption-ratio-fact",
                "structural_disruption_revenue_ratio",
                0.6,
                as_of,
                "hard-disruption-ratio",
            ),
            _fact(
                "hard-replacement-fact",
                "replacement_earnings_engine",
                False,
                as_of,
                "hard-replacement",
            ),
            _fact(
                "hard-dependency-fact",
                "single_point_dependency_ratio",
                0.6,
                as_of,
                "hard-dependency",
            ),
        ],
        evidence,
    )

    rules = evaluate_business_quality_hard_rules(normalized_input, load_profile("strict-v1"))
    by_id = {rule.rule_id: rule for rule in rules}

    assert by_id["BUSINESS.STRUCTURAL_REVENUE_DECLINE"].status.value == "PASS"
    assert by_id["BUSINESS.NON_CORE_PROFIT_DEPENDENCE"].status.value == "SPECIAL_REVIEW"
    assert by_id["BUSINESS.CORE_CASH_GENERATION"].status.value == "SPECIAL_REVIEW"
    assert by_id["BUSINESS.STRUCTURAL_DISRUPTION"].status.value == "FAIL"
    assert by_id["BUSINESS.SINGLE_POINT_DEPENDENCY"].status.value == "SPECIAL_REVIEW"
    assert "hard-disruption-ratio" in by_id["BUSINESS.STRUCTURAL_DISRUPTION"].evidence_ids


def test_structural_disruption_without_exposure_ratio_requires_review():
    as_of = "AS_OF_2026-09-08"
    normalized_input = _input_with_facts(
        [
            _fact("disruption-fact", "structural_disruption", True, as_of, "disruption"),
            _fact(
                "replacement-fact",
                "replacement_earnings_engine",
                False,
                as_of,
                "replacement",
            ),
        ],
        [
            _evidence("disruption", "SUPPORT", "E3"),
            _evidence("replacement", "COUNTER", "E2"),
        ],
    )

    rule = next(
        rule
        for rule in evaluate_business_quality_hard_rules(
            normalized_input, load_profile("strict-v1")
        )
        if rule.rule_id == "BUSINESS.STRUCTURAL_DISRUPTION"
    )
    assert rule.status.value == "SPECIAL_REVIEW"


def test_hard_gate_preserves_not_evaluated_without_explicit_assessment():
    normalized_input = load_normalized_input(Path("fixtures/healthy_cash_cow.json"))
    gate = evaluate_business_quality_gate(
        None,
        load_profile("strict-v1"),
        normalized_input=normalized_input,
    )

    assert gate.status.value == "NOT_EVALUATED"
    assert gate.rules[0].rule_id == "STAGE.NOT_EVALUATED"
