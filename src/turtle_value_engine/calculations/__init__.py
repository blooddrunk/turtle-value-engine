"""Deterministic calculation modules."""

from .cdc import (
    CDCCalculationError,
    build_cdc_input_from_facts,
    build_cdc_input_from_normalized_input,
    calculate_cdc,
    calculate_year_cdc,
)

__all__ = [
    "CDCCalculationError",
    "build_cdc_input_from_facts",
    "build_cdc_input_from_normalized_input",
    "calculate_cdc",
    "calculate_year_cdc",
]
