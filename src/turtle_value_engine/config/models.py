"""Typed representation of ``rules/*.yaml`` strategy profiles."""

from pydantic import BaseModel, ConfigDict, Field


class ProfileMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: str
    description: str


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_listing_years_pass: int = Field(gt=0)
    min_listing_years_watch: int = Field(gt=0)
    exclude_special_treatment: bool
    exclude_negative_parent_equity: bool
    special_models: list[str]


class CDCContinuityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_years: int = Field(gt=0)
    min_positive_years: int = Field(ge=0)
    require_positive_cumulative: bool
    require_positive_normalized: bool


class CDCNormalizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard_method: str
    cyclical_method: str
    cyclical_min_years: int = Field(gt=0)
    cyclical_preferred_years: int = Field(gt=0)


class CDCYieldBands(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    s: float = Field(gt=0)
    a: float = Field(gt=0)
    pass_: float = Field(alias="pass", gt=0)
    watch: float = Field(gt=0)
    fail_below: float = Field(gt=0)


class CDCConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    continuity: CDCContinuityConfig
    normalization: CDCNormalizationConfig
    working_capital_distortion_threshold: float = Field(ge=0)
    capex_payables_materiality_vs_core_cdc: float = Field(ge=0)
    interest_classification_materiality_vs_reported_cfo: float = Field(ge=0)
    yield_bands: CDCYieldBands


class CashWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_cash: float = Field(ge=0)
    near_cash: float = Field(ge=0)
    liquid_financial_assets: float = Field(ge=0)
    strategic_investments: float = Field(ge=0)


class UpstreamabilityFactors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fully_accessible: float = Field(ge=0)
    moderate_friction: float = Field(ge=0)
    meaningful_constraints: float = Field(ge=0)
    unavailable: float = Field(ge=0)


class HybridDebtWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pure_equity_like_min: float = Field(ge=0)
    pure_equity_like_max: float = Field(ge=0)
    hybrid: float = Field(ge=0)
    debt_like: float = Field(ge=0)


class NCIMateriality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minority_profit_ratio: float = Field(ge=0)
    minority_equity_ratio: float = Field(ge=0)


class OwnerNetCashRatioBands(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s_plus: float
    s: float
    a: float
    b: float
    c: float


class LiquidityCoverageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s: float
    a: float
    b: float
    watch: float
    fail_below: float


class StressConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cdc_retention_factor: float = Field(ge=0, le=1)
    preferred_coverage: float
    ideal_coverage: float
    fail_below: float


class LeverageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_net_debt_to_ebitda_pass: float
    max_net_debt_to_ebitda_watch: float
    fail_above: float
    interest_coverage_pass: float
    interest_coverage_watch: float
    fail_below: float


class CashGovernanceFactorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strong: float = Field(ge=0, le=1)
    sound: float = Field(ge=0, le=1)
    weak_distribution: float = Field(ge=0, le=1)
    poor_capital_allocation: float = Field(ge=0, le=1)
    severe_governance_max: float = Field(ge=0, le=1)


class NetCashConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cash_weights: CashWeights
    upstreamability_factors: UpstreamabilityFactors
    hybrid_debt_weights: HybridDebtWeights
    nci_materiality: NCIMateriality
    owner_net_cash_ratio_bands: OwnerNetCashRatioBands
    liquidity_coverage: LiquidityCoverageConfig
    stress: StressConfig
    leverage: LeverageConfig
    cash_governance_factor: CashGovernanceFactorConfig


class PayoutRatioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formal_policy_method: str
    no_policy_method: str


class ThroughReturnYieldBands(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    s: float = Field(gt=0)
    a: float = Field(gt=0)
    pass_: float = Field(alias="pass", gt=0)
    watch: float = Field(gt=0)
    fail_below: float = Field(gt=0)


class ThroughReturnConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distributable_base_method: str
    payout_ratio: PayoutRatioConfig
    normalized_buyback_years: int = Field(gt=0)
    yield_bands: ThroughReturnYieldBands
    formal_candidate_threshold: float = Field(gt=0)


class BusinessQualityScoreBands(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    s: int
    a: int
    pass_: int = Field(alias="pass")
    watch: int
    fail_below: int


class EvidenceCoverageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: float = Field(ge=0, le=1)
    medium: float = Field(ge=0, le=1)
    low_below: float = Field(ge=0, le=1)


class EvidenceRequirementsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score_4_min_strong_evidence: int = Field(ge=0)
    score_5_min_strong_evidence: int = Field(ge=0)
    score_without_strong_evidence_max: int = Field(ge=0, le=5)


class BusinessQualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: dict[str, int]
    critical_dimensions: list[str]
    critical_dimension_fail_at_or_below: int = Field(ge=0, le=5)
    score_bands: BusinessQualityScoreBands
    evidence_coverage: EvidenceCoverageConfig
    evidence_requirements: EvidenceRequirementsConfig


class BuybackCashCreditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    default_cash: float = Field(ge=0)
    min_history_years: int = Field(gt=0)
    require_high_confidence: bool
    require_net_diluted_share_reduction: bool


class ValuationTierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cdc_yield: float = Field(gt=0)
    recurring_shareholder_cash_yield: float = Field(gt=0)
    decision: str


class CashCushionLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thick: float = Field(ge=0)
    strong: float = Field(ge=0)
    moderate: float = Field(ge=0)


class ValuationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyback_cash_credit: BuybackCashCreditConfig
    tiers: dict[str, ValuationTierConfig]
    combine_constraints: str
    quality_premium_enabled: bool
    risk_free_rate_adjustment_enabled: bool
    net_cash_raises_primary_price_ceiling: bool
    cash_cushion_labels: CashCushionLabels
    negative_adjusted_ev_mode: str


class ConfidenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    levels: list[str]
    low_critical_input_blocks_auto_pass: bool


class ResultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    states: list[str]


class RuleProfile(BaseModel):
    """Complete typed strategy profile loaded from a YAML rule file."""

    model_config = ConfigDict(extra="forbid")

    profile: ProfileMetadata
    universe: UniverseConfig
    cdc: CDCConfig
    net_cash: NetCashConfig
    through_return: ThroughReturnConfig
    business_quality: BusinessQualityConfig
    valuation: ValuationConfig
    confidence: ConfidenceConfig
    results: ResultsConfig
