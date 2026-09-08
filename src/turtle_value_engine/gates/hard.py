"""Composition of the currently implemented independent hard gates.

This module intentionally stops at ``Gates``.  Business-quality scoring,
valuation orchestration and final ``CompanyAnalysis`` assembly are not
implemented here, so an unfinished stage is represented as
``NOT_EVALUATED`` instead of being treated as a pass.
"""

from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.models import (
    CDCResult,
    ConfidenceLevel,
    Gates,
    GateStatus,
    NormalizedCompanyInput,
)
from turtle_value_engine.models.net_cash import NetCashResult
from turtle_value_engine.models.through_return import ThroughReturnResult

from .balance_sheet import evaluate_balance_sheet_gate
from .cdc import evaluate_cdc_gate
from .common import aggregate_status, result_or_not_evaluated
from .eligibility import evaluate_eligibility_gate
from .governance import evaluate_governance_data_quality_gate
from .through_return import evaluate_through_return_gate


def evaluate_hard_gates(
    normalized_input: NormalizedCompanyInput,
    *,
    cdc_result: CDCResult | None = None,
    net_cash_result: NetCashResult | None = None,
    through_return_result: ThroughReturnResult | None = None,
    profile: RuleProfile | None = None,
) -> Gates:
    """Evaluate available gates and preserve unimplemented stages explicitly."""

    active_profile = profile or load_profile(normalized_input.profile_id)
    return Gates(
        universe=evaluate_eligibility_gate(normalized_input, active_profile),
        balance_sheet=(
            evaluate_balance_sheet_gate(net_cash_result, active_profile)
            if net_cash_result is not None
            else result_or_not_evaluated("Net-cash stage has not been run.")
        ),
        cdc=(
            evaluate_cdc_gate(cdc_result, active_profile)
            if cdc_result is not None
            else result_or_not_evaluated("CDC stage has not been run.")
        ),
        through_return=(
            evaluate_through_return_gate(through_return_result, active_profile)
            if through_return_result is not None
            else result_or_not_evaluated("Through Return stage has not been run.")
        ),
        business_quality=result_or_not_evaluated(
            "Business-quality evidence scoring is not implemented in this milestone."
        ),
        governance_data_quality=evaluate_governance_data_quality_gate(
            normalized_input, active_profile
        ),
    )


def hard_gate_status(gates: Gates) -> GateStatus:
    """Return the precedence-aware status across all fixed gate keys."""

    return aggregate_status(
        gate.status
        for gate in (
            gates.universe,
            gates.balance_sheet,
            gates.cdc,
            gates.through_return,
            gates.business_quality,
            gates.governance_data_quality,
        )
    )


def hard_gates_passed(gates: Gates) -> bool:
    """Return true only when every required gate explicitly reports PASS."""

    return all(
        gate.status is GateStatus.PASS and gate.confidence is not ConfidenceLevel.LOW
        for gate in (
            gates.universe,
            gates.balance_sheet,
            gates.cdc,
            gates.through_return,
            gates.business_quality,
            gates.governance_data_quality,
        )
    )
