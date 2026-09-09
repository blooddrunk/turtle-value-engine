"""Deterministic stage entry points and CompanyAnalysis orchestration."""

from collections.abc import Iterable, Sequence

from turtle_value_engine.calculations import (
    build_business_quality_input_from_normalized_input,
    build_cdc_input_from_normalized_input,
    build_net_cash_input_from_normalized_input,
    build_through_return_input_from_normalized_input,
    build_valuation_input_from_normalized_input,
    calculate_business_quality,
    calculate_cdc,
    calculate_net_cash,
    calculate_through_return,
    calculate_valuation,
)
from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.gates import evaluate_hard_gates, hard_gate_status, hard_gates_passed
from turtle_value_engine.models import (
    BusinessQuality,
    BusinessQualityDimension,
    BusinessQualityInput,
    CDCInput,
    CDCMetric,
    CDCResult,
    CompanyAnalysis,
    ConfidenceLevel,
    Decision,
    DecisionState,
    Gates,
    GateStatus,
    Metrics,
    NetCashInput,
    NetCashMetric,
    NetCashResult,
    NormalizedCompanyInput,
    ThroughReturnInput,
    ThroughReturnMetric,
    ThroughReturnResult,
    ValuationInput,
    ValuationResult,
    ValuationState,
)

_GATE_NAMES = (
    "universe",
    "balance_sheet",
    "cdc",
    "through_return",
    "business_quality",
    "governance_data_quality",
)
_CONFIDENCE_ORDER = {
    ConfidenceLevel.HIGH: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.LOW: 2,
}
_MANUAL_REVIEW_VALUATION_FLAGS = frozenset(
    {
        "CYCLICAL_VALUATION_UNAVAILABLE",
        "MANUAL_REVIEW_REQUIRED",
        "NON_PRICE_GATES_NOT_PASSED",
        "NON_PRICE_GATES_UNRESOLVED",
        "VALUATION_CRITICAL_INPUT_MISSING",
    }
)


def _unique(items: Iterable[str]) -> list[str]:
    """Return strings in first-seen order without changing lineage order."""

    return list(dict.fromkeys(items))


def _worst_confidence(levels: Iterable[ConfidenceLevel | None]) -> ConfidenceLevel | None:
    """Propagate the weakest available confidence to the final decision."""

    available = [level for level in levels if level is not None]
    if not available:
        return None
    return max(available, key=_CONFIDENCE_ORDER.__getitem__)


def _resolve_cyclical_mode(
    normalized_input: NormalizedCompanyInput, cyclical: bool | None
) -> bool:
    """Resolve an explicit mode, or honor the input's declared special model.

    The normalized input is the only offline source of context.  A cyclical
    model is recognized only when it is explicitly declared as such; the
    engine never infers cyclicality from a recent price or one strong year.
    """

    if cyclical is not None:
        return cyclical
    return (normalized_input.company.special_model or "").lower() == "cyclical"


def _validate_business_quality_lineage(
    normalized_input: NormalizedCompanyInput, business_quality: BusinessQuality | None
) -> None:
    """Reject an offline assessment that points outside the input evidence index."""

    if business_quality is None:
        return
    known_evidence_ids = {evidence.id for evidence in normalized_input.evidence_index}
    referenced_ids = {
        evidence_id
        for dimension in business_quality.dimension_results
        for evidence_id in (
            *dimension.supporting_evidence_ids,
            *dimension.counter_evidence_ids,
        )
    }
    unknown_ids = sorted(referenced_ids - known_evidence_ids)
    if unknown_ids:
        raise ValueError(
            "business-quality assessment references undefined evidence ID(s): "
            + ", ".join(unknown_ids)
        )


def _non_price_gate_argument(gates: Gates) -> bool | None:
    """Translate hard-gate status into valuation's explicit tri-state input."""

    status = hard_gate_status(gates)
    if status is GateStatus.PASS:
        return True
    if status is GateStatus.FAIL:
        return False
    # WATCH, SPECIAL_REVIEW and NOT_EVALUATED all require more than a normal
    # valuation classification can provide.  Preserve that uncertainty rather
    # than collapsing it into a successful or failed investment decision.
    return None


