"""Deterministic Phase 6-A monitoring planning (pure, offline, no I/O).

The service layer maps a validated watchlist, a canonical event batch, an
optional prior committed state and an explicit ``as_of`` boundary into a
``MonitoringRunV1``.  It is a pure function of its inputs: no filesystem, no
network, no provider transport, no analyst/model runtime and no investment
re-analysis.  State mutations implied by the run are only *planned* here;
they become current when the workspace atomically commits the run.

Documented processing rules
---------------------------

1. Events are processed in canonical order ``(available_at, source_id,
   event_id, listing_id)`` regardless of input order.
2. An event whose listing is absent from the watchlist is recorded with
   reason ``OUT_OF_WATCHLIST``; a disabled listing is recorded with reason
   ``LISTING_DISABLED``.  Both are reported, never silently applied.
3. An event whose ``event_id`` was already processed for the same listing is
   idempotent when its content hash matches and a hard conflict otherwise.
4. An event with ``available_at > as_of`` is deferred; deferred events never
   advance cursors and never trigger re-analysis.
5. A new event whose ``available_at`` is at or below its source/listing
   cursor high-water mark is a late (stale) arrival; it is recorded as
   ``STALE``, generates no re-analysis request and does not advance cursors.
6. New eligible events are grouped per listing; the request carries every
   event id and the highest orchestration severity.
7. Cursors advance only to the maximum ``available_at`` of events actually
   processed in the run, and only become visible through the committed
   ``next_state``.
8. When no new event is processed, ``next_state`` equals the prior state
   byte-for-byte (``last_committed_run_id`` included), so repeated replays
   converge instead of growing state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from .canonical import canonical_datetime_str, canonical_sha256, to_utc_datetime
from .models import (
    CanonicalEventType,
    DeferredEventRecordV1,
    EventCursorV1,
    EventImpactDecisionV1,
    ExcludedEventRecordV1,
    ExclusionReason,
    MonitoringEventBatchV1,
    MonitoringEventV1,
    MonitoringRunV1,
    ProcessedEventRecordV1,
    ReanalysisPlanV1,
    ReanalysisRequestV1,
    SkippedEventRecordV1,
    SkipReason,
    WatchlistEntryStateV1,
    WatchlistSpecV1,
    WatchlistStateV1,
)
from .policy import (
    EVENT_IMPACT_POLICY_ID,
    ImpactClass,
    combine_impacts,
    impact_for_event_type,
)


class MonitoringError(ValueError):
    """Base class for deterministic monitoring failures."""


class MonitoringConflictError(MonitoringError):
    """Raised when the same event identity carries conflicting content."""


def initial_watchlist_state(watchlist: WatchlistSpecV1) -> WatchlistStateV1:
    """Build the empty pre-run state for a watchlist (no invented facts)."""

    return WatchlistStateV1.build(
        watchlist_id=watchlist.watchlist_id,
        last_committed_run_id=None,
        entries=[
            WatchlistEntryStateV1(listing_id=entry.listing_id)
            for entry in sorted(watchlist.entries, key=lambda item: item.listing_id)
        ],
    )


def build_event(
    payload: Mapping[str, object],
) -> MonitoringEventV1:
    """Validate and canonically hash one raw event payload."""

    return MonitoringEventV1.build(**dict(payload))


def build_event_batch(
    payloads: Sequence[Mapping[str, object]],
) -> MonitoringEventBatchV1:
    """Validate raw event payloads into a canonical batch.

    Exact duplicate events (identical semantic content) collapse to one
    entry.  The same ``(listing_id, event_id)`` with different content is a
    hard conflict and fails closed before any state is touched.
    """

    events: list[MonitoringEventV1] = []
    seen: dict[tuple[str, str], MonitoringEventV1] = {}
    for payload in payloads:
        event = build_event(payload)
        key = (event.listing_id, event.event_id)
        existing = seen.get(key)
        if existing is None:
            seen[key] = event
            events.append(event)
            continue
        if existing.content_sha256 != event.content_sha256:
            raise MonitoringConflictError(
                "EVENT_CONFLICT: event_id "
                f"{event.event_id!r} for listing {event.listing_id!r} has "
                "conflicting content in the same batch "
                f"({existing.content_sha256[:12]}.. vs {event.content_sha256[:12]}..)"
            )
    return MonitoringEventBatchV1.build(events)


def _merged_state_entries(
    watchlist: WatchlistSpecV1, prior_state: WatchlistStateV1
) -> list[WatchlistEntryStateV1]:
    """Carry prior per-listing state onto the current watchlist entries.

    Entries removed from the watchlist are dropped; new entries start from an
    empty sub-state.  This is a documented rule, not an inference.
    """

    merged: list[WatchlistEntryStateV1] = []
    for entry in sorted(watchlist.entries, key=lambda item: item.listing_id):
        prior = prior_state.entry_for(entry.listing_id)
        merged.append(
            prior
            if prior is not None
            else WatchlistEntryStateV1(listing_id=entry.listing_id)
        )
    return merged


def run_monitoring(
    watchlist: WatchlistSpecV1,
    batch: MonitoringEventBatchV1,
    prior_state: WatchlistStateV1 | None,
    as_of: datetime | str,
    policy_id: str = EVENT_IMPACT_POLICY_ID,
) -> MonitoringRunV1:
    """Plan one deterministic monitoring run without mutating anything."""

    boundary = to_utc_datetime(as_of)
    if prior_state is None:
        prior_state = initial_watchlist_state(watchlist)
    if prior_state.watchlist_id != watchlist.watchlist_id:
        raise MonitoringError(
            "prior state belongs to watchlist "
            f"{prior_state.watchlist_id!r}, expected {watchlist.watchlist_id!r}"
        )

    entry_states = _merged_state_entries(watchlist, prior_state)
    state_by_listing = {entry.listing_id: entry for entry in entry_states}
    watch_by_listing = {entry.listing_id: entry for entry in watchlist.entries}

    decisions: list[EventImpactDecisionV1] = []
    deferred: list[DeferredEventRecordV1] = []
    skipped: list[SkippedEventRecordV1] = []
    excluded: list[ExcludedEventRecordV1] = []

    # Planned mutations applied to copies only after the whole batch validates.
    new_processed: dict[str, list[ProcessedEventRecordV1]] = {}
    cursor_updates: dict[str, dict[str, tuple[datetime, str]]] = {}

    for event in batch.events:
        watched = watch_by_listing.get(event.listing_id)
        if watched is None:
            excluded.append(
                ExcludedEventRecordV1(
                    event_id=event.event_id,
                    listing_id=event.listing_id,
                    event_type=event.event_type,
                    available_at=event.available_at,
                    reason=ExclusionReason.OUT_OF_WATCHLIST,
                )
            )
            continue
        if not watched.enabled:
            excluded.append(
                ExcludedEventRecordV1(
                    event_id=event.event_id,
                    listing_id=event.listing_id,
                    event_type=event.event_type,
                    available_at=event.available_at,
                    reason=ExclusionReason.LISTING_DISABLED,
                )
            )
            continue
        state_entry = state_by_listing[event.listing_id]
        prior_record = state_entry.processed_event(event.event_id)
        if prior_record is not None:
            if prior_record.content_sha256 != event.content_sha256:
                raise MonitoringConflictError(
                    "EVENT_CONFLICT: event_id "
                    f"{event.event_id!r} for listing {event.listing_id!r} was already "
                    "processed with different content "
                    f"({prior_record.content_sha256[:12]}.. vs "
                    f"{event.content_sha256[:12]}..)"
                )
            skipped.append(
                SkippedEventRecordV1(
                    event_id=event.event_id,
                    listing_id=event.listing_id,
                    event_type=event.event_type,
                    available_at=event.available_at,
                    reason=SkipReason.ALREADY_PROCESSED,
                )
            )
            continue
        if event.available_at > boundary:
            deferred.append(
                DeferredEventRecordV1(
                    event_id=event.event_id,
                    listing_id=event.listing_id,
                    event_type=event.event_type,
                    available_at=event.available_at,
                )
            )
            continue
        cursor = state_entry.cursor_for(event.source_id)
        if (
            cursor is not None
            and event.available_at <= cursor.last_processed_available_at
        ):
            skipped.append(
                SkippedEventRecordV1(
                    event_id=event.event_id,
                    listing_id=event.listing_id,
                    event_type=event.event_type,
                    available_at=event.available_at,
                    reason=SkipReason.STALE,
                )
            )
            continue

        impact = impact_for_event_type(str(event.event_type), policy_id=policy_id)
        decisions.append(
            EventImpactDecisionV1(
                event_id=event.event_id,
                listing_id=event.listing_id,
                event_type=event.event_type,
                available_at=event.available_at,
                impact=impact,
            )
        )
        new_processed.setdefault(event.listing_id, []).append(
            ProcessedEventRecordV1(
                event_id=event.event_id,
                event_type=event.event_type,
                available_at=event.available_at,
                content_sha256=event.content_sha256,
            )
        )
        updates = cursor_updates.setdefault(event.listing_id, {})
        current = updates.get(event.source_id)
        if current is None or event.available_at > current[0]:
            updates[event.source_id] = (event.available_at, event.event_id)

    decisions.sort(key=lambda decision: (decision.available_at, decision.event_id))
    deferred.sort(key=lambda record: (record.available_at, record.event_id))
    skipped.sort(key=lambda record: (record.available_at, record.event_id))
    excluded.sort(key=lambda record: (record.available_at, record.event_id))

    # The run identity depends only on logical inputs, so it is computable
    # before the plan/state payloads that reference it exist.
    run_id = canonical_sha256(
        {
            "domain": "tve-monitoring-run-v1",
            "watchlist_id": watchlist.watchlist_id,
            "watchlist_content_sha256": watchlist.content_sha256,
            "event_batch_id": batch.batch_id,
            "prior_state_id": prior_state.state_id,
            "as_of": canonical_datetime_str(boundary),
            "policy_id": policy_id,
        }
    )

    requests_by_listing: dict[str, ReanalysisRequestV1] = {}
    for listing_id, listing_decisions in _group_by_listing(decisions).items():
        requests_by_listing[listing_id] = ReanalysisRequestV1.build(
            watchlist_id=watchlist.watchlist_id,
            listing_id=listing_id,
            impact=combine_impacts([decision.impact for decision in listing_decisions]),
            event_ids=[decision.event_id for decision in listing_decisions],
            available_through=max(
                decision.available_at for decision in listing_decisions
            ),
        )
    plan = ReanalysisPlanV1.build(
        watchlist_id=watchlist.watchlist_id,
        run_id=run_id,
        requests=sorted(requests_by_listing.values(), key=lambda r: r.listing_id),
    )

    next_entries: list[WatchlistEntryStateV1] = []
    for entry in entry_states:
        added = new_processed.get(entry.listing_id, [])
        if not added:
            next_entries.append(entry)
            continue
        processed = sorted(
            [*entry.processed_events, *added],
            key=lambda record: (record.available_at, record.event_id),
        )
        cursors = {cursor.source_id: cursor for cursor in entry.cursors}
        for source_id, (available_at, event_id) in cursor_updates.get(
            entry.listing_id, {}
        ).items():
            cursors[source_id] = EventCursorV1(
                source_id=source_id,
                last_processed_available_at=available_at,
                last_event_id=event_id,
                advanced_by_run_id=run_id,
            )
        next_entries.append(
            WatchlistEntryStateV1(
                listing_id=entry.listing_id,
                last_analysis_id=entry.last_analysis_id,
                last_surface_id=entry.last_surface_id,
                last_analysis_as_of=entry.last_analysis_as_of,
                last_profile_id=entry.last_profile_id,
                last_engine_version=entry.last_engine_version,
                last_deterministic_result=entry.last_deterministic_result,
                last_filing_id=entry.last_filing_id,
                last_source_id=entry.last_source_id,
                cursors=sorted(cursors.values(), key=lambda cursor: cursor.source_id),
                processed_events=processed,
                open_questions=entry.open_questions,
            )
        )

    next_state = (
        WatchlistStateV1.build(
            watchlist_id=watchlist.watchlist_id,
            last_committed_run_id=run_id,
            entries=next_entries,
        )
        if new_processed
        else prior_state
    )

    return MonitoringRunV1.build(
        watchlist_id=watchlist.watchlist_id,
        watchlist_content_sha256=watchlist.content_sha256,
        event_batch_id=batch.batch_id,
        prior_state_id=prior_state.state_id,
        as_of=boundary,
        policy_id=policy_id,
        decisions=decisions,
        deferred=deferred,
        skipped=skipped,
        excluded=excluded,
        plan=plan,
        next_state=next_state,
    )


def _group_by_listing(
    decisions: list[EventImpactDecisionV1],
) -> dict[str, list[EventImpactDecisionV1]]:
    grouped: dict[str, list[EventImpactDecisionV1]] = {}
    for decision in decisions:
        grouped.setdefault(decision.listing_id, []).append(decision)
    return grouped


def event_type_catalog() -> list[str]:
    """Return the closed canonical event type catalog (for audits/tests)."""

    return [member.value for member in CanonicalEventType]


__all__ = [
    "EVENT_IMPACT_POLICY_ID",
    "ImpactClass",
    "MonitoringConflictError",
    "MonitoringError",
    "build_event",
    "build_event_batch",
    "event_type_catalog",
    "initial_watchlist_state",
    "run_monitoring",
]
