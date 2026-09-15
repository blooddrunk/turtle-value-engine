"""Typed, persisted contracts for point-in-time backtesting.

This module contains data envelopes only.  It deliberately does not import
the deterministic calculation modules and does not own any investment rule.
The backtest layer can project an existing ``CompanyAnalysis`` into a
snapshot, but it cannot manufacture a new analysis or change its state.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from turtle_value_engine.models import CompanyAnalysis, NormalizedCompanyInput
from turtle_value_engine.providers.models import canonical_json_bytes

BACKTEST_CONTRACT_VERSION = "backtest-v1"
DATASET_CONTRACT_VERSION = "backtest-dataset-v1"
PORTFOLIO_POLICY_CONTRACT_VERSION = "portfolio-policy-v1"
CALIBRATION_CONTRACT_VERSION = "calibration-v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
DateTimeLike: TypeAlias = datetime | date


class Market(StrEnum):
    """Listing market; A and H listings are never merged by the simulator."""

    A = "A"
    H = "H"


class PriceBasis(StrEnum):
    """Whether a market series has already incorporated corporate actions."""

    UNADJUSTED = "UNADJUSTED"
    ADJUSTED = "ADJUSTED"


class CorporateActionType(StrEnum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    SPLIT = "SPLIT"
    CONSOLIDATION = "CONSOLIDATION"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    SHARE_ISSUANCE = "SHARE_ISSUANCE"
    DELISTING = "DELISTING"
    TERMINAL_VALUE = "TERMINAL_VALUE"


class BenchmarkReturnType(StrEnum):
    PRICE_RETURN = "PRICE_RETURN"
    TOTAL_RETURN = "TOTAL_RETURN"


class UniverseCoverage(StrEnum):
    HISTORICAL = "HISTORICAL"
    FIXED_RESEARCH_UNIVERSE = "FIXED_RESEARCH_UNIVERSE"
    CURRENT_UNIVERSE = "CURRENT_UNIVERSE"
    UNKNOWN = "UNKNOWN"


class AvailabilityStatus(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    EXPLICIT_POLICY = "EXPLICIT_POLICY"


class SignalOutcomeStatus(StrEnum):
    COMPLETE = "COMPLETE"
    NO_ENTRY = "NO_ENTRY"
    NO_EXIT = "NO_EXIT"
    MISSING_PRICE = "MISSING_PRICE"
    SUSPENDED = "SUSPENDED"
    DELISTED_TERMINAL = "DELISTED_TERMINAL"
    INVALID_CORPORATE_ACTION_DATA = "INVALID_CORPORATE_ACTION_DATA"


class RebalanceFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ExecutionPrice(StrEnum):
    NEXT_OPEN = "NEXT_OPEN"
    NEXT_CLOSE = "NEXT_CLOSE"


class SizingRule(StrEnum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    EQUAL_RISK = "EQUAL_RISK"


class MissingDataAction(StrEnum):
    SKIP = "SKIP"
    NO_FILL = "NO_FILL"
    FAIL = "FAIL"


class PortfolioEventType(StrEnum):
    INITIAL_CASH = "INITIAL_CASH"
    ORDER = "ORDER"
    FILL = "FILL"
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    TERMINAL_VALUE = "TERMINAL_VALUE"
    FEE = "FEE"
    MARK = "MARK"
    REBALANCE = "REBALANCE"
    CASH_FLOW = "CASH_FLOW"
    SKIP = "SKIP"


class CalibrationStage(StrEnum):
    SEARCH = "SEARCH"
    HOLDOUT_EVALUATION = "HOLDOUT_EVALUATION"


def _finite(value: float | None, field_name: str) -> float | None:
    if value is not None and not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return value


def _unique(values: list[str], field_name: str = "values") -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def _hash_model(model: BaseModel, *excluded: str) -> str:
    return hashlib.sha256(
        canonical_json_bytes(model.model_dump(mode="json", exclude=set(excluded)))
    ).hexdigest()


class HistoricalAvailability(BaseModel):
    """Availability metadata for one frozen historical artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_availability_v1"] = "historical_availability_v1"
    artifact_id: StrictStr = Field(min_length=1)
    period_end: date | None = None
    published_at: DateTimeLike | None = None
    available_at: DateTimeLike | None = None
    retrieved_at: DateTimeLike | None = None
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    source_id: StrictStr | None = Field(default=None, min_length=1)
    status: AvailabilityStatus = AvailabilityStatus.KNOWN
    notes: StrictStr | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        for field_name in ("published_at", "available_at", "retrieved_at"):
            value = getattr(self, field_name)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.status is AvailabilityStatus.KNOWN and self.available_at is None:
            raise ValueError("KNOWN availability requires available_at")
        if self.status is AvailabilityStatus.UNKNOWN and self.available_at is not None:
            raise ValueError("UNKNOWN availability must not provide available_at")
        return self


class ListingLifecycle(BaseModel):
    """Listing-level lifecycle; A/H classes remain distinct assets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["listing_lifecycle_v1"] = "listing_lifecycle_v1"
    listing_id: StrictStr = Field(min_length=1)
    company_id: StrictStr | None = Field(default=None, min_length=1)
    economic_company_id: StrictStr | None = Field(default=None, min_length=1)
    market: Market
    currency: StrictStr = Field(min_length=3, max_length=3)
    listing_date: date
    delisting_date: date | None = None
    terminal_status: Literal["ACTIVE", "DELISTED", "TERMINAL", "UNKNOWN"] = "ACTIVE"
    trading_calendar: StrictStr = Field(default="UNSPECIFIED", min_length=1)
    timezone: StrictStr = Field(default="UTC", min_length=1)
    sector: StrictStr | None = Field(default=None, min_length=1)
    industry: StrictStr | None = Field(default=None, min_length=1)
    source_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    source_hash: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.company_id is None and self.economic_company_id is None:
            raise ValueError("listing lifecycle requires company_id or economic_company_id")
        if self.delisting_date is not None and self.delisting_date < self.listing_date:
            raise ValueError("delisting_date must not precede listing_date")
        if self.delisting_date is not None and self.terminal_status == "ACTIVE":
            raise ValueError("a delisted listing cannot have ACTIVE terminal_status")
        return self

    @property
    def resolved_company_id(self) -> str:
        return self.company_id or self.economic_company_id  # type: ignore[return-value]

    def is_listed_on(self, value: date) -> bool:
        return value >= self.listing_date and (
            self.delisting_date is None or value <= self.delisting_date
        )


class UniverseMembership(BaseModel):
    """One historical membership interval for one listing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["universe_membership_v1"] = "universe_membership_v1"
    membership_id: StrictStr = Field(min_length=1)
    universe_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    included: StrictBool = True
    availability: HistoricalAvailability | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("universe membership valid_to must not precede valid_from")
        if self.availability is not None and self.availability.artifact_id != self.membership_id:
            raise ValueError("membership availability artifact_id must match membership_id")
        return self

    def includes(self, value: date) -> bool:
        return value >= self.valid_from and (self.valid_to is None or value <= self.valid_to)