def _metrics_from_results(
    cdc_result: CDCResult,
    net_cash_result: NetCashResult,
    through_return_result: ThroughReturnResult,
) -> Metrics:
    """Project full stage results into the permissive CompanyAnalysis metric groups."""

    return Metrics(
        cdc=CDCMetric.model_validate(cdc_result.model_dump(mode="json")),
        net_cash=NetCashMetric.model_validate(net_cash_result.model_dump(mode="json")),
        through_return=ThroughReturnMetric.model_validate(
            through_return_result.model_dump(mode="json")
        ),
    )


def _gate_reasons(gates: Gates) -> list[str]:
    """Collect deterministic reasons for every gate that is not an explicit pass."""

    reasons: list[str] = []
    for name in _GATE_NAMES:
        gate = getattr(gates, name)
        if gate.status is GateStatus.PASS:
            continue
        reasons.extend(gate.blocking_reasons)
        reasons.extend(
            rule.message
            for rule in gate.rules
            if rule.status is not GateStatus.PASS and rule.message is not None
        )
        if not gate.blocking_reasons and not any(
            rule.message is not None
            for rule in gate.rules
            if rule.status is not GateStatus.PASS
        ):
            reasons.append(f"{name} gate is {gate.status.value}.")
    return _unique(reasons)


def _decision_state(gates: Gates, valuation: ValuationResult) -> DecisionState:
    """Apply gate precedence before mapping an eligible valuation state."""

    gate_status = hard_gate_status(gates)
    if gate_status is GateStatus.FAIL:
        return DecisionState.FAIL
    if gate_status in {GateStatus.SPECIAL_REVIEW, GateStatus.NOT_EVALUATED}:
        return DecisionState.SPECIAL_REVIEW
    if gate_status is GateStatus.WATCH:
        return DecisionState.WATCH
    try:
        return DecisionState(valuation.current_valuation_state.value)
    except ValueError:
        # The model enums are intentionally aligned, but a future valuation
        # state must not accidentally become an automatic recommendation.
        return DecisionState.SPECIAL_REVIEW


def _build_decision(
    normalized_input: NormalizedCompanyInput,
    gates: Gates,
    valuation: ValuationResult,
    business_quality: BusinessQuality | None,
) -> Decision:
    """Build the final derived decision without introducing a new opinion layer."""

    state = _decision_state(gates, valuation)
    gate_passed = hard_gates_passed(gates)
    valuation_requires_review = bool(
        _MANUAL_REVIEW_VALUATION_FLAGS.intersection(valuation.flags)
    )
    auto_decision_allowed = (
        gate_passed
        and business_quality is not None
        and normalized_input.data_quality.confidence is not ConfidenceLevel.LOW
        and not normalized_input.data_quality.critical_missing_fields
        and valuation.confidence is not ConfidenceLevel.LOW
        and valuation.current_valuation_state
        not in {ValuationState.SPECIAL_REVIEW, ValuationState.NO_NORMAL_VALUATION}
        and not valuation_requires_review
    )

    blocking_reasons = _gate_reasons(gates)
    if valuation.current_valuation_state is ValuationState.SPECIAL_REVIEW:
        blocking_reasons.append("Valuation state is withheld pending unresolved prerequisites.")
    elif valuation.current_valuation_state is ValuationState.NO_NORMAL_VALUATION:
        blocking_reasons.append("The strict-v1 inputs do not support a normal valuation.")
    blocking_reasons = _unique(blocking_reasons)

    supporting_ids = _unique(
        evidence_id
        for name in _GATE_NAMES
        for rule in getattr(gates, name).rules
        if rule.status is GateStatus.PASS
        for evidence_id in rule.evidence_ids
    )
    counter_ids = _unique(
        evidence_id
        for name in _GATE_NAMES
        for rule in getattr(gates, name).rules
        if rule.status is not GateStatus.PASS
        for evidence_id in rule.evidence_ids
    )

    if state is DecisionState.SPECIAL_REVIEW:
        summary = (
            "Deterministic analysis requires manual review; no automated investment "
            "recommendation is issued."
        )
    elif state is DecisionState.FAIL:
        summary = "A hard gate failed; no normal investment recommendation is issued."
    elif state is DecisionState.NO_NORMAL_VALUATION:
        summary = "No normal strict-v1 valuation is available for this input."
    else:
        summary = f"Deterministic strict-v1 state: {state.value}."

    confidence = _worst_confidence(
        [
            normalized_input.data_quality.confidence,
            valuation.confidence,
            *(getattr(gates, name).confidence for name in _GATE_NAMES),
            None if business_quality is None else business_quality.confidence,
        ]
    )
    return Decision(
        state=state,
        auto_decision_allowed=auto_decision_allowed,
        summary=summary,
        blocking_reasons=blocking_reasons,
        top_supporting_evidence_ids=supporting_ids,
        top_counter_evidence_ids=counter_ids,
        confidence=confidence,
    )


