from turtle_value_engine import load_normalized_input
from turtle_value_engine.calculations import (
    build_cdc_input_from_normalized_input,
    build_net_cash_input_from_normalized_input,
    calculate_cdc,
    calculate_net_cash,
)
from turtle_value_engine.gates import evaluate_hard_gates, hard_gate_status, hard_gates_passed
from turtle_value_engine.gates.cdc import evaluate_cdc_gate
from turtle_value_engine.gates.eligibility import evaluate_eligibility_gate
from turtle_value_engine.gates.governance import evaluate_governance_data_quality_gate
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


def test_governance_missing_context_messages_name_the_point_in_time_period():
    """Issue #81: governance point-in-time facts must fail closed actionably.

    ``GOVERNANCE.ACCOUNTING_OPINION`` and ``GOVERNANCE.RISK_LEVEL`` read only
    the exact ``AS_OF_<as_of>`` label, just like the universe rules.  When the
    operator supplied the fact at a wrong (e.g. fiscal or day-before) period
    label, the reason must still name the canonical point-in-time period —
    the same ``... is missing at the analysis point-in-time period`` shape as
    ``UNIVERSE.*`` — so the operator knows which label to register instead of
    re-pulling fiscal-year data.
    """

    normalized_input = load_normalized_input("fixtures/healthy_cash_cow.json")
    payload = normalized_input.model_dump(mode="json")
    as_of = normalized_input.as_of.isoformat()
    point_in_time_period = f"AS_OF_{as_of}"
    payload["facts"] = [
        fact
        for fact in payload["facts"]
        if fact["field"] not in {"accounting_opinion", "governance_risk_level"}
        or fact["period"] != point_in_time_period
    ]
    provider_shaped = NormalizedCompanyInput.model_validate(payload)

    gate = evaluate_governance_data_quality_gate(provider_shaped, PROFILE)

    messages = {rule.rule_id: rule.message for rule in gate.rules}
    assert gate.status is GateStatus.SPECIAL_REVIEW
    for rule_id in (
        "GOVERNANCE.ACCOUNTING_OPINION",
        "GOVERNANCE.RISK_LEVEL",
    ):
        assert point_in_time_period in messages[rule_id], messages[rule_id]


def test_governance_explicit_null_stays_generic_unresolved():
    """An explicitly registered null stays an explicit-null diagnosis.

    Only the absent-at-``AS_OF_<as_of>`` case names the canonical period; a
    present but explicitly null fact (``value: null``) keeps the unchanged
    generic ``unavailable``/``missing`` wording so the two missingness classes
    stay distinguishable for the operator.
    """

    normalized_input = load_normalized_input("fixtures/healthy_cash_cow.json")
    payload = normalized_input.model_dump(mode="json")
    as_of = normalized_input.as_of.isoformat()
    point_in_time_period = f"AS_OF_{as_of}"
    for fact in payload["facts"]:
        if fact["field"] in {"accounting_opinion", "governance_risk_level"}:
            if fact["period"] == point_in_time_period:
                fact["value"] = None
    provider_shaped = NormalizedCompanyInput.model_validate(payload)

    gate = evaluate_governance_data_quality_gate(provider_shaped, PROFILE)

    messages = {rule.rule_id: rule.message for rule in gate.rules}
    assert messages["GOVERNANCE.ACCOUNTING_OPINION"] == (
        "Accounting opinion is unavailable or unresolved."
    )
    assert messages["GOVERNANCE.RISK_LEVEL"] == "Governance risk level is missing."


def _mutated_healthy_input(mutate):
    """Return a deep-mutated copy of the healthy fixture as a typed input."""

    normalized_input = load_normalized_input("fixtures/healthy_cash_cow.json")
    payload = normalized_input.model_dump(mode="json")
    mutate(payload, normalized_input.as_of.isoformat())
    return NormalizedCompanyInput.model_validate(payload)


def _balance_gate_for(normalized_input):
    """Run the CDC + net-cash stages and evaluate the balance-sheet gate."""

    cdc = calculate_cdc(
        build_cdc_input_from_normalized_input(normalized_input), PROFILE
    )
    net_cash = calculate_net_cash(
        build_net_cash_input_from_normalized_input(
            normalized_input,
            normalized_parent_core_cdc=cdc.normalized_parent_core_cdc,
        ),
        PROFILE,
    )
    return evaluate_hard_gates(
        normalized_input, net_cash_result=net_cash, profile=PROFILE
    ).balance_sheet


