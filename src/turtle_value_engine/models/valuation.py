"""Typed input for the strict-v1 valuation calculation."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from .common import ConfidenceLevel


class ValuationInput(BaseModel):
    """Validated upstream metrics and listing context for valuation.

    This is deliberately not a complete CompanyAnalysis object.  The caller
    may provide ``non_price_gates_passed`` once the gate stage is available;
    the valuation function can still produce auditable indicative tiers while
    withholding a normal current-state decision when prerequisites are false
    or unresolved.
    """

    model_config = ConfigDict(extra="forbid")

    as_of: date
    valuation_currency: str = Field(min_length=3, max_length=3)
    listing: str = Field(min_length=1)
    current_price: float | None = Field(default=None, ge=0)
    listing_equivalent_market_cap: float | None = Field(default=None, ge=0)
    actual_aggregate_company_market_cap: float | None = Field(default=None, ge=0)
    normalized_diluted_economic_shares: float | None = Field(default=None, gt=0)

    normalized_parent_core_cdc: float | None = None
    distributable_base: float | None = None
    conservative_payout_ratio: float | None = None
    recurring_dividend_cash: float | None = None
    verified_recurring_buyback_cash: float = Field(default=0, ge=0)
    buyback_credit_eligible: bool | None = None
    buyback_credit_confidence: ConfidenceLevel | None = None
    buyback_history_years: int | None = Field(default=None, ge=0)
    buyback_recurring: bool | None = None
    net_diluted_share_reduction_verified: bool | None = None

    owner_realizable_net_cash: float | None = None
    valuation_net_cash: float | None = None
    cash_governance_factor: float | None = Field(default=None, ge=0, le=1)

    non_price_gates_passed: bool | None = None
    cyclical: bool = False
    full_cycle_normalization_available: bool = True
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
