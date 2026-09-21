"""Typed Phase 6-A monitoring contracts (watchlist/events/state/plan/run).

All contracts are frozen, fail-closed pydantic models.  Artifacts that are
persisted or exchanged as JSON carry a canonical ``content_sha256`` over
their own payload (the hash field itself excluded), recomputed on every
validation, so truncation or tampering fails closed.  Derived identities
(``batch_id``, ``state_id``, ``plan_id``) equal their content hash, following
the ``ResearchSurfaceSnapshotV1`` convention.  ``run_id`` is derived from the
run's logical inputs so a replay of the same inputs against the same prior
state reproduces the same run identity and bytes.

``build()`` performs a coercion pass with the private validation context
``skip_derived_hash_validation`` so raw input values are structurally
validated (nested models, defaults, UTC normalization) before their derived
hashes exist, then revalidates the completed payload with every hash check
enforced.  Readers never pass that context, so persisted artifacts always
fail closed on identity mismatch.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .canonical import canonical_json_bytes, canonical_sha256, normalize_utc
from .policy import EVENT_IMPACT_POLICY_ID, ImpactClass

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_ZERO_HASH = "0" * 64
_WATCHLIST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
_SKIP_HASH_CONTEXT_KEY = "skip_derived_hash_validation"
_DERIVED_ID_FIELDS = frozenset(
    {
        "content_sha256",
        "batch_id",
        "state_id",
        "plan_id",
        "run_id",
        "request_id",
        "commit_id",
    }
)

FrozenContract = ConfigDict(extra="forbid", frozen=True)


def _hash_checks_enabled(info: ValidationInfo) -> bool:
    context = info.context
    return not (isinstance(context, dict) and context.get(_SKIP_HASH_CONTEXT_KEY))


def _normalized_datetime(value: datetime) -> datetime:
    return normalize_utc(value)


def _normalized_datetime_optional(value: datetime | None) -> datetime | None:
    return None if value is None else normalize_utc(value)


class CanonicalEventType(StrEnum):
    """Closed set of canonical monitoring event types."""

    ANNUAL_REPORT = "ANNUAL_REPORT"
    INTERIM_REPORT = "INTERIM_REPORT"
    EARNINGS_PREANNOUNCEMENT = "EARNINGS_PREANNOUNCEMENT"
    DIVIDEND_POLICY_CHANGE = "DIVIDEND_POLICY_CHANGE"
    DIVIDEND_DECLARATION = "DIVIDEND_DECLARATION"
    BUYBACK = "BUYBACK"
    SHARE_ISSUANCE = "SHARE_ISSUANCE"
    MAJOR_ACQUISITION = "MAJOR_ACQUISITION"
    MAJOR_DISPOSAL = "MAJOR_DISPOSAL"
    AUDIT_OPINION_CHANGE = "AUDIT_OPINION_CHANGE"
    REGULATORY_PENALTY = "REGULATORY_PENALTY"
    CONTROLLING_SHAREHOLDER_EVENT = "CONTROLLING_SHAREHOLDER_EVENT"
    MATERIAL_LITIGATION = "MATERIAL_LITIGATION"
    PROFIT_WARNING = "PROFIT_WARNING"
    TRADING_SUSPENSION = "TRADING_SUSPENSION"
    INFORMATIONAL_DISCLOSURE = "INFORMATIONAL_DISCLOSURE"


class SkipReason(StrEnum):
    """Documented reasons an in-watchlist event generates no new work."""

    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    STALE = "STALE"


class ExclusionReason(StrEnum):
    """Documented reasons an event is not applied to watchlist state."""

    OUT_OF_WATCHLIST = "OUT_OF_WATCHLIST"
    LISTING_DISABLED = "LISTING_DISABLED"


class _MonitoringContract(BaseModel):
    """Shared plumbing: canonical serialization and derived content hashes."""

    model_config = FrozenContract

    def canonical_payload(
        self,
        *,
        exclude: set[str] | None = None,
        include: set[str] | None = None,
    ) -> dict:
        return self.model_dump(
            mode="json", exclude=exclude, include=include, warnings=False
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())

    @classmethod
    def _coerced(cls, values: dict) -> Self:
        """Structurally validate raw values before derived hashes exist."""

        payload = dict(values)
        for name, field in cls.model_fields.items():
            if name in _DERIVED_ID_FIELDS and field.is_required() and name not in payload:
                payload[name] = _ZERO_HASH
        return cls.model_validate(payload, context={_SKIP_HASH_CONTEXT_KEY: True})

    @classmethod
    def _finalize(cls, coerced: Self, updates: dict[str, str]) -> Self:
        """Revalidate with derived identity fields filled in and checked."""

        exclude = {name for name in updates if name != "content_sha256"} | {
            "content_sha256"
        }
        payload = coerced.canonical_payload(exclude=exclude)
        return cls.model_validate(payload | updates)


class WatchlistEntryV1(_MonitoringContract):
    """One watched listing; no company facts are inferred here."""

    listing_id: StrictStr = Field(min_length=1, max_length=32)
    company_display_name: StrictStr | None = Field(default=None, max_length=200)
    enabled: StrictBool = True
    current_analysis_id: StrictStr | None = Field(default=None, min_length=1)
    current_surface_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    open_questions: list[StrictStr] = Field(default_factory=list)

    @field_validator("company_display_name", mode="before")
    @classmethod
    def _blank_name_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class WatchlistSpecV1(_MonitoringContract):
    """Validated watchlist specification with a canonical content hash."""

    contract: Literal["watchlist_spec_v1"] = "watchlist_spec_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    profile_id: StrictStr = Field(min_length=1)
    entries: list[WatchlistEntryV1] = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_watchlist(self, info: ValidationInfo) -> Self:
        listing_ids = [entry.listing_id for entry in self.entries]
        duplicates = sorted({lid for lid in listing_ids if listing_ids.count(lid) > 1})
        if duplicates:
            raise ValueError(f"duplicate watchlist listing_id: {', '.join(duplicates)}")
        if _hash_checks_enabled(info):
            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError(
                    "watchlist content_sha256 does not match canonical content"
                )
        return self

    @classmethod
    def build(cls, **values: object) -> WatchlistSpecV1:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})


class MonitoringEventV1(_MonitoringContract):
    """One canonical monitoring event with auditable source provenance."""

    contract: Literal["monitoring_event_v1"] = "monitoring_event_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: StrictStr = Field(min_length=1, max_length=200)
    listing_id: StrictStr = Field(min_length=1, max_length=32)
    event_type: CanonicalEventType
    source_id: StrictStr = Field(min_length=1, max_length=100)
    source_event_id: StrictStr | None = Field(default=None, min_length=1)
    source_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    published_at: datetime | None = None
    available_at: datetime
    title: StrictStr | None = Field(default=None, max_length=300)
    summary: StrictStr | None = Field(default=None, max_length=2000)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_published_at = field_validator("published_at")(
        _normalized_datetime_optional
    )
    _normalize_available_at = field_validator("available_at")(_normalized_datetime)

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _blank_text_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_event(self, info: ValidationInfo) -> Self:
        if self.source_event_id is None and self.source_artifact_id is None:
            raise ValueError(
                "monitoring event requires an auditable source reference: "
                "source_event_id or source_artifact_id"
            )
        if _hash_checks_enabled(info):
            expected = canonical_sha256(
                self.canonical_payload(exclude={"content_sha256"})
            )
            if self.content_sha256 != expected:
                raise ValueError(
                    f"monitoring event {self.event_id!r} content_sha256 does not "
                    "match canonical content"
                )
        return self

    @classmethod
    def build(cls, **values: object) -> MonitoringEventV1:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(payload | {"content_sha256": canonical_sha256(payload)})

    def canonical_sort_key(self) -> tuple[datetime, str, str, str]:
        """Documented stable ordering key for deterministic replay.

        Events are ordered by ``(available_at, source_id, event_id,
        listing_id)``.  ``(listing_id, event_id)`` is unique within a
        canonical batch, so the key totally orders every batch.
        """

        return (self.available_at, self.source_id, self.event_id, self.listing_id)


class MonitoringEventBatchV1(_MonitoringContract):
    """Canonical, deduplicated, deterministically ordered event batch."""

    contract: Literal["monitoring_event_batch_v1"] = "monitoring_event_batch_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    events: list[MonitoringEventV1] = Field(default_factory=list)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_batch(self, info: ValidationInfo) -> Self:
        keys = [event.canonical_sort_key() for event in self.events]
        if keys != sorted(keys):
            raise ValueError("event batch must be in canonical order")
        scopes: set[str] = set()
        for event in self.events:
            scope = f"{event.listing_id}:{event.event_id}"
            if scope in scopes:
                raise ValueError(f"event batch contains duplicate event scope: {scope}")
            scopes.add(scope)
        if _hash_checks_enabled(info):
            expected = canonical_sha256(
                self.canonical_payload(exclude={"batch_id", "content_sha256"})
            )
            if self.batch_id != expected or self.content_sha256 != expected:
                raise ValueError(
                    "event batch identity does not match canonical content"
                )
        return self

    @classmethod
    def build(cls, events: list[MonitoringEventV1]) -> MonitoringEventBatchV1:
        coerced = cls._coerced(
            {"events": sorted(events, key=MonitoringEventV1.canonical_sort_key)}
        )
        payload = coerced.canonical_payload(exclude={"batch_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(
            payload | {"batch_id": digest, "content_sha256": digest}
        )


class EventCursorV1(_MonitoringContract):
    """Source/listing-scoped high-water mark over processed events."""

    source_id: StrictStr = Field(min_length=1, max_length=100)
    last_processed_available_at: datetime
    last_event_id: StrictStr = Field(min_length=1)
    advanced_by_run_id: StrictStr = Field(min_length=1)

    _normalize_last_processed = field_validator("last_processed_available_at")(
        _normalized_datetime
    )


class ProcessedEventRecordV1(_MonitoringContract):
    """Retained processed-event identity used for duplicate/conflict checks."""

    event_id: StrictStr = Field(min_length=1)
    event_type: CanonicalEventType
    available_at: datetime
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_available_at = field_validator("available_at")(_normalized_datetime)


class WatchlistEntryStateV1(_MonitoringContract):
    """Per-listing monitoring state; absent facts stay explicitly absent."""

    listing_id: StrictStr = Field(min_length=1, max_length=32)
    last_analysis_id: StrictStr | None = Field(default=None, min_length=1)
    last_surface_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    last_analysis_as_of: date | None = None
    last_profile_id: StrictStr | None = Field(default=None, min_length=1)
    last_engine_version: StrictStr | None = Field(default=None, min_length=1)
    last_deterministic_result: StrictStr | None = Field(default=None, min_length=1)
    last_filing_id: StrictStr | None = Field(default=None, min_length=1)
    last_source_id: StrictStr | None = Field(default=None, min_length=1)
    cursors: list[EventCursorV1] = Field(default_factory=list)
    processed_events: list[ProcessedEventRecordV1] = Field(default_factory=list)
    open_questions: list[StrictStr] = Field(default_factory=list)

    def cursor_for(self, source_id: str) -> EventCursorV1 | None:
        for cursor in self.cursors:
            if cursor.source_id == source_id:
                return cursor
        return None

    def processed_event(self, event_id: str) -> ProcessedEventRecordV1 | None:
        for record in self.processed_events:
            if record.event_id == event_id:
                return record
        return None


class WatchlistStateV1(_MonitoringContract):
    """Committed watchlist monitoring state with a canonical identity."""

    contract: Literal["watchlist_state_v1"] = "watchlist_state_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    last_committed_run_id: StrictStr | None = Field(default=None, min_length=1)
    entries: list[WatchlistEntryStateV1] = Field(min_length=1)
    state_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_state(self, info: ValidationInfo) -> Self:
        listing_ids = [entry.listing_id for entry in self.entries]
        if listing_ids != sorted(listing_ids):
            raise ValueError("watchlist state entries must be sorted by listing_id")
        if len(set(listing_ids)) != len(listing_ids):
            raise ValueError("watchlist state entries contain duplicate listing_id")
        for entry in self.entries:
            sources = [cursor.source_id for cursor in entry.cursors]
            if sources != sorted(sources) or len(set(sources)) != len(sources):
                raise ValueError(
                    f"watchlist state cursors for {entry.listing_id} must be sorted "
                    "and source-unique"
                )
            records = [
                (record.available_at, record.event_id)
                for record in entry.processed_events
            ]
            if records != sorted(records):
                raise ValueError(
                    f"processed events for {entry.listing_id} must be canonically sorted"
                )
            event_ids = [record.event_id for record in entry.processed_events]
            if len(set(event_ids)) != len(event_ids):
                raise ValueError(
                    f"processed events for {entry.listing_id} contain duplicate event_id"
                )
        if _hash_checks_enabled(info):
            expected = canonical_sha256(
                self.canonical_payload(exclude={"state_id", "content_sha256"})
            )
            if self.state_id != expected or self.content_sha256 != expected:
                raise ValueError(
                    "watchlist state identity does not match canonical content"
                )
        return self

    @classmethod
    def build(cls, **values: object) -> WatchlistStateV1:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"state_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(
            payload | {"state_id": digest, "content_sha256": digest}
        )

    def entry_for(self, listing_id: str) -> WatchlistEntryStateV1 | None:
        for entry in self.entries:
            if entry.listing_id == listing_id:
                return entry
        return None


class EventImpactDecisionV1(_MonitoringContract):
    """Policy decision for one new point-in-time-eligible event."""

    event_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    event_type: CanonicalEventType
    available_at: datetime
    impact: ImpactClass
    policy_id: Literal["event-impact-v1"] = EVENT_IMPACT_POLICY_ID

    _normalize_available_at = field_validator("available_at")(_normalized_datetime)


class DeferredEventRecordV1(_MonitoringContract):
    """Future event withheld until its availability passes the as_of boundary."""

    event_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    event_type: CanonicalEventType
    available_at: datetime

    _normalize_available_at = field_validator("available_at")(_normalized_datetime)


class SkippedEventRecordV1(_MonitoringContract):
    """In-watchlist event that generates no new work, with the documented rule."""

    event_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    event_type: CanonicalEventType
    available_at: datetime
    reason: SkipReason

    _normalize_available_at = field_validator("available_at")(_normalized_datetime)


class ExcludedEventRecordV1(_MonitoringContract):
    """Event not applied to state because its listing is not actively watched."""

    event_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    event_type: CanonicalEventType
    available_at: datetime
    reason: ExclusionReason

    _normalize_available_at = field_validator("available_at")(_normalized_datetime)


class ReanalysisRequestV1(_MonitoringContract):
    """Deterministic grouped follow-up request for one listing in one run."""

    request_id: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    listing_id: StrictStr = Field(min_length=1)
    impact: ImpactClass
    event_ids: list[StrictStr] = Field(min_length=1)
    available_through: datetime
    policy_id: Literal["event-impact-v1"] = EVENT_IMPACT_POLICY_ID

    _normalize_available_through = field_validator("available_through")(
        _normalized_datetime
    )

    def _request_identity_payload(self) -> dict:
        return {
            "domain": "tve-reanalysis-request-v1",
            "watchlist_id": self.watchlist_id,
            "listing_id": self.listing_id,
            "impact": str(self.impact),
            "event_ids": self.event_ids,
        }

    @model_validator(mode="after")
    def _validate_request(self, info: ValidationInfo) -> Self:
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("reanalysis request contains duplicate event_ids")
        if _hash_checks_enabled(info):
            if self.request_id != canonical_sha256(self._request_identity_payload()):
                raise ValueError(
                    "reanalysis request_id does not match canonical content"
                )
        return self

    @classmethod
    def build(
        cls,
        *,
        watchlist_id: str,
        listing_id: str,
        impact: ImpactClass,
        event_ids: list[str],
        available_through: datetime,
    ) -> ReanalysisRequestV1:
        coerced = cls._coerced(
            {
                "watchlist_id": watchlist_id,
                "listing_id": listing_id,
                "impact": impact,
                "event_ids": list(event_ids),
                "available_through": available_through,
            }
        )
        return cls._finalize(
            coerced, {"request_id": canonical_sha256(coerced._request_identity_payload())}
        )


class ReanalysisPlanV1(_MonitoringContract):
    """Byte-stable grouping of re-analysis requests produced by one run."""

    contract: Literal["reanalysis_plan_v1"] = "reanalysis_plan_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    run_id: StrictStr = Field(pattern=_HASH_PATTERN)
    requests: list[ReanalysisRequestV1] = Field(default_factory=list)
    plan_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_plan(self, info: ValidationInfo) -> Self:
        listing_ids = [request.listing_id for request in self.requests]
        if listing_ids != sorted(listing_ids):
            raise ValueError("reanalysis plan requests must be sorted by listing_id")
        if len(set(listing_ids)) != len(listing_ids):
            raise ValueError("reanalysis plan contains duplicate listing requests")
        for request in self.requests:
            if request.watchlist_id != self.watchlist_id:
                raise ValueError("reanalysis request does not belong to this watchlist")
        if _hash_checks_enabled(info):
            expected = canonical_sha256(
                self.canonical_payload(exclude={"plan_id", "content_sha256"})
            )
            if self.plan_id != expected or self.content_sha256 != expected:
                raise ValueError(
                    "reanalysis plan identity does not match canonical content"
                )
        return self

    @classmethod
    def build(
        cls,
        *,
        watchlist_id: str,
        run_id: str,
        requests: list[ReanalysisRequestV1],
    ) -> ReanalysisPlanV1:
        coerced = cls._coerced(
            {
                "watchlist_id": watchlist_id,
                "run_id": run_id,
                "requests": sorted(requests, key=lambda request: request.listing_id),
            }
        )
        payload = coerced.canonical_payload(exclude={"plan_id", "content_sha256"})
        digest = canonical_sha256(payload)
        return cls.model_validate(
            payload | {"plan_id": digest, "content_sha256": digest}
        )


class MonitoringRunV1(_MonitoringContract):
    """One deterministic monitoring run over a watchlist and event batch.

    ``run_id`` is derived from the run's logical inputs (watchlist identity,
    event batch identity, prior state identity, ``as_of`` and policy id), not
    from the run payload, so planning is reproducible before any commit.  The
    run embeds the exact ``plan`` and ``next_state`` the workspace commits.
    """

    contract: Literal["monitoring_run_v1"] = "monitoring_run_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    watchlist_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    event_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    prior_state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    as_of: datetime
    policy_id: Literal["event-impact-v1"] = EVENT_IMPACT_POLICY_ID
    decisions: list[EventImpactDecisionV1] = Field(default_factory=list)
    deferred: list[DeferredEventRecordV1] = Field(default_factory=list)
    skipped: list[SkippedEventRecordV1] = Field(default_factory=list)
    excluded: list[ExcludedEventRecordV1] = Field(default_factory=list)
    plan: ReanalysisPlanV1
    next_state: WatchlistStateV1
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_as_of = field_validator("as_of")(_normalized_datetime)

    _RUN_IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "watchlist_id",
        "watchlist_content_sha256",
        "event_batch_id",
        "prior_state_id",
        "as_of",
        "policy_id",
    )

    def _run_identity_payload(self) -> dict:
        payload = self.canonical_payload(include=set(self._RUN_IDENTITY_FIELDS))
        return {"domain": "tve-monitoring-run-v1", **payload}

    @model_validator(mode="after")
    def _validate_run(self, info: ValidationInfo) -> Self:
        decision_keys = [
            (decision.available_at, decision.event_id) for decision in self.decisions
        ]
        if decision_keys != sorted(decision_keys):
            raise ValueError("monitoring run decisions must be canonically ordered")
        for records in (self.deferred, self.skipped, self.excluded):
            record_keys = [(record.available_at, record.event_id) for record in records]
            if record_keys != sorted(record_keys):
                raise ValueError(
                    "monitoring run event records must be canonically ordered"
                )
        if self.next_state.watchlist_id != self.watchlist_id:
            raise ValueError("monitoring run next_state belongs to another watchlist")
        if _hash_checks_enabled(info):
            if self.run_id != canonical_sha256(self._run_identity_payload()):
                raise ValueError("monitoring run_id does not match its logical inputs")
            if self.plan.run_id != self.run_id:
                raise ValueError("monitoring run plan does not reference this run")
            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError(
                    "monitoring run content_sha256 does not match canonical content"
                )
        return self

    @classmethod
    def build(cls, **values: object) -> MonitoringRunV1:
        coerced = cls._coerced(dict(values))
        run_id = canonical_sha256(coerced._run_identity_payload())
        return cls._finalize(
            coerced,
            {
                "run_id": run_id,
                "content_sha256": canonical_sha256(
                    coerced.canonical_payload(exclude={"content_sha256", "run_id"})
                    | {"run_id": run_id}
                ),
            },
        )


class MonitoringStatePointerV1(_MonitoringContract):
    """Atomic current-state pointer; it moves only after durable artifacts."""

    contract: Literal["monitoring_state_pointer_v1"] = "monitoring_state_pointer_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    state_id: StrictStr = Field(pattern=_HASH_PATTERN)
    run_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_pointer(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            expected = canonical_sha256(
                self.canonical_payload(exclude={"content_sha256"})
            )
            if self.content_sha256 != expected:
                raise ValueError("monitoring state pointer content_sha256 mismatch")
        return self

    @classmethod
    def build(cls, **values: object) -> MonitoringStatePointerV1:
        coerced = cls._coerced(dict(values))
        payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(
            payload | {"content_sha256": canonical_sha256(payload)}
        )


class MonitoringCommitProofV1(_MonitoringContract):
    """Explicit proof that one monitoring run passed the workspace commit boundary.

    A run JSON file is only an immutable candidate artifact.  This additive
    record is written after the run, watchlist, event batch and next-state
    artifacts are durable and before the current-state pointer is moved.  The
    executor validates every bound identity instead of treating a filename as
    evidence that a run was committed.
    """

    contract: Literal["monitoring_commit_proof_v1"] = "monitoring_commit_proof_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    watchlist_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    event_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    event_batch_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    run_id: StrictStr = Field(pattern=_HASH_PATTERN)
    run_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    state_id: StrictStr = Field(pattern=_HASH_PATTERN)
    state_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    commit_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "domain": "tve-monitoring-commit-proof-v1",
            "watchlist_id": self.watchlist_id,
            "watchlist_content_sha256": self.watchlist_content_sha256,
            "event_batch_id": self.event_batch_id,
            "event_batch_content_sha256": self.event_batch_content_sha256,
            "run_id": self.run_id,
            "run_content_sha256": self.run_content_sha256,
            "state_id": self.state_id,
            "state_content_sha256": self.state_content_sha256,
        }

    @model_validator(mode="after")
    def _validate_commit_proof(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            expected = canonical_sha256(self._identity_payload())
            if self.commit_id != expected or self.content_sha256 != expected:
                raise ValueError("monitoring commit proof identity does not match content")
        return self

    @classmethod
    def build(cls, **values: object) -> MonitoringCommitProofV1:
        coerced = cls._coerced(dict(values))
        identity = canonical_sha256(coerced._identity_payload())
        payload = coerced.canonical_payload(exclude={"commit_id", "content_sha256"})
        return cls.model_validate(payload | {"commit_id": identity, "content_sha256": identity})


class MonitoringStatusEntryV1(_MonitoringContract):
    """Read-only status projection for one watched listing."""

    listing_id: StrictStr = Field(min_length=1)
    last_analysis_id: StrictStr | None = None
    last_surface_id: StrictStr | None = None
    last_analysis_as_of: date | None = None
    last_profile_id: StrictStr | None = None
    last_deterministic_result: StrictStr | None = None
    last_filing_id: StrictStr | None = None
    cursors: list[EventCursorV1] = Field(default_factory=list)
    processed_event_count: int = Field(ge=0)
    open_questions: list[StrictStr] = Field(default_factory=list)


class MonitoringStatusV1(_MonitoringContract):
    """Read-only status projection returned by ``tve watch status``."""

    contract: Literal["monitoring_status_v1"] = "monitoring_status_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    watchlist_id: StrictStr = Field(pattern=_WATCHLIST_ID_PATTERN)
    availability: Literal["NOT_AVAILABLE", "AVAILABLE"]
    state_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    last_committed_run_id: StrictStr | None = None
    entries: list[MonitoringStatusEntryV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_status(self) -> Self:
        if self.availability == "NOT_AVAILABLE" and (
            self.state_id is not None
            or self.last_committed_run_id is not None
            or self.entries
        ):
            raise ValueError("unavailable monitoring status cannot contain state facts")
        if self.availability == "AVAILABLE" and self.state_id is None:
            raise ValueError("available monitoring status requires a state_id")
        return self


__all__ = [
    "CanonicalEventType",
    "EventCursorV1",
    "EventImpactDecisionV1",
    "ExcludedEventRecordV1",
    "ExclusionReason",
    "DeferredEventRecordV1",
    "MonitoringEventBatchV1",
    "MonitoringEventV1",
    "MonitoringCommitProofV1",
    "MonitoringRunV1",
    "MonitoringStatePointerV1",
    "MonitoringStatusEntryV1",
    "MonitoringStatusV1",
    "ProcessedEventRecordV1",
    "ReanalysisPlanV1",
    "ReanalysisRequestV1",
    "SkipReason",
    "SkippedEventRecordV1",
    "WatchlistEntryStateV1",
    "WatchlistEntryV1",
    "WatchlistSpecV1",
    "WatchlistStateV1",
]
