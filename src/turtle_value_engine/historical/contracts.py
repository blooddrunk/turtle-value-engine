"""Typed contracts for bounded, production-oriented historical replay.

These contracts sit beside the Phase 5 manifest rather than replacing it.  A
``HistoricalDatasetManifest`` describes where a frozen dataset came from and
how large artifacts are stored; the compiler projects verified rows into the
existing ``BacktestDatasetManifest`` consumed by the offline engine.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from turtle_value_engine.backtest.contracts import (
    AvailabilityStatus,
    DateTimeLike,
    Market,
    PriceBasis,
)
from turtle_value_engine.providers.models import canonical_json_bytes

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_MEDIA_TYPE_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+\-]+/[a-z0-9!#$&^_.+\-]+$")
HISTORICAL_CONTRACT_VERSION = "historical-v1"
HISTORICAL_SHARD_CONTRACT_VERSION = "historical-shard-v1"
HISTORICAL_ARCHIVE_CONTRACT_VERSION = "historical-research-archive-v1"


def _hash_model(model: BaseModel, *excluded: str) -> str:
    # Preserve hashes for older manifests when a new optional field was not
    # present in their JSON.  Explicitly persisted nulls remain part of the
    # identity, while an omitted additive field stays omitted.
    payload = model.model_dump(
        mode="json",
        exclude=set(excluded),
        exclude_unset=True,
        warnings=False,
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _finite(value: float | None, field_name: str) -> float | None:
    if value is not None and not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return value


def _unique(values: list[str], field_name: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def _preserve_date_only(value: object) -> object:
    """Keep a JSON date-only value from being coerced to a naive datetime."""

    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _safe_http_uri(value: str) -> str:
    """Normalize a persisted filing URI without retaining credentials/signatures."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("filing URI must be a non-empty string")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("filing URI must be an absolute HTTP(S) URI")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("filing URI must not contain userinfo")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower().replace("-", "_")
        if any(
            fragment in normalized
            for fragment in (
                "signature",
                "token",
                "secret",
                "credential",
                "access_key",
                "authorization",
            )
        ):
            raise ValueError("filing URI must not contain credential/signature query parameters")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, "", ""))


class HistoricalSourceKind(StrEnum):
    """Source categories required to make a historical claim auditable."""

    UNIVERSE_MEMBERSHIP = "UNIVERSE_MEMBERSHIP"
    LISTING_LIFECYCLE = "LISTING_LIFECYCLE"
    DELISTINGS = "DELISTINGS"
    PRICES = "PRICES"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    BENCHMARK = "BENCHMARK"
    FX = "FX"
    FILINGS = "FILINGS"
    RESEARCH_ARCHIVE = "RESEARCH_ARCHIVE"


class SourceAuthority(StrEnum):
    """Authority classification; a provider name alone is not authority."""

    OFFICIAL_EXCHANGE = "OFFICIAL_EXCHANGE"
    REGULATOR = "REGULATOR"
    ISSUER = "ISSUER"
    DOCUMENTED_PROVIDER = "DOCUMENTED_PROVIDER"
    ARCHIVE = "ARCHIVE"
    FIXTURE = "FIXTURE"
    UNKNOWN = "UNKNOWN"


class LicenseStatus(StrEnum):
    """Redistribution state carried with every persisted source descriptor."""

    OPEN_REDISTRIBUTABLE = "OPEN_REDISTRIBUTABLE"
    RESTRICTED_INTERNAL = "RESTRICTED_INTERNAL"
    UNKNOWN = "UNKNOWN"
    PROHIBITED = "PROHIBITED"


