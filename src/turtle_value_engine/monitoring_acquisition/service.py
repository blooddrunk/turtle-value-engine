"""Opt-in live event acquisition orchestration (Phase 6-B).

This service connects one explicitly authorized, bounded live source slice
to the frozen Phase 6-A monitoring boundary:

    committed WatchlistStateV1
      -> derive a bounded source/listing acquisition window
      -> explicit network acquisition through the frozen filing-discovery
         provider boundary (raw records land in the existing raw cache)
      -> deterministic filing -> MonitoringEventV1 mapping
      -> MonitoringEventBatchV1 (canonical, deduplicated, ordered)

Acquisition is a read-only transaction.  It never writes to a
``MonitoringWorkspace``, never approves anything and never advances a
committed cursor: cursors move only inside the atomically committed next
state of a Phase 6-A ``run_monitoring`` commit.  A failed fetch, truncated
page, normalization failure or batch-write failure therefore leaves every
committed artifact untouched.

Network discipline: ``network_allowed`` defaults to ``False`` and is checked
before the provider is constructed or called, so the deny path cannot touch
a transport even by accident.  Offline replay (``offline=True``) reads the
persisted raw cache record only and needs no network authorization at all.

Point-in-time discipline: an optional explicit ``as_of`` boundary filters
mapped events by ``available_at`` at acquisition time (future-unavailable
events are counted and excluded from the batch); without ``as_of`` no
filtering happens here and the Phase 6-A replay ``--as-of`` remains the
authoritative boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

from ..monitoring.canonical import to_utc_datetime
from ..monitoring.models import (
    MonitoringEventBatchV1,
    MonitoringEventV1,
    WatchlistStateV1,
)
from ..monitoring.service import build_event_batch
from ..providers.cache import CacheKey, ProviderFetchResult, RawResponseCache
from ..providers.errors import ProviderError
from ..providers.filings import (
    FilingDiscoveryQuery,
    FilingDiscoveryResult,
    FilingSource,
    OfficialFilingDiscoveryProvider,
    fetch_filing_discovery_with_cache,
    parse_filing_discovery_record,
)
from .mapping import FilingEventMapping, map_filing_record_to_event

MAX_WINDOW_DAYS = 366
MAX_LISTINGS_PER_ACQUISITION = 8
DEFAULT_LIMIT = 30


class AcquisitionError(ValueError):
    """Raised when an acquisition request is invalid or fails closed."""


class NetworkDeniedError(AcquisitionError):
    """Raised when a live acquisition is attempted without explicit allow."""


def derive_window_start_from_state(
    state: WatchlistStateV1, listing_id: str, source_id: str
) -> date | None:
    """Return the first publication date after a listing's committed cursor.

    ``available_at`` for date-only evidence is the end of the publication
    date, so re-acquiring the cursor date itself could only ever produce
    stale events; the derived window therefore starts on the next calendar
    day.  ``None`` means no cursor exists and the caller must supply an
    explicit start.
    """

    entry = state.entry_for(listing_id)
    if entry is None:
        raise AcquisitionError(
            f"listing {listing_id!r} is not present in the committed watchlist state"
        )
    cursor = entry.cursor_for(source_id)
    if cursor is None:
        return None
    return cursor.last_processed_available_at.astimezone(UTC).date() + timedelta(days=1)


@dataclass(frozen=True, slots=True)
class AcquisitionWindow:
    """Explicit, bounded publication-date window for one acquisition."""

    published_from: date
    published_to: date

    def __post_init__(self) -> None:
        if self.published_from > self.published_to:
            raise AcquisitionError(
                "acquisition window published_from must not be after published_to"
            )
        span = (self.published_to - self.published_from).days + 1
        if span > MAX_WINDOW_DAYS:
            raise AcquisitionError(
                f"acquisition window spans {span} days; the maximum is {MAX_WINDOW_DAYS}"
            )


class ListingAcquisitionSummary(BaseModel):
    """Non-secret per-listing provenance summary (CLI output only)."""

    model_config = ConfigDict(extra="forbid")

    listing_id: StrictStr = Field(min_length=1)
    source_id: StrictStr = Field(min_length=1)
    retrieval_mode: StrictStr = Field(min_length=1)
    raw_cache_digest: StrictStr = Field(min_length=1)
    source_record_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    deferred_future_count: int = Field(ge=0)
    mappings: list[FilingEventMapping] = Field(default_factory=list)


class EventAcquisitionResult(BaseModel):
    """Typed, non-persisted acquisition summary (stdout/output only).

    The canonical batch is the only artifact intended for later Phase 6-A
    replay; this summary carries bounded non-secret diagnostics only.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: StrictStr = Field(min_length=1)
    adapter_version: StrictStr = Field(min_length=1)
    network_allowed: bool
    offline_replay: bool
    published_from: date
    published_to: date
    limit: int = Field(ge=1)
    as_of: datetime | None = None
    listings: list[ListingAcquisitionSummary] = Field(default_factory=list)
    batch_id: StrictStr = Field(min_length=1)
    event_count: int = Field(ge=0)

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime | None) -> datetime | None:
        return None if value is None else to_utc_datetime(value)


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    """Service return value: typed summary plus the canonical batch."""

    summary: EventAcquisitionResult
    batch: MonitoringEventBatchV1

    @property
    def batch_id(self) -> str:
        return self.batch.batch_id


