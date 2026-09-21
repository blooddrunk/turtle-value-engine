"""Opt-in live monitoring-event acquisition boundary (Phase 6-B).

This package bridges the frozen filing-discovery provider boundary
(``turtle_value_engine.providers.filings``) to the frozen Phase 6-A
monitoring contracts (``turtle_value_engine.monitoring``).  It lives outside
``monitoring`` on purpose: the Phase 6-A monitoring package stays importable
without any provider transport, and its frozen no-engine-import test remains
untouched.

Responsibilities:

- provider-neutral, network-gated acquisition orchestration
  (``acquire_filing_events``) with deny-by-default network policy;
- deterministic, fail-closed filing -> event classification and the
  conservative date-to-availability policy (``mapping``);
- the CNINFO live source client lives in
  ``turtle_value_engine.providers.cninfo_disclosure`` next to the frozen
  discovery contract it implements.

The package performs no research, no CompanyAnalysis, no adjustment
approval, no scheduling and never advances a committed monitoring cursor.
"""

from .mapping import (
    FILING_EVENT_CLASSIFICATION,
    FilingEventMapping,
    classification_rule_for,
    conservative_available_at,
    map_filing_record_to_event,
)
from .service import (
    DEFAULT_LIMIT,
    MAX_LISTINGS_PER_ACQUISITION,
    MAX_WINDOW_DAYS,
    AcquisitionError,
    AcquisitionOutcome,
    AcquisitionWindow,
    EventAcquisitionResult,
    ListingAcquisitionSummary,
    NetworkDeniedError,
    acquire_filing_events,
    batch_for_events,
    derive_window_start_from_state,
)

__all__ = [
    "AcquisitionError",
    "AcquisitionOutcome",
    "AcquisitionWindow",
    "DEFAULT_LIMIT",
    "EventAcquisitionResult",
    "FILING_EVENT_CLASSIFICATION",
    "FilingEventMapping",
    "ListingAcquisitionSummary",
    "MAX_LISTINGS_PER_ACQUISITION",
    "MAX_WINDOW_DAYS",
    "NetworkDeniedError",
    "acquire_filing_events",
    "batch_for_events",
    "classification_rule_for",
    "conservative_available_at",
    "derive_window_start_from_state",
    "map_filing_record_to_event",
]