def run_business_quality(
    inputs: BusinessQualityInput, profile: RuleProfile | None = None
) -> BusinessQuality:
    """Score an explicitly supplied offline business-quality assessment.

    This stage validates evidence and applies deterministic profile rules.  It
    does not infer business judgments or produce a final recommendation.
    """

    return calculate_business_quality(inputs, profile or load_profile("strict-v1"))


def run_business_quality_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    dimension_results: Sequence[BusinessQualityDimension],
    profile: RuleProfile | None = None,
    *,
    confidence: ConfidenceLevel | None = None,
) -> BusinessQuality:
    """Score structured dimensions using the normalized input evidence index."""

    active_profile = profile or load_profile(normalized_input.profile_id)
    inputs = build_business_quality_input_from_normalized_input(
        normalized_input,
        dimension_results,
        confidence=confidence,
    )
    return run_business_quality(inputs, active_profile)


def run_cdc(inputs: CDCInput, profile: RuleProfile | None = None) -> CDCResult:
    """Run the isolated deterministic CDC stage."""

    active_profile = profile or load_profile("strict-v1")
    return calculate_cdc(inputs, active_profile)


def run_cdc_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile | None = None,
    *,
    current_market_cap: float | None = None,
    cyclical: bool = False,
) -> CDCResult:
    """Run CDC from the repository-compatible normalized fact payload."""

    inputs = build_cdc_input_from_normalized_input(
        normalized_input,
        current_market_cap=current_market_cap,
        cyclical=cyclical,
    )
    return run_cdc(inputs, profile)


def run_net_cash(inputs: NetCashInput, profile: RuleProfile | None = None) -> NetCashResult:
    """Run the isolated deterministic net-cash stage."""

    return calculate_net_cash(inputs, profile or load_profile("strict-v1"))


def run_net_cash_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile | None = None,
    *,
    normalized_parent_core_cdc: float | None = None,
    current_market_cap: float | None = None,
) -> NetCashResult:
    """Run net cash from normalized facts and an optional upstream CDC value."""

    inputs = build_net_cash_input_from_normalized_input(
        normalized_input,
        normalized_parent_core_cdc=normalized_parent_core_cdc,
        current_market_cap=current_market_cap,
    )
    return run_net_cash(inputs, profile)


def run_through_return(
    inputs: ThroughReturnInput, profile: RuleProfile | None = None
) -> ThroughReturnResult:
    """Run the isolated deterministic Through Return stage."""

    return calculate_through_return(inputs, profile or load_profile("strict-v1"))


def run_through_return_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile | None = None,
    *,
    normalized_parent_core_cdc: float | None = None,
    current_market_cap: float | None = None,
) -> ThroughReturnResult:
    """Run Through Return from normalized facts and an upstream CDC value."""

    inputs = build_through_return_input_from_normalized_input(
        normalized_input,
        normalized_parent_core_cdc=normalized_parent_core_cdc,
        current_market_cap=current_market_cap,
    )
    return run_through_return(inputs, profile)


def run_valuation(inputs: ValuationInput, profile: RuleProfile | None = None) -> ValuationResult:
    """Run valuation tiers as an isolated calculation stage."""

    return calculate_valuation(inputs, profile or load_profile("strict-v1"))


