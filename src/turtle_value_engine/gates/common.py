"""Shared deterministic gate-result helpers."""

from collections.abc import Iterable, Mapping, Sequence

from turtle_value_engine.models import ConfidenceLevel, GateResult, GateRule, GateStatus

_STATUS_PRIORITY = {
    GateStatus.PASS: 0,
    GateStatus.WATCH: 1,
    GateStatus.NOT_EVALUATED: 2,
    GateStatus.SPECIAL_REVIEW: 3,
    GateStatus.FAIL: 4,
}


def aggregate_status(statuses: Iterable[GateStatus]) -> GateStatus:
    """Apply hard-gate precedence to a sequence of rule statuses."""

    values = list(statuses)
    return max(values, key=_STATUS_PRIORITY.__getitem__) if values else GateStatus.NOT_EVALUATED


def unique_strings(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def metric_evidence_ids(metric: object) -> list[str]:
    """Flatten metric lineage for gate rules without inventing evidence."""

    evidence_index = getattr(metric, "source_evidence_ids", {})
    if not isinstance(evidence_index, Mapping):
        return []
    return unique_strings(
        evidence_id
        for evidence_ids in evidence_index.values()
        if isinstance(evidence_ids, Iterable) and not isinstance(evidence_ids, (str, bytes))
        for evidence_id in evidence_ids
        if isinstance(evidence_id, str)
    )


def make_gate_result(
    rules: Sequence[GateRule],
    *,
    confidence: ConfidenceLevel | None = None,
) -> GateResult:
    """Build a gate with stable blocking-reason order."""

    status = aggregate_status(rule.status for rule in rules)
    reasons = [
        rule.message
        for rule in rules
        if rule.message is not None and rule.status in {GateStatus.FAIL, GateStatus.SPECIAL_REVIEW}
    ]
    return GateResult(
        status=status,
        rules=list(rules),
        blocking_reasons=unique_strings(reasons),
        confidence=confidence,
    )


def result_or_not_evaluated(message: str) -> GateResult:
    """Represent an intentionally unavailable stage without pretending PASS."""

    return make_gate_result(
        [
            GateRule(
                rule_id="STAGE.NOT_EVALUATED",
                status=GateStatus.NOT_EVALUATED,
                message=message,
            )
        ]
    )
