import pytest

from turtle_value_engine.calculations import (
    build_cdc_input_from_facts,
    calculate_cdc,
    calculate_year_cdc,
)
from turtle_value_engine.config import load_profile
from turtle_value_engine.models import CDCInput, ConfidenceLevel, Fact


@pytest.fixture
def profile():
    return load_profile("strict-v1")


def test_year_cdc_applies_each_adjustment_once(year_factory, profile):
    year = year_factory(
        reported_cfo=100,
        cash_interest_paid_total=10,
        cash_interest_in_cfo=4,
        non_recurring_operating_inflows=5,
        operating_outflows_misclassified_outside_cfo=3,
        ppe_purchase_cash=20,
        intangible_purchase_cash=10,
        other_operating_long_term_asset_cash=1,
        capex_payables_change=2,
        lease_principal_outside_cfo=4,
        acquisition_cash=7,
        strategic_investment_cash=2,
        parent_economic_share=0.8,
    )

    result = calculate_year_cdc(year, profile)

    # Adjusted CFO = 100 - (10 - 4) - 5 + 3 = 92.
    assert result.adjusted_cfo == pytest.approx(92)
    # Economic gross capex = 20 + 10 + 1 + 2 = 33.
    assert result.economic_gross_capex == pytest.approx(33)
    # Core CDC = 92 - 33 - 4 = 55; parent share = 80%.
    assert result.core_cdc == pytest.approx(55)
    assert result.parent_core_cdc == pytest.approx(44)
    assert result.all_in_cdc == pytest.approx(46)
    assert result.interest_outside_cfo == pytest.approx(6)


def test_interest_already_in_cfo_is_not_deducted_twice(year_factory, profile):
    year = year_factory(
        reported_cfo=100,
        cash_interest_paid_total=10,
        cash_interest_in_cfo=10,
        cash_interest_outside_cfo=0,
        ppe_purchase_cash=0,
        intangible_purchase_cash=0,
    )

    result = calculate_year_cdc(year, profile)

    assert result.interest_outside_cfo == 0
    assert result.adjusted_cfo == pytest.approx(100)
    assert result.core_cdc == pytest.approx(100)


def test_capitalized_development_already_in_intangibles_is_not_deducted_twice(
    year_factory, profile
):
    year = year_factory(
        ppe_purchase_cash=10,
        intangible_purchase_cash=20,
        capitalized_dev_already_in_capex=True,
        lease_principal_outside_cfo=0,
    )

    result = calculate_year_cdc(year, profile)

    assert result.economic_gross_capex == pytest.approx(30)
    assert "CAPITALIZED_DEVELOPMENT_ALREADY_INCLUDED" in result.flags
    assert result.core_cdc == pytest.approx(64)


def test_capitalized_development_outside_capex_is_added_once(year_factory, profile):
    year = year_factory(
        ppe_purchase_cash=10,
        intangible_purchase_cash=20,
        capitalized_dev_already_in_capex=False,
        capitalized_development_cash_outside_capex=5,
        lease_principal_outside_cfo=0,
    )

    result = calculate_year_cdc(year, profile)

    assert result.economic_gross_capex == pytest.approx(35)
    assert result.core_cdc == pytest.approx(59)


def test_missing_key_data_is_not_treated_as_zero(year_factory, profile):
    year = year_factory(lease_principal_outside_cfo=None)

    result = calculate_year_cdc(year, profile)

    assert result.core_cdc is None
    assert result.confidence is ConfidenceLevel.LOW
    assert "MISSING_CDC_FIELD:lease_principal_outside_cfo" in result.flags