class CoverageClaim(StrEnum):
    """Evidence level declared for the target, never inferred from row count."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class CoverageEvidenceBasis(StrEnum):
    """Evidence basis required before a coverage claim can be trusted.

    A row count is meaningful for trading sessions, but an empty corporate
    action or filing result is not evidence that the source was complete.  The
    basis is additive so historical-v1 manifests without it remain readable.
    """

    TRADING_SESSIONS = "TRADING_SESSIONS"
    OBSERVATION_SESSIONS = "OBSERVATION_SESSIONS"
    MEMBERSHIP_INTERVALS = "MEMBERSHIP_INTERVALS"
    LIFECYCLE_INDEX = "LIFECYCLE_INDEX"
    EVENT_INDEX = "EVENT_INDEX"
    FILING_INDEX = "FILING_INDEX"
    ARCHIVE_BINDING = "ARCHIVE_BINDING"
    EXPLICIT_SOURCE_SCOPE = "EXPLICIT_SOURCE_SCOPE"


class HistoricalTerminalOutcome(StrEnum):
    """Terminal lifecycle outcome without pretending all outcomes have value."""

    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"
    ACQUIRED_CANCELLED = "ACQUIRED_CANCELLED"
    TRANSFERRED = "TRANSFERRED"
    PROLONGED_SUSPENSION = "PROLONGED_SUSPENSION"
    UNRESOLVED_TERMINAL = "UNRESOLVED_TERMINAL"
    UNKNOWN = "UNKNOWN"


class ShardFormat(StrEnum):
    JSONL = "JSONL"


class ShardArtifactKind(StrEnum):
    LISTING_LIFECYCLE = "LISTING_LIFECYCLE"
    TRADING_SESSION = "TRADING_SESSION"
    UNIVERSE_MEMBERSHIP = "UNIVERSE_MEMBERSHIP"
    AVAILABILITY = "AVAILABILITY"
    MARKET_BAR = "MARKET_BAR"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    FX_OBSERVATION = "FX_OBSERVATION"
    BENCHMARK_OBSERVATION = "BENCHMARK_OBSERVATION"
    DECISION_ARTIFACT = "DECISION_ARTIFACT"
    FILING_DOCUMENT = "FILING_DOCUMENT"


class ArchiveArtifactType(StrEnum):
    EVIDENCE_PACKET = "EVIDENCE_PACKET"
    RESEARCH_TASK = "RESEARCH_TASK"
    ANALYST_RUN = "ANALYST_RUN"
    BUSINESS_QUALITY = "BUSINESS_QUALITY"
    RESEARCH_REPORT = "RESEARCH_REPORT"
    FILING = "FILING"
    FILING_DOCUMENT = "FILING_DOCUMENT"
    FILING_EXTRACTION = "FILING_EXTRACTION"
    FILING_EVIDENCE = "FILING_EVIDENCE"
    ADJUSTMENT = "ADJUSTMENT"


class ReviewStatus(StrEnum):
    FROZEN_VALIDATED = "FROZEN_VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class ReconciliationStatus(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    MISSING = "MISSING"


RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN = (
    "RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN"
)


class ReconciliationSourceIdentity(BaseModel):
    """Provider/upstream identity used to qualify a reconciliation source.

    ``source_id`` and ``adapter_id`` identify persisted transport artifacts;
    they are deliberately not used as proof that two observations are
    independent.  ``upstream_id`` is optional so a bounded specification can
    persist an unresolved source and fail closed at the qualification step.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_reconciliation_source_identity_v1"] = (
        "historical_reconciliation_source_identity_v1"
    )
    source_id: StrictStr = Field(min_length=1)
    adapter_id: StrictStr = Field(min_length=1)
    provider_id: StrictStr | None = Field(default=None, min_length=1)
    upstream_id: StrictStr | None = Field(default=None, min_length=1)


