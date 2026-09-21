"""Deterministic official-filing to monitoring-event mapping (Phase 6-B).

This is the auditable bridge between the frozen Phase 3.84 filing-discovery
records and the frozen Phase 6-A ``MonitoringEventV1`` contract.  The mapping
is a pure function of one ``FilingRecord``: no network, no clock, no title
parsing and no guessed classification.

Classification policy (fail closed)
-----------------------------------

A filing may receive a typed canonical event only when the source's own
document-class metadata matches a frozen, probe-verified rule.  For CNINFO
the class evidence is the last ``announcementType`` taxonomy code:

=============  =============================  ==========================================
Leaf code      Verified meaning               Canonical event type
=============  =============================  ==========================================
``010301``     annual report                  ``ANNUAL_REPORT``
``010303``     interim (half-year) report     ``INTERIM_REPORT``
anything else  not verified by live evidence  ``INFORMATIONAL_DISCLOSURE``
=============  =============================  ==========================================

The two codes above were verified against real CNINFO responses for SH and
SZ listings on 2026-09-21 (annual: ``600519``; interim: ``600519`` and
``000858``; see ``docs/status/phase-6-b-2026-09-21.md``).  Quarterly-report
codes (``010305``/``010307``) intentionally stay informational: the frozen
Phase 6-A catalog has no quarterly type, and inventing one or coercing it
into a higher-severity type would be a guess.  High-impact categories such
as profit warnings, dividends, buybacks or litigation deliberately map to
``INFORMATIONAL_DISCLOSURE`` until a separate verified rule exists.

Date-to-availability policy (conservative, deterministic)
---------------------------------------------------------

``FilingRecord`` carries only ``published_date``.  A calendar date cannot
establish an intra-day instant, so the adapter never fabricates one:

- ``published_at`` stays ``None`` (the source provides no reliable time of
  day; CNINFO stamps scheduled disclosures at Beijing midnight, which is
  indistinguishable from date-only normalization);
- ``available_at`` becomes the *last microsecond of the publication date in
  the source's official disclosure timezone* (CNINFO discloses on the
  Beijing calendar, a fixed UTC+08:00 offset with no DST).  This is the
  latest instant that is guaranteed to be at or after the true publication
  instant, so point-in-time filtering can never treat a disclosure as
  available before it actually was, and no local fetch clock is involved.

Event identity is derived only from source identity (never retrieval time
or row order) via the existing ``deterministic_id`` helper, so replaying
the same raw source record reproduces byte-identical events.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..monitoring.models import CanonicalEventType, MonitoringEventV1
from ..providers.filings import FilingMarket, FilingRecord, FilingSource
from ..providers.normalization import deterministic_id

#: Frozen, probe-verified document-class rules (source, document_type) -> event.
FILING_EVENT_CLASSIFICATION: dict[tuple[FilingSource, str], CanonicalEventType] = {
    (FilingSource.CNINFO, "010301"): CanonicalEventType.ANNUAL_REPORT,
    (FilingSource.CNINFO, "010303"): CanonicalEventType.INTERIM_REPORT,
}

#: A/H official disclosure calendars both use a fixed UTC+08:00 offset.
_AH_DISCLOSURE_TZ = timezone(timedelta(hours=8))

_EVENT_TITLE_MAX_LENGTH = 300
_MONITORING_EVENT_ID_NAMESPACE = "monitoring-event"


class FilingEventMapping(BaseModel):
    """Deterministic mapping outcome for one filing (typed, for audits)."""

    model_config = ConfigDict(extra="forbid")

    filing_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    source_id: StrictStr = Field(min_length=1)
    document_type: StrictStr = Field(min_length=1)
    classification_rule: StrictStr = Field(min_length=1)
    event_type: CanonicalEventType
    published_date: date
    available_at: datetime
    classification_basis: StrictStr = Field(min_length=1)


def conservative_available_at(published_date: date, market: FilingMarket) -> datetime:
    """Return the last instant of the publication date in the disclosure TZ.

    A/H official disclosure calendars (Beijing / Hong Kong) both use a fixed
    UTC+08:00 offset with no DST, so the conversion needs no timezone
    database and stays deterministic.  The result is the latest instant that
    is guaranteed to be at or after the true publication instant.
    """

    end_of_day = datetime.combine(
        published_date, time(23, 59, 59, 999999, tzinfo=_AH_DISCLOSURE_TZ)
    )
    return end_of_day.astimezone(UTC)


def classification_rule_for(source: FilingSource, document_type: str) -> str:
    """Return the frozen rule id that classifies one source document type."""

    key = (source, document_type)
    if key in FILING_EVENT_CLASSIFICATION:
        return f"{source.value}:{document_type}"
    return "unverified:informational"


def map_filing_record_to_event(
    filing: FilingRecord,
    *,
    source_id: str | None = None,
) -> tuple[MonitoringEventV1, FilingEventMapping]:
    """Map one validated filing record into one canonical monitoring event.

    Returns the event and the audit record documenting which frozen rule
    classified it and which availability policy applied.  Every unverified
    document class fails closed to ``INFORMATIONAL_DISCLOSURE``.
    """

    resolved_source_id = source_id if source_id is not None else filing.source.value
    if not resolved_source_id.strip():
        raise ValueError("source_id must be a non-empty string")
    rule = classification_rule_for(filing.source, filing.document_type)
    event_type = FILING_EVENT_CLASSIFICATION.get(
        (filing.source, filing.document_type), CanonicalEventType.INFORMATIONAL_DISCLOSURE
    )
    event_id = deterministic_id(
        _MONITORING_EVENT_ID_NAMESPACE,
        resolved_source_id,
        filing.listing_id,
        filing.filing_id,
    )
    event = MonitoringEventV1.build(
        event_id=event_id,
        listing_id=filing.listing_id,
        event_type=event_type,
        source_id=resolved_source_id,
        source_event_id=filing.source_document_id,
        source_artifact_id=filing.filing_id,
        published_at=None,
        available_at=conservative_available_at(filing.published_date, filing.market),
        title=filing.title[:_EVENT_TITLE_MAX_LENGTH],
        summary=None,
    )
    mapping = FilingEventMapping(
        filing_id=filing.filing_id,
        listing_id=filing.listing_id,
        source_id=resolved_source_id,
        document_type=filing.document_type,
        classification_rule=rule,
        event_type=event_type,
        published_date=filing.published_date,
        available_at=event.available_at,
        classification_basis=(
            "source document-class metadata matched a frozen probe-verified rule"
            if rule != "unverified:informational"
            else "source document-class metadata matched no verified rule; "
            "fail-closed informational classification"
        ),
    )
    return event, mapping


__all__ = [
    "FILING_EVENT_CLASSIFICATION",
    "FilingEventMapping",
    "classification_rule_for",
    "conservative_available_at",
    "map_filing_record_to_event",
]