def test_flat_fact_projection_preserves_missing_cdc_fields():
    facts = [
        Fact(
            id=f"fact-{field}",
            field=field,
            value=value,
            period="FY2025",
            source_evidence_ids=["evidence-1"],
            confidence=1,
        )
        for field, value in {
            "reported_cfo": 100,
            "cash_interest_paid_total": 0,
            "cash_interest_in_cfo": 0,
            "non_recurring_operating_inflows": 0,
            "operating_outflows_misclassified_outside_cfo": 0,
            "ppe_purchase_cash": 0,
            "intangible_purchase_cash": 0,
            "other_operating_long_term_asset_cash": 0,
            "capex_payables_change": 0,
            "parent_economic_share": 1,
            "acquisition_cash": 0,
            "strategic_investment_cash": 0,
        }.items()
    ]

    inputs = build_cdc_input_from_facts(
        facts,
        current_market_cap=1000,
        default_confidence=ConfidenceLevel.HIGH,
    )

    assert inputs.years[0].lease_principal_outside_cfo is None
    assert inputs.years[0].reported_cfo == 100


def test_standard_normalization_uses_minimum_of_average_and_median(year_factory, profile):
    years = [
        year_factory(
            f"FY{year}",
            reported_cfo=value,
            cash_interest_paid_total=0,
            cash_interest_in_cfo=0,
            ppe_purchase_cash=0,
            intangible_purchase_cash=0,
        )
        for year, value in zip(range(2021, 2026), [10, 20, 30, 40, 50])
    ]

    result = calculate_cdc(CDCInput(years=years, current_market_cap=100), profile)

    # Last-3 average = 40, last-5 median = 30, so normalized CDC = 30.
    assert result.normalized_core_cdc == pytest.approx(30)
    assert result.normalized_parent_core_cdc == pytest.approx(30)
    assert result.cdc_yield == pytest.approx(0.30)
    assert result.positive_years_5y == 5
    assert result.cumulative_core_cdc_5y == pytest.approx(150)
    assert result.confidence is ConfidenceLevel.HIGH


def test_working_capital_distortion_uses_strict_greater_than_boundary(year_factory, profile):
    at_boundary = calculate_year_cdc(year_factory(working_capital_contribution=30), profile)
    above_boundary = calculate_year_cdc(year_factory(working_capital_contribution=30.01), profile)

    assert "WORKING_CAPITAL_DISTORTION" not in at_boundary.flags
    assert "WORKING_CAPITAL_DISTORTION" in above_boundary.flags


def test_material_interest_classification_gap_is_explicitly_flagged(year_factory, profile):
    result = calculate_year_cdc(
        year_factory(cash_interest_in_cfo=None, cash_interest_outside_cfo=None), profile
    )

    assert result.core_cdc is None
    assert "INTEREST_CLASSIFICATION_MATERIALITY_UNRESOLVED" in result.flags


def test_capex_payables_materiality_is_based_on_adjusted_core_cdc(year_factory, profile):
    below = calculate_year_cdc(year_factory(capex_payables_change=5), profile)
    above = calculate_year_cdc(year_factory(capex_payables_change=6), profile)

    assert "CAPEX_PAYABLES_MATERIAL_ADJUSTMENT" not in below.flags
    assert "CAPEX_PAYABLES_MATERIAL_ADJUSTMENT" in above.flags


def test_confidence_propagates_to_multi_year_result(year_factory, profile):
    years = [year_factory(f"FY{year}", confidence="HIGH") for year in range(2021, 2026)]
    years[2] = year_factory("FY2023", confidence="MEDIUM")

    result = calculate_cdc(CDCInput(years=years), profile)

    assert result.confidence is ConfidenceLevel.MEDIUM


def test_cyclical_normalization_uses_full_cycle_not_five_year_continuity_window(
    year_factory, profile
):
    years = [
        year_factory(
            f"FY{year}",
            reported_cfo=value,
            cash_interest_paid_total=0,
            cash_interest_in_cfo=0,
            ppe_purchase_cash=0,
            intangible_purchase_cash=0,
        )
        for year, value in zip(range(2019, 2026), [10, 20, 100, 80, 20, 10, 5])
    ]

    result = calculate_cdc(CDCInput(years=years, cyclical=True), profile)

    assert result.normalized_parent_core_cdc == pytest.approx(20)
    assert "CYCLICAL_NORMALIZATION_UNAVAILABLE" not in result.flags
