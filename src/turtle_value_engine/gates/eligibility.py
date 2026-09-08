"""Deterministic universe eligibility gate."""

from turtle_value_engine.calculations.facts import FactBook, boolean_value, numeric_value
from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import (
    ConfidenceLevel,
    GateResult,
    GateRule,
    GateStatus,
    NormalizedCompanyInput,
)

from .common import make_gate_result


def evaluate_eligibility_gate(
    normalized_input: NormalizedCompanyInput, profile: RuleProfile
) -> GateResult:
    """Evaluate listing age, special-treatment and model eligibility."""

    book = FactBook(normalized_input.facts)
    period = book.as_of_period(normalized_input.as_of)
    rules: list[GateRule] = []
    confidence = normalized_input.data_quality.confidence

    listing_ref = book.get("listing_years", period)
    listing_years = numeric_value(listing_ref, field="listing_years")
    listing_evidence = [] if listing_ref is None else list(listing_ref.evidence_ids)
    if listing_years is None:
        rules.append(
            GateRule(
                rule_id="UNIVERSE.LISTING_YEARS",
                status=GateStatus.SPECIAL_REVIEW,
                threshold=profile.universe.min_listing_years_pass,
                evidence_ids=listing_evidence,
                message="Listing history is missing.",
            )
        )
    elif listing_years < profile.universe.min_listing_years_watch:
        rules.append(
            GateRule(
                rule_id="UNIVERSE.LISTING_YEARS",
                status=GateStatus.FAIL,
                actual=listing_years,
                threshold=profile.universe.min_listing_years_watch,
                evidence_ids=listing_evidence,
                message="Listing history is below the watch minimum.",
            )
        )
    elif listing_years < profile.universe.min_listing_years_pass:
        rules.append(
            GateRule(
                rule_id="UNIVERSE.LISTING_YEARS",
                status=GateStatus.WATCH,
                actual=listing_years,
                threshold=profile.universe.min_listing_years_pass,
                evidence_ids=listing_evidence,
                message="Listing history is below the normal pass minimum.",
            )
        )
    else:
        rules.append(
            GateRule(
                rule_id="UNIVERSE.LISTING_YEARS",
                status=GateStatus.PASS,
                actual=listing_years,
                threshold=profile.universe.min_listing_years_pass,
                evidence_ids=listing_evidence,
            )
        )

    treatment_ref = book.get("special_treatment", period)
    special_treatment = boolean_value(treatment_ref, field="special_treatment")
    treatment_evidence = [] if treatment_ref is None else list(treatment_ref.evidence_ids)
    if special_treatment is None:
        treatment_status = GateStatus.SPECIAL_REVIEW
        message = "Special-treatment status is missing."
    elif special_treatment and profile.universe.exclude_special_treatment:
        treatment_status = GateStatus.FAIL
        message = "Special-treatment status is excluded by the active profile."
    else:
        treatment_status = GateStatus.PASS
        message = None
    rules.append(
        GateRule(
            rule_id="UNIVERSE.SPECIAL_TREATMENT",
            status=treatment_status,
            actual=special_treatment,
            threshold=profile.universe.exclude_special_treatment,
            evidence_ids=treatment_evidence,
            message=message,
        )
    )

    equity_ref = book.get("parent_equity", period)
    parent_equity = numeric_value(equity_ref, field="parent_equity")
    equity_evidence = [] if equity_ref is None else list(equity_ref.evidence_ids)
    if parent_equity is None:
        equity_status = GateStatus.SPECIAL_REVIEW
        equity_message = "Parent equity is missing."
    elif parent_equity < 0 and profile.universe.exclude_negative_parent_equity:
        equity_status = GateStatus.FAIL
        equity_message = "Parent equity is negative."
    else:
        equity_status = GateStatus.PASS
        equity_message = None
    rules.append(
        GateRule(
            rule_id="UNIVERSE.PARENT_EQUITY",
            status=equity_status,
            actual=parent_equity,
            threshold=0,
            evidence_ids=equity_evidence,
            message=equity_message,
        )
    )

    special_model = normalized_input.company.special_model
    model_status = (
        GateStatus.SPECIAL_REVIEW
        if special_model is not None
        and special_model.lower() in {model.lower() for model in profile.universe.special_models}
        else GateStatus.PASS
    )
    rules.append(
        GateRule(
            rule_id="UNIVERSE.SPECIAL_MODEL",
            status=model_status,
            actual=special_model,
            threshold="ordinary_operating_company",
            message=(
                "Company requires a sector-specific model."
                if model_status is GateStatus.SPECIAL_REVIEW
                else None
            ),
        )
    )

    if any(rule.status is GateStatus.SPECIAL_REVIEW for rule in rules):
        confidence = ConfidenceLevel.LOW
    return make_gate_result(rules, confidence=confidence)
