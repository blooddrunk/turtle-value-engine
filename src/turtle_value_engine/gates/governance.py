"""Deterministic governance and data-quality gate."""

from turtle_value_engine.calculations.facts import FactBook, boolean_value, enum_value
from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import (
    ConfidenceLevel,
    GateResult,
    GateRule,
    GateStatus,
    NormalizedCompanyInput,
)
from turtle_value_engine.models.common import AdjustmentStatus

from .common import make_gate_result


def evaluate_governance_data_quality_gate(
    normalized_input: NormalizedCompanyInput, profile: RuleProfile
) -> GateResult:
    """Block known governance failures and unresolved critical data."""

    del profile  # The profile is part of the stable gate signature for future rule versions.
    book = FactBook(normalized_input.facts)
    period = book.as_of_period(normalized_input.as_of)
    rules: list[GateRule] = []

    for field, rule_id, message in (
        (
            "major_illegal_guarantee",
            "GOVERNANCE.MAJOR_ILLEGAL_GUARANTEE",
            "A major illegal guarantee is present.",
        ),
        (
            "controlling_shareholder_fund_occupation",
            "GOVERNANCE.CONTROLLING_SHAREHOLDER_FUND_OCCUPATION",
            "Controlling-shareholder fund occupation is present.",
        ),
    ):
        reference = book.get(field, period)
        value = boolean_value(reference, field=field)
        evidence_ids = [] if reference is None else list(reference.evidence_ids)
        # These are red-flag disclosures, rather than affirmative claims that
        # every possible issue was investigated.  An omitted fact therefore
        # means "no disclosed red flag"; an explicit null remains unresolved.
        if reference is None:
            status = GateStatus.PASS
            rule_message = None
        elif value is None:
            status = GateStatus.SPECIAL_REVIEW
            rule_message = f"{field} status is missing."
        elif value is True:
            status = GateStatus.FAIL
            rule_message = message
        else:
            status = GateStatus.PASS
            rule_message = None
        rules.append(
            GateRule(
                rule_id=rule_id,
                status=status,
                actual=value,
                threshold=False,
                evidence_ids=evidence_ids,
                message=rule_message,
            )
        )

    opinion_reference = book.get("accounting_opinion", period)
    opinion = enum_value(opinion_reference, field="accounting_opinion")
    opinion_evidence = [] if opinion_reference is None else list(opinion_reference.evidence_ids)
    if opinion is None or opinion == "UNKNOWN":
        opinion_status = GateStatus.SPECIAL_REVIEW
        opinion_message = "Accounting opinion is unavailable or unresolved."
    elif opinion in {"ADVERSE", "DISCLAIMER"}:
        opinion_status = GateStatus.FAIL
        opinion_message = "Adverse or disclaimer accounting opinion requires a governance failure."
    elif opinion == "QUALIFIED":
        opinion_status = GateStatus.SPECIAL_REVIEW
        opinion_message = "Qualified accounting opinion requires manual review."
    else:
        opinion_status = GateStatus.PASS
        opinion_message = None
    rules.append(
        GateRule(
            rule_id="GOVERNANCE.ACCOUNTING_OPINION",
            status=opinion_status,
            actual=opinion,
            threshold="UNMODIFIED",
            evidence_ids=opinion_evidence,
            message=opinion_message,
        )
    )

    risk_reference = book.get("governance_risk_level", period)
    risk = enum_value(risk_reference, field="governance_risk_level")
    risk_evidence = [] if risk_reference is None else list(risk_reference.evidence_ids)
    if risk is None:
        risk_status = GateStatus.SPECIAL_REVIEW
        risk_message = "Governance risk level is missing."
    elif risk in {"HIGH", "SEVERE"}:
        risk_status = GateStatus.FAIL
        risk_message = "Governance risk level is high or severe."
    else:
        risk_status = GateStatus.PASS
        risk_message = None
    rules.append(
        GateRule(
            rule_id="GOVERNANCE.RISK_LEVEL",
            status=risk_status,
            actual=risk,
            threshold="HIGH",
            evidence_ids=risk_evidence,
            message=risk_message,
        )
    )

    for field, rule_id, message in (
        (
            "cash_authenticity_verified",
            "DATA_QUALITY.CASH_AUTHENTICITY",
            "Cash authenticity is not verified.",
        ),
        (
            "cash_upstreamability_verified",
            "DATA_QUALITY.CASH_UPSTREAMABILITY",
            "Cash upstreamability is not verified.",
        ),
    ):
        reference = book.get(field, period)
        value = boolean_value(reference, field=field)
        evidence_ids = [] if reference is None else list(reference.evidence_ids)
        if value is True:
            status = GateStatus.PASS
            rule_message = None
        elif value is False:
            status = GateStatus.SPECIAL_REVIEW
            rule_message = message
        else:
            status = GateStatus.SPECIAL_REVIEW
            rule_message = f"{field} status is missing."
        rules.append(
            GateRule(
                rule_id=rule_id,
                status=status,
                actual=value,
                threshold=True,
                evidence_ids=evidence_ids,
                message=rule_message,
            )
        )

    proposed_adjustments = [
        adjustment
        for adjustment in normalized_input.adjustments
        if adjustment.status is AdjustmentStatus.PROPOSED
    ]
    rules.append(
        GateRule(
            rule_id="DATA_QUALITY.UNACCEPTED_ADJUSTMENTS",
            status=GateStatus.SPECIAL_REVIEW if proposed_adjustments else GateStatus.PASS,
            actual=len(proposed_adjustments),
            threshold=0,
            evidence_ids=[
                evidence_id
                for adjustment in proposed_adjustments
                for evidence_id in adjustment.source_evidence_ids
            ],
            message=(
                "One or more economic adjustments remain unaccepted."
                if proposed_adjustments
                else None
            ),
        )
    )

    if normalized_input.data_quality.confidence is ConfidenceLevel.LOW:
        rules.append(
            GateRule(
                rule_id="DATA_QUALITY.OVERALL_CONFIDENCE",
                status=GateStatus.SPECIAL_REVIEW,
                actual=ConfidenceLevel.LOW.value,
                threshold=ConfidenceLevel.MEDIUM.value,
                message="Overall data confidence is LOW.",
            )
        )
    else:
        rules.append(
            GateRule(
                rule_id="DATA_QUALITY.OVERALL_CONFIDENCE",
                status=GateStatus.PASS,
                actual=normalized_input.data_quality.confidence.value,
                threshold=ConfidenceLevel.MEDIUM.value,
            )
        )

    confidence = normalized_input.data_quality.confidence
    if any(rule.status in {GateStatus.FAIL, GateStatus.SPECIAL_REVIEW} for rule in rules):
        confidence = ConfidenceLevel.LOW
    return make_gate_result(rules, confidence=confidence)


# Short alias for callers that use the gate name without the data-quality suffix.
evaluate_governance_gate = evaluate_governance_data_quality_gate
