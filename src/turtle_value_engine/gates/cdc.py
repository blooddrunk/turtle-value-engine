"""Deterministic CDC continuity and yield gate."""

from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import CDCResult, GateResult, GateRule, GateStatus

from .common import make_gate_result, metric_evidence_ids


def evaluate_cdc_gate(result: CDCResult, profile: RuleProfile) -> GateResult:
    """Evaluate continuity and configured CDC-yield bands."""

    rules: list[GateRule] = []
    evidence_ids = metric_evidence_ids(result)
    continuity = profile.cdc.continuity

    insufficient_history = "INSUFFICIENT_CDC_HISTORY" in result.flags
    if result.positive_years_5y is None or insufficient_history:
        positive_status = GateStatus.SPECIAL_REVIEW
        positive_message = "The required CDC lookback history is incomplete."
    elif result.positive_years_5y < continuity.min_positive_years:
        positive_status = GateStatus.FAIL
        positive_message = "Positive Core CDC years are below the configured minimum."
    else:
        positive_status = GateStatus.PASS
        positive_message = None
    rules.append(
        GateRule(
            rule_id="CDC.CONTINUITY.POSITIVE_YEARS",
            status=positive_status,
            actual=result.positive_years_5y,
            threshold=continuity.min_positive_years,
            evidence_ids=evidence_ids,
            message=positive_message,
        )
    )

    cumulative = result.cumulative_core_cdc_5y
    if continuity.require_positive_cumulative:
        if cumulative is None:
            cumulative_status = GateStatus.SPECIAL_REVIEW
            cumulative_message = "Cumulative Core CDC is unavailable."
        elif cumulative <= 0:
            cumulative_status = GateStatus.FAIL
            cumulative_message = "Cumulative Core CDC is not positive."
        else:
            cumulative_status = GateStatus.PASS
            cumulative_message = None
        rules.append(
            GateRule(
                rule_id="CDC.CONTINUITY.POSITIVE_CUMULATIVE",
                status=cumulative_status,
                actual=cumulative,
                threshold=0,
                evidence_ids=evidence_ids,
                message=cumulative_message,
            )
        )

    normalized = result.normalized_parent_core_cdc
    if continuity.require_positive_normalized:
        if normalized is None:
            normalized_status = GateStatus.SPECIAL_REVIEW
            normalized_message = "Normalized parent Core CDC is unavailable."
        elif normalized <= 0:
            normalized_status = GateStatus.FAIL
            normalized_message = "Normalized parent Core CDC is not positive."
        else:
            normalized_status = GateStatus.PASS
            normalized_message = None
        rules.append(
            GateRule(
                rule_id="CDC.NORMALIZATION.POSITIVE",
                status=normalized_status,
                actual=normalized,
                threshold=0,
                evidence_ids=evidence_ids,
                message=normalized_message,
            )
        )

    yield_value = result.cdc_yield
    if yield_value is None:
        yield_status = GateStatus.SPECIAL_REVIEW
        yield_message = "CDC yield is unavailable."
    elif yield_value < profile.cdc.yield_bands.fail_below:
        yield_status = GateStatus.FAIL
        yield_message = "CDC yield is below the configured watch floor."
    elif yield_value >= profile.cdc.yield_bands.pass_:
        yield_status = GateStatus.PASS
        yield_message = None
    else:
        yield_status = GateStatus.WATCH
        yield_message = "CDC yield is below the configured pass threshold."
    rules.append(
        GateRule(
            rule_id="CDC.YIELD",
            status=yield_status,
            actual=yield_value,
            threshold=profile.cdc.yield_bands.pass_,
            evidence_ids=evidence_ids,
            message=yield_message,
        )
    )

    return make_gate_result(rules, confidence=result.confidence)