def _validate_listing_scope(listings: Sequence[str]) -> list[str]:
    if not listings:
        raise AcquisitionError("at least one listing is required")
    unique: list[str] = []
    for listing_id in listings:
        if not isinstance(listing_id, str) or not listing_id.strip():
            raise AcquisitionError("listing ids must be non-empty strings")
        if listing_id in unique:
            raise AcquisitionError(
                f"duplicate listing in acquisition scope: {listing_id}"
            )
        unique.append(listing_id)
    if len(unique) > MAX_LISTINGS_PER_ACQUISITION:
        raise AcquisitionError(
            f"at most {MAX_LISTINGS_PER_ACQUISITION} listings may be acquired per "
            f"invocation; got {len(unique)}"
        )
    return unique


def _filing_source_for(source_id: str) -> FilingSource:
    try:
        return FilingSource(source_id)
    except (TypeError, ValueError) as exc:
        raise AcquisitionError(
            f"unsupported acquisition source {source_id!r}: the first live slice "
            "supports only the CNINFO official filing source"
        ) from exc


def acquire_filing_events(
    *,
    provider: OfficialFilingDiscoveryProvider,
    listings: Sequence[str],
    window: AcquisitionWindow,
    source_id: str,
    adapter_version: str,
    cache: RawResponseCache,
    limit: int = DEFAULT_LIMIT,
    as_of: datetime | str | None = None,
    network_allowed: bool = False,
    offline: bool = False,
) -> AcquisitionOutcome:
    """Acquire and canonically map one bounded filing-discovery slice.

    ``network_allowed=True`` (live) or ``offline=True`` (cache replay) must
    be requested explicitly; the default denies both and never touches the
    provider.  Live mode writes each raw response through the existing cache
    boundary; offline mode replays the persisted raw record and performs no
    provider call at all.
    """

    if offline and network_allowed:
        raise AcquisitionError(
            "offline replay and live network acquisition are mutually exclusive"
        )
    if not offline and not network_allowed:
        raise NetworkDeniedError(
            "network is denied; pass --network=allow for an explicit live "
            "acquisition or --from-cache for offline replay"
        )
    scoped = _validate_listing_scope(listings)
    if not source_id.strip():
        raise AcquisitionError("source_id must be a non-empty string")
    if not adapter_version.strip():
        raise AcquisitionError("adapter_version must be a non-empty string")
    if limit < 1:
        raise AcquisitionError("limit must be a positive integer")
    boundary = None if as_of is None else to_utc_datetime(as_of)
    filing_source = _filing_source_for(source_id)

    events: list[MonitoringEventV1] = []
    summaries: list[ListingAcquisitionSummary] = []
    for listing_id in scoped:
        try:
            query = FilingDiscoveryQuery(
                listing_id=listing_id,
                source=filing_source,
                published_from=window.published_from,
                published_to=window.published_to,
                limit=limit,
            )
        except ValidationError as exc:
            raise AcquisitionError(
                f"invalid acquisition scope for listing {listing_id!r} under source "
                f"{source_id}: {exc}"
            ) from exc
        try:
            fetch: ProviderFetchResult = fetch_filing_discovery_with_cache(
                provider, query.to_provider_request(), cache, offline=offline
            )
        except ProviderError as exc:
            raise AcquisitionError(
                f"acquisition failed for {source_id}/{listing_id}: {exc}"
            ) from exc
        record = fetch.record
        try:
            result: FilingDiscoveryResult = parse_filing_discovery_record(record)
        except ProviderError as exc:
            raise AcquisitionError(
                f"acquired raw record failed validation for {listing_id}: {exc}"
            ) from exc
        key = CacheKey.from_request(record.provider, record.request)
        listing_events: list[MonitoringEventV1] = []
        mappings: list[FilingEventMapping] = []
        deferred = 0
        for filing in result.filings:
            event, mapping = map_filing_record_to_event(filing, source_id=source_id)
            if boundary is not None and event.available_at > boundary:
                deferred += 1
                continue
            listing_events.append(event)
            mappings.append(mapping)
        events.extend(listing_events)
        summaries.append(
            ListingAcquisitionSummary(
                listing_id=listing_id,
                source_id=source_id,
                retrieval_mode=fetch.mode.value,
                raw_cache_digest=key.digest,
                source_record_count=len(result.filings),
                event_count=len(listing_events),
                deferred_future_count=deferred,
                mappings=mappings,
            )
        )

    batch = batch_for_events(events)
    summary = EventAcquisitionResult(
        source_id=source_id,
        adapter_version=adapter_version,
        network_allowed=network_allowed,
        offline_replay=offline,
        published_from=window.published_from,
        published_to=window.published_to,
        limit=limit,
        as_of=boundary,
        listings=summaries,
        batch_id=batch.batch_id,
        event_count=len(batch.events),
    )
    return AcquisitionOutcome(summary=summary, batch=batch)


def batch_for_events(events: Sequence[MonitoringEventV1]) -> MonitoringEventBatchV1:
    """Build the canonical batch from already-mapped events (public helper)."""

    return build_event_batch([event.model_dump(mode="json") for event in events])


__all__ = [
    "AcquisitionError",
    "AcquisitionOutcome",
    "AcquisitionWindow",
    "DEFAULT_LIMIT",
    "EventAcquisitionResult",
    "ListingAcquisitionSummary",
    "MAX_LISTINGS_PER_ACQUISITION",
    "MAX_WINDOW_DAYS",
    "NetworkDeniedError",
    "acquire_filing_events",
    "batch_for_events",
    "derive_window_start_from_state",
]
