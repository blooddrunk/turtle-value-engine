"""Independent-reference return/price reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from turtle_value_engine.backtest.contracts import PriceBasis

from .contracts import (
    HistoricalReconciliationReport,
    ReconciliationComparison,
)


def reconcile_observations(
    *,
    target_id: str,
    canonical_source_id: str,
    independent_source_id: str,
    canonical_values: Mapping[tuple[str, date], float | None],
    independent_values: Mapping[tuple[str, date], float | None],
    absolute_tolerance: float,
    relative_tolerance: float,
    canonical_price_basis: PriceBasis = PriceBasis.UNADJUSTED,
    return_semantics: str = "PRICE_RETURN",
    explicit_actions_used: bool = False,
    report_id: str = "reconciliation",
) -> HistoricalReconciliationReport:
    """Compare two cached series and persist missingness as MISSING rows."""

    if return_semantics not in {"PRICE_RETURN", "TOTAL_RETURN"}:
        raise ValueError("return_semantics must be PRICE_RETURN or TOTAL_RETURN")
    if absolute_tolerance < 0 or relative_tolerance < 0:
        raise ValueError("reconciliation tolerances must be non-negative")
    keys = sorted(
        set(canonical_values) | set(independent_values),
        key=lambda item: (item[0], item[1]),
    )
    comparisons = [
        ReconciliationComparison(
            comparison_id=f"{listing_id}:{observation_date.isoformat()}",
            listing_id=listing_id,
            observation_date=observation_date,
            canonical_value=canonical_values.get((listing_id, observation_date)),
            independent_value=independent_values.get((listing_id, observation_date)),
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
            canonical_source_id=canonical_source_id,
            independent_source_id=independent_source_id,
        )
        for listing_id, observation_date in keys
    ]
    return HistoricalReconciliationReport.build(
        report_id=report_id,
        target_id=target_id,
        canonical_source_id=canonical_source_id,
        independent_source_id=independent_source_id,
        canonical_price_basis=canonical_price_basis,
        return_semantics=return_semantics,
        explicit_actions_used=explicit_actions_used,
        comparisons=comparisons,
    )


__all__ = ["reconcile_observations"]
