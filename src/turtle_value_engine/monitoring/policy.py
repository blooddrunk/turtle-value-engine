"""Versioned monitoring-only event impact policy ``event-impact-v1``.

This policy is an *orchestration* rule: it decides how much follow-up work a
canonical monitoring event should trigger.  It is completely isolated from
``rules/strict-v1`` and never changes CDC, Net Cash, Through Return, hard
gate or valuation semantics.  Impact classes are not investment decisions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal

EVENT_IMPACT_POLICY_ID: Literal["event-impact-v1"] = "event-impact-v1"


class ImpactClass(StrEnum):
    """Deterministic follow-up severity for one event or listing group."""

    NO_REANALYSIS = "NO_REANALYSIS"
    PARTIAL_REANALYSIS = "PARTIAL_REANALYSIS"
    FULL_REANALYSIS = "FULL_REANALYSIS"
    URGENT_MANUAL_REVIEW = "URGENT_MANUAL_REVIEW"


class UnknownEventTypeError(ValueError):
    """Raised when an event type has no mapping in the active policy."""


def event_impact_mapping() -> Mapping[str, ImpactClass]:
    """Return the frozen ``event-impact-v1`` default mapping.

    The mapping is defined here, versioned with the policy id, and covers
    exactly the canonical event types accepted by ``MonitoringEventV1``.
    """

    return dict(_EVENT_IMPACT_V1)


_EVENT_IMPACT_V1: dict[str, ImpactClass] = {
    "INFORMATIONAL_DISCLOSURE": ImpactClass.NO_REANALYSIS,
    "INTERIM_REPORT": ImpactClass.PARTIAL_REANALYSIS,
    "EARNINGS_PREANNOUNCEMENT": ImpactClass.PARTIAL_REANALYSIS,
    "DIVIDEND_POLICY_CHANGE": ImpactClass.PARTIAL_REANALYSIS,
    "DIVIDEND_DECLARATION": ImpactClass.PARTIAL_REANALYSIS,
    "BUYBACK": ImpactClass.PARTIAL_REANALYSIS,
    "ANNUAL_REPORT": ImpactClass.FULL_REANALYSIS,
    "SHARE_ISSUANCE": ImpactClass.FULL_REANALYSIS,
    "MAJOR_ACQUISITION": ImpactClass.FULL_REANALYSIS,
    "MAJOR_DISPOSAL": ImpactClass.FULL_REANALYSIS,
    "AUDIT_OPINION_CHANGE": ImpactClass.URGENT_MANUAL_REVIEW,
    "REGULATORY_PENALTY": ImpactClass.URGENT_MANUAL_REVIEW,
    "CONTROLLING_SHAREHOLDER_EVENT": ImpactClass.URGENT_MANUAL_REVIEW,
    "MATERIAL_LITIGATION": ImpactClass.URGENT_MANUAL_REVIEW,
    "PROFIT_WARNING": ImpactClass.URGENT_MANUAL_REVIEW,
    "TRADING_SUSPENSION": ImpactClass.URGENT_MANUAL_REVIEW,
}

IMPACT_PRECEDENCE: tuple[ImpactClass, ...] = (
    ImpactClass.NO_REANALYSIS,
    ImpactClass.PARTIAL_REANALYSIS,
    ImpactClass.FULL_REANALYSIS,
    ImpactClass.URGENT_MANUAL_REVIEW,
)

_IMPACT_RANK = {impact: rank for rank, impact in enumerate(IMPACT_PRECEDENCE)}


def impact_for_event_type(event_type: str, policy_id: str = EVENT_IMPACT_POLICY_ID) -> ImpactClass:
    """Map one canonical event type to its impact class.

    Unknown types fail closed; they are never coerced to ``NO_REANALYSIS``.
    Unknown policy ids also fail closed because there is no versioned mapping
    to consult.
    """

    if policy_id != EVENT_IMPACT_POLICY_ID:
        raise UnknownEventTypeError(
            f"unknown event impact policy: {policy_id!r}; expected {EVENT_IMPACT_POLICY_ID!r}"
        )
    try:
        return _EVENT_IMPACT_V1[event_type]
    except KeyError:
        raise UnknownEventTypeError(
            f"event type {event_type!r} has no {EVENT_IMPACT_POLICY_ID} mapping; "
            "map it to a canonical event type in an upstream adapter first"
        ) from None


def combine_impacts(impacts: Sequence[ImpactClass]) -> ImpactClass:
    """Return the highest orchestration severity among the given impacts.

    Precedence (orchestration only, never an investment result):

    ``NO_REANALYSIS < PARTIAL_REANALYSIS < FULL_REANALYSIS < URGENT_MANUAL_REVIEW``
    """

    if not impacts:
        raise ValueError("combine_impacts requires at least one impact")
    unknown = [impact for impact in impacts if impact not in _IMPACT_RANK]
    if unknown:
        raise ValueError(f"unknown impact class(es): {unknown!r}")
    return max(impacts, key=lambda impact: _IMPACT_RANK[impact])


__all__ = [
    "EVENT_IMPACT_POLICY_ID",
    "IMPACT_PRECEDENCE",
    "ImpactClass",
    "UnknownEventTypeError",
    "combine_impacts",
    "event_impact_mapping",
    "impact_for_event_type",
]
