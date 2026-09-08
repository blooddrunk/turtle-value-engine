"""Deterministic core of the Turtle Value Engine."""

from .input_loader import (
    NormalizedInputLoadError,
    load_normalized_input,
    parse_normalized_input,
)

__version__ = "0.1.0"

__all__ = [
    "NormalizedInputLoadError",
    "__version__",
    "load_normalized_input",
    "parse_normalized_input",
]
