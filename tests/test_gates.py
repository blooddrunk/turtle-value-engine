from turtle_value_engine import load_normalized_input
from turtle_value_engine.gates import hard_gate_status, hard_gates_passed
from turtle_value_engine.gates.cdc import evaluate_cdc_gate
from turtle_value_engine.gates.eligibility import evaluate_eligibility_gate
from turtle_value_engine.gates.through_return import evaluate_through_return_gate
from turtle_value_engine.models import (
    CDCResult,
    ConfidenceLevel,
    GateStatus,
    NormalizedCompanyInput,
    ThroughReturnResult,
)

from .stage_support import PROFILE, load_stage_results


def test_healthy_fixed_gates_without_assessment_block_composite():
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


def test_universe_missing_context_messages_name_the_point_in_time_period():
    """Issue #71: a bare ``... is missing.`` reason contradicts the report.

    A provider-normalized input carries fiscal-period balance-sheet facts
    (``parent_equity`` at ``2024-12-31``/``2025-12-31``) but no point-in-time
    context facts at the canonical ``AS_OF_<as_of>`` period.  The engine is
    right to fail closed, but the operator-facing reason must say WHAT is
    missing — the fact at the analysis point-in-time period — otherwise the
    same report simultaneously shows the field with values and calls it
    missing.
    """

    normalized_input = load_normalized_input("fixtures/healthy_cash_cow.json")
    payload = normalized_input.model_dump(mode="json")
    as_of = normalized_input.as_of.isoformat()
    point_in_time_period = f"AS_OF_{as_of}"
    payload["facts"] = [
        fact
        for fact in payload["facts"]
        if fact["field"] not in {"listing_years", "special_treatment", "parent_equity"}
        or fact["period"] != point_in_time_period
    ] + [
        {
            "id": "fact-provider-parent-equity-fy2025",
            "field": "parent_equity",
            "value": 5_000.0,
            "unit": "reported_currency_amount",
            "currency": "CNY",
            "period": "2025-12-31",
            "source_evidence_ids": ["ev-healthy_cash_cow-balance"],
            "estimated": False,
            "confidence": 0.9,
        }
    ]
    provider_shaped = NormalizedCompanyInput.model_validate(payload)

    gate = evaluate_eligibility_gate(provider_shaped, PROFILE)

    messages = {rule.rule_id: rule.message for rule in gate.rules}
    assert gate.status is GateStatus.SPECIAL_REVIEW
    for rule_id in (
        "UNIVERSE.LISTING_YEARS",
        "UNIVERSE.SPECIAL_TREATMENT",
        "UNIVERSE.PARENT_EQUITY",
    ):
        assert point_in_time_period in messages[rule_id], messages[rule_id]