class MarketBar(BaseModel):
    """One immutable listing-specific market observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["market_bar_v1"] = "market_bar_v1"
    bar_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    market: Market
    trading_date: date
    timestamp: DateTimeLike | None = None
    session_open_at: datetime | None = None
    session_close_at: datetime | None = None
    open: StrictFloat | None = None
    high: StrictFloat | None = None
    low: StrictFloat | None = None
    close: StrictFloat | None = None
    volume: StrictFloat | None = Field(default=None, ge=0)
    amount: StrictFloat | None = Field(default=None, ge=0)
    currency: StrictStr = Field(min_length=3, max_length=3)
    price_basis: PriceBasis = PriceBasis.UNADJUSTED
    adjustment_scope: list[StrictStr] = Field(default_factory=list)
    tradable: StrictBool = True
    suspended: StrictBool = False
    missing_reason: StrictStr | None = Field(default=None, min_length=1)
    available_at: DateTimeLike | None = None
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def suspended_bars_are_not_tradable(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("suspended") is True:
            copied = dict(value)
            copied["tradable"] = False
            return copied
        return value

    @model_validator(mode="after")
    def validate_bar(self) -> Self:
        for field_name in ("open", "high", "low", "close", "volume", "amount"):
            _finite(getattr(self, field_name), field_name)
        for field_name in ("session_open_at", "session_close_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if isinstance(self.timestamp, datetime) and self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if (
            self.session_open_at
            and self.session_close_at
            and self.session_close_at < self.session_open_at
        ):
            raise ValueError("session_close_at must not precede session_open_at")
        _unique(self.adjustment_scope, "adjustment_scope")
        if self.price_basis is PriceBasis.ADJUSTED and not self.adjustment_scope:
            raise ValueError("ADJUSTED bars must declare adjustment_scope")
        if self.price_basis is PriceBasis.UNADJUSTED and self.adjustment_scope:
            raise ValueError("UNADJUSTED bars must not declare adjustment_scope")
        if self.close is not None and self.close <= 0:
            raise ValueError("close must be positive when present")
        if self.tradable and self.close is None:
            raise ValueError("tradable market bars require a close price")
        if self.suspended and self.tradable:
            raise ValueError("suspended market bars cannot be tradable")
        return self

    @property
    def execution_time(self) -> datetime | date:
        return self.session_close_at or self.timestamp or self.trading_date

    def execution_price(self, field: Literal["open", "close"] = "close") -> float | None:
        return getattr(self, field)


class CorporateAction(BaseModel):
    """Listing-level corporate action used exactly once by return paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["corporate_action_v1"] = "corporate_action_v1"
    action_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    action_type: CorporateActionType
    effective_date: date
    ex_date: date | None = None
    payment_date: date | None = None
    announced_at: DateTimeLike | None = None
    available_at: DateTimeLike | None = None
    cash_per_share: StrictFloat | None = Field(default=None, ge=0)
    split_factor: StrictFloat | None = Field(default=None, gt=0)
    rights_ratio: StrictFloat | None = Field(default=None, ge=0)
    rights_price: StrictFloat | None = Field(default=None, gt=0)
    terminal_value_per_share: StrictFloat | None = Field(default=None, ge=0)
    currency: StrictStr | None = Field(default=None, min_length=3, max_length=3)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    notes: StrictStr | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action_type is CorporateActionType.CASH_DIVIDEND:
            if self.cash_per_share is None or self.cash_per_share <= 0:
                raise ValueError("cash dividends require positive cash_per_share")
        elif self.action_type in {CorporateActionType.SPLIT, CorporateActionType.CONSOLIDATION}:
            if self.split_factor is None or self.split_factor <= 0 or self.split_factor == 1:
                raise ValueError("splits/consolidations require a non-unit split_factor")
        elif self.action_type is CorporateActionType.TERMINAL_VALUE:
            if self.terminal_value_per_share is None:
                raise ValueError("terminal values require terminal_value_per_share")
        if self.ex_date and self.ex_date < self.effective_date:
            raise ValueError("ex_date must not precede effective_date")
        for field_name in ("announced_at", "available_at"):
            value = getattr(self, field_name)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        return self


class FXObservation(BaseModel):
    """Point-in-time FX observation for optional reporting conversion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["fx_observation_v1"] = "fx_observation_v1"
    observation_id: StrictStr = Field(min_length=1)
    # Optional for backward compatibility with compact Phase 5 manifests;
    # source-aware historical datasets preserve listing-specific FX identity.
    listing_id: StrictStr | None = Field(default=None, min_length=1)
    base_currency: StrictStr = Field(min_length=3, max_length=3)
    quote_currency: StrictStr = Field(min_length=3, max_length=3)
    observation_date: date
    rate: StrictFloat = Field(gt=0)
    available_at: DateTimeLike | None = None
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_fx(self) -> Self:
        _finite(self.rate, "rate")
        if self.base_currency == self.quote_currency:
            raise ValueError("FX base and quote currencies must differ")
        if isinstance(self.available_at, datetime) and self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return self


class BenchmarkObservation(BaseModel):
    """One benchmark level with an explicit price/total return identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["benchmark_observation_v1"] = "benchmark_observation_v1"
    observation_id: StrictStr = Field(min_length=1)
    benchmark_id: StrictStr = Field(min_length=1)
    observation_date: date
    value: StrictFloat = Field(gt=0)
    return_type: BenchmarkReturnType
    currency: StrictStr = Field(min_length=3, max_length=3)
    available_at: DateTimeLike | None = None
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_benchmark(self) -> Self:
        _finite(self.value, "value")
        if isinstance(self.available_at, datetime) and self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return self


