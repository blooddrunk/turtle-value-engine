"""Pydantic models corresponding to the repository's JSON contracts.

The model names and serialized field names intentionally follow the existing
schemas under ``schemas/``.  Calculators use the same objects as their input
and output boundary so that a result can be serialized without a second,
untracked transformation layer.
"""

from datetime import date
from typing import Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from .common import (
    AdjustmentStatus,
    AdjustmentType,
    ApprovedBy,
    ConfidenceLevel,
    DecisionState,
    EvidenceDirection,
    EvidenceStrength,
    FactValue,
    GateStatus,
    ProposedBy,
    SourceType,
    ValuationState,
)


class Source(BaseModel):
    """Stable provenance locator for an evidence item."""

    model_config = ConfigDict(extra="forbid")

    type: SourceType
    title: str = Field(min_length=1)
    issuer: str | None = None
    published_date: date | None = None
    fiscal_period: str | None = None
    url: AnyUrl | None = None
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    table_or_note: str | None = None
    locator: str | None = None


class MetricContext(BaseModel):
    """Optional metric context attached to evidence."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    period: str | None = None
    value: FactValue = None
    unit: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class Evidence(BaseModel):
    """Auditable evidence item used by facts, adjustments and judgments."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    direction: EvidenceDirection
    strength: EvidenceStrength
    statement: str = Field(min_length=1)
    metric_context: MetricContext | None = None
    source: Source
    confidence: float = Field(ge=0, le=1)
    notes: str | None = None


class Fact(BaseModel):
    """Sourced fact before strategy interpretation or adjustment."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: FactValue
    unit: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    estimated: bool = False
    estimation_method: str | None = None
    confidence: float = Field(ge=0, le=1)


class Adjustment(BaseModel):
    """Explicit economic adjustment with proposal/approval provenance."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    adjustment_type: AdjustmentType
    input_value: float | None = None
    proposed_adjusted_value: float | None = None
    status: AdjustmentStatus
    reason: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    proposed_by: ProposedBy
    approved_by: ApprovedBy | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Company(BaseModel):
    """Company identity and accounting context."""

    model_config = ConfigDict(extra="forbid")

    name: str
    legal_name: str | None = None
    primary_listing: str
    other_listings: list[str] = Field(default_factory=list)
    sector: str
    industry: str | None = None
    country_or_region: str | None = None
    reporting_currency: str = Field(min_length=3, max_length=3)
    accounting_standard: str | None = None
    accounting_standard_version: str | None = None
    fiscal_year_end: str | None = None
    special_model: str | None = None


class DataQuality(BaseModel):
    """Overall data-quality summary for an analysis."""

    model_config = ConfigDict(extra="forbid")

    confidence: ConfidenceLevel
    evidence_coverage: float = Field(ge=0, le=1)
    critical_missing_fields: list[str]
    notes: str | None = None


class CDCMetric(BaseModel):
    """CDC metric payload; fields extend the permissive CDC schema section."""

    model_config = ConfigDict(extra="allow")

    reported_cfo: float | None = None
    adjusted_cfo: float | None = None
    economic_gross_capex: float | None = None
    lease_principal_outside_cfo: float | None = None
    core_cdc: float | None = None
    parent_core_cdc: float | None = None
    normalized_core_cdc: float | None = None
    normalized_parent_core_cdc: float | None = None
    cdc_yield: float | None = None
    positive_years_5y: int | None = None
    cumulative_core_cdc_5y: float | None = None
    all_in_cdc: float | None = None
    all_in_cdc_5y: float | None = None
    flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class NetCashMetric(BaseModel):
    """Net-cash metric payload."""

    model_config = ConfigDict(extra="allow")

    book_cash: float | None = None
    strict_cash: float | None = None
    owner_accessible_cash: float | None = None
    financial_debt: float | None = None
    lease_debt: float | None = None
    debt_equivalent: float | None = None
    book_net_cash: float | None = None
    strict_net_cash: float | None = None
    owner_realizable_net_cash: float | None = None
    valuation_net_cash: float | None = None
    owner_net_cash_ratio: float | None = None
    liquidity_coverage: float | None = None
    stress_coverage: float | None = None
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class ThroughReturnMetric(BaseModel):
    """Shareholder-through-return metric payload."""

    model_config = ConfigDict(extra="allow")

    normalized_parent_profit: float | None = None
    normalized_parent_core_cdc: float | None = None
    distributable_base: float | None = None
    payout_policy_floor: float | None = None
    conservative_payout_ratio: float | None = None
    dividend_through_return: float | None = None
    normalized_net_share_reduction: float | None = None
    through_return: float | None = None
    special_return: float | None = None
    flags: list[str] = Field(default_factory=list)
    policy_confidence: ConfidenceLevel | None = None
    confidence: ConfidenceLevel | None = None


class Metrics(BaseModel):
    """Top-level deterministic metric groups."""

    model_config = ConfigDict(extra="forbid")

    cdc: CDCMetric
    net_cash: NetCashMetric
    through_return: ThroughReturnMetric