class HistoricalReconciliationSampleSpec(BaseModel):
    """A deterministic, persisted sample definition for M4 reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_reconciliation_sample_spec_v1"] = (
        "historical_reconciliation_sample_spec_v1"
    )
    sample_id: StrictStr = Field(min_length=1)
    target_id: StrictStr = Field(min_length=1)
    listing_ids: list[StrictStr] = Field(min_length=1)
    start_date: date
    end_date: date
    canonical_source_id: StrictStr = Field(min_length=1)
    canonical_adapter_id: StrictStr = Field(min_length=1)
    canonical_provider_id: StrictStr | None = Field(default=None, min_length=1)
    canonical_upstream_id: StrictStr | None = Field(default=None, min_length=1)
    independent_source_id: StrictStr = Field(min_length=1)
    independent_adapter_id: StrictStr = Field(min_length=1)
    independent_provider_id: StrictStr | None = Field(default=None, min_length=1)
    independent_upstream_id: StrictStr | None = Field(default=None, min_length=1)
    currency: StrictStr = Field(min_length=3, max_length=3)
    canonical_price_basis: PriceBasis
    independent_price_basis: PriceBasis
    compared_field: Literal["close"] = "close"
    return_semantics: Literal["PRICE_RETURN", "TOTAL_RETURN"] = "PRICE_RETURN"
    absolute_tolerance: StrictFloat = Field(ge=0)
    relative_tolerance: StrictFloat = Field(ge=0)
    selection_rationale: StrictStr = Field(min_length=1, max_length=2_000)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("listing_ids")
    @classmethod
    def validate_listing_ids(cls, value: list[str]) -> list[str]:
        return _unique(value, "reconciliation sample listing_ids")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value != "CNY":
            raise ValueError("M4 sampled price reconciliation requires CNY")
        return value

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("reconciliation sample end_date must not precede start_date")
        if self.canonical_source_id == self.independent_source_id:
            raise ValueError("reconciliation sample requires distinct source IDs")
        if self.content_sha256 != _hash_model(self, "content_sha256"):
            raise ValueError("reconciliation sample content_sha256 does not match content")
        return self

    @property
    def canonical_source(self) -> ReconciliationSourceIdentity:
        return ReconciliationSourceIdentity(
            source_id=self.canonical_source_id,
            adapter_id=self.canonical_adapter_id,
            provider_id=self.canonical_provider_id,
            upstream_id=self.canonical_upstream_id,
        )

    @property
    def independent_source(self) -> ReconciliationSourceIdentity:
        return ReconciliationSourceIdentity(
            source_id=self.independent_source_id,
            adapter_id=self.independent_adapter_id,
            provider_id=self.independent_provider_id,
            upstream_id=self.independent_upstream_id,
        )

    @classmethod
    def build(
        cls,
        *,
        sample_id: str,
        target_id: str,
        listing_ids: list[str],
        start_date: date,
        end_date: date,
        canonical_source_id: str,
        canonical_adapter_id: str,
        canonical_provider_id: str | None,
        canonical_upstream_id: str | None,
        independent_source_id: str,
        independent_adapter_id: str,
        independent_provider_id: str | None,
        independent_upstream_id: str | None,
        currency: str,
        canonical_price_basis: PriceBasis,
        independent_price_basis: PriceBasis,
        absolute_tolerance: float,
        relative_tolerance: float,
        selection_rationale: str,
        compared_field: Literal["close"] = "close",
        return_semantics: Literal["PRICE_RETURN", "TOTAL_RETURN"] = "PRICE_RETURN",
    ) -> HistoricalReconciliationSampleSpec:
        candidate = cls.model_construct(
            contract="historical_reconciliation_sample_spec_v1",
            sample_id=sample_id,
            target_id=target_id,
            listing_ids=listing_ids,
            start_date=start_date,
            end_date=end_date,
            canonical_source_id=canonical_source_id,
            canonical_adapter_id=canonical_adapter_id,
            canonical_provider_id=canonical_provider_id,
            canonical_upstream_id=canonical_upstream_id,
            independent_source_id=independent_source_id,
            independent_adapter_id=independent_adapter_id,
            independent_provider_id=independent_provider_id,
            independent_upstream_id=independent_upstream_id,
            currency=currency,
            canonical_price_basis=canonical_price_basis,
            independent_price_basis=independent_price_basis,
            compared_field=compared_field,
            return_semantics=return_semantics,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
            selection_rationale=selection_rationale,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


# Short descriptive aliases keep the additive contract discoverable for
# callers without introducing another wire version.
HistoricalReconciliationSample = HistoricalReconciliationSampleSpec
ReconciliationSampleSpec = HistoricalReconciliationSampleSpec


class HistoricalAvailabilityRecord(BaseModel):
    """Availability evidence tied to exactly one persisted artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_availability_record_v1"] = (
        "historical_availability_record_v1"
    )
    artifact_id: StrictStr = Field(min_length=1)
    artifact_kind: StrictStr = Field(min_length=1)
    published_at: DateTimeLike | None = None
    available_at: DateTimeLike | None = None
    retrieved_at: DateTimeLike | None = None
    source_artifact_id: StrictStr = Field(min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    status: AvailabilityStatus = AvailabilityStatus.KNOWN
    notes: StrictStr | None = Field(default=None, max_length=2_000)

    @model_validator(mode="before")
    @classmethod
    def preserve_date_only_values(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        copied = dict(value)
        for field_name in ("published_at", "available_at", "retrieved_at"):
            copied[field_name] = _preserve_date_only(copied.get(field_name))
        return copied

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        for field_name in ("published_at", "available_at", "retrieved_at"):
            value = getattr(self, field_name)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.status is AvailabilityStatus.KNOWN and self.available_at is None:
            raise ValueError("KNOWN availability requires available_at")
        if self.status is AvailabilityStatus.UNKNOWN and self.available_at is not None:
            raise ValueError("UNKNOWN availability must not provide available_at")
        return self


class HistoricalSourceDescriptor(BaseModel):
    """Identity and coverage evidence for one acquired source artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_source_descriptor_v1"] = (
        "historical_source_descriptor_v1"
    )
    source_id: StrictStr = Field(min_length=1)
    source_kind: HistoricalSourceKind
    # Additive identity fields.  Older manifests omitted these fields and remain
    # readable; M4 artifact-backed reconciliation requires them to be resolved.
    adapter_id: StrictStr | None = Field(default=None, min_length=1)
    upstream_id: StrictStr | None = Field(default=None, min_length=1)
    provider_id: StrictStr = Field(min_length=1)
    source_name: StrictStr = Field(min_length=1)
    authority: SourceAuthority
    query_parameters: dict[str, object] = Field(default_factory=dict)
    retrieved_at: datetime
    source_version: StrictStr | None = Field(default=None, min_length=1)
    coverage_start: date
    coverage_end: date
    coverage_listing_ids: list[StrictStr] = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    source_uri: StrictStr | None = Field(default=None, min_length=1)
    license_status: LicenseStatus = LicenseStatus.UNKNOWN
    licensing_constraints: StrictStr = Field(min_length=1)
    license_evidence_uri: StrictStr | None = Field(default=None, min_length=1)
    license_evidence_sha256: StrictStr | None = Field(
        default=None, pattern=_HASH_PATTERN
    )
    access_grant_reference: StrictStr | None = Field(default=None, min_length=1)
    historical_capable: StrictBool = False
    is_current_snapshot: StrictBool = False

    @field_validator("coverage_listing_ids")
    @classmethod
    def validate_listing_ids(cls, value: list[str]) -> list[str]:
        return _unique(value, "coverage_listing_ids")

    @model_validator(mode="after")
    def validate_descriptor(self) -> Self:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.coverage_end < self.coverage_start:
            raise ValueError("source coverage_end must not precede coverage_start")
        if self.source_kind is HistoricalSourceKind.UNIVERSE_MEMBERSHIP and (
            self.is_current_snapshot
        ):
            raise ValueError("current constituent snapshots are not historical membership")
        if (self.license_evidence_uri is None) != (
            self.license_evidence_sha256 is None
        ):
            raise ValueError(
                "license_evidence_uri and license_evidence_sha256 must be supplied together"
            )
        return self


class HistoricalTargetScope(BaseModel):
    """Named, bounded universe against which all production claims are scoped."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_target_scope_v1"] = "historical_target_scope_v1"
    target_id: StrictStr = Field(min_length=1)
    target_name: StrictStr = Field(min_length=1)
    universe_id: StrictStr = Field(min_length=1)
    markets: list[Market] = Field(min_length=1, max_length=2)
    listing_ids: list[StrictStr] = Field(min_length=1)
    start_date: date
    end_date: date
    membership_claim: Literal["HISTORICAL", "FIXED_RESEARCH_UNIVERSE", "UNKNOWN"]
    coverage_claim: CoverageClaim
    required_source_kinds: list[HistoricalSourceKind] = Field(min_length=1)
    calendar_ids: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    # Optional additive identity map.  Acquisition plans use it to prove that
    # a bounded target really contains distinct A/H listings; old manifests
    # remain readable when the map is absent.
    listing_markets: dict[StrictStr, Market] = Field(default_factory=dict)
    licensing_scope: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("target end_date must not precede start_date")
        if len(self.markets) != len(set(self.markets)):
            raise ValueError("target markets must be unique")
        _unique(self.listing_ids, "target listing_ids")
        if not set(self.listing_markets).issubset(self.listing_ids):
            raise ValueError("listing_markets contains listings outside target")
        if any(market not in self.markets for market in self.listing_markets.values()):
            raise ValueError("listing_markets contains a market outside target markets")
        _unique([item.value for item in self.required_source_kinds], "required_source_kinds")
        if (
            self.membership_claim == "HISTORICAL"
            and self.coverage_claim is not CoverageClaim.COMPLETE
        ):
            raise ValueError("HISTORICAL target claims require COMPLETE declared coverage")
        return self


class HistoricalCodeChange(BaseModel):
    """Effective code/name identity change for a listing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_code_change_v1"] = "historical_code_change_v1"
    effective_date: date
    previous_code: StrictStr = Field(min_length=1)
    new_code: StrictStr = Field(min_length=1)
    source_artifact_id: StrictStr = Field(min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        if self.previous_code == self.new_code:
            raise ValueError("code change must change the code")
        return self


class HistoricalListingLifecycle(BaseModel):
    """A/H listing lifecycle retaining terminal and unresolved outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_listing_lifecycle_v1"] = (
        "historical_listing_lifecycle_v1"
    )
    listing_id: StrictStr = Field(min_length=1)
    economic_company_id: StrictStr = Field(min_length=1)
    market: Market
    currency: StrictStr = Field(min_length=3, max_length=3)
    listing_date: date
    terminal_date: date | None = None
    terminal_outcome: HistoricalTerminalOutcome = HistoricalTerminalOutcome.ACTIVE
    trading_calendar: StrictStr = Field(min_length=1)
    timezone: StrictStr = Field(min_length=1)
    historical_codes: list[StrictStr] = Field(min_length=1)
    code_changes: list[HistoricalCodeChange] = Field(default_factory=list)
    source_artifact_id: StrictStr = Field(min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("historical_codes")
    @classmethod
    def validate_codes(cls, value: list[str]) -> list[str]:
        return _unique(value, "historical_codes")

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.terminal_date is not None and self.terminal_date < self.listing_date:
            raise ValueError("terminal_date must not precede listing_date")
        if self.terminal_outcome is HistoricalTerminalOutcome.ACTIVE and self.terminal_date:
            raise ValueError("ACTIVE listing must not have terminal_date")
        if self.terminal_outcome is not HistoricalTerminalOutcome.ACTIVE and not self.terminal_date:
            raise ValueError("non-active listing outcomes require terminal_date")
        for change in self.code_changes:
            if change.effective_date < self.listing_date:
                raise ValueError("code change precedes listing date")
        return self

    def is_listed_on(self, value: date) -> bool:
        return value >= self.listing_date and (
            self.terminal_date is None or value <= self.terminal_date
        )


class HistoricalTradingSession(BaseModel):
    """One explicit exchange-calendar observation for one target listing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_trading_session_v1"] = (
        "historical_trading_session_v1"
    )
    session_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    calendar_id: StrictStr = Field(min_length=1)
    session_date: date
    is_trading_day: StrictBool
    timezone: StrictStr = Field(min_length=1)
    source_artifact_id: StrictStr = Field(min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        expected_id = f"{self.listing_id}:{self.calendar_id}:{self.session_date.isoformat()}"
        if self.session_id != expected_id:
            raise ValueError("session_id does not match listing/calendar/date identity")
        return self


class HistoricalMembershipInterval(BaseModel):
    """Historical membership interval with a separately auditable availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_membership_interval_v1"] = (
        "historical_membership_interval_v1"
    )
    membership_id: StrictStr = Field(min_length=1)
    universe_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    included: StrictBool = True
    availability_id: StrictStr = Field(min_length=1)
    source_artifact_id: StrictStr = Field(min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("membership valid_to must not precede valid_from")
        return self

    def includes(self, value: date) -> bool:
        return value >= self.valid_from and (self.valid_to is None or value <= self.valid_to)


class HistoricalFXObservation(BaseModel):
    """Listing-specific FX observation retained before Phase 5 projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_fx_observation_v1"] = "historical_fx_observation_v1"
    observation_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    base_currency: StrictStr = Field(min_length=3, max_length=3)
    quote_currency: StrictStr = Field(min_length=3, max_length=3)
    observation_date: date
    rate: StrictFloat = Field(gt=0)
    available_at: DateTimeLike | None = None
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def preserve_date_only_availability(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        copied = dict(value)
        copied["available_at"] = _preserve_date_only(copied.get("available_at"))
        return copied

    @model_validator(mode="after")
    def validate_fx(self) -> Self:
        _finite(self.rate, "rate")
        if self.base_currency == self.quote_currency:
            raise ValueError("FX base and quote currencies must differ")
        if isinstance(self.available_at, datetime) and self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return self


class HistoricalCoverageRecord(BaseModel):
    """Coverage for one listing and one source category over one period."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_coverage_record_v1"] = "historical_coverage_record_v1"
    source_kind: HistoricalSourceKind
    listing_id: StrictStr = Field(min_length=1)
    period_start: date
    period_end: date
    expected_session_count: StrictInt = Field(ge=0)
    observed_session_count: StrictInt = Field(ge=0)
    missing_dates: list[date] = Field(default_factory=list)
    source_artifact_ids: list[StrictStr] = Field(min_length=1)
    status: CoverageClaim
    terminal_outcome: HistoricalTerminalOutcome | None = None
    # Optional for wire compatibility with previously persisted manifests.
    # Production validation requires a category-appropriate value.
    evidence_basis: CoverageEvidenceBasis | None = None

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("coverage period_end must not precede period_start")
        _unique(self.source_artifact_ids, "source_artifact_ids")
        if (
            self.status is not CoverageClaim.UNKNOWN
            and self.observed_session_count > self.expected_session_count
        ):
            raise ValueError("observed sessions cannot exceed expected sessions")
        if self.status is CoverageClaim.COMPLETE and (
            self.observed_session_count != self.expected_session_count or self.missing_dates
        ):
            raise ValueError("COMPLETE coverage cannot contain missing sessions")
        if (
            self.status is CoverageClaim.COMPLETE
            and self.expected_session_count == 0
            and self.evidence_basis is not CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE
        ):
            raise ValueError(
                "COMPLETE coverage with zero expected observations requires explicit source scope"
            )
        if self.status is CoverageClaim.PARTIAL and not self.missing_dates:
            raise ValueError("PARTIAL coverage must report missing dates")
        return self


