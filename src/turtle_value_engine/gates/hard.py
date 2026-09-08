"""Composition of the independent hard gates.

Business-quality scoring is accepted only when a structured assessment is
explicitly supplied.  Full ``CompanyAnalysis`` assembly and final decision
orchestration remain outside this stage; absent assessments stay
``NOT_EVALUATED`` rather than being treated as a pass.
"""

from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.models import (
    BusinessQuality,
    CDCResult,
    ConfidenceLevel,
    Gates,
    GateStatus,
    NormalizedCompanyInput,
)
from turtle_value_engine.models.net_cash import NetCashResult
from turtle_value_engine.models.through_return import ThroughReturnResult

from .balance_sheet import evaluate_balance_sheet_gate
from .business_quality import evaluate_business_quality_gate
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
    business_quality: BusinessQuality | None = None,
    business_quality_result: BusinessQuality | None = None,
    profile: RuleProfile | None = None,
) -> Gates:
    """Evaluate available gates and preserve unfinished stages explicitly."""

    active_profile = profile or load_profile(normalized_input.profile_id)
    if business_quality is not None and business_quality_result is not None:
        raise ValueError("supply only one of business_quality or business_quality_result")
    supplied_business_quality = (
        business_quality_result if business_quality_result is not None else business_quality
    )
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
        business_quality=(
            evaluate_business_quality_gate(
                supplied_business_quality,
                active_profile,
                normalized_input=normalized_input,
            )
            if supplied_business_quality is not None
            else result_or_not_evaluated("Business-quality evidence scoring has not been supplied.")
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
