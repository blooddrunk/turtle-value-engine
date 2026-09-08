"""Deterministic shareholder-through-return gate."""

from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import GateResult, GateRule, GateStatus
from turtle_value_engine.models.through_return import ThroughReturnResult

from .common import make_gate_result, metric_evidence_ids


def evaluate_through_return_gate(result: ThroughReturnResult, profile: RuleProfile) -> GateResult:
    """Evaluate the configured Through Return candidate threshold."""

    value = result.through_return
    evidence_ids = metric_evidence_ids(result)
    bands = profile.through_return.yield_bands
    if value is None:
        status = GateStatus.SPECIAL_REVIEW
        message = "Through Return is unavailable."
    elif value < bands.fail_below:
        status = GateStatus.FAIL
        message = "Through Return is below the configured watch floor."
    elif value >= profile.through_return.formal_candidate_threshold:
        status = GateStatus.PASS
        message = None
    else:
        status = GateStatus.WATCH
        message = "Through Return is below the formal candidate threshold."

    return make_gate_result(
        [
            GateRule(
                rule_id="THROUGH_RETURN.CANDIDATE_THRESHOLD",
                status=status,
                actual=value,
                threshold=profile.through_return.formal_candidate_threshold,
                evidence_ids=evidence_ids,
                message=message,
            )
        ],
        confidence=result.confidence,
    )