class BusinessQualityDimension(BaseModel):
    """One evidence-backed business-quality dimension."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal[
        "demand_durability",
        "cyclicality",
        "pricing_power",
        "moat",
        "capital_efficiency",
        "dependency",
        "regulatory_risk",
        "predictability",
    ]
    score: int = Field(ge=0, le=5)
    supporting_evidence_ids: list[str]
    counter_evidence_ids: list[str]
    confidence: ConfidenceLevel
    reasoning_summary: str | None = None


class BusinessQuality(BaseModel):
    """Structured business-quality assessment."""

    model_config = ConfigDict(extra="forbid")

    score: int | None = Field(default=None, ge=0, le=40)
    grade: Literal["S", "A", "B", "WATCH", "FAIL"] | None = None
    confidence: ConfidenceLevel | None = None
    critical_weaknesses: list[str] = Field(default_factory=list)
    dimension_results: list[BusinessQualityDimension] = Field(default_factory=list)


class GateRule(BaseModel):
    """One deterministic rule result within a gate."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    status: GateStatus
    actual: FactValue = None
    threshold: FactValue = None
    evidence_ids: list[str] = Field(default_factory=list)
    message: str | None = None


class GateResult(BaseModel):
    """Independent gate result with explainable rule outcomes."""

    model_config = ConfigDict(extra="forbid")

    status: GateStatus
    rules: list[GateRule]
    blocking_reasons: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class Gates(BaseModel):
    """The fixed independent gate keys required by CompanyAnalysis."""

    model_config = ConfigDict(extra="forbid")

    universe: GateResult
    balance_sheet: GateResult
    cdc: GateResult
    through_return: GateResult
    business_quality: GateResult
    governance_data_quality: GateResult


class Decision(BaseModel):
    """Final derived decision; never an independent narrative opinion."""

    model_config = ConfigDict(extra="forbid")

    state: DecisionState
    auto_decision_allowed: bool
    summary: str
    blocking_reasons: list[str]
    top_supporting_evidence_ids: list[str] = Field(default_factory=list)
    top_counter_evidence_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class NormalizedCompanyInput(BaseModel):
    """Input-side projection of the fact/evidence portion of CompanyAnalysis.

    The repository currently defines the complete output schema, not a separate
    input JSON Schema.  This model deliberately reuses the exact contract
    objects and excludes calculated fields that do not exist yet at input time.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    analysis_id: str = Field(min_length=1)
    as_of: date
    profile_id: str = Field(min_length=1)
    company: Company
    data_quality: DataQuality
    facts: list[Fact]
    adjustments: list[Adjustment]
    evidence_index: list[Evidence] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ValuationTier(BaseModel):
    """One strict-v1 valuation tier."""

    model_config = ConfigDict(extra="forbid")

    cdc_hurdle: float = Field(gt=0)
    return_hurdle: float = Field(gt=0)
    market_cap: float | None = Field(default=None, ge=0)
    price: float | None = Field(default=None, ge=0)
    owner_net_cash_ratio: float | None = None
    valuation_net_cash_ratio: float | None = None


class ValuationTiers(BaseModel):
    """The four fixed tier keys required by valuation-result.schema.json."""

    model_config = ConfigDict(extra="forbid")

    observation: ValuationTier
    acceptable: ValuationTier
    turtle_entry: ValuationTier
    extreme_safety: ValuationTier


class ValuationResult(BaseModel):
    """Strict-v1 valuation output matching valuation-result.schema.json."""

    model_config = ConfigDict(extra="forbid")

    as_of: date
    valuation_currency: str = Field(min_length=3, max_length=3)
    listing: str
    current_price: float | None = Field(default=None, ge=0)
    listing_equivalent_market_cap: float | None = Field(default=None, ge=0)
    actual_aggregate_company_market_cap: float | None = Field(default=None, ge=0)
    normalized_diluted_economic_shares: float | None = Field(default=None, gt=0)
    normalized_parent_core_cdc: float
    distributable_base: float
    recurring_dividend_cash: float | None = None
    verified_recurring_buyback_cash: float = Field(default=0, ge=0)
    recurring_shareholder_cash: float
    owner_realizable_net_cash: float | None = None
    valuation_net_cash: float | None = None
    adjusted_ev: float | None = None
    ex_cash_cdc_yield: float | None = None
    asset_supported_market_cap: float | None = None
    tiers: ValuationTiers
    current_valuation_state: ValuationState
    mos_acceptable: float | None = None
    mos_turtle: float | None = None
    mos_extreme: float | None = None
    flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel


class CompanyAnalysis(BaseModel):
    """Complete top-level CompanyAnalysis output contract."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    analysis_id: str = Field(min_length=1)
    as_of: date
    profile_id: str = Field(min_length=1)
    company: Company
    data_quality: DataQuality
    facts: list[Fact]
    adjustments: list[Adjustment]
    metrics: Metrics
    gates: Gates
    valuation: ValuationResult
    decision: Decision
    business_quality: BusinessQuality | None = None
    evidence_index: list[Evidence] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
