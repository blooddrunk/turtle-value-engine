"""Helpers for exercising the isolated deterministic stage pipeline."""

import json
from pathlib import Path

from turtle_value_engine import load_normalized_input
from turtle_value_engine.calculations import (
    build_cdc_input_from_normalized_input,
    build_net_cash_input_from_normalized_input,
    build_through_return_input_from_normalized_input,
    build_valuation_input_from_normalized_input,
    calculate_cdc,
    calculate_net_cash,
    calculate_through_return,
    calculate_valuation,
)
from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.gates import evaluate_hard_gates

FIXTURE_DIR = Path("fixtures")
PROFILE = load_profile("strict-v1")
EXPECTATIONS = json.loads((FIXTURE_DIR / "expectations.json").read_text(encoding="utf-8"))
FIXTURE_NAMES = tuple(item["fixture"] for item in EXPECTATIONS["fixtures"])


def load_stage_results(
    name: str,
    profile: RuleProfile = PROFILE,
    *,
    non_price_gates_passed: bool | None = None,
):
    """Run the implemented stages without assembling a pretend final analysis."""

    normalized_input = load_normalized_input(FIXTURE_DIR / f"{name}.json")
    cyclical = name == "cyclical_peak_false_cheap"
    cdc = calculate_cdc(
        build_cdc_input_from_normalized_input(normalized_input, cyclical=cyclical), profile
    )
    net_cash = calculate_net_cash(
        build_net_cash_input_from_normalized_input(
            normalized_input,
            normalized_parent_core_cdc=cdc.normalized_parent_core_cdc,
        ),
        profile,
    )
    through_return = calculate_through_return(
        build_through_return_input_from_normalized_input(
            normalized_input,
            normalized_parent_core_cdc=cdc.normalized_parent_core_cdc,
        ),
        profile,
    )
    valuation = calculate_valuation(
        build_valuation_input_from_normalized_input(
            normalized_input,
            cdc_result=cdc,
            net_cash_result=net_cash,
            through_return_result=through_return,
            cyclical=cyclical,
            non_price_gates_passed=non_price_gates_passed,
        ),
        profile,
    )
    gates = evaluate_hard_gates(
        normalized_input,
        cdc_result=cdc,
        net_cash_result=net_cash,
        through_return_result=through_return,
        profile=profile,
    )
    return normalized_input, cdc, net_cash, through_return, valuation, gates
