import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.calculations import calculate_valuation
from turtle_value_engine.config import load_profile
from turtle_value_engine.models import ValuationInput

from .stage_support import load_stage_results


def test_healthy_valuation_uses_minimum_of_cdc_and_shareholder_cash_caps():
    _, _, _, _, result, _ = load_stage_results("healthy_cash_cow")

    assert result.recurring_dividend_cash == pytest.approx(29.75)
    assert result.verified_recurring_buyback_cash == pytest.approx(12)
    assert result.recurring_shareholder_cash == pytest.approx(41.75)
    assert result.tiers.observation.market_cap == pytest.approx(41.75 / 0.04)
    assert result.tiers.acceptable.market_cap == pytest.approx(41.75 / 0.05)
    assert result.tiers.turtle_entry.market_cap == pytest.approx(41.75 / 0.05)
    assert result.tiers.extreme_safety.market_cap == pytest.approx(41.75 / 0.06)
    assert result.current_valuation_state.value == "SPECIAL_REVIEW"
    assert "NON_PRICE_GATES_UNRESOLVED" in result.flags


def test_valuation_tier_caps_are_monotonic():
    _, _, _, _, result, _ = load_stage_results("healthy_cash_cow")
    caps = [
        getattr(result.tiers, name).market_cap
        for name in ("observation", "acceptable", "turtle_entry", "extreme_safety")
    ]

    assert all(previous >= current for previous, current in zip(caps, caps[1:]))


def test_explicitly_passed_non_price_gates_unlock_current_valuation_state():
    _, _, _, _, result, _ = load_stage_results("healthy_cash_cow", non_price_gates_passed=True)

    assert result.current_valuation_state.value == "EXTREME_SAFETY"


def test_negative_adjusted_ev_has_no_infinite_ex_cash_yield():
    _, _, _, _, result, gates = load_stage_results("negative_ev_governance_risk")

    assert result.adjusted_ev == pytest.approx(-95)
    assert result.ex_cash_cdc_yield is None
    assert "NET_NET_SPECIAL_CASE" in result.flags
    assert result.current_valuation_state.value == "NO_NORMAL_VALUATION"
    assert gates.governance_data_quality.status.value == "FAIL"


def test_unverified_buyback_cash_is_not_capitalized_in_target_value():
    _, _, _, _, result, _ = load_stage_results("share_dilution_offsets_buyback")

    assert result.verified_recurring_buyback_cash == 0
    assert result.recurring_shareholder_cash == pytest.approx(25.8)


def test_positive_buyback_amount_requires_explicit_verification():
    result = calculate_valuation(
        ValuationInput(
            as_of="2026-09-08",
            valuation_currency="CNY",
            listing="SH600000",
            listing_equivalent_market_cap=100,
            normalized_diluted_economic_shares=10,
            normalized_parent_core_cdc=10,
            distributable_base=10,
            conservative_payout_ratio=0.5,
            verified_recurring_buyback_cash=2,
            buyback_credit_confidence="HIGH",
            buyback_history_years=5,
            owner_realizable_net_cash=0,
            valuation_net_cash=0,
        ),
        load_profile("strict-v1"),
    )

    assert result.verified_recurring_buyback_cash == 0
    assert "BUYBACK_CREDIT_NOT_VERIFIED" in result.flags


def test_valuation_with_missing_operating_inputs_preserves_nullable_contract():
    result = calculate_valuation(
        ValuationInput(
            as_of="2026-09-08",
            valuation_currency="CNY",
            listing="SH600000",
            listing_equivalent_market_cap=100,
            normalized_diluted_economic_shares=10,
            normalized_parent_core_cdc=None,
            distributable_base=None,
            conservative_payout_ratio=None,
            owner_realizable_net_cash=0,
            valuation_net_cash=0,
            confidence="HIGH",
        ),
        load_profile("strict-v1"),
    )

    assert result.normalized_parent_core_cdc is None
    assert result.distributable_base is None
    assert result.recurring_shareholder_cash is None
    assert result.current_valuation_state.value == "NO_NORMAL_VALUATION"

    schema = json.loads(Path("schemas/valuation-result.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))