class HistoricalCoverageReport(BaseModel):
    """Deterministic per-listing/per-period coverage report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_coverage_report_v1"] = "historical_coverage_report_v1"
    report_id: StrictStr = Field(min_length=1)
    target_id: StrictStr = Field(min_length=1)
    records: list[HistoricalCoverageRecord] = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        ids = [
            f"{item.source_kind.value}:{item.listing_id}:{item.period_start}:{item.period_end}"
            for item in self.records
        ]
        _unique(ids, "coverage records")
        if self.content_sha256 != _hash_model(self, "content_sha256"):
            raise ValueError("coverage report content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        report_id: str,
        target_id: str,
        records: list[HistoricalCoverageRecord],
    ) -> HistoricalCoverageReport:
        candidate = cls.model_construct(
            contract="historical_coverage_report_v1",
            report_id=report_id,
            target_id=target_id,
            records=records,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


class HistoricalShardReference(BaseModel):
    """Content-addressed JSONL shard metadata; rows are never embedded here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_shard_reference_v1"] = "historical_shard_reference_v1"
    shard_id: StrictStr = Field(min_length=1)
    artifact_kind: ShardArtifactKind
    format: ShardFormat = ShardFormat.JSONL
    schema_version: StrictStr = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    row_count: StrictInt = Field(ge=0)
    date_start: date
    date_end: date
    listing_scope: list[StrictStr] = Field(min_length=1)
    source_artifact_id: StrictStr = Field(min_length=1)
    relative_path: StrictStr | None = Field(default=None, min_length=1)

    @field_validator("listing_scope")
    @classmethod
    def validate_listing_scope(cls, value: list[str]) -> list[str]:
        return _unique(value, "listing_scope")

    @model_validator(mode="after")
    def validate_shard(self) -> Self:
        if self.date_end < self.date_start:
            raise ValueError("shard date_end must not precede date_start")
        if self.relative_path is not None and (
            self.relative_path.startswith("/")
            or "\\" in self.relative_path
            or ".." in self.relative_path.split("/")
        ):
            raise ValueError("shard relative_path must remain within the artifact store")
        return self


