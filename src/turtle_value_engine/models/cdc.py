"""Typed normalized inputs and outputs for the CDC calculation module."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import ConfidenceLevel

_NON_NEGATIVE_FIELDS = (
    "cash_interest_paid_total",
    "cash_interest_in_cfo",
    "cash_interest_outside_cfo",
    "non_recurring_operating_inflows",
    "operating_outflows_misclassified_outside_cfo",
    "ppe_purchase_cash",
    "intangible_purchase_cash",
    "other_operating_long_term_asset_cash",
    "lease_principal_outside_cfo",
    "capitalized_development_cash_outside_capex",
    "acquisition_cash",
    "strategic_investment_cash",
)


class CDCYearInput(BaseModel):
    """One chronological year's normalized CDC facts.

    Cash outflows are represented as positive magnitudes.  The signed fields
    ``capex_payables_change`` and ``working_capital_contribution`` retain their
    economic sign.  A missing field remains ``None`` and is never interpreted
    as a zero adjustment by the calculator.
    """

    model_config = ConfigDict(extra="forbid")

    period: str = Field(min_length=1)
    reported_cfo: float | None = None
    cash_interest_paid_total: float | None = None
    cash_interest_in_cfo: float | None = None
    cash_interest_outside_cfo: float | None = None
    non_recurring_operating_inflows: float | None = None
    operating_outflows_misclassified_outside_cfo: float | None = None
    ppe_purchase_cash: float | None = None
    intangible_purchase_cash: float | None = None
    other_operating_long_term_asset_cash: float | None = None
    capex_payables_change: float | None = None
    lease_principal_outside_cfo: float | None = None
    capitalized_dev_already_in_capex: bool | None = None
    capitalized_development_cash_outside_capex: float | None = None
    acquisition_cash: float | None = None
    strategic_investment_cash: float | None = None
    working_capital_contribution: float | None = None
    parent_economic_share: float | None = Field(default=None, ge=0, le=1)
    parent_net_profit: float | None = None
    consolidated_net_profit: float | None = None
    confidence: ConfidenceLevel | None = None

    @field_validator(*_NON_NEGATIVE_FIELDS)
    @classmethod
    def validate_non_negative_amounts(cls, value: float | None) -> float | None:
        """Keep cash expenditure and classification amounts as magnitudes."""

        if value is not None and value < 0:
            raise ValueError("cash outflow/classification amounts must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_capitalized_development_claim(self) -> Self:
        """Prevent an input from claiming the same development cash twice."""

        outside = self.capitalized_development_cash_outside_capex
        if self.capitalized_dev_already_in_capex is True and outside not in (None, 0):
            raise ValueError(
                "capitalized development cannot be both already included in capex "
                "and separately outside capex"
            )
        if outside is not None and self.capitalized_dev_already_in_capex is None:
            raise ValueError(
                "capitalized_dev_already_in_capex must be explicit when outside-capex "
                "development cash is supplied"
            )
        return self


class CDCInput(BaseModel):
    """Input boundary for multi-year deterministic CDC calculation."""

    model_config = ConfigDict(extra="forbid")

    years: list[CDCYearInput] = Field(min_length=1)
    current_market_cap: float | None = Field(default=None, gt=0)
    cyclical: bool = False

    @model_validator(mode="after")
    def validate_unique_periods(self) -> Self:
        periods = [year.period for year in self.years]
        if len(periods) != len(set(periods)):
            raise ValueError("CDC periods must be unique")
        return self


class CDCYearResult(BaseModel):
    """Auditable result for one year."""

    model_config = ConfigDict(extra="forbid")

    period: str
    reported_cfo: float | None = None
    interest_outside_cfo: float | None = None
    adjusted_cfo: float | None = None
    economic_gross_capex: float | None = None
    lease_principal_outside_cfo: float | None = None
    core_cdc: float | None = None
    parent_economic_share: float | None = None
    parent_core_cdc: float | None = None
    all_in_cdc: float | None = None
    working_capital_contribution: float | None = None
    flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel


class CDCResult(BaseModel):
    """Multi-year CDC result consumed by later gates and valuation."""

    model_config = ConfigDict(extra="forbid")

    reported_cfo: float | None = None
    adjusted_cfo: float | None = None
    economic_gross_capex: float | None = None
    lease_principal_outside_cfo: float | None = None
    core_cdc: float | None = None
    parent_core_cdc: float | None = None
    normalized_core_cdc: float | None = None
    normalized_parent_core_cdc: float | None = None
    cdc_yield: float | None = None
    all_in_cdc: float | None = None
    positive_years_5y: int | None = None
    cumulative_core_cdc_5y: float | None = None
    all_in_cdc_5y: float | None = None
    year_results: list[CDCYearResult] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
