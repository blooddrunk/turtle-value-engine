import pytest
from pydantic import ValidationError

from turtle_value_engine.calculations import (
    build_net_cash_input_from_normalized_input,
    calculate_net_cash,
)
from turtle_value_engine.config import load_profile
from turtle_value_engine.models import NetCashInput

from .stage_support import load_stage_results


def test_healthy_fixture_uses_strict_buckets_and_owner_attribution_once():
    _, _, result, _, _, _ = load_stage_results("healthy_cash_cow")

    # 300 + 95% * 50 + 80% * 40; strategic investments receive zero credit.
    assert result.strict_cash == pytest.approx(379.5)
    assert result.financial_net_cash == pytest.approx(299.5)
    assert result.obligation_adjusted_net_cash == pytest.approx(289.5)
    assert result.debt_equivalent == pytest.approx(90)
    assert result.strict_net_cash == pytest.approx(289.5)
    assert result.owner_realizable_net_cash == pytest.approx(289.5)
    assert result.valuation_net_cash == pytest.approx(289.5)
    assert result.source_evidence_ids["hard_cash"]


def test_restricted_cash_unknown_keeps_owner_value_and_valuation_null():
    _, _, result, _, valuation, _ = load_stage_results("cash_rich_dying_business")

    assert result.strict_cash == pytest.approx(878)
    assert result.strict_net_cash == pytest.approx(833)
    assert result.owner_realizable_net_cash is None
    assert result.valuation_net_cash is None
    assert "RESTRICTED_CASH_UNRESOLVED" in result.flags
    assert valuation.valuation_net_cash is None
    assert valuation.ex_cash_cdc_yield is None


def test_proposed_adjustment_does_not_mutate_normalized_fact_projection():
    normalized_input, cdc, original, _, _, _ = load_stage_results("cash_rich_dying_business")
    assert any(adjustment.status.value == "PROPOSED" for adjustment in normalized_input.adjustments)

    without_adjustments = normalized_input.model_copy(update={"adjustments": []})
    result = calculate_net_cash(
        build_net_cash_input_from_normalized_input(
            without_adjustments,
            normalized_parent_core_cdc=cdc.normalized_parent_core_cdc,
        ),
        load_profile("strict-v1"),
    )

    assert result.model_dump() == original.model_dump()


def test_debt_equivalents_include_lease_and_financing_obligations_once():
    _, _, result, _, _, gates = load_stage_results("leveraged_dividend_trap")

    # 900 financial + 120 lease + 180 supplier finance + 30 recourse
    # factoring + 50 hybrid + 40 quasi-debt.
    assert result.debt_equivalent == pytest.approx(1320)
    assert result.financial_net_cash == pytest.approx(-781)
    assert result.obligation_adjusted_net_cash == pytest.approx(-901)
    assert result.strict_net_cash == pytest.approx(-1201)
    assert result.interest_coverage == pytest.approx(130 / 45)
    assert gates.balance_sheet.status.value == "FAIL"


def test_owner_net_cash_attributes_a_disclosed_subsidiary_debt_component():
    profile = load_profile("strict-v1")
    result = calculate_net_cash(
        NetCashInput(
            current_market_cap=100,
            normalized_parent_core_cdc=10,
            book_cash=100,
            reported_interest_bearing_debt=50,
            hard_cash=100,
            near_cash=0,
            liquid_financial_assets=0,
            strategic_investments=0,
            restricted_cash=0,
            pledged_deposits=0,
            financial_debt=50,
            lease_debt=0,
            supplier_finance=0,
            recourse_factoring=0,
            debt_like_hybrids=0,
            material_quasi_debt=0,
            subsidiary_cash=40,
            subsidiary_debt=20,
            subsidiary_ownership=0.5,
            upstreamability_factor=1,
            debt_due_within_one_year=10,
            normalized_ebitda=100,
            cash_interest_expense=10,
            cash_authenticity_verified=True,
            cash_upstreamability_verified=True,
        ),
        profile,
    )

    assert result.owner_accessible_cash == pytest.approx(80)
    assert result.owner_debt_equivalent == pytest.approx(40)
    assert result.owner_realizable_net_cash == pytest.approx(40)


def test_missing_cash_bucket_is_not_silently_coerced_to_zero():
    profile = load_profile("strict-v1")
    normalized_input, cdc, _, _, _, _ = load_stage_results("healthy_cash_cow")
    inputs = build_net_cash_input_from_normalized_input(
        normalized_input,
        normalized_parent_core_cdc=cdc.normalized_parent_core_cdc,
    ).model_copy(update={"near_cash": None})

    result = calculate_net_cash(inputs, profile)

    assert result.strict_cash is None
    assert result.owner_realizable_net_cash is None
    assert "MISSING_NET_CASH_FIELD:near_cash" in result.flags


def test_net_cash_input_rejects_negative_cash_and_debt_amounts():
    with pytest.raises(ValidationError):
        NetCashInput(hard_cash=-1)
