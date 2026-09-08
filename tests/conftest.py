"""Shared fixtures for deterministic calculation tests."""

import pytest

from turtle_value_engine.models import CDCYearInput


@pytest.fixture
def year_factory():
    """Build complete CDC years with explicit zeroes for optional adjustments."""

    def factory(period: str = "FY2025", **overrides) -> CDCYearInput:
        values = {
            "period": period,
            "reported_cfo": 100.0,
            "cash_interest_paid_total": 10.0,
            "cash_interest_in_cfo": 4.0,
            "non_recurring_operating_inflows": 0.0,
            "operating_outflows_misclassified_outside_cfo": 0.0,
            "ppe_purchase_cash": 20.0,
            "intangible_purchase_cash": 10.0,
            "other_operating_long_term_asset_cash": 0.0,
            "capex_payables_change": 0.0,
            "lease_principal_outside_cfo": 0.0,
            "acquisition_cash": 0.0,
            "strategic_investment_cash": 0.0,
            "parent_economic_share": 1.0,
            "confidence": "HIGH",
        }
        values.update(overrides)
        return CDCYearInput(**values)

    return factory
