"""Offline loader for the frozen normalized-input JSON contract."""

from pathlib import Path

from pydantic import ValidationError

from turtle_value_engine.models import NormalizedCompanyInput


class NormalizedInputLoadError(ValueError):
    """Raised when a normalized-input document cannot be parsed safely."""


def parse_normalized_input(payload: str | bytes) -> NormalizedCompanyInput:
    """Parse one JSON document without calculating or filling any values."""

    try:
        return NormalizedCompanyInput.model_validate_json(payload)
    except ValidationError as exc:
        raise NormalizedInputLoadError(f"invalid normalized input: {exc}") from exc


def load_normalized_input(path: str | Path) -> NormalizedCompanyInput:
    """Load and strictly validate a local normalized-input JSON file.

    The loader is intentionally filesystem-only.  It does not resolve URLs,
    call providers, apply adjustments, calculate metrics or replace missing
    facts with zeroes.
    """

    input_path = Path(path)
    try:
        payload = input_path.read_bytes()
    except OSError as exc:
        raise NormalizedInputLoadError(f"cannot read normalized input {input_path}: {exc}") from exc
    return parse_normalized_input(payload)


__all__ = [
    "NormalizedInputLoadError",
    "load_normalized_input",
    "parse_normalized_input",
]
