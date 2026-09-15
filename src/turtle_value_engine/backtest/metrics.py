"""Deterministic performance, benchmark and failure-attribution helpers."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from statistics import mean, pstdev

from .contracts import (
    BacktestDatasetManifest,
    BenchmarkObservation,
    BenchmarkResult,
    DecisionSnapshot,
    FailureAttribution,
    ForwardReturnObservation,
    PerformanceMetrics,
    PortfolioSnapshot,
    SignalOutcomeStatus,
)
from .dataset import is_available_at


def _annual_factor(values: list[float], periods_per_year: float = 252.0) -> float | None:
    if len(values) < 2:
        return None
    deviation = pstdev(values)
    if deviation == 0:
        return 0.0
    return deviation * math.sqrt(periods_per_year)


def _cagr(start: float, end: float, start_date: date, end_date: date) -> float | None:
    if start <= 0 or end <= 0 or end_date <= start_date:
        return None
    years = (end_date - start_date).days / 365.2425
    if years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def _drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    high_water = values[0]
    worst = 0.0
    for value in values:
        high_water = max(high_water, value)
        if high_water > 0:
            worst = min(worst, value / high_water - 1)
    return worst


def calculate_performance_metrics(
    snapshots: Iterable[PortfolioSnapshot],
    *,
    initial_nav: float | None = None,
    benchmark_cagr: float | None = None,
    benchmark_daily_returns: Iterable[float] | None = None,
    turnover: float | None = None,
    expected_observations: int | None = None,
    factor_exposure: dict[str, float] | None = None,
) -> PerformanceMetrics:
    """Calculate auditable portfolio statistics from persisted snapshots."""

    ordered = sorted(snapshots, key=lambda item: item.timestamp)
    values = [float(item.net_asset_value) for item in ordered]
    if initial_nav is not None and (not values or not math.isclose(values[0], initial_nav)):
        values.insert(0, initial_nav)
    daily_returns = [
        values[index] / values[index - 1] - 1
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]
    cagr = (
        _cagr(
            values[0],
            values[-1],
            ordered[0].timestamp.date(),
            ordered[-1].timestamp.date(),
        )
        if ordered and values
        else None
    )
    volatility = _annual_factor(daily_returns)
    mean_return = mean(daily_returns) if daily_returns else None
    sharpe = (
        mean_return / pstdev(daily_returns) * math.sqrt(252)
        if mean_return is not None and len(daily_returns) > 1 and pstdev(daily_returns) > 0
        else None
    )
    benchmark_returns = list(benchmark_daily_returns or [])
    tracking_error = None
    if benchmark_returns and daily_returns:
        aligned_portfolio_returns = daily_returns
        if len(daily_returns) == len(benchmark_returns) + 1 and initial_nav is not None:
            aligned_portfolio_returns = daily_returns[1:]
        paired = [
            portfolio - benchmark
            for portfolio, benchmark in zip(
                aligned_portfolio_returns,
                benchmark_returns,
                strict=False,
            )
        ]
        if len(paired) > 1:
            tracking_error = pstdev(paired) * math.sqrt(252)
    negative = [item for item in daily_returns if item < 0]
    downside = pstdev(negative) if len(negative) > 1 else 0.0
    sortino = (
        mean_return / downside * math.sqrt(252)
        if mean_return is not None and downside > 0
        else None
    )
    # An initial NAV anchor is a calculation aid, not an additional observed
    # portfolio snapshot.  Keeping it out of the count prevents coverage from
    # exceeding one when the first fill changes NAV before the first mark.
    complete_count = len(ordered)
    expected = expected_observations if expected_observations is not None else complete_count
    missing = max(0, expected - complete_count)
    max_sector = max(
        (
            sum(
                position.market_value
                for position in snapshot.positions
                if position.sector == sector
            )
            / snapshot.net_asset_value
            for snapshot in ordered
            for sector in {position.sector for position in snapshot.positions if position.sector}
            if snapshot.net_asset_value > 0
        ),
        default=None,
    )
    max_position = max(
        (
            position.market_value / snapshot.net_asset_value
            for snapshot in ordered
            for position in snapshot.positions
            if snapshot.net_asset_value > 0
        ),
        default=None,
    )
    average_cash = mean(snapshot.cash_exposure for snapshot in ordered) if ordered else None
    return PerformanceMetrics(
        observation_count=expected,
        complete_observation_count=complete_count,
        cagr=cagr,
        max_drawdown=_drawdown(values),
        volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        turnover=max(0.0, turnover or sum(snapshot.turnover for snapshot in ordered)),
        hit_rate=(
            sum(item > 0 for item in daily_returns) / len(daily_returns) if daily_returns else None
        ),
        excess_return=(None if cagr is None or benchmark_cagr is None else cagr - benchmark_cagr),
        tracking_error=tracking_error,
        max_sector_concentration=max_sector,
        max_position_concentration=max_position,
        average_cash_exposure=average_cash,
        coverage_ratio=complete_count / expected if expected else 0.0,
        missing_data_ratio=missing / expected if expected else 0.0,
        factor_exposure=factor_exposure or {},
    )


def benchmark_result(
    observations: Iterable[BenchmarkObservation],
    *,
    benchmark_id: str,
    start_date: date,
    end_date: date,
) -> BenchmarkResult:
    """Evaluate one explicitly typed benchmark series."""

    selected = sorted(
        (
            item
            for item in observations
            if item.benchmark_id == benchmark_id and start_date <= item.observation_date <= end_date
        ),
        key=lambda item: item.observation_date,
    )
    if not selected:
        raise ValueError(f"benchmark {benchmark_id!r} has no observations in the requested range")
    if len({item.return_type for item in selected}) != 1:
        raise ValueError("one benchmark identity cannot mix PRICE_RETURN and TOTAL_RETURN")
    if len({item.currency for item in selected}) != 1:
        raise ValueError("one benchmark identity cannot mix currencies")
    if len({item.observation_date for item in selected}) != len(selected):
        raise ValueError("one benchmark identity cannot contain duplicate dates")
    first = selected[0]
    last = selected[-1]
    total = last.value / first.value - 1
    return BenchmarkResult(
        benchmark_id=benchmark_id,
        return_type=first.return_type,
        currency=first.currency,
        start_value=first.value,
        end_value=last.value,
        total_return=total,
        cagr=_cagr(first.value, last.value, first.observation_date, last.observation_date),
        coverage_ratio=len({item.observation_date for item in selected})
        / max(1, (end_date - start_date).days + 1),
    )


def benchmark_results(
    manifest: BacktestDatasetManifest,
    benchmark_ids: Iterable[str],
    *,
    start_date: date,
    end_date: date,
) -> list[BenchmarkResult]:
    """Return benchmark results in deterministic ID order."""

    return [
        benchmark_result(
            manifest.benchmarks,
            benchmark_id=benchmark_id,
            start_date=start_date,
            end_date=end_date,
        )
        for benchmark_id in sorted(set(benchmark_ids))
    ]


def benchmark_daily_returns_for_snapshots(
    manifest: BacktestDatasetManifest,
    snapshots: Iterable[PortfolioSnapshot],
    *,
    benchmark_id: str,
) -> list[float]:
    """Align one explicit benchmark level series to portfolio observations."""

    ordered_snapshots = sorted(snapshots, key=lambda item: item.timestamp)
    selected = sorted(
        (item for item in manifest.benchmarks if item.benchmark_id == benchmark_id),
        key=lambda item: (item.observation_date, item.observation_id),
    )
    if len(ordered_snapshots) < 2 or not selected:
        return []
    if len({item.return_type for item in selected}) != 1:
        raise ValueError("one benchmark identity cannot mix PRICE_RETURN and TOTAL_RETURN")
    if len({item.currency for item in selected}) != 1:
        raise ValueError("one benchmark identity cannot mix currencies")

    def level_on(value: date) -> float | None:
        candidates = [
            item
            for item in selected
            if item.observation_date <= value
            and is_available_at(
                item.available_at,
                datetime.combine(value, time.max, tzinfo=UTC),
            )
        ]
        return None if not candidates else candidates[-1].value

    returns: list[float] = []
    for previous, current in zip(ordered_snapshots, ordered_snapshots[1:], strict=False):
        previous_level = level_on(previous.timestamp.date())
        current_level = level_on(current.timestamp.date())
        if previous_level is None or current_level is None:
            return []
        returns.append(current_level / previous_level - 1)
    return returns


def _mean_or_zero(values: list[float]) -> float:
    return mean(values) if values else 0.0


def build_failure_attribution(
    observations: Iterable[ForwardReturnObservation],
    snapshots: Iterable[DecisionSnapshot],
    *,
    manifest: BacktestDatasetManifest | None = None,
) -> FailureAttribution:
    """Aggregate forward outcomes by deterministic signal dimensions."""

    snapshot_by_id = {item.snapshot_id: item for item in snapshots}
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    missing_states: dict[str, float] = defaultdict(float)
    excluded_winners: dict[str, float] = defaultdict(float)
    passed_losses: dict[str, float] = defaultdict(float)
    manual: dict[str, float] = defaultdict(float)
    for observation in observations:
        snapshot = snapshot_by_id.get(observation.snapshot_id)
        if snapshot is None:
            continue
        complete = observation.status in {
            SignalOutcomeStatus.COMPLETE,
            SignalOutcomeStatus.DELISTED_TERMINAL,
        }
        return_value = observation.total_return
        if not complete or return_value is None:
            missing_states[snapshot.final_state] += 1
        else:
            if return_value > 0 and snapshot.final_state not in {
                "PASS",
                "ACCEPTABLE",
                "TURTLE_ENTRY",
                "EXTREME_SAFETY",
            }:
                reasons = [
                    f"{gate}:{reason}"
                    for gate, values in sorted(snapshot.gate_failure_reasons.items())
                    for reason in values
                ] or [f"state:{snapshot.final_state}"]
                for reason in reasons:
                    excluded_winners[reason] += 1
            groups["valuation"][snapshot.valuation_tier or "UNKNOWN"].append(return_value)
            groups["business_quality"][
                "EVALUATED" if snapshot.business_quality_evaluated else "NOT_EVALUATED"
            ].append(return_value)
            groups["listing"][snapshot.listing_id].append(return_value)
            if (
                snapshot.final_state in {"PASS", "ACCEPTABLE", "TURTLE_ENTRY", "EXTREME_SAFETY"}
                and return_value < 0
            ):
                passed_losses[snapshot.listing_id] += return_value
        if snapshot.final_state in {"SPECIAL_REVIEW", "WATCH"}:
            manual[snapshot.final_state] += 1
    for state, count in missing_states.items():
        manual[f"missing:{state}"] += count
    sector: dict[str, list[float]] = defaultdict(list)
    market: dict[str, list[float]] = defaultdict(list)
    if manifest is not None:
        lifecycles = {item.listing_id: item for item in manifest.listing_lifecycles}
        for listing_id, values in groups["listing"].items():
            lifecycle = lifecycles.get(listing_id)
            if lifecycle is not None:
                # Keep listing-specific result values in the output; sector
                # and market keys are filled by the same deterministic map.
                if lifecycle.sector:
                    sector[lifecycle.sector].extend(values)
                market[lifecycle.market.value].extend(values)

    def means(values: dict[str, list[float]]) -> dict[str, float]:
        return {key: _mean_or_zero(value) for key, value in sorted(values.items())}

    return FailureAttribution(
        excluded_later_winners=dict(sorted(excluded_winners.items())),
        largest_passed_losses=dict(sorted(passed_losses.items())),
        manual_review_coverage=dict(sorted(manual.items())),
        by_valuation_tier=means(groups["valuation"]),
        by_business_quality_bucket=means(groups["business_quality"]),
        by_sector=means(sector),
        by_market=means(market),
        by_listing=means(groups["listing"]),
    )


__all__ = [
    "benchmark_result",
    "benchmark_daily_returns_for_snapshots",
    "benchmark_results",
    "build_failure_attribution",
    "calculate_performance_metrics",
]