def run_valuation_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile | None = None,
    *,
    cdc_result: CDCResult | None = None,
    through_return_result: ThroughReturnResult | None = None,
    net_cash_result: NetCashResult | None = None,
    non_price_gates_passed: bool | None = None,
    cyclical: bool = False,
) -> ValuationResult:
    """Run valuation from normalized facts and explicitly supplied upstream outputs."""

    active_profile = profile or load_profile(normalized_input.profile_id)
    inputs = build_valuation_input_from_normalized_input(
        normalized_input,
        cdc_result=cdc_result,
        through_return_result=through_return_result,
        net_cash_result=net_cash_result,
        non_price_gates_passed=non_price_gates_passed,
        cyclical=cyclical,
    )
    return run_valuation(inputs, active_profile)


def run_analyze(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile | None = None,
    *,
    cyclical: bool | None = None,
    business_quality: BusinessQuality | None = None,
) -> CompanyAnalysis:
    """Run the complete offline deterministic analysis pipeline.

    The input facts are projected into the existing calculation modules in
    dependency order, then hard gates are evaluated before valuation.  No
    provider, network call, LLM judgment or qualitative score inference is
    performed here.  A structured ``business_quality`` result may be supplied
    by an offline caller; when it is absent the corresponding gate remains
    ``NOT_EVALUATED`` and the final decision cannot become an automatic pass.
    """

    active_profile = profile or load_profile(normalized_input.profile_id)
    if active_profile.profile.id != normalized_input.profile_id:
        raise ValueError(
            "normalized input profile_id "
            f"{normalized_input.profile_id!r} does not match active profile "
            f"{active_profile.profile.id!r}"
        )
    _validate_business_quality_lineage(normalized_input, business_quality)

    cyclical_mode = _resolve_cyclical_mode(normalized_input, cyclical)
    cdc_result = calculate_cdc(
        build_cdc_input_from_normalized_input(normalized_input, cyclical=cyclical_mode),
        active_profile,
    )
    net_cash_result = calculate_net_cash(
        build_net_cash_input_from_normalized_input(
            normalized_input,
            normalized_parent_core_cdc=cdc_result.normalized_parent_core_cdc,
        ),
        active_profile,
    )
    through_return_result = calculate_through_return(
        build_through_return_input_from_normalized_input(
            normalized_input,
            normalized_parent_core_cdc=cdc_result.normalized_parent_core_cdc,
        ),
        active_profile,
    )

    gates = evaluate_hard_gates(
        normalized_input,
        cdc_result=cdc_result,
        net_cash_result=net_cash_result,
        through_return_result=through_return_result,
        business_quality=business_quality,
        profile=active_profile,
    )
    valuation = calculate_valuation(
        build_valuation_input_from_normalized_input(
            normalized_input,
            cdc_result=cdc_result,
            net_cash_result=net_cash_result,
            through_return_result=through_return_result,
            non_price_gates_passed=_non_price_gate_argument(gates),
            cyclical=cyclical_mode,
        ),
        active_profile,
    )
    decision = _build_decision(normalized_input, gates, valuation, business_quality)
    metrics = _metrics_from_results(cdc_result, net_cash_result, through_return_result)

    flags = list(normalized_input.flags)
    if business_quality is None:
        flags.append("BUSINESS_QUALITY_NOT_EVALUATED")
    if not hard_gates_passed(gates):
        flags.append("HARD_GATES_NOT_PASSED")
    if not decision.auto_decision_allowed:
        flags.append("AUTO_DECISION_DISABLED")

    return CompanyAnalysis(
        schema_version=normalized_input.schema_version,
        analysis_id=normalized_input.analysis_id,
        as_of=normalized_input.as_of,
        profile_id=active_profile.profile.id,
        company=normalized_input.company,
        data_quality=normalized_input.data_quality,
        facts=normalized_input.facts,
        adjustments=normalized_input.adjustments,
        metrics=metrics,
        gates=gates,
        valuation=valuation,
        decision=decision,
        business_quality=business_quality,
        evidence_index=normalized_input.evidence_index,
        flags=_unique(flags),
    )


def run_analyze_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    profile: RuleProfile | None = None,
    *,
    cyclical: bool | None = None,
    business_quality: BusinessQuality | None = None,
) -> CompanyAnalysis:
    """Named normalized-input entry point matching the other pipeline stages."""

    return run_analyze(
        normalized_input,
        profile,
        cyclical=cyclical,
        business_quality=business_quality,
    )
