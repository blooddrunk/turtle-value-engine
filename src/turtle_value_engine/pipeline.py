"""Pipeline entry points available in the first deterministic milestone."""

from collections.abc import Sequence

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
from turtle_value_engine.models import (
    BusinessQuality,
    BusinessQualityDimension,
    BusinessQualityInput,
    CDCInput,
    CDCResult,
    ConfidenceLevel,
    NetCashInput,
    NetCashResult,
    NormalizedCompanyInput,
    ThroughReturnInput,
    ThroughReturnResult,
    ValuationInput,
    ValuationResult,
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
    """Run the currently implemented deterministic CDC stage.

    Full ``CompanyAnalysis`` assembly and final decision orchestration remain
    future work. Keeping this entry point explicit prevents callers from
    mistaking a partial result for a complete investment decision.
    """

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
