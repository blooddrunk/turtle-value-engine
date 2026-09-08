from turtle_value_engine.gates import hard_gate_status, hard_gates_passed
from turtle_value_engine.gates.cdc import evaluate_cdc_gate
from turtle_value_engine.gates.through_return import evaluate_through_return_gate
from turtle_value_engine.models import (
    CDCResult,
    ConfidenceLevel,
    GateStatus,
    ThroughReturnResult,
)

from .stage_support import load_stage_results


def test_healthy_fixed_gates_pass_but_unimplemented_business_quality_blocks_composite():
    _, _, _, _, _, gates = load_stage_results("healthy_cash_cow")

    assert gates.universe.status is GateStatus.PASS
    assert gates.balance_sheet.status is GateStatus.PASS
    assert gates.cdc.status is GateStatus.PASS
    assert gates.through_return.status is GateStatus.PASS
    assert gates.governance_data_quality.status is GateStatus.PASS
    assert gates.business_quality.status is GateStatus.NOT_EVALUATED
    assert hard_gate_status(gates) is GateStatus.NOT_EVALUATED
    assert hard_gates_passed(gates) is False
    assert gates.cdc.rules[-1].evidence_ids
    assert gates.balance_sheet.rules[-1].evidence_ids


def test_governance_red_flags_take_hard_precedence():
    _, _, _, _, _, gates = load_stage_results("negative_ev_governance_risk")

    assert gates.governance_data_quality.status is GateStatus.FAIL
    assert any(
        rule.rule_id == "GOVERNANCE.MAJOR_ILLEGAL_GUARANTEE" and rule.status is GateStatus.FAIL
        for rule in gates.governance_data_quality.rules
    )
    assert hard_gate_status(gates) is GateStatus.FAIL


def test_cdc_yield_boundaries_use_profile_thresholds():
    from turtle_value_engine.config import load_profile

    profile = load_profile("strict-v1")
    common = {
        "positive_years_5y": 4,
        "cumulative_core_cdc_5y": 1,
        "normalized_parent_core_cdc": 1,
        "confidence": ConfidenceLevel.HIGH,
    }
    assert (
        evaluate_cdc_gate(CDCResult(cdc_yield=0.06, **common), profile).status is GateStatus.WATCH
    )
    assert evaluate_cdc_gate(CDCResult(cdc_yield=0.08, **common), profile).status is GateStatus.PASS


def test_through_return_boundaries_use_profile_thresholds():
    from turtle_value_engine.config import load_profile

    profile = load_profile("strict-v1")
    assert (
        evaluate_through_return_gate(
            ThroughReturnResult(through_return=0.04, confidence=ConfidenceLevel.HIGH), profile
        ).status
        is GateStatus.WATCH
    )
    assert (
        evaluate_through_return_gate(
            ThroughReturnResult(through_return=0.05, confidence=ConfidenceLevel.HIGH), profile
        ).status
        is GateStatus.PASS
    )