def test_coverage_missing_debt_due_names_the_point_in_time_period():
    """Issue #83: a missing coverage denominator must be identifiable.

    ``NET_CASH.STRESS_COVERAGE``/``LIQUIDITY_COVERAGE`` degrade to
    ``SPECIAL_REVIEW`` whenever the ``debt_due_within_one_year`` fact is
    absent (or registered only under a wrong period label), but the reason
    used to say only ``... is unavailable.`` — byte-identical to the case
    where coverage is blocked by genuinely unresolved restricted cash
    requiring human evidence.  The absent-fact case must name the canonical
    fact and the ``AS_OF_<as_of>`` period, the same
    ``... is missing at the analysis point-in-time period`` shape as the
    universe/governance rules, so the operator knows which sourced fact to
    register instead of chasing an evidence problem.
    """

    def remove_debt_due(payload, as_of):
        payload["facts"] = [
            fact
            for fact in payload["facts"]
            if not (
                fact["field"] == "debt_due_within_one_year"
                and fact["period"] == f"AS_OF_{as_of}"
            )
        ]

    provider_shaped = _mutated_healthy_input(remove_debt_due)
    point_in_time_period = f"AS_OF_{provider_shaped.as_of.isoformat()}"
    gate = _balance_gate_for(provider_shaped)

    messages = {rule.rule_id: rule.message for rule in gate.rules}
    assert gate.status is GateStatus.SPECIAL_REVIEW
    for rule_id in ("NET_CASH.STRESS_COVERAGE", "NET_CASH.LIQUIDITY_COVERAGE"):
        assert "debt_due_within_one_year" in messages[rule_id], messages[rule_id]
        assert point_in_time_period in messages[rule_id], messages[rule_id]
    completeness = messages["NET_CASH.DATA_COMPLETENESS"]
    assert completeness is None or "debt_due" not in completeness


def test_coverage_wrong_period_debt_due_names_the_point_in_time_period():
    """A wrong-period label is read as absent and must be named equally."""

    def relabel_debt_due(payload, as_of):
        for fact in payload["facts"]:
            if fact["field"] == "debt_due_within_one_year":
                fact["period"] = f"AS_OF_{as_of}T00:00:00"

    provider_shaped = _mutated_healthy_input(relabel_debt_due)
    point_in_time_period = f"AS_OF_{provider_shaped.as_of.isoformat()}"
    gate = _balance_gate_for(provider_shaped)

    messages = {rule.rule_id: rule.message for rule in gate.rules}
    for rule_id in ("NET_CASH.STRESS_COVERAGE", "NET_CASH.LIQUIDITY_COVERAGE"):
        assert point_in_time_period in messages[rule_id], messages[rule_id]


def test_coverage_explicit_null_debt_due_stays_generic_unresolved():
    """An explicitly registered null keeps the generic wording.

    A present but explicitly null ``debt_due_within_one_year`` is a declared
    unresolved input, not an operator omission; its reason stays the
    unchanged generic ``... is unavailable.`` so the missingness classes
    remain distinguishable, matching the Issue #81 governance precedent.
    """

    def null_debt_due(payload, as_of):
        for fact in payload["facts"]:
            if fact["field"] == "debt_due_within_one_year":
                if fact["period"] == f"AS_OF_{as_of}":
                    fact["value"] = None

    provider_shaped = _mutated_healthy_input(null_debt_due)
    gate = _balance_gate_for(provider_shaped)

    messages = {rule.rule_id: rule.message for rule in gate.rules}
    assert messages["NET_CASH.STRESS_COVERAGE"] == "Stress coverage is unavailable."
    assert messages["NET_CASH.LIQUIDITY_COVERAGE"] == "Liquidity coverage is unavailable."


def test_coverage_unavailable_from_unresolved_cash_keeps_generic_wording():
    """The restricted-cash cause must keep its deliberately generic reason.

    ``cash_rich_dying_business`` blocks coverage through unresolved
    owner-accessible cash (restricted/subsidiary cash authenticity), which
    genuinely requires human evidence rather than a mechanical fact
    registration.  Its reasons must stay byte-identical and must not be
    misattributed to ``debt_due_within_one_year`` (which the fixture
    supplies).
    """

    _, _, _, _, _, gates = load_stage_results("cash_rich_dying_business")

    messages = {rule.rule_id: rule.message for rule in gates.balance_sheet.rules}
    assert messages["NET_CASH.STRESS_COVERAGE"] == "Stress coverage is unavailable."
    assert messages["NET_CASH.LIQUIDITY_COVERAGE"] == "Liquidity coverage is unavailable."
