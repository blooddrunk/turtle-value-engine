import pytest

from turtle_value_engine.calculations import calculate_through_return
from turtle_value_engine.config import load_profile
from turtle_value_engine.models import (
    ConfidenceLevel,
    ThroughReturnInput,
    ThroughReturnYearInput,
)

from .stage_support import load_stage_results


def test_healthy_fixture_separates_dividend_and_verified_buyback_cash():
    _, _, _, result, _, _ = load_stage_results("healthy_cash_cow")

    assert result.normalized_parent_profit == pytest.approx(88)
    assert result.normalized_parent_core_cdc == pytest.approx(85)
    assert result.distributable_base == pytest.approx(85)
    assert result.conservative_payout_ratio == pytest.approx(0.35)
    assert result.dividend_through_return == pytest.approx(29.75 / 650)
    assert result.normalized_net_share_reduction == pytest.approx(0.005050505, rel=1e-6)
    assert result.through_return == pytest.approx(0.0508197358)
    assert result.verified_recurring_buyback_cash == pytest.approx(12)
    assert result.buyback_credit_eligible is True


def test_negative_cdc_prevents_a_positive_distributable_base():
    _, cdc, _, result, valuation, _ = load_stage_results("high_dividend_bad_cashflow")

    assert cdc.normalized_parent_core_cdc < 0
    assert result.distributable_base < 0
    assert result.through_return < 0
    assert "UNSUSTAINABLE_PAYOUT_WARNING" in result.flags
    assert valuation.current_valuation_state.value == "NO_NORMAL_VALUATION"
    assert "NON_POSITIVE_OPERATING_BASE" in valuation.flags


def test_dilution_can_make_through_return_lower_than_dividend_return():
    _, _, _, result, valuation, _ = load_stage_results("share_dilution_offsets_buyback")

    assert result.normalized_net_share_reduction < 0
    assert result.through_return < result.dividend_through_return
    assert result.verified_recurring_buyback_cash == 0
    assert result.buyback_credit_eligible is False
    assert "BUYBACK_CREDIT_REJECTED_DILUTION" in result.flags
    assert valuation.verified_recurring_buyback_cash == 0


def test_no_formal_policy_uses_profile_p25_method():
    profile = load_profile("strict-v1")
    years = [
        ThroughReturnYearInput(
            period=f"FY{year}",
            parent_net_profit=100,
            ordinary_dividend_cash=20,
            special_dividend_cash=0,
            payout_ratio=payout,
            fully_diluted_shares=100,
        )
        for year, payout in zip(range(2021, 2026), (0.2, 0.4, 0.6, 0.8, 1.0))
    ]
    result = calculate_through_return(
        ThroughReturnInput(
            years=years,
            normalized_parent_core_cdc=50,
            current_market_cap=100,
            payout_policy_formal=False,
            payout_policy_confidence=None,
        ),
        profile,
    )

    # Linear P25 of the ordered five values is the second value, 40%.
    assert result.conservative_payout_ratio == pytest.approx(0.4)
    assert result.distributable_base == pytest.approx(50)
    assert result.dividend_through_return == pytest.approx(0.2)


def test_missing_profit_stays_null_instead_of_becoming_zero():
    profile = load_profile("strict-v1")
    years = [
        ThroughReturnYearInput(
            period=f"FY{year}",
            parent_net_profit=None if year == 2023 else 100,
            ordinary_dividend_cash=20,
            special_dividend_cash=0,
            payout_ratio=0.2,
            fully_diluted_shares=100,
        )
        for year in range(2021, 2026)
    ]
    result = calculate_through_return(
        ThroughReturnInput(
            years=years,
            normalized_parent_core_cdc=50,
            current_market_cap=100,
            payout_policy_formal=True,
            payout_policy_confidence=ConfidenceLevel.HIGH,
            formal_payout_floor=0.2,
        ),
        profile,
    )

    assert result.normalized_parent_profit is None
    assert result.distributable_base is None
    assert result.through_return is None
    assert "NORMALIZED_PARENT_PROFIT_UNAVAILABLE" in result.flags
