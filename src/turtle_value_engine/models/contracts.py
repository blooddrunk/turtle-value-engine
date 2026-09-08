"""Pydantic models corresponding to the repository's JSON contracts.

The model names and serialized field names intentionally follow the existing
schemas under ``schemas/``.  Calculators use the same objects as their input
and output boundary so that a result can be serialized without a second,
untracked transformation layer.
"""

from datetime import date
from typing import Literal, Self

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

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

# The normalized contract intentionally keeps ``Fact.field`` open for future
# adapters, while these fields have a frozen scalar type in strict-v1.  The
# same namespaces are expressed as conditional branches in
# ``schemas/normalized-input.schema.json``.  Unknown fact names remain valid
# scalar facts so a new fact does not silently become an output field or force
# a strategy-version change before its calculation module exists.
NORMALIZED_NUMERIC_FACT_FIELDS = frozenset(
    {
        # Eligibility and valuation context.
        "listing_years",
        "parent_equity",
        "current_market_cap",
        "current_price",
        "normalized_diluted_economic_shares",
        "actual_aggregate_company_market_cap",
        "listing_equivalent_market_cap",
        # CDC inputs.
        "reported_cfo",
        "cash_interest_paid_total",
        "cash_interest_in_cfo",
        "cash_interest_outside_cfo",
        "non_recurring_operating_inflows",
        "operating_outflows_misclassified_outside_cfo",
        "ppe_purchase_cash",
        "intangible_purchase_cash",
        "other_operating_long_term_asset_cash",
        "capex_payables_change",
        "lease_principal_outside_cfo",
        "capitalized_development_cash_outside_capex",
        "acquisition_cash",
        "strategic_investment_cash",
        "working_capital_contribution",
        "parent_economic_share",
        "parent_net_profit",
        "consolidated_net_profit",
        # Net-cash inputs.
        "book_cash",
        "reported_interest_bearing_debt",
        "hard_cash",
        "near_cash",
        "liquid_financial_assets",
        "strategic_investments",
        "restricted_cash",
        "pledged_deposits",
        "financial_debt",
        "lease_debt",
        "supplier_finance",
        "recourse_factoring",
        "debt_like_hybrids",
        "material_quasi_debt",
        "subsidiary_cash",
        "subsidiary_debt",
        "subsidiary_ownership",
        "upstreamability_factor",
        "debt_due_within_one_year",
        "normalized_ebitda",
        "cash_interest_expense",
        "minority_profit",
        "minority_equity",
        "total_equity",
        "cash_governance_factor",
        "equity_financing",
        "debt_financing",
        "other_financing",
        # Through-return inputs.
        "ordinary_dividend_cash",
        "special_dividend_cash",
        "formal_payout_floor",
        "payout_ratio",
        "fully_diluted_shares",
        "buyback_cash",
        "share_issuance_cash",
        "share_split_factor",
        # Business-quality diagnostics.
        "revenue",
        "core_revenue",
        "operating_profit",
        "gross_margin",
        "ebit_margin",
        "roic",
        "recurring_revenue_ratio",
        "largest_customer_ratio",
        "top5_customer_ratio",
        "channel_concentration",
        "critical_supplier_concentration",
        "asp",
        "asp_change",
        "volume",
        "volume_change",
        "market_share",
        "capex_intensity",
        "normalized_operating_nwc",
        "invested_capital",
        "nopat",
        "m_and_a_cash",
        "goodwill",
        "impairment",
        "revenue_cagr_5y",
        "profit_cv",
        "core_cdc_cv",
    }
)

NORMALIZED_BOOLEAN_FACT_FIELDS = frozenset(
    {
        "special_treatment",
        "capitalized_dev_already_in_capex",
        "structural_demand_decline",
        "replacement_earnings_engine",
        "core_business_cash_generation",
        "structural_disruption",
        "single_point_survival_dependency",
        "controlling_shareholder_fund_occupation",
        "major_illegal_guarantee",
        "cash_authenticity_verified",
        "cash_upstreamability_verified",
        "payout_policy_formal",
        "buyback_recurring",
        "net_diluted_share_reduction_verified",
        "special_dividend",
    }
)

NORMALIZED_ENUM_FACT_VALUES = {
    "payout_policy_confidence": frozenset({"HIGH", "MEDIUM", "LOW"}),
    "governance_risk_level": frozenset({"NONE", "LOW", "MEDIUM", "HIGH", "SEVERE"}),
    "cycle_phase": frozenset({"TROUGH", "MID_CYCLE", "PEAK", "DECLINE", "UNKNOWN"}),
    "demand_classification": frozenset(
        {"ESSENTIAL", "REPEAT_PURCHASE", "REPLACEMENT", "DISCRETIONARY", "FASHION", "ONE_OFF"}
    ),
    "accounting_opinion": frozenset(
        {"UNMODIFIED", "QUALIFIED", "ADVERSE", "DISCLAIMER", "UNKNOWN"}
    ),
    "cash_governance_class": frozenset(
        {
            "STRONG",
            "SOUND",
            "WEAK_DISTRIBUTION",
            "POOR_CAPITAL_ALLOCATION",
            "SEVERE_GOVERNANCE",
        }
    ),
}


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
    page: StrictInt | None = Field(default=None, ge=1)
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
    confidence: StrictFloat = Field(ge=0, le=1)
    notes: str | None = None


