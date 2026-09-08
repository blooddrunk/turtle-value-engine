"""Deterministic balance-sheet safety gate."""

from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import GateResult, GateRule, GateStatus
from turtle_value_engine.models.net_cash import NetCashResult

from .common import make_gate_result, metric_evidence_ids


def evaluate_balance_sheet_gate(result: NetCashResult, profile: RuleProfile) -> GateResult:
    """Evaluate leverage, coverage and refinancing rules independently."""

    rules: list[GateRule] = []
    evidence_ids = metric_evidence_ids(result)
    net_debt_to_ebitda = result.net_debt_to_ebitda
    strict_net_cash = result.strict_net_cash

    if strict_net_cash is None:
        strict_status = GateStatus.SPECIAL_REVIEW
        strict_message = "Strict net cash is unavailable."
    elif strict_net_cash < 0 and (
        net_debt_to_ebitda is None or net_debt_to_ebitda > profile.net_cash.leverage.fail_above
    ):
        strict_status = (
            GateStatus.FAIL if net_debt_to_ebitda is not None else GateStatus.SPECIAL_REVIEW
        )
        strict_message = (
            "Negative strict net cash coincides with excessive net leverage."
            if strict_status is GateStatus.FAIL
            else "Negative strict net cash cannot be assessed against net leverage."
        )
    elif strict_net_cash < 0:
        strict_status = GateStatus.WATCH
        strict_message = (
            "Strict net cash is negative, but the configured leverage failure rule is not met."
        )
    else:
        strict_status = GateStatus.PASS
        strict_message = None
    rules.append(
        GateRule(
            rule_id="NET_CASH.STRICT_NET_CASH",
            status=strict_status,
            actual=strict_net_cash,
            threshold=0,
            evidence_ids=evidence_ids,
            message=strict_message,
        )
    )

    if net_debt_to_ebitda is None:
        leverage_status = GateStatus.SPECIAL_REVIEW
        leverage_message = "Net debt to EBITDA is unavailable."
    elif net_debt_to_ebitda > profile.net_cash.leverage.fail_above:
        leverage_status = GateStatus.FAIL
        leverage_message = "Net debt to EBITDA exceeds the configured failure ceiling."
    elif net_debt_to_ebitda <= profile.net_cash.leverage.max_net_debt_to_ebitda_pass:
        leverage_status = GateStatus.PASS
        leverage_message = None
    else:
        leverage_status = GateStatus.WATCH
        leverage_message = "Net debt to EBITDA is above the normal pass band."
    rules.append(
        GateRule(
            rule_id="NET_CASH.NET_DEBT_TO_EBITDA",
            status=leverage_status,
            actual=net_debt_to_ebitda,
            threshold=profile.net_cash.leverage.fail_above,
            evidence_ids=evidence_ids,
            message=leverage_message,
        )
    )

    interest_coverage = result.interest_coverage
    if "INTEREST_COVERAGE_NOT_APPLICABLE" in result.flags:
        interest_status = GateStatus.PASS
        interest_message = None
    elif interest_coverage is None:
        interest_status = GateStatus.SPECIAL_REVIEW
        interest_message = "Interest coverage is unavailable."
    elif interest_coverage < profile.net_cash.leverage.fail_below:
        interest_status = GateStatus.FAIL
        interest_message = "Interest coverage is below the configured failure floor."
    elif interest_coverage >= profile.net_cash.leverage.interest_coverage_pass:
        interest_status = GateStatus.PASS
        interest_message = None
    else:
        interest_status = GateStatus.WATCH
        interest_message = "Interest coverage is below the normal pass band."
    rules.append(
        GateRule(
            rule_id="NET_CASH.INTEREST_COVERAGE",
            status=interest_status,
            actual=interest_coverage,
            threshold=profile.net_cash.leverage.fail_below,
            evidence_ids=evidence_ids,
            message=interest_message,
        )
    )

    stress_coverage = result.stress_coverage
    if stress_coverage is None:
        stress_status = GateStatus.SPECIAL_REVIEW
        stress_message = "Stress coverage is unavailable."
    elif stress_coverage < profile.net_cash.stress.fail_below:
        stress_status = GateStatus.FAIL
        stress_message = "Stress coverage is below the configured failure floor."
    elif stress_coverage >= profile.net_cash.stress.preferred_coverage:
        stress_status = GateStatus.PASS
        stress_message = None
    else:
        stress_status = GateStatus.WATCH
        stress_message = "Stress coverage is below the preferred coverage level."
    rules.append(
        GateRule(
            rule_id="NET_CASH.STRESS_COVERAGE",
            status=stress_status,
            actual=stress_coverage,
            threshold=profile.net_cash.stress.fail_below,
            evidence_ids=evidence_ids,
            message=stress_message,
        )
    )

    liquidity_coverage = result.liquidity_coverage
    if liquidity_coverage is None:
        liquidity_status = GateStatus.SPECIAL_REVIEW
        liquidity_message = "Liquidity coverage is unavailable."
    elif liquidity_coverage < profile.net_cash.liquidity_coverage.fail_below:
        liquidity_status = GateStatus.FAIL
        liquidity_message = "Liquidity coverage is below the configured failure floor."
    elif liquidity_coverage >= profile.net_cash.liquidity_coverage.b:
        liquidity_status = GateStatus.PASS
        liquidity_message = None
    else:
        liquidity_status = GateStatus.WATCH
        liquidity_message = "Liquidity coverage is below the normal pass band."
    rules.append(
        GateRule(
            rule_id="NET_CASH.LIQUIDITY_COVERAGE",
            status=liquidity_status,
            actual=liquidity_coverage,
            threshold=profile.net_cash.liquidity_coverage.fail_below,
            evidence_ids=evidence_ids,
            message=liquidity_message,
        )
    )

    refinancing = "REFINANCING_DEPENDENCY" in result.flags
    rules.append(
        GateRule(
            rule_id="NET_CASH.REFINANCING_DEPENDENCY",
            status=GateStatus.FAIL if refinancing else GateStatus.PASS,
            actual=refinancing,
            threshold=False,
            evidence_ids=evidence_ids,
            message=(
                "Near-term debt cannot be covered by accessible cash and normalized CDC."
                if refinancing
                else None
            ),
        )
    )

    critical_prefixes = (
        "MISSING_NET_CASH_FIELD:",
        "RESTRICTED_CASH_UNRESOLVED",
        "PLEDGED_DEPOSITS_UNRESOLVED",
        "CASH_AUTHENTICITY_UNVERIFIED",
        "CASH_UPSTREAMABILITY_UNVERIFIED",
        "CASH_AUTHENTICITY_VERIFICATION_MISSING",
        "CASH_UPSTREAMABILITY_VERIFICATION_MISSING",
        "UPSTREAMABILITY_UNRESOLVED",
    )
    incomplete = (
        any(flag.startswith(critical_prefixes) for flag in result.flags)
        or result.owner_realizable_net_cash is None
    )
    rules.append(
        GateRule(
            rule_id="NET_CASH.DATA_COMPLETENESS",
            status=GateStatus.SPECIAL_REVIEW if incomplete else GateStatus.PASS,
            actual=None if not incomplete else "INCOMPLETE",
            threshold="COMPLETE",
            evidence_ids=evidence_ids,
            message=(
                "Owner-realizable net cash has unresolved critical inputs." if incomplete else None
            ),
        )
    )

    return make_gate_result(rules, confidence=result.confidence)
