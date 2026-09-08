"""Small, deterministic helpers for projecting normalized facts.

The normalized-input contract intentionally stores facts in one flat list.
Calculation modules use this read-only index so a field/period collision is
never resolved by whichever provider happened to appear last.  Adjustments
are not applied here: accepted adjustments must already be represented by an
explicit normalized fact, while proposed adjustments remain review metadata.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from turtle_value_engine.models import Fact


class FactLookupError(ValueError):
    """Raised when normalized facts cannot be projected unambiguously."""


def period_sort_key(period: str) -> tuple[int, int | str, str]:
    """Sort fiscal labels chronologically when they contain a calendar year."""

    match = re.search(r"(?:19|20)\d{2}", period)
    if match:
        return (0, int(match.group()), period)
    return (1, period, period)


@dataclass(frozen=True)
class FactReference:
    """The value and provenance needed by a calculation boundary."""

    field: str
    period: str
    value: object
    fact_id: str
    evidence_ids: tuple[str, ...]
    confidence: float


class FactBook:
    """Read-only index over a normalized fact collection."""

    def __init__(self, facts: Sequence[Fact]) -> None:
        indexed: dict[tuple[str, str], FactReference] = {}
        for fact in facts:
            key = (fact.field, fact.period)
            if key in indexed:
                raise FactLookupError(
                    f"duplicate normalized fact for field={fact.field!r}, period={fact.period!r}"
                )
            indexed[key] = FactReference(
                field=fact.field,
                period=fact.period,
                value=fact.value,
                fact_id=fact.id,
                evidence_ids=tuple(fact.source_evidence_ids),
                confidence=fact.confidence,
            )
        self._indexed = indexed

    def get(self, field: str, period: str) -> FactReference | None:
        """Return one fact reference, or ``None`` when the fact is absent."""

        return self._indexed.get((field, period))

    def value(self, field: str, period: str) -> object | None:
        """Return a fact value while preserving ``None`` as missing."""

        reference = self.get(field, period)
        return None if reference is None else reference.value

    def evidence_ids(self, fields: Iterable[str], period: str) -> list[str]:
        """Return unique evidence IDs for the selected fields in one period."""

        ids: list[str] = []
        for field in fields:
            reference = self.get(field, period)
            if reference is not None:
                ids.extend(reference.evidence_ids)
        return list(dict.fromkeys(ids))

    def periods(self, fields: Iterable[str] | None = None) -> list[str]:
        """Return deterministic periods containing at least one selected field."""

        selected = None if fields is None else set(fields)
        periods = {
            period for (field, period) in self._indexed if selected is None or field in selected
        }
        return sorted(periods, key=period_sort_key)

    def as_of_period(self, as_of: date | str) -> str:
        """Resolve the canonical ``AS_OF_YYYY-MM-DD`` period.

        A normalized payload produced by this repository uses the canonical
        label.  The fallback accepts a different stable ``AS_OF_`` label for
        hand-prepared inputs, but never guesses a fiscal-year fact instead.
        """

        expected = f"AS_OF_{as_of.isoformat() if isinstance(as_of, date) else as_of}"
        if any(period == expected for _, period in self._indexed):
            return expected
        candidates = sorted(
            {period for _, period in self._indexed if period.startswith("AS_OF_")},
            key=period_sort_key,
        )
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise FactLookupError("normalized input has no AS_OF fact period")
        raise FactLookupError(
            f"normalized input has no AS_OF period for {expected!r}; candidates: {candidates}"
        )


def numeric_value(reference: FactReference | None, *, field: str) -> float | None:
    """Read a numeric fact without coercing strings or booleans to zero."""

    if reference is None or reference.value is None:
        return None
    if isinstance(reference.value, bool) or not isinstance(reference.value, (int, float)):
        raise FactLookupError(f"normalized fact {field!r} must be numeric or null")
    return float(reference.value)


def boolean_value(reference: FactReference | None, *, field: str) -> bool | None:
    """Read a boolean fact without interpreting missing values as false."""

    if reference is None or reference.value is None:
        return None
    if not isinstance(reference.value, bool):
        raise FactLookupError(f"normalized fact {field!r} must be boolean or null")
    return reference.value


def enum_value(reference: FactReference | None, *, field: str) -> str | None:
    """Read an enum-like fact while retaining explicit missingness."""

    if reference is None or reference.value is None:
        return None
    if not isinstance(reference.value, str):
        raise FactLookupError(f"normalized fact {field!r} must be a string or null")
    return reference.value
