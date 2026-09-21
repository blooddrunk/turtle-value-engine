"""Hermetic canonical-JSON helpers for the monitoring core.

The monitoring package must not import the provider, research or analysis
layers (not even ``turtle_value_engine.providers.models``, whose package
``__init__`` imports the AKShare transport).  These helpers mirror the
canonical-JSON semantics used elsewhere in the repository so monitoring
artifact identities remain comparable, while keeping the module import graph
restricted to the standard library.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON data canonically for stable IDs and hashes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Return the lowercase hex SHA-256 of the canonical JSON encoding."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC.

    Naive datetimes are interpreted as UTC so point-in-time comparisons and
    canonical serialization stay deterministic regardless of host timezone.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_utc_datetime(value: datetime | str) -> datetime:
    """Parse and normalize a datetime from a raw value (ISO-8601 string ok)."""

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid ISO-8601 datetime: {value!r}") from exc
    if not isinstance(value, datetime):
        raise ValueError(f"expected a datetime or ISO-8601 string, got {type(value)!r}")
    return normalize_utc(value)


def canonical_datetime_str(value: datetime) -> str:
    """Serialize a UTC datetime the way pydantic ``mode="json"`` does.

    pydantic-core emits RFC 3339 with a ``Z`` suffix for UTC instants; raw
    ``datetime.isoformat()`` would emit ``+00:00`` and break identity
    round-trips between manually composed preimages and model dumps.
    """

    text = normalize_utc(value).isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


__all__ = [
    "canonical_datetime_str",
    "canonical_json_bytes",
    "canonical_sha256",
    "normalize_utc",
    "to_utc_datetime",
]