class HistoricalDecisionArtifact(BaseModel):
    """Frozen input/output artifact from which a decision snapshot is projected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_decision_artifact_v1"] = "historical_decision_artifact_v1"
    artifact_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    decision_time: datetime
    as_of: date
    available_at: DateTimeLike | None = None
    normalized_input: NormalizedCompanyInput | None = None
    analysis: CompanyAnalysis | None = None
    research_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    historical_business_quality_valid: StrictBool = False

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.decision_time.date() < self.as_of:
            raise ValueError("decision_time must not precede as_of")
        if self.normalized_input is None and self.analysis is None:
            raise ValueError("historical decision artifact requires normalized_input or analysis")
        if self.normalized_input is not None:
            if self.normalized_input.company.primary_listing != self.listing_id:
                raise ValueError("normalized input listing does not match artifact")
            if self.normalized_input.as_of != self.as_of:
                raise ValueError("normalized input as_of does not match artifact")
        if self.analysis is not None:
            if self.analysis.company.primary_listing != self.listing_id:
                raise ValueError("analysis listing does not match artifact")
            if self.analysis.as_of != self.as_of:
                raise ValueError("analysis as_of does not match artifact")
            if (
                self.analysis.business_quality is not None
                and not self.historical_business_quality_valid
            ):
                raise ValueError(
                    "historical Business Quality requires a frozen valid research artifact"
                )
            if self.historical_business_quality_valid and self.research_artifact_id is None:
                raise ValueError(
                    "historical Business Quality validity requires research_artifact_id"
                )
        if self.normalized_input is not None and self.analysis is not None:
            if self.normalized_input.analysis_id != self.analysis.analysis_id:
                raise ValueError("normalized input and analysis IDs do not match")
        if isinstance(self.available_at, datetime) and self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return self


class BacktestDatasetManifest(BaseModel):
    """Complete frozen data boundary for an offline backtest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["backtest_dataset_manifest_v1"] = "backtest_dataset_manifest_v1"
    dataset_id: StrictStr = Field(min_length=1)
    dataset_version: StrictStr = Field(min_length=1)
    start_date: date
    end_date: date
    timezone: StrictStr = Field(default="UTC", min_length=1)
    calendar_id: StrictStr = Field(min_length=1)
    universe_id: StrictStr = Field(min_length=1)
    universe_coverage: UniverseCoverage
    listing_lifecycles: list[ListingLifecycle] = Field(min_length=1, max_length=100_000)
    universe_memberships: list[UniverseMembership] = Field(
        default_factory=list, max_length=1_000_000
    )
    availability: list[HistoricalAvailability] = Field(default_factory=list, max_length=1_000_000)
    market_bars: list[MarketBar] = Field(default_factory=list, max_length=10_000_000)
    corporate_actions: list[CorporateAction] = Field(default_factory=list, max_length=1_000_000)
    fx_observations: list[FXObservation] = Field(default_factory=list, max_length=1_000_000)
    benchmarks: list[BenchmarkObservation] = Field(default_factory=list, max_length=1_000_000)
    decision_artifacts: list[HistoricalDecisionArtifact] = Field(
        default_factory=list, max_length=1_000_000
    )
    source_artifact_ids: list[StrictStr] = Field(default_factory=list, max_length=1_000_000)
    financial_artifact_ids: list[StrictStr] = Field(default_factory=list, max_length=1_000_000)
    business_quality_artifact_ids: list[StrictStr] = Field(
        default_factory=list, max_length=1_000_000
    )
    missing_data_summary: dict[str, StrictInt] = Field(default_factory=dict)
    limitations: list[StrictStr] = Field(default_factory=list, max_length=256)
    survivorship_bias_note: StrictStr | None = Field(default=None, max_length=2_000)
    claims_survivorship_bias_free: StrictBool = False
    allow_undated_evidence: StrictBool = False
    undated_evidence_attestation: StrictStr | None = Field(default=None, min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("dataset end_date must not precede start_date")
        if self.universe_coverage is UniverseCoverage.CURRENT_UNIVERSE:
            raise ValueError("current-universe substitution is not a historical dataset")
        if (
            self.claims_survivorship_bias_free
            and self.universe_coverage is not UniverseCoverage.HISTORICAL
        ):
            raise ValueError("survivorship-free claims require HISTORICAL universe coverage")
        if (
            self.universe_coverage is UniverseCoverage.HISTORICAL
            and self.claims_survivorship_bias_free
            and not self.universe_memberships
        ):
            raise ValueError("survivorship-free historical coverage requires membership intervals")
        if self.allow_undated_evidence and not self.undated_evidence_attestation:
            raise ValueError("allow_undated_evidence requires an explicit attestation")
        if not self.allow_undated_evidence and self.undated_evidence_attestation is not None:
            raise ValueError("undated_evidence_attestation requires allow_undated_evidence")
        _unique(self.source_artifact_ids, "source_artifact_ids")
        _unique(self.financial_artifact_ids, "financial_artifact_ids")
        _unique(self.business_quality_artifact_ids, "business_quality_artifact_ids")
        lifecycle_by_listing = {item.listing_id: item for item in self.listing_lifecycles}
        if len(lifecycle_by_listing) != len(self.listing_lifecycles):
            raise ValueError("listing_lifecycles must contain one record per listing")
        for bar in self.market_bars:
            lifecycle = lifecycle_by_listing.get(bar.listing_id)
            if lifecycle is None:
                raise ValueError(f"market bar references unknown listing: {bar.listing_id}")
            if bar.market is not lifecycle.market or bar.currency != lifecycle.currency:
                raise ValueError("market bar market/currency does not match listing lifecycle")
            if not lifecycle.is_listed_on(bar.trading_date):
                raise ValueError("market bar lies outside listing lifecycle")
        for action in self.corporate_actions:
            lifecycle = lifecycle_by_listing.get(action.listing_id)
            if lifecycle is None:
                raise ValueError(
                    f"corporate action references unknown listing: {action.listing_id}"
                )
            if action.effective_date < lifecycle.listing_date:
                raise ValueError("corporate action precedes listing date")
            if (
                lifecycle.delisting_date is not None
                and action.effective_date > lifecycle.delisting_date
            ):
                raise ValueError("corporate action follows listing terminal date")
            if action.currency is not None and action.currency != lifecycle.currency:
                raise ValueError("corporate action currency does not match listing lifecycle")
        for fx in self.fx_observations:
            if fx.listing_id is None:
                continue
            lifecycle = lifecycle_by_listing.get(fx.listing_id)
            if lifecycle is None:
                raise ValueError(f"FX observation references unknown listing: {fx.listing_id}")
            if fx.base_currency != lifecycle.currency:
                raise ValueError("FX base currency does not match listing lifecycle")
            if not lifecycle.is_listed_on(fx.observation_date):
                raise ValueError("FX observation lies outside listing lifecycle")
        for listing_id in lifecycle_by_listing:
            listing_bars = [bar for bar in self.market_bars if bar.listing_id == listing_id]
            adjusted_scopes = {
                scope.upper()
                for bar in listing_bars
                if bar.price_basis is PriceBasis.ADJUSTED
                for scope in bar.adjustment_scope
            }
            if not adjusted_scopes:
                continue
            represented_actions = {
                "CASH_DIVIDEND": {
                    "CASH_DIVIDEND",
                    "CASH_DIVIDENDS",
                    "DIVIDEND",
                    "DIVIDENDS",
                    "TOTAL_RETURN",
                    "CORPORATE_ACTIONS",
                    "ALL",
                },
                "SPLIT": {"SPLIT", "SPLITS", "TOTAL_RETURN", "CORPORATE_ACTIONS", "ALL"},
                "CONSOLIDATION": {
                    "CONSOLIDATION",
                    "SPLITS",
                    "TOTAL_RETURN",
                    "CORPORATE_ACTIONS",
                    "ALL",
                },
            }
            for action in self.corporate_actions:
                if action.listing_id != listing_id:
                    continue
                represented = represented_actions.get(action.action_type.value, set())
                if adjusted_scopes.intersection(represented):
                    raise ValueError(
                        "adjusted prices and explicit corporate actions would double count "
                        f"{action.action_type.value} ({action.action_id})"
                    )
        artifact_ids = [item.artifact_id for item in self.decision_artifacts]
        _unique(artifact_ids, "decision_artifact IDs")
        expected_hash = _hash_model(self, "content_sha256")
        if self.content_sha256 != expected_hash:
            raise ValueError("content_sha256 does not match manifest content")
        return self

    @property
    def manifest_id(self) -> str:
        return self.dataset_id

    @classmethod
    def build(
        cls,
        *,
        dataset_id: str,
        dataset_version: str,
        start_date: date,
        end_date: date,
        calendar_id: str,
        universe_id: str,
        universe_coverage: UniverseCoverage,
        listing_lifecycles: list[ListingLifecycle],
        universe_memberships: list[UniverseMembership] | None = None,
        availability: list[HistoricalAvailability] | None = None,
        market_bars: list[MarketBar] | None = None,
        corporate_actions: list[CorporateAction] | None = None,
        fx_observations: list[FXObservation] | None = None,
        benchmarks: list[BenchmarkObservation] | None = None,
        decision_artifacts: list[HistoricalDecisionArtifact] | None = None,
        source_artifact_ids: list[str] | None = None,
        financial_artifact_ids: list[str] | None = None,
        business_quality_artifact_ids: list[str] | None = None,
        missing_data_summary: dict[str, int] | None = None,
        limitations: list[str] | None = None,
        survivorship_bias_note: str | None = None,
        claims_survivorship_bias_free: bool = False,
        allow_undated_evidence: bool = False,
        undated_evidence_attestation: str | None = None,
        timezone: str = "UTC",
    ) -> BacktestDatasetManifest:
        """Build a schema-ready manifest and derive its content hash."""

        candidate = cls.model_construct(
            contract="backtest_dataset_manifest_v1",
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            calendar_id=calendar_id,
            universe_id=universe_id,
            universe_coverage=universe_coverage,
            listing_lifecycles=listing_lifecycles,
            universe_memberships=universe_memberships or [],
            availability=availability or [],
            market_bars=market_bars or [],
            corporate_actions=corporate_actions or [],
            fx_observations=fx_observations or [],
            benchmarks=benchmarks or [],
            decision_artifacts=decision_artifacts or [],
            source_artifact_ids=source_artifact_ids or [],
            financial_artifact_ids=financial_artifact_ids or [],
            business_quality_artifact_ids=business_quality_artifact_ids or [],
            missing_data_summary=missing_data_summary or {},
            limitations=limitations or [],
            survivorship_bias_note=survivorship_bias_note,
            claims_survivorship_bias_free=claims_survivorship_bias_free,
            allow_undated_evidence=allow_undated_evidence,
            undated_evidence_attestation=undated_evidence_attestation,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)

    def lifecycle(self, listing_id: str) -> ListingLifecycle:
        for item in self.listing_lifecycles:
            if item.listing_id == listing_id:
                return item
        raise KeyError(f"unknown listing: {listing_id}")

    def memberships_on(self, value: date) -> tuple[str, ...]:
        included = {
            item.listing_id
            for item in self.universe_memberships
            if item.universe_id == self.universe_id and item.included and item.includes(value)
        }
        if (
            not self.universe_memberships
            and self.universe_coverage is UniverseCoverage.FIXED_RESEARCH_UNIVERSE
        ):
            included = {
                item.listing_id for item in self.listing_lifecycles if item.is_listed_on(value)
            }
        return tuple(sorted(included))

    def bars_for(self, listing_id: str) -> tuple[MarketBar, ...]:
        return tuple(
            sorted(
                (item for item in self.market_bars if item.listing_id == listing_id),
                key=lambda item: (item.trading_date, str(item.execution_time), item.bar_id),
            )
        )

    def actions_for(self, listing_id: str) -> tuple[CorporateAction, ...]:
        return tuple(
            sorted(
                (item for item in self.corporate_actions if item.listing_id == listing_id),
                key=lambda item: (item.effective_date, item.action_id),
            )
        )

    def validate_for_decision(self, decision_time: datetime) -> None:
        """Fail closed when a frozen input was not available at a signal time."""

        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        for artifact in self.decision_artifacts:
            if artifact.decision_time > decision_time:
                continue
            if artifact.available_at is None:
                raise ValueError(
                    f"decision artifact has unknown availability: {artifact.artifact_id}"
                )
            if _compare_time(artifact.available_at, decision_time) > 0:
                raise ValueError(f"decision artifact is future-dated: {artifact.artifact_id}")
            source = artifact.normalized_input
            if source is None:
                continue
            for evidence in source.evidence_index:
                published = evidence.source.published_date
                if published is None and not self.allow_undated_evidence:
                    raise ValueError(f"undated evidence is unavailable by default: {evidence.id}")
                if published is not None and published >= decision_time.date():
                    raise ValueError(f"future evidence is unavailable: {evidence.id}")


def _compare_time(value: DateTimeLike, boundary: datetime) -> int:
    if isinstance(value, datetime):
        candidate = value
        if candidate.tzinfo is None:
            raise ValueError("availability datetime must be timezone-aware")
        candidate = candidate.astimezone(boundary.tzinfo)
    else:
        # A date-only availability value cannot establish an intraday time.
        # Its earliest conservative use is the following calendar session.
        candidate = datetime.combine(
            value + timedelta(days=1),
            datetime.min.time(),
            tzinfo=boundary.tzinfo,
        )
    return (candidate > boundary) - (candidate < boundary)


class DecisionSnapshot(BaseModel):
    """A non-mutating projection of an existing deterministic CompanyAnalysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["decision_snapshot_v1"] = "decision_snapshot_v1"
    snapshot_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    company_id: StrictStr | None = Field(default=None, min_length=1)
    decision_time: datetime
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    input_artifact_id: StrictStr = Field(min_length=1)
    input_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    analysis_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    research_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    final_state: StrictStr = Field(min_length=1)
    valuation_state: StrictStr | None = Field(default=None, min_length=1)
    valuation_tier: StrictStr | None = Field(default=None, min_length=1)
    gate_statuses: dict[str, StrictStr]
    gate_failure_reasons: dict[str, list[StrictStr]] = Field(default_factory=dict)
    selected_metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
    business_quality_evaluated: StrictBool = False
    unresolved_flags: list[StrictStr] = Field(default_factory=list)
    flags: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.decision_time.date() < self.as_of:
            raise ValueError("decision_time must not precede as_of")
        if len(self.gate_statuses) == 0:
            raise ValueError("decision snapshot requires gate statuses")
        for value in self.selected_metrics.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("selected_metrics must contain finite values")
        _unique(self.unresolved_flags, "unresolved_flags")
        _unique(self.flags, "flags")
        if self.business_quality_evaluated and self.research_artifact_id is None:
            raise ValueError("evaluated historical Business Quality requires research_artifact_id")
        return self


class ForwardReturnObservation(BaseModel):
    """One signal-to-forward-outcome observation, including missingness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["forward_return_observation_v1"] = "forward_return_observation_v1"
    observation_id: StrictStr = Field(min_length=1)
    snapshot_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    decision_time: datetime
    horizon: StrictStr = Field(pattern=r"^[0-9]+[DWMY]$")
    target_date: date
    entry_date: date | None = None
    exit_date: date | None = None
    entry_price: StrictFloat | None = Field(default=None, gt=0)
    exit_price: StrictFloat | None = Field(default=None, gt=0)
    price_return: StrictFloat | None = None
    total_return: StrictFloat | None = None
    dividends_per_share: StrictFloat = Field(default=0, ge=0)
    share_multiplier: StrictFloat = Field(default=1, gt=0)
    terminal_value_per_share: StrictFloat = Field(default=0, ge=0)
    entry_bar_id: StrictStr | None = Field(default=None, min_length=1)
    exit_bar_id: StrictStr | None = Field(default=None, min_length=1)
    corporate_action_ids: list[StrictStr] = Field(default_factory=list)
    status: SignalOutcomeStatus
    missing_reason: StrictStr | None = Field(default=None, min_length=1)
    currency: StrictStr | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        _unique(self.corporate_action_ids, "corporate_action_ids")
        if self.status in {SignalOutcomeStatus.COMPLETE, SignalOutcomeStatus.DELISTED_TERMINAL}:
            if self.entry_date is None or self.exit_date is None:
                raise ValueError("complete return observations require entry and exit dates")
            if self.entry_price is None or self.exit_price is None:
                raise ValueError("complete return observations require entry and exit prices")
            if self.price_return is None or self.total_return is None:
                raise ValueError("complete return observations require return values")
        elif self.missing_reason is None:
            raise ValueError("incomplete observations require missing_reason")
        for field_name in ("price_return", "total_return"):
            _finite(getattr(self, field_name), field_name)
        return self


class CalibrationObservation(BaseModel):
    """One point-in-time target and feature row available to calibration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["calibration_observation_v1"] = "calibration_observation_v1"
    observation_id: StrictStr = Field(min_length=1)
    observed_at: date
    target_return: StrictFloat
    eligible: StrictBool = True
    feature_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    source_observation_id: StrictStr | None = Field(default=None, min_length=1)
    source_hash: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_calibration_observation(self) -> Self:
        _finite(self.target_return, "target_return")
        for key, value in self.feature_values.items():
            if not key:
                raise ValueError("feature_values keys must not be empty")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"feature_values.{key} must be finite")
        return self


class SignalBucket(BaseModel):
    """Aggregated signal bucket used for auditable attribution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bucket_key: StrictStr = Field(min_length=1)
    horizon: StrictStr = Field(pattern=r"^[0-9]+[DWMY]$")
    observation_count: StrictInt = Field(ge=0)
    complete_count: StrictInt = Field(ge=0)
    mean_price_return: StrictFloat | None = None
    median_price_return: StrictFloat | None = None
    mean_total_return: StrictFloat | None = None
    median_total_return: StrictFloat | None = None
    positive_total_return_rate: StrictFloat | None = Field(default=None, ge=0, le=1)
    failure_rate: StrictFloat | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_bucket(self) -> Self:
        if self.complete_count > self.observation_count:
            raise ValueError("complete_count cannot exceed observation_count")
        for field_name in (
            "mean_price_return",
            "median_price_return",
            "mean_total_return",
            "median_total_return",
        ):
            _finite(getattr(self, field_name), field_name)
        return self


class TransactionCostPolicy(BaseModel):
    """Explicit, versioned transaction-cost assumptions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["transaction_cost_policy_v1"] = "transaction_cost_policy_v1"
    commission_bps: StrictFloat = Field(default=0, ge=0)
    sell_stamp_duty_bps: StrictFloat = Field(default=0, ge=0)
    transfer_fee_bps: StrictFloat = Field(default=0, ge=0)
    slippage_bps: StrictFloat = Field(default=0, ge=0)
    minimum_fee: StrictFloat = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_costs(self) -> Self:
        for field_name in (
            "commission_bps",
            "sell_stamp_duty_bps",
            "transfer_fee_bps",
            "slippage_bps",
            "minimum_fee",
        ):
            _finite(getattr(self, field_name), field_name)
        if self.slippage_bps >= 10_000:
            raise ValueError("slippage_bps must be below 10000 for positive sell prices")
        return self


class LiquidityPolicy(BaseModel):
    """Participation and missing-liquidity behavior for fills."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["liquidity_policy_v1"] = "liquidity_policy_v1"
    max_participation_rate: StrictFloat = Field(default=1, gt=0, le=1)
    min_daily_volume: StrictFloat | None = Field(default=None, ge=0)
    min_daily_amount: StrictFloat | None = Field(default=None, ge=0)
    max_order_notional: StrictFloat | None = Field(default=None, gt=0)
    missing_data_action: MissingDataAction = MissingDataAction.NO_FILL


class PortfolioPolicy(BaseModel):
    """Separate portfolio/execution policy; never folded into strict-v1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["portfolio_policy_v1"] = "portfolio_policy_v1"
    policy_id: StrictStr = Field(min_length=1)
    policy_version: StrictStr = Field(default=PORTFOLIO_POLICY_CONTRACT_VERSION, min_length=1)
    base_currency: StrictStr = Field(min_length=3, max_length=3)
    initial_cash: StrictFloat = Field(gt=0)
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY
    eligible_states: list[StrictStr] = Field(min_length=1, max_length=16)
    sizing_rule: SizingRule = SizingRule.EQUAL_WEIGHT
    max_position_weight: StrictFloat = Field(default=1, gt=0, le=1)
    max_sector_weight: StrictFloat | None = Field(default=None, gt=0, le=1)
    execution_price: ExecutionPrice = ExecutionPrice.NEXT_OPEN
    transaction_costs: TransactionCostPolicy = Field(default_factory=TransactionCostPolicy)
    liquidity: LiquidityPolicy = Field(default_factory=LiquidityPolicy)
    cash_buffer: StrictFloat = Field(default=0, ge=0, lt=1)
    lot_size_a: StrictInt = Field(default=100, gt=0)
    lot_size_h: StrictInt = Field(default=1, gt=0)
    dividends_to_cash: StrictBool = True
    allow_short: StrictBool = False
    allow_leverage: StrictBool = False
    terminal_value_policy: Literal["USE_EXPLICIT_ACTION", "NO_VALUE"] = "USE_EXPLICIT_ACTION"
    rights_issue_policy: Literal["FAIL", "IGNORE", "SUBSCRIBE_IF_FUNDED"] = "FAIL"
    share_issuance_policy: Literal["FAIL", "IGNORE", "APPLY_FACTOR"] = "FAIL"

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        _unique(self.eligible_states, "eligible_states")
        if self.allow_short or self.allow_leverage:
            raise ValueError("portfolio-policy-v1 is long-only and unlevered")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        return self


class PortfolioEvent(BaseModel):
    """Replayable event emitted by the deterministic simulator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["portfolio_event_v1"] = "portfolio_event_v1"
    event_id: StrictStr = Field(min_length=1)
    timestamp: datetime
    event_type: PortfolioEventType
    listing_id: StrictStr | None = Field(default=None, min_length=1)
    side: Literal["BUY", "SELL", "NONE"] = "NONE"
    quantity: StrictFloat = Field(default=0, ge=0)
    price: StrictFloat | None = Field(default=None, gt=0)
    gross_value: StrictFloat = Field(default=0, ge=0)
    fees: StrictFloat = Field(default=0, ge=0)
    cash_delta: StrictFloat = 0
    action_id: StrictStr | None = Field(default=None, min_length=1)
    bar_id: StrictStr | None = Field(default=None, min_length=1)
    reason: StrictStr | None = Field(default=None, min_length=1)
    source_hashes: list[StrictStr] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.timestamp.tzinfo is None:
            raise ValueError("portfolio event timestamp must be timezone-aware")
        _unique(self.source_hashes, "source_hashes")
        for field_name in ("quantity", "price", "gross_value", "fees", "cash_delta"):
            _finite(getattr(self, field_name), field_name)
        if self.event_type is PortfolioEventType.FILL and self.listing_id is None:
            raise ValueError("fill events require listing_id")
        return self


class PositionSnapshot(BaseModel):
    """One listing position at a portfolio valuation timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    listing_id: StrictStr = Field(min_length=1)
    market: Market
    sector: StrictStr | None = None
    quantity: StrictFloat = Field(ge=0)
    mark_price: StrictFloat | None = Field(default=None, gt=0)
    market_value: StrictFloat = Field(ge=0)
    average_cost: StrictFloat = Field(ge=0)
    suspended: StrictBool = False
    price_missing: StrictBool = False


class PortfolioSnapshot(BaseModel):
    """Portfolio state required to replay P&L and inspect cash drag."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["portfolio_snapshot_v1"] = "portfolio_snapshot_v1"
    timestamp: datetime
    cash: StrictFloat = Field(ge=0)
    gross_exposure: StrictFloat = Field(ge=0)
    net_asset_value: StrictFloat = Field(gt=0)
    positions: list[PositionSnapshot] = Field(default_factory=list)
    daily_return: StrictFloat | None = None
    cumulative_return: StrictFloat | None = None
    cash_exposure: StrictFloat = Field(ge=0, le=1)
    turnover: StrictFloat = Field(default=0, ge=0)
    missing_price_listings: list[StrictStr] = Field(default_factory=list)
    source_bar_ids: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.timestamp.tzinfo is None:
            raise ValueError("portfolio snapshot timestamp must be timezone-aware")
        _unique(self.missing_price_listings, "missing_price_listings")
        _unique(self.source_bar_ids, "source_bar_ids")
        for field_name in ("daily_return", "cumulative_return"):
            _finite(getattr(self, field_name), field_name)
        if self.cash > self.net_asset_value + 1e-9:
            raise ValueError("cash cannot exceed net_asset_value")
        return self


class PerformanceMetrics(BaseModel):
    """Deterministic performance and coverage metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["performance_metrics_v1"] = "performance_metrics_v1"
    observation_count: StrictInt = Field(ge=0)
    complete_observation_count: StrictInt = Field(ge=0)
    cagr: StrictFloat | None = None
    max_drawdown: StrictFloat | None = None
    volatility: StrictFloat | None = None
    sharpe: StrictFloat | None = None
    sortino: StrictFloat | None = None
    turnover: StrictFloat = Field(default=0, ge=0)
    hit_rate: StrictFloat | None = Field(default=None, ge=0, le=1)
    excess_return: StrictFloat | None = None
    tracking_error: StrictFloat | None = None
    max_sector_concentration: StrictFloat | None = Field(default=None, ge=0, le=1)
    max_position_concentration: StrictFloat | None = Field(default=None, ge=0, le=1)
    average_cash_exposure: StrictFloat | None = Field(default=None, ge=0, le=1)
    coverage_ratio: StrictFloat | None = Field(default=None, ge=0, le=1)
    missing_data_ratio: StrictFloat | None = Field(default=None, ge=0, le=1)
    factor_exposure: dict[str, StrictFloat] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if self.complete_observation_count > self.observation_count:
            raise ValueError("complete_observation_count cannot exceed observation_count")
        for field_name in (
            "cagr",
            "max_drawdown",
            "volatility",
            "sharpe",
            "sortino",
            "excess_return",
            "tracking_error",
        ):
            _finite(getattr(self, field_name), field_name)
        for key, value in self.factor_exposure.items():
            if not key:
                raise ValueError("factor_exposure keys must not be empty")
            _finite(value, f"factor_exposure.{key}")
        return self


class BenchmarkResult(BaseModel):
    """Benchmark return result with explicit return type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["benchmark_result_v1"] = "benchmark_result_v1"
    benchmark_id: StrictStr = Field(min_length=1)
    return_type: BenchmarkReturnType
    currency: StrictStr = Field(min_length=3, max_length=3)
    start_value: StrictFloat | None = Field(default=None, gt=0)
    end_value: StrictFloat | None = Field(default=None, gt=0)
    total_return: StrictFloat | None = None
    cagr: StrictFloat | None = None
    coverage_ratio: StrictFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_benchmark_result(self) -> Self:
        for field_name in ("total_return", "cagr"):
            _finite(getattr(self, field_name), field_name)
        return self


class FailureAttribution(BaseModel):
    """Structured attribution of exclusions, losses, missingness and sensitivity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["failure_attribution_v1"] = "failure_attribution_v1"
    excluded_later_winners: dict[str, StrictFloat] = Field(default_factory=dict)
    largest_passed_losses: dict[str, StrictFloat] = Field(default_factory=dict)
    manual_review_coverage: dict[str, StrictFloat] = Field(default_factory=dict)
    by_valuation_tier: dict[str, StrictFloat] = Field(default_factory=dict)
    by_business_quality_bucket: dict[str, StrictFloat] = Field(default_factory=dict)
    by_sector: dict[str, StrictFloat] = Field(default_factory=dict)
    by_market: dict[str, StrictFloat] = Field(default_factory=dict)
    by_listing: dict[str, StrictFloat] = Field(default_factory=dict)
    cost_liquidity_sensitivity: dict[str, StrictFloat] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_attribution(self) -> Self:
        for mapping_name in (
            "excluded_later_winners",
            "largest_passed_losses",
            "manual_review_coverage",
            "by_valuation_tier",
            "by_business_quality_bucket",
            "by_sector",
            "by_market",
            "by_listing",
            "cost_liquidity_sensitivity",
        ):
            mapping = getattr(self, mapping_name)
            for key, value in mapping.items():
                if not key:
                    raise ValueError(f"{mapping_name} keys must not be empty")
                _finite(value, f"{mapping_name}.{key}")
        return self


class SignalEvaluationResult(BaseModel):
    """Reproducible signal-level evaluation before portfolio construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["signal_evaluation_result_v1"] = "signal_evaluation_result_v1"
    evaluation_id: StrictStr = Field(min_length=1)
    manifest_id: StrictStr = Field(min_length=1)
    profile_id: StrictStr = Field(min_length=1)
    snapshot_ids: list[StrictStr] = Field(default_factory=list)
    horizons: list[StrictStr] = Field(min_length=1)
    observations: list[ForwardReturnObservation] = Field(default_factory=list)
    buckets: list[SignalBucket] = Field(default_factory=list)
    coverage: dict[str, StrictFloat] = Field(default_factory=dict)
    failure_attribution: FailureAttribution = Field(default_factory=FailureAttribution)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_signal_result(self) -> Self:
        _unique(self.snapshot_ids, "snapshot_ids")
        _unique(self.horizons, "horizons")
        for key, value in self.coverage.items():
            if key != "snapshot_count" and not 0 <= value <= 1:
                raise ValueError(f"coverage.{key} must be between 0 and 1")
        expected = _hash_model(self, "content_sha256")
        if self.content_sha256 != expected:
            raise ValueError("signal evaluation content_sha256 does not match result content")
        return self


class PortfolioSimulationResult(BaseModel):
    """Replayable long-only portfolio simulation output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["portfolio_simulation_result_v1"] = "portfolio_simulation_result_v1"
    simulation_id: StrictStr = Field(min_length=1)
    manifest_id: StrictStr = Field(min_length=1)
    policy_id: StrictStr = Field(min_length=1)
    policy_version: StrictStr = Field(min_length=1)
    policy_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    start_date: date
    end_date: date
    events: list[PortfolioEvent] = Field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = Field(default_factory=list)
    metrics: PerformanceMetrics
    benchmark_results: list[BenchmarkResult] = Field(default_factory=list)
    failure_attribution: FailureAttribution = Field(default_factory=FailureAttribution)
    final_net_asset_value: StrictFloat = Field(gt=0)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_simulation(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("simulation end_date must not precede start_date")
        if self.snapshots and self.snapshots[0].timestamp.date() < self.start_date:
            raise ValueError("portfolio snapshot precedes simulation start")
        if self.snapshots and self.snapshots[-1].timestamp.date() > self.end_date:
            raise ValueError("portfolio snapshot exceeds simulation end")
        expected = _hash_model(self, "content_sha256")
        if self.content_sha256 != expected:
            raise ValueError("portfolio simulation content_sha256 does not match result content")
        return self


class BacktestRunSpec(BaseModel):
    """Offline run specification tying a manifest to signal/portfolio work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["backtest_run_spec_v1"] = "backtest_run_spec_v1"
    run_id: StrictStr = Field(min_length=1)
    manifest_id: StrictStr = Field(min_length=1)
    profile_id: StrictStr = Field(min_length=1)
    start_date: date
    end_date: date
    horizons: list[StrictStr] = Field(default_factory=lambda: ["1M", "3M", "6M", "12M"])
    snapshot_ids: list[StrictStr] = Field(default_factory=list)
    portfolio_policy_id: StrictStr | None = Field(default=None, min_length=1)
    benchmark_ids: list[StrictStr] = Field(default_factory=list)
    run_signal_evaluation: StrictBool = True
    run_portfolio_simulation: StrictBool = False
    assumptions: dict[str, object] = Field(default_factory=dict)
    spec_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_run_spec(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("backtest run end_date must not precede start_date")
        _unique(self.horizons, "horizons")
        _unique(self.snapshot_ids, "snapshot_ids")
        _unique(self.benchmark_ids, "benchmark_ids")
        if self.run_portfolio_simulation and self.portfolio_policy_id is None:
            raise ValueError("portfolio simulation requires portfolio_policy_id")
        expected = _hash_model(self, "spec_sha256")
        if self.spec_sha256 != expected:
            raise ValueError("backtest run spec hash does not match specification content")
        return self

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        manifest_id: str,
        profile_id: str,
        start_date: date,
        end_date: date,
        horizons: list[str] | None = None,
        snapshot_ids: list[str] | None = None,
        portfolio_policy_id: str | None = None,
        benchmark_ids: list[str] | None = None,
        run_signal_evaluation: bool = True,
        run_portfolio_simulation: bool = False,
        assumptions: dict[str, object] | None = None,
    ) -> BacktestRunSpec:
        """Construct a run specification and derive its immutable hash."""

        payload = {
            "contract": "backtest_run_spec_v1",
            "run_id": run_id,
            "manifest_id": manifest_id,
            "profile_id": profile_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "horizons": horizons or ["1M", "3M", "6M", "12M"],
            "snapshot_ids": snapshot_ids or [],
            "portfolio_policy_id": portfolio_policy_id,
            "benchmark_ids": benchmark_ids or [],
            "run_signal_evaluation": run_signal_evaluation,
            "run_portfolio_simulation": run_portfolio_simulation,
            "assumptions": assumptions or {},
        }
        payload["spec_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return cls.model_validate(payload)


class BacktestResult(BaseModel):
    """Combined signal/portfolio result for one immutable run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["backtest_result_v1"] = "backtest_result_v1"
    run_id: StrictStr = Field(min_length=1)
    manifest_id: StrictStr = Field(min_length=1)
    run_spec_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    signal_evaluation: SignalEvaluationResult | None = None
    portfolio_simulation: PortfolioSimulationResult | None = None
    metrics: PerformanceMetrics | None = None
    failure_attribution: FailureAttribution = Field(default_factory=FailureAttribution)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.signal_evaluation is None and self.portfolio_simulation is None:
            raise ValueError("backtest result requires signal or portfolio output")
        expected = _hash_model(self, "content_sha256")
        if self.content_sha256 != expected:
            raise ValueError("backtest result content_sha256 does not match result content")
        return self


class CalibrationSearchSpace(BaseModel):
    """Explicit finite candidate values; no hidden mutation of strict-v1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["calibration_search_space_v1"] = "calibration_search_space_v1"
    space_id: StrictStr = Field(min_length=1)
    base_profile_id: StrictStr = Field(min_length=1)
    parameters: dict[str, list[float | int | str | bool]] = Field(min_length=1, max_length=64)
    max_trials: StrictInt = Field(default=10_000, gt=0, le=1_000_000)
    objective: Literal["MEAN_RETURN", "MEDIAN_RETURN", "HIT_RATE", "RISK_ADJUSTED"] = (
        "RISK_ADJUSTED"
    )

    @model_validator(mode="after")
    def validate_search_space(self) -> Self:
        for name, values in self.parameters.items():
            if not name or not values:
                raise ValueError("calibration parameter names and value lists must be non-empty")
            if len(values) != len({canonical_json_bytes(value) for value in values}):
                raise ValueError(f"calibration values for {name} must be unique")
        return self


class ChronologicalSplit(BaseModel):
    """Non-overlapping train/validation/holdout time ranges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["chronological_split_v1"] = "chronological_split_v1"
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    holdout_start: date
    holdout_end: date

    @model_validator(mode="after")
    def validate_chronology(self) -> Self:
        if not (
            self.train_start
            <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.holdout_start
            <= self.holdout_end
        ):
            raise ValueError(
                "train, validation and holdout ranges must be chronological and disjoint"
            )
        return self

    def stage_for(self, value: date) -> CalibrationStage | None:
        if self.train_start <= value <= self.train_end:
            return CalibrationStage.SEARCH
        if self.validation_start <= value <= self.validation_end:
            return CalibrationStage.SEARCH
        if self.holdout_start <= value <= self.holdout_end:
            return CalibrationStage.HOLDOUT_EVALUATION
        return None


class CalibrationTrial(BaseModel):
    """One candidate result; search trials never contain holdout outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["calibration_trial_v1"] = "calibration_trial_v1"
    trial_id: StrictStr = Field(min_length=1)
    experiment_id: StrictStr = Field(min_length=1)
    candidate_profile_id: StrictStr = Field(min_length=1)
    parameters: dict[str, float | int | str | bool]
    stage: CalibrationStage = CalibrationStage.SEARCH
    train_count: StrictInt = Field(ge=0)
    validation_count: StrictInt = Field(ge=0)
    holdout_count: StrictInt = Field(default=0, ge=0)
    train_score: StrictFloat | None = None
    validation_score: StrictFloat | None = None
    holdout_score: StrictFloat | None = None
    stability_penalty: StrictFloat = 0
    objective_score: StrictFloat | None = None
    observation_ids: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trial(self) -> Self:
        if self.stage is CalibrationStage.SEARCH and (
            self.holdout_count != 0 or self.holdout_score is not None
        ):
            raise ValueError("search trial cannot contain holdout observations or score")
        if self.stage is CalibrationStage.HOLDOUT_EVALUATION and self.holdout_count == 0:
            raise ValueError("holdout evaluation trial requires holdout observations")
        for field_name in (
            "train_score",
            "validation_score",
            "holdout_score",
            "stability_penalty",
            "objective_score",
        ):
            _finite(getattr(self, field_name), field_name)
        _unique(self.observation_ids, "observation_ids")
        return self


class CandidateProfileProposal(BaseModel):
    """Calibration output that is a proposal, never an automatic rule change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["candidate_profile_proposal_v1"] = "candidate_profile_proposal_v1"
    proposal_id: StrictStr = Field(min_length=1)
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    candidate_profile_id: StrictStr = Field(min_length=1)
    parameter_overrides: dict[str, float | int | str | bool]
    train_score: StrictFloat | None = None
    validation_score: StrictFloat | None = None
    holdout_score: StrictFloat | None = None
    stability_summary: dict[str, float] = Field(default_factory=dict)
    rationale: StrictStr = Field(min_length=1, max_length=8_000)
    status: Literal["PROPOSAL_ONLY", "HUMAN_APPROVED", "REJECTED"] = "PROPOSAL_ONLY"
    automatic_application_allowed: StrictBool = False

    @model_validator(mode="after")
    def validate_proposal(self) -> Self:
        if self.candidate_profile_id == self.base_profile_id:
            raise ValueError("candidate profile must be distinct from base profile")
        if self.automatic_application_allowed:
            raise ValueError("candidate profile proposals cannot authorize automatic application")
        for key, value in self.stability_summary.items():
            _finite(value, f"stability_summary.{key}")
        for field_name in ("train_score", "validation_score", "holdout_score"):
            _finite(getattr(self, field_name), field_name)
        return self


class CalibrationExperiment(BaseModel):
    """Chronologically guarded calibration experiment and candidate proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["calibration_experiment_v1"] = "calibration_experiment_v1"
    experiment_id: StrictStr = Field(min_length=1)
    manifest_id: StrictStr = Field(min_length=1)
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    search_space: CalibrationSearchSpace
    split: ChronologicalSplit
    trials: list[CalibrationTrial] = Field(default_factory=list, max_length=1_000_000)
    selected_trial_id: StrictStr | None = Field(default=None, min_length=1)
    proposal: CandidateProfileProposal | None = None
    holdout_locked: StrictBool = True
    holdout_observation_ids: list[StrictStr] = Field(default_factory=list)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_experiment(self) -> Self:
        if self.search_space.base_profile_id != self.base_profile_id:
            raise ValueError("search space base profile does not match experiment")
        trial_ids = [item.trial_id for item in self.trials]
        _unique(trial_ids, "trial IDs")
        for trial in self.trials:
            if trial.experiment_id != self.experiment_id:
                raise ValueError("calibration trial does not belong to experiment")
            if trial.stage is not CalibrationStage.SEARCH:
                raise ValueError("calibration experiment trials must remain search-only")
        if self.selected_trial_id is not None and self.selected_trial_id not in trial_ids:
            raise ValueError("selected_trial_id does not reference a trial")
        if self.holdout_locked and self.holdout_observation_ids:
            raise ValueError(
                "holdout observation IDs must remain outside a locked search experiment"
            )
        if self.proposal is not None and self.proposal.base_profile_id != self.base_profile_id:
            raise ValueError("proposal base profile does not match experiment")
        if self.proposal is not None and self.selected_trial_id is not None:
            selected = next(
                trial for trial in self.trials if trial.trial_id == self.selected_trial_id
            )
            if self.proposal.candidate_profile_id != selected.candidate_profile_id:
                raise ValueError("proposal does not match selected calibration trial")
        expected = _hash_model(self, "content_sha256")
        if self.content_sha256 != expected:
            raise ValueError("calibration experiment content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        experiment_id: str,
        manifest_id: str,
        base_profile_id: str,
        base_profile_sha256: str,
        search_space: CalibrationSearchSpace,
        split: ChronologicalSplit,
        trials: list[CalibrationTrial] | None = None,
        selected_trial_id: str | None = None,
        proposal: CandidateProfileProposal | None = None,
        holdout_locked: bool = True,
        holdout_observation_ids: list[str] | None = None,
    ) -> CalibrationExperiment:
        """Construct an experiment with a content hash after search/selection."""

        candidate = cls.model_construct(
            contract="calibration_experiment_v1",
            experiment_id=experiment_id,
            manifest_id=manifest_id,
            base_profile_id=base_profile_id,
            base_profile_sha256=base_profile_sha256,
            search_space=search_space,
            split=split,
            trials=trials or [],
            selected_trial_id=selected_trial_id,
            proposal=proposal,
            holdout_locked=holdout_locked,
            holdout_observation_ids=holdout_observation_ids or [],
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


class CalibrationHoldoutResult(BaseModel):
    """Separate post-selection holdout evaluation, never fed back into search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["calibration_holdout_result_v1"] = "calibration_holdout_result_v1"
    experiment_id: StrictStr = Field(min_length=1)
    proposal_id: StrictStr = Field(min_length=1)
    holdout_start: date
    holdout_end: date
    observation_count: StrictInt = Field(ge=0)
    score: StrictFloat | None = None
    notes: list[StrictStr] = Field(default_factory=list)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_holdout(self) -> Self:
        if self.holdout_end < self.holdout_start:
            raise ValueError("holdout_end must not precede holdout_start")
        _finite(self.score, "score")
        expected = _hash_model(self, "content_sha256")
        if self.content_sha256 != expected:
            raise ValueError("calibration holdout content_sha256 does not match content")
        return self


class BacktestWorkspaceIndex(BaseModel):
    """Optional immutable index for resumable backtest artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["backtest_workspace_index_v1"] = "backtest_workspace_index_v1"
    workspace_id: StrictStr = Field(min_length=1)
    manifest_ids: list[StrictStr] = Field(default_factory=list)
    run_spec_ids: list[StrictStr] = Field(default_factory=list)
    result_ids: list[StrictStr] = Field(default_factory=list)
    calibration_experiment_ids: list[StrictStr] = Field(default_factory=list)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_index(self) -> Self:
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        for field_name in (
            "manifest_ids",
            "run_spec_ids",
            "result_ids",
            "calibration_experiment_ids",
        ):
            _unique(getattr(self, field_name), field_name)
        return self


__all__ = [
    "AvailabilityStatus",
    "BACKTEST_CONTRACT_VERSION",
    "BacktestDatasetManifest",
    "BacktestResult",
    "BacktestRunSpec",
    "BacktestWorkspaceIndex",
    "BenchmarkObservation",
    "BenchmarkResult",
    "BenchmarkReturnType",
    "CalibrationExperiment",
    "CalibrationHoldoutResult",
    "CalibrationObservation",
    "CALIBRATION_CONTRACT_VERSION",
    "CalibrationSearchSpace",
    "CalibrationStage",
    "CalibrationTrial",
    "CandidateProfileProposal",
    "ChronologicalSplit",
    "CorporateAction",
    "CorporateActionType",
    "DATASET_CONTRACT_VERSION",
    "DateTimeLike",
    "DecisionSnapshot",
    "ExecutionPrice",
    "FailureAttribution",
    "ForwardReturnObservation",
    "FXObservation",
    "HistoricalAvailability",
    "HistoricalDecisionArtifact",
    "LiquidityPolicy",
    "ListingLifecycle",
    "Market",
    "MarketBar",
    "MissingDataAction",
    "PerformanceMetrics",
    "PORTFOLIO_POLICY_CONTRACT_VERSION",
    "PortfolioEvent",
    "PortfolioEventType",
    "PortfolioPolicy",
    "PortfolioSimulationResult",
    "PortfolioSnapshot",
    "PositionSnapshot",
    "PriceBasis",
    "RebalanceFrequency",
    "SignalBucket",
    "SignalEvaluationResult",
    "SignalOutcomeStatus",
    "SizingRule",
    "TransactionCostPolicy",
    "UniverseCoverage",
    "UniverseMembership",
]
