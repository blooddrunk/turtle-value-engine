"""Pipeline entry points available in the first deterministic milestone."""

from turtle_value_engine.calculations import (
    build_cdc_input_from_normalized_input,
    calculate_cdc,
)
from turtle_value_engine.config import RuleProfile, load_profile
from turtle_value_engine.models import CDCInput, CDCResult, NormalizedCompanyInput


def run_cdc(inputs: CDCInput, profile: RuleProfile | None = None) -> CDCResult:
    """Run the currently implemented deterministic CDC stage.

    The full ``CompanyAnalysis`` pipeline will be added after net-cash,
    through-return, gates and valuation are implemented.  Keeping this small
    entry point explicit prevents callers from mistaking a partial result for
    a complete investment decision.
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