class Fact(BaseModel):
    """Sourced fact before strategy interpretation or adjustment."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    field: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    value: FactValue
    unit: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    estimation_method: str | None = None
    estimated: StrictBool = False
    confidence: StrictFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_known_field_type(self) -> Self:
        """Reject scalar values that contradict a canonical normalized field."""

        value = self.value
        if value is None:
            return self

        if self.field in NORMALIZED_NUMERIC_FACT_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"fact {self.field!r} requires a numeric value or null")
        elif self.field in NORMALIZED_BOOLEAN_FACT_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"fact {self.field!r} requires a boolean value or null")
        elif self.field in NORMALIZED_ENUM_FACT_VALUES:
            allowed = NORMALIZED_ENUM_FACT_VALUES[self.field]
            if not isinstance(value, str) or value not in allowed:
                choices = ", ".join(sorted(allowed))
                raise ValueError(f"fact {self.field!r} requires one of [{choices}] or null")
        return self

    @field_validator("source_evidence_ids")
    @classmethod
    def validate_unique_evidence_ids(cls, value: list[str]) -> list[str]:
        """Prevent duplicate references that obscure evidence coverage."""

        if len(value) != len(set(value)):
            raise ValueError("source_evidence_ids must not contain duplicates")
        return value


class Adjustment(BaseModel):
    """Explicit economic adjustment with proposal/approval provenance."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    target_field: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    adjustment_type: AdjustmentType
    input_value: StrictFloat | None = None
    proposed_adjusted_value: StrictFloat | None = None
    status: AdjustmentStatus
    reason: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    proposed_by: ProposedBy
    approved_by: ApprovedBy | None = None
    confidence: StrictFloat | None = Field(default=None, ge=0, le=1)

    @field_validator("source_evidence_ids")
    @classmethod
    def validate_unique_evidence_ids(cls, value: list[str]) -> list[str]:
        """Prevent duplicate adjustment provenance references."""

        if len(value) != len(set(value)):
            raise ValueError("source_evidence_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_approval_state(self) -> Self:
        """Require an explicit approver before an adjustment becomes effective."""

        if self.status is AdjustmentStatus.ACCEPTED and self.approved_by is None:
            raise ValueError("accepted adjustments require approved_by")
        return self


class Company(BaseModel):
    """Company identity and accounting context.

    ``primary_listing`` is the canonical stable issuer/listing identifier;
    additional listings stay in ``other_listings`` for later price mapping.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    legal_name: str | None = None
    primary_listing: str = Field(min_length=1)
    other_listings: list[str] = Field(default_factory=list)
    sector: str = Field(min_length=1)
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
    evidence_coverage: StrictFloat = Field(ge=0, le=1)
    critical_missing_fields: list[str]
    notes: str | None = None

    @field_validator("critical_missing_fields")
    @classmethod
    def validate_unique_missing_fields(cls, value: list[str]) -> list[str]:
        """Keep the missing-field inventory deterministic and auditable."""

        if any(not field for field in value):
            raise ValueError("critical_missing_fields must contain non-empty names")
        if len(value) != len(set(value)):
            raise ValueError("critical_missing_fields must not contain duplicates")
        return value


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
    financial_net_cash: float | None = None
    obligation_adjusted_net_cash: float | None = None
    owner_debt_equivalent: float | None = None
    book_net_cash: float | None = None
    strict_net_cash: float | None = None
    owner_realizable_net_cash: float | None = None
    valuation_net_cash: float | None = None
    adjusted_ev: float | None = None
    ex_cash_cdc_yield: float | None = None
    owner_net_cash_ratio: float | None = None
    liquidity_coverage: float | None = None
    stress_coverage: float | None = None
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    source_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
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
    verified_recurring_buyback_cash: float = Field(default=0, ge=0)
    buyback_credit_eligible: bool = False
    buyback_history_years: int | None = Field(default=None, ge=0)
    source_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)


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
    """Frozen input-side contract for deterministic calculations.

    This is intentionally separate from ``CompanyAnalysis`` at the field
    boundary: it contains only identity, source facts, evidence, adjustments
    and data-quality metadata.  Metrics, gates, valuation and decision fields
    are output-only and are rejected by ``extra='forbid'``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    analysis_id: str = Field(min_length=1)
    as_of: date
    profile_id: str = Field(min_length=1)
    company: Company
    data_quality: DataQuality
    facts: list[Fact]
    adjustments: list[Adjustment]
    evidence_index: list[Evidence]
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids_and_evidence_references(self) -> Self:
        """Validate all local IDs and every fact/adjustment evidence reference."""

        evidence_ids = [item.id for item in self.evidence_index]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_index IDs must be unique")

        fact_ids = [item.id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact IDs must be unique")

        adjustment_ids = [item.id for item in self.adjustments]
        if len(adjustment_ids) != len(set(adjustment_ids)):
            raise ValueError("adjustment IDs must be unique")

        known_evidence_ids = set(evidence_ids)
        references = [
            reference for fact in self.facts for reference in fact.source_evidence_ids
        ] + [
            reference
            for adjustment in self.adjustments
            for reference in adjustment.source_evidence_ids
        ]
        unknown_references = sorted(set(references) - known_evidence_ids)
        if unknown_references:
            raise ValueError("undefined evidence ID reference(s): " + ", ".join(unknown_references))
        if len(self.flags) != len(set(self.flags)):
            raise ValueError("flags must not contain duplicates")
        return self


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
    normalized_parent_core_cdc: float | None
    distributable_base: float | None
    recurring_dividend_cash: float | None = None
    verified_recurring_buyback_cash: float = Field(default=0, ge=0)
    recurring_shareholder_cash: float | None
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