class HistoricalFilingLocator(BaseModel):
    """Stable locator retained with every archived research artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_filing_locator_v1"] = "historical_filing_locator_v1"
    filing_id: StrictStr = Field(min_length=1)
    document_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    page: StrictInt | None = Field(default=None, ge=1)
    section: StrictStr | None = Field(default=None, min_length=1)
    locator: StrictStr | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_locator(self) -> Self:
        if self.page is None and self.section is None and self.locator is None:
            raise ValueError("filing locator requires page, section or locator")
        return self


def filing_document_artifact_id(filing_id: str, document_hash: str) -> str:
    """Return the stable artifact identity for one filing revision."""

    if not isinstance(filing_id, str) or not filing_id:
        raise ValueError("filing_id must be a non-empty string")
    if not re.fullmatch(_HASH_PATTERN, document_hash):
        raise ValueError("document_hash must be a lowercase SHA-256 value")
    identity = canonical_json_bytes(
        {"filing_id": filing_id, "document_hash": document_hash}
    )
    return "filing-document-" + hashlib.sha256(identity).hexdigest()[:32]


class HistoricalFilingDocumentRecord(BaseModel):
    """One immutable official filing revision projected from a raw document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_filing_document_record_v1"] = (
        "historical_filing_document_record_v1"
    )
    artifact_id: StrictStr = Field(min_length=1)
    filing_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    market: Market
    source: StrictStr = Field(min_length=1)
    title: StrictStr = Field(min_length=1)
    document_type: StrictStr = Field(min_length=1)
    published_at: date
    available_at: datetime
    retrieved_at: datetime
    source_uri: StrictStr = Field(min_length=1)
    document_locator: StrictStr = Field(min_length=1)
    source_document_id: StrictStr | None = Field(default=None, min_length=1)
    report_period: StrictStr | None = Field(default=None, min_length=1)
    document_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    document_size: StrictInt = Field(ge=1)
    media_type: StrictStr = Field(min_length=1, max_length=256)
    revision_identity: StrictStr = Field(min_length=1)
    source_artifact_id: StrictStr = Field(min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("source_uri", "document_locator")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        return _safe_http_uri(value)

    @field_validator(
        "title",
        "document_type",
        "source_document_id",
        "report_period",
        "source",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 for char in normalized):
            raise ValueError("filing metadata text must be non-empty and printable")
        return normalized

    @field_validator("media_type")
    @classmethod
    def normalize_media_type(cls, value: str) -> str:
        normalized = value.split(";", 1)[0].strip().lower()
        if not _MEDIA_TYPE_PATTERN.fullmatch(normalized):
            raise ValueError("media_type must be a valid type/subtype")
        return normalized

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        for field_name in ("available_at", "retrieved_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.available_at < self.retrieved_at:
            raise ValueError("available_at must not precede retrieved_at")
        expected_revision = f"{self.filing_id}:{self.document_hash}"
        if self.revision_identity != expected_revision:
            raise ValueError("revision_identity does not match filing/document hash")
        if self.artifact_id != filing_document_artifact_id(
            self.filing_id, self.document_hash
        ):
            raise ValueError("artifact_id does not match filing/document identity")
        return self


class HistoricalResearchArtifactReference(BaseModel):
    """Reference to one immutable Phase 4/research/filing artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_research_artifact_reference_v1"] = (
        "historical_research_artifact_reference_v1"
    )
    artifact_id: StrictStr = Field(min_length=1)
    artifact_type: ArchiveArtifactType
    listing_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    as_of: date
    available_at: DateTimeLike | None = None
    source_document_hashes: list[StrictStr] = Field(min_length=1)
    filing_ids: list[StrictStr] = Field(min_length=1)
    locators: list[HistoricalFilingLocator] = Field(min_length=1)
    source_artifact_ids: list[StrictStr] = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    review_status: ReviewStatus
    relative_path: StrictStr | None = Field(default=None, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def preserve_date_only_availability(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        copied = dict(value)
        copied["available_at"] = _preserve_date_only(copied.get("available_at"))
        return copied

    @field_validator("source_document_hashes")
    @classmethod
    def validate_document_hashes(cls, value: list[str]) -> list[str]:
        for item in value:
            if not re.fullmatch(_HASH_PATTERN, item):
                raise ValueError("source_document_hashes must be SHA-256 values")
        return _unique(value, "source_document_hashes")

    @field_validator("filing_ids", "source_artifact_ids")
    @classmethod
    def validate_reference_ids(cls, value: list[str]) -> list[str]:
        return _unique(value, "reference IDs")

    @model_validator(mode="after")
    def validate_archive_reference(self) -> Self:
        if isinstance(self.available_at, datetime) and self.available_at.tzinfo is None:
            raise ValueError("research artifact available_at must be timezone-aware")
        locator_filing_ids = {item.filing_id for item in self.locators}
        if not locator_filing_ids.issubset(self.filing_ids):
            raise ValueError("filing locators must refer to filing_ids on the artifact")
        locator_document_hashes = {item.document_hash for item in self.locators}
        if not locator_document_hashes.issubset(self.source_document_hashes):
            raise ValueError(
                "filing locator document hashes must be retained in source_document_hashes"
            )
        if self.relative_path is not None and (
            self.relative_path.startswith("/")
            or "\\" in self.relative_path
            or ".." in self.relative_path.split("/")
        ):
            raise ValueError("archive relative_path must remain within the artifact store")
        return self

    @classmethod
    def from_model(
        cls,
        *,
        artifact_id: str,
        artifact_type: ArchiveArtifactType,
        artifact: BaseModel,
        listing_id: str,
        analysis_id: str,
        as_of: date,
        available_at: DateTimeLike,
        source_document_hashes: list[str],
        filing_ids: list[str],
        locators: list[HistoricalFilingLocator],
        source_artifact_ids: list[str],
        review_status: ReviewStatus,
        relative_path: str | None = None,
    ) -> HistoricalResearchArtifactReference:
        """Create a reference from an already-frozen Phase 4 model artifact."""

        if not isinstance(artifact, BaseModel):
            raise TypeError("artifact must be a Pydantic model")
        content_sha256 = hashlib.sha256(
            canonical_json_bytes(artifact.model_dump(mode="json", warnings=False))
        ).hexdigest()
        return cls(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            listing_id=listing_id,
            analysis_id=analysis_id,
            as_of=as_of,
            available_at=available_at,
            source_document_hashes=source_document_hashes,
            filing_ids=filing_ids,
            locators=locators,
            source_artifact_ids=source_artifact_ids,
            content_sha256=content_sha256,
            review_status=review_status,
            relative_path=relative_path,
        )


class HistoricalDecisionResearchBinding(BaseModel):
    """Point-in-time link from a decision artifact to frozen research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_decision_research_binding_v1"] = (
        "historical_decision_research_binding_v1"
    )
    decision_artifact_id: StrictStr = Field(min_length=1)
    research_artifact_id: StrictStr = Field(min_length=1)
    business_quality_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    as_of: date
    decision_time: datetime
    used_artifact_ids: list[StrictStr] = Field(min_length=1)

    @field_validator("used_artifact_ids")
    @classmethod
    def validate_used_ids(cls, value: list[str]) -> list[str]:
        return _unique(value, "used_artifact_ids")

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.decision_time.date() < self.as_of:
            raise ValueError("decision_time must not precede as_of")
        if self.research_artifact_id not in self.used_artifact_ids:
            raise ValueError("research_artifact_id must be in used_artifact_ids")
        return self


class HistoricalResearchArchiveManifest(BaseModel):
    """Frozen archive index for historical Business Quality and evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_research_archive_manifest_v1"] = (
        "historical_research_archive_manifest_v1"
    )
    archive_id: StrictStr = Field(min_length=1)
    target_id: StrictStr = Field(min_length=1)
    artifacts: list[HistoricalResearchArtifactReference] = Field(min_length=1)
    decision_bindings: list[HistoricalDecisionResearchBinding] = Field(default_factory=list)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_archive(self) -> Self:
        ids = [item.artifact_id for item in self.artifacts]
        _unique(ids, "research artifact IDs")
        binding_ids = [item.decision_artifact_id for item in self.decision_bindings]
        _unique(binding_ids, "decision binding IDs")
        if self.content_sha256 != _hash_model(self, "content_sha256"):
            raise ValueError("research archive content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        archive_id: str,
        target_id: str,
        artifacts: list[HistoricalResearchArtifactReference],
        decision_bindings: list[HistoricalDecisionResearchBinding],
    ) -> HistoricalResearchArchiveManifest:
        candidate = cls.model_construct(
            contract="historical_research_archive_manifest_v1",
            archive_id=archive_id,
            target_id=target_id,
            artifacts=artifacts,
            decision_bindings=decision_bindings,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


class ReconciliationComparison(BaseModel):
    """One canonical-vs-independent comparison with deterministic tolerance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_reconciliation_comparison_v1"] = (
        "historical_reconciliation_comparison_v1"
    )
    comparison_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    observation_date: date
    canonical_value: StrictFloat | None = None
    independent_value: StrictFloat | None = None
    absolute_tolerance: StrictFloat = Field(ge=0)
    relative_tolerance: StrictFloat = Field(ge=0)
    absolute_difference: StrictFloat | None = None
    relative_difference: StrictFloat | None = None
    status: ReconciliationStatus
    canonical_source_id: StrictStr = Field(min_length=1)
    independent_source_id: StrictStr = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def derive_comparison(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        copied = dict(value)
        canonical = copied.get("canonical_value")
        independent = copied.get("independent_value")
        if canonical is not None:
            _finite(float(canonical), "canonical_value")
        if independent is not None:
            _finite(float(independent), "independent_value")
        if canonical is None or independent is None:
            copied["absolute_difference"] = None
            copied["relative_difference"] = None
            derived = ReconciliationStatus.MISSING
        else:
            absolute = abs(float(canonical) - float(independent))
            denominator = max(abs(float(independent)), 1e-12)
            relative = absolute / denominator
            copied["absolute_difference"] = absolute
            copied["relative_difference"] = relative
            derived = (
                ReconciliationStatus.PASS
                if absolute <= float(copied["absolute_tolerance"])
                or relative <= float(copied["relative_tolerance"])
                else ReconciliationStatus.FAIL
            )
        supplied = copied.get("status")
        if supplied is not None and ReconciliationStatus(supplied) is not derived:
            raise ValueError("reconciliation status does not match values and tolerances")
        copied["status"] = derived.value
        return copied


class HistoricalReconciliationReport(BaseModel):
    """Persisted independent-reference reconciliation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_reconciliation_report_v1"] = (
        "historical_reconciliation_report_v1"
    )
    report_id: StrictStr = Field(min_length=1)
    target_id: StrictStr = Field(min_length=1)
    canonical_source_id: StrictStr = Field(min_length=1)
    independent_source_id: StrictStr = Field(min_length=1)
    canonical_price_basis: PriceBasis
    return_semantics: Literal["PRICE_RETURN", "TOTAL_RETURN"]
    explicit_actions_used: StrictBool = False
    comparisons: list[ReconciliationComparison] = Field(min_length=1)
    status: ReconciliationStatus
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def derive_report_status(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        copied = dict(value)
        comparisons = copied.get("comparisons", [])
        statuses = {
            item.status if isinstance(item, ReconciliationComparison) else item.get("status")
            for item in comparisons
        }
        normalized = {ReconciliationStatus(item) for item in statuses}
        if ReconciliationStatus.FAIL in normalized:
            status = ReconciliationStatus.FAIL
        elif ReconciliationStatus.MISSING in normalized:
            status = ReconciliationStatus.PARTIAL
        else:
            status = ReconciliationStatus.PASS
        supplied = copied.get("status")
        if supplied is not None and ReconciliationStatus(supplied) is not status:
            raise ValueError("reconciliation report status does not match comparisons")
        copied["status"] = status.value
        return copied

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.canonical_source_id == self.independent_source_id:
            raise ValueError("reconciliation requires an independent source")
        if self.canonical_price_basis is PriceBasis.ADJUSTED and self.explicit_actions_used:
            raise ValueError("adjusted prices cannot be reconciled with explicit actions")
        if self.content_sha256 != _hash_model(self, "content_sha256"):
            raise ValueError("reconciliation report content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        report_id: str,
        target_id: str,
        canonical_source_id: str,
        independent_source_id: str,
        canonical_price_basis: PriceBasis,
        return_semantics: Literal["PRICE_RETURN", "TOTAL_RETURN"],
        explicit_actions_used: bool,
        comparisons: list[ReconciliationComparison],
    ) -> HistoricalReconciliationReport:
        statuses = {item.status for item in comparisons}
        if ReconciliationStatus.FAIL in statuses:
            report_status = ReconciliationStatus.FAIL
        elif ReconciliationStatus.MISSING in statuses:
            report_status = ReconciliationStatus.PARTIAL
        else:
            report_status = ReconciliationStatus.PASS
        candidate = cls.model_construct(
            contract="historical_reconciliation_report_v1",
            report_id=report_id,
            target_id=target_id,
            canonical_source_id=canonical_source_id,
            independent_source_id=independent_source_id,
            canonical_price_basis=canonical_price_basis,
            return_semantics=return_semantics,
            explicit_actions_used=explicit_actions_used,
            comparisons=comparisons,
            status=report_status,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {
                    key: value
                    for key, value in candidate.model_dump(mode="json", warnings=False).items()
                    if key != "content_sha256"
                }
            )
        ).hexdigest()
        return cls.model_validate(payload)


class HistoricalDatasetManifest(BaseModel):
    """Source-aware manifest whose large collections live in verified shards."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_dataset_manifest_v1"] = "historical_dataset_manifest_v1"
    dataset_id: StrictStr = Field(min_length=1)
    dataset_version: StrictStr = Field(min_length=1)
    target: HistoricalTargetScope
    source_descriptors: list[HistoricalSourceDescriptor] = Field(min_length=1)
    shards: list[HistoricalShardReference] = Field(min_length=1)
    coverage_reports: list[HistoricalCoverageReport] = Field(min_length=1)
    research_archive: HistoricalResearchArchiveManifest | None = None
    reconciliation_reports: list[HistoricalReconciliationReport] = Field(default_factory=list)
    missing_data_summary: dict[str, StrictInt] = Field(default_factory=dict)
    limitations: list[StrictStr] = Field(default_factory=list, max_length=256)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        _unique([item.source_id for item in self.source_descriptors], "source IDs")
        _unique([item.shard_id for item in self.shards], "shard IDs")
        if not self.coverage_reports:
            raise ValueError("historical manifest requires coverage reports")
        for report in self.coverage_reports:
            if report.target_id != self.target.target_id:
                raise ValueError("coverage report target does not match manifest target")
        for report in self.reconciliation_reports:
            if report.target_id != self.target.target_id:
                raise ValueError("reconciliation report target does not match manifest target")
        if (
            self.research_archive is not None
            and self.research_archive.target_id != self.target.target_id
        ):
            raise ValueError("research archive target does not match manifest target")
        if self.content_sha256 != _hash_model(self, "content_sha256"):
            raise ValueError("historical manifest content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        dataset_id: str,
        dataset_version: str,
        target: HistoricalTargetScope,
        source_descriptors: list[HistoricalSourceDescriptor],
        shards: list[HistoricalShardReference],
        coverage_reports: list[HistoricalCoverageReport],
        research_archive: HistoricalResearchArchiveManifest | None = None,
        reconciliation_reports: list[HistoricalReconciliationReport] | None = None,
        missing_data_summary: dict[str, int] | None = None,
        limitations: list[str] | None = None,
    ) -> HistoricalDatasetManifest:
        candidate = cls.model_construct(
            contract="historical_dataset_manifest_v1",
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            target=target,
            source_descriptors=source_descriptors,
            shards=shards,
            coverage_reports=coverage_reports,
            research_archive=research_archive,
            reconciliation_reports=reconciliation_reports or [],
            missing_data_summary=missing_data_summary or {},
            limitations=limitations or [],
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


# A descriptive alias for callers that want to make the production boundary
# explicit without creating a second wire contract.
ProductionHistoricalDatasetManifest = HistoricalDatasetManifest


__all__ = [
    "ArchiveArtifactType",
    "CoverageClaim",
    "CoverageEvidenceBasis",
    "HistoricalAvailabilityRecord",
    "HistoricalCodeChange",
    "HistoricalCoverageRecord",
    "HistoricalCoverageReport",
    "HistoricalDatasetManifest",
    "HistoricalDecisionResearchBinding",
    "HistoricalFilingDocumentRecord",
    "HistoricalFilingLocator",
    "HistoricalFXObservation",
    "HistoricalListingLifecycle",
    "HistoricalMembershipInterval",
    "HistoricalReconciliationReport",
    "HistoricalReconciliationSample",
    "HistoricalReconciliationSampleSpec",
    "HistoricalResearchArchiveManifest",
    "HistoricalResearchArtifactReference",
    "HistoricalShardReference",
    "HistoricalSourceDescriptor",
    "HistoricalSourceKind",
    "HistoricalTargetScope",
    "HistoricalTerminalOutcome",
    "HistoricalTradingSession",
    "HISTORICAL_ARCHIVE_CONTRACT_VERSION",
    "HISTORICAL_CONTRACT_VERSION",
    "HISTORICAL_SHARD_CONTRACT_VERSION",
    "LicenseStatus",
    "ProductionHistoricalDatasetManifest",
    "ReconciliationComparison",
    "ReconciliationSampleSpec",
    "ReconciliationSourceIdentity",
    "ReconciliationStatus",
    "RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN",
    "filing_document_artifact_id",
    "ReviewStatus",
    "ShardArtifactKind",
    "ShardFormat",
    "SourceAuthority",
]
