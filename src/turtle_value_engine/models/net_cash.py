"""Typed inputs and results for the net-cash calculation stage."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import ConfidenceLevel
from .contracts import NetCashMetric


class NetCashInput(BaseModel):
    """Normalized balance-sheet facts consumed by the net-cash calculator.

    Cash-bucket fields are already economically classified: ``hard_cash`` is
    unrestricted C0 cash, while restricted and pledged balances are tracked
    separately for the accessibility check.  Missing fields stay ``None``;
    callers must not use zero as a stand-in for an unresolved classification.
    When subsidiary fields are supplied, ``subsidiary_cash`` and
    ``subsidiary_debt`` are consolidated components expressed on the same
    strict-cash/debt basis as the total inputs.
    """

    model_config = ConfigDict(extra="forbid")

    current_market_cap: float | None = Field(default=None, gt=0)
    normalized_parent_core_cdc: float | None = None

    book_cash: float | None = Field(default=None, ge=0)
    reported_interest_bearing_debt: float | None = Field(default=None, ge=0)
    hard_cash: float | None = Field(default=None, ge=0)
    near_cash: float | None = Field(default=None, ge=0)
    liquid_financial_assets: float | None = Field(default=None, ge=0)
    strategic_investments: float | None = Field(default=None, ge=0)
    restricted_cash: float | None = Field(default=None, ge=0)
    pledged_deposits: float | None = Field(default=None, ge=0)

    financial_debt: float | None = Field(default=None, ge=0)
    lease_debt: float | None = Field(default=None, ge=0)
    supplier_finance: float | None = Field(default=None, ge=0)
    recourse_factoring: float | None = Field(default=None, ge=0)
    debt_like_hybrids: float | None = Field(default=None, ge=0)
    material_quasi_debt: float | None = Field(default=None, ge=0)

    subsidiary_cash: float | None = Field(default=None, ge=0)
    subsidiary_debt: float | None = Field(default=None, ge=0)
    subsidiary_ownership: float | None = Field(default=None, ge=0, le=1)
    upstreamability_factor: float | None = Field(default=None, ge=0, le=1)
    debt_due_within_one_year: float | None = Field(default=None, ge=0)
    normalized_ebitda: float | None = None
    cash_interest_expense: float | None = Field(default=None, ge=0)

    minority_profit: float | None = None
    minority_equity: float | None = None
    total_equity: float | None = None
    cash_governance_factor: float | None = Field(default=None, ge=0, le=1)
    cash_governance_class: (
        Literal[
            "STRONG",
            "SOUND",
            "WEAK_DISTRIBUTION",
            "POOR_CAPITAL_ALLOCATION",
            "SEVERE_GOVERNANCE",
        ]
        | None
    ) = None

    cash_authenticity_verified: bool | None = None
    cash_upstreamability_verified: bool | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    source_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)


class NetCashResult(NetCashMetric):
    """Auditable net-cash metrics and coverage diagnostics."""

    model_config = ConfigDict(extra="allow")
