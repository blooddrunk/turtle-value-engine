"""Typed inputs and results for shareholder-through-return calculations."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import ConfidenceLevel
from .contracts import ThroughReturnMetric


class ThroughReturnYearInput(BaseModel):
    """One period of normalized earnings, payout and diluted-share facts."""

    model_config = ConfigDict(extra="forbid")

    period: str = Field(min_length=1)
    parent_net_profit: float | None = None
    ordinary_dividend_cash: float | None = Field(default=None, ge=0)
    special_dividend_cash: float | None = Field(default=None, ge=0)
    formal_payout_floor: float | None = Field(default=None, ge=0, le=1)
    payout_ratio: float | None = Field(default=None, ge=0)
    fully_diluted_shares: float | None = Field(default=None, gt=0)
    share_split_factor: float | None = Field(default=None, gt=0)
    buyback_cash: float | None = Field(default=None, ge=0)
    share_issuance_cash: float | None = Field(default=None, ge=0)


class ThroughReturnInput(BaseModel):
    """Normalized facts and upstream CDC output for Through Return."""

    model_config = ConfigDict(extra="forbid")

    years: list[ThroughReturnYearInput] = Field(min_length=1)
    normalized_parent_core_cdc: float | None = None
    current_market_cap: float | None = Field(default=None, gt=0)
    payout_policy_formal: bool | None = None
    payout_policy_confidence: ConfidenceLevel | None = None
    formal_payout_floor: float | None = Field(default=None, ge=0, le=1)
    buyback_recurring: bool | None = None
    net_diluted_share_reduction_verified: bool | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    source_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_periods(self) -> "ThroughReturnInput":
        periods = [year.period for year in self.years]
        if len(periods) != len(set(periods)):
            raise ValueError("Through Return periods must be unique")
        return self


class ThroughReturnResult(ThroughReturnMetric):
    """Auditable Through Return output, including buyback-credit metadata."""

    model_config = ConfigDict(extra="allow")
