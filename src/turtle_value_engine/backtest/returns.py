"""Deterministic listing-level return calculations and action handling."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime
from typing import Literal

from turtle_value_engine.providers.normalization import deterministic_id

from .contracts import (
    BacktestDatasetManifest,
    CorporateAction,
    CorporateActionType,
    DecisionSnapshot,
    ForwardReturnObservation,
    MarketBar,
    PriceBasis,
    SignalOutcomeStatus,
)
from .dataset import validate_manifest


class ReturnCalculationError(ValueError):
    """Raised when an action/price representation is economically ambiguous."""


_HORIZON_PATTERN = re.compile(r"^(\d+)([DWMY])$")


def add_horizon(value: date, horizon: str) -> date:
    """Add a calendar horizon without assuming a trading-day fill."""

    match = _HORIZON_PATTERN.fullmatch(horizon.upper())
    if match is None or int(match.group(1)) <= 0:
        raise ValueError("horizon must look like 1D, 1W, 1M or 1Y")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "D":
        from datetime import timedelta

        return value + timedelta(days=amount)
    if unit == "W":
        from datetime import timedelta

        return value + timedelta(weeks=amount)
    if unit == "Y":
        try:
            return value.replace(year=value.year + amount)
        except ValueError:
            return value.replace(year=value.year + amount, day=28)
    month_index = value.month - 1 + amount
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _bar_time(bar: MarketBar, price_field: Literal["open", "close"]) -> datetime | date:
    if price_field == "open" and bar.session_open_at is not None:
        return bar.session_open_at
    if price_field == "close" and bar.session_close_at is not None:
        return bar.session_close_at
    return bar.timestamp or bar.trading_date


def _after(value: datetime | date, boundary: datetime) -> bool:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ReturnCalculationError("bar timestamp must be timezone-aware")
        return value > boundary
    # A date-only series has no intraday timing.  Requiring the next date is
    # the conservative default and prevents a post-close signal filling the
    # same close.
    return value > boundary.date()


def _on_or_after(value: date, target: date) -> bool:
    return value >= target


def _action_date(action: CorporateAction) -> date:
    return action.ex_date or action.effective_date


def _actions_between(
    actions: tuple[CorporateAction, ...],
    *,
    start: date,
    end: date,
) -> tuple[CorporateAction, ...]:
    return tuple(action for action in actions if start < _action_date(action) <= end)


def validate_no_double_count(
    bars: tuple[MarketBar, ...] | list[MarketBar],
    actions: tuple[CorporateAction, ...] | list[CorporateAction],
    *,
    start: date | None = None,
    end: date | None = None,
) -> None:
    """Reject adjusted-price plus explicit-action double counting."""

    selected_bars = [
        bar
        for bar in bars
        if (start is None or bar.trading_date >= start) and (end is None or bar.trading_date <= end)
    ]
    if not any(bar.price_basis is PriceBasis.ADJUSTED for bar in selected_bars):
        return
    adjusted_scopes = {
        scope.upper()
        for bar in selected_bars
        if bar.price_basis is PriceBasis.ADJUSTED
        for scope in bar.adjustment_scope
    }
    if not adjusted_scopes:
        raise ReturnCalculationError("adjusted price series must declare adjustment_scope")
    relevant_actions = [
        action
        for action in actions
        if (start is None or _action_date(action) >= start)
        and (end is None or _action_date(action) <= end)
    ]
    for action in relevant_actions:
        represented = {
            "CASH_DIVIDEND": {
                "CASH_DIVIDEND",
                "CASH_DIVIDENDS",
                "DIVIDEND",
                "DIVIDENDS",
                "TOTAL_RETURN",
                "CORPORATE_ACTIONS",
                "ALL",
            },
            "SPLIT": {"SPLIT", "SPLITS", "TOTAL_RETURN", "CORPORATE_ACTIONS", "ALL"},
            "CONSOLIDATION": {
                "CONSOLIDATION",
                "SPLITS",
                "TOTAL_RETURN",
                "CORPORATE_ACTIONS",
                "ALL",
            },
        }.get(action.action_type.value, set())
        if adjusted_scopes.intersection(represented):
            raise ReturnCalculationError(
                "adjusted prices and explicit corporate actions would double count "
                f"{action.action_type.value} ({action.action_id})"
            )


class ReturnEngine:
    """One canonical return path over unadjusted bars plus explicit actions."""

    def __init__(self, manifest: BacktestDatasetManifest) -> None:
        self.manifest = validate_manifest(manifest)

    def _bars(self, listing_id: str) -> tuple[MarketBar, ...]:
        bars = self.manifest.bars_for(listing_id)
        if not bars:
            raise ReturnCalculationError(f"no market bars for listing {listing_id}")
        return bars

    def _entry_bar(
        self,
        listing_id: str,
        decision_time: datetime,
        *,
        price_field: Literal["open", "close"],
    ) -> MarketBar | None:
        bars = self._bars(listing_id)
        for bar in bars:
            price = bar.execution_price(price_field)
            if not bar.tradable or price is None or price <= 0:
                continue
            if _after(_bar_time(bar, price_field), decision_time):
                return bar
        return None

    def _exit_bar(
        self,
        listing_id: str,
        target_date: date,
        *,
        after_date: date,
    ) -> MarketBar | None:
        for bar in self._bars(listing_id):
            if (
                bar.tradable
                and bar.close is not None
                and bar.trading_date > after_date
                and _on_or_after(bar.trading_date, target_date)
            ):
                return bar
        return None

    def _actions(
        self,
        listing_id: str,
        *,
        entry_date: date,
        exit_date: date,
    ) -> tuple[CorporateAction, ...]:
        actions = _actions_between(
            self.manifest.actions_for(listing_id),
            start=entry_date,
            end=exit_date,
        )
        validate_no_double_count(
            self.manifest.bars_for(listing_id),
            actions,
            start=entry_date,
            end=exit_date,
        )
        return actions

    def forward_return(
        self,
        snapshot: DecisionSnapshot,
        horizon: str,
        *,
        entry_price: Literal["open", "close"] = "open",
    ) -> ForwardReturnObservation:
        """Evaluate one signal using only a strictly later executable bar."""

        target_date = add_horizon(snapshot.decision_time.date(), horizon)
        base_id = deterministic_id(
            "forward-return",
            snapshot.snapshot_id,
            horizon,
            entry_price,
            target_date.isoformat(),
        )
        try:
            bars = self._bars(snapshot.listing_id)
        except ReturnCalculationError:
            return ForwardReturnObservation(
                observation_id=base_id,
                snapshot_id=snapshot.snapshot_id,
                listing_id=snapshot.listing_id,
                decision_time=snapshot.decision_time,
                horizon=horizon,
                target_date=target_date,
                status=SignalOutcomeStatus.NO_ENTRY,
                missing_reason="NO_MARKET_BARS",
            )
        entry = self._entry_bar(
            snapshot.listing_id,
            snapshot.decision_time,
            price_field=entry_price,
        )
        if entry is None:
            status = (
                SignalOutcomeStatus.SUSPENDED
                if bars and all(not item.tradable or item.close is None for item in bars)
                else SignalOutcomeStatus.NO_ENTRY
            )
            return ForwardReturnObservation(
                observation_id=base_id,
                snapshot_id=snapshot.snapshot_id,
                listing_id=snapshot.listing_id,
                decision_time=snapshot.decision_time,
                horizon=horizon,
                target_date=target_date,
                status=status,
                missing_reason="NO_LATER_TRADABLE_ENTRY_BAR",
            )
        exit_bar = self._exit_bar(
            snapshot.listing_id,
            target_date,
            after_date=entry.trading_date,
        )
        terminal_action = next(
            (
                action
                for action in self.manifest.actions_for(snapshot.listing_id)
                if action.action_type is CorporateActionType.TERMINAL_VALUE
                and action.effective_date > entry.trading_date
                and action.effective_date <= target_date
            ),
            None,
        )
        if terminal_action is not None and (
            exit_bar is None or terminal_action.effective_date <= exit_bar.trading_date
        ):
            exit_bar = None
        if exit_bar is None and terminal_action is None:
            return ForwardReturnObservation(
                observation_id=base_id,
                snapshot_id=snapshot.snapshot_id,
                listing_id=snapshot.listing_id,
                decision_time=snapshot.decision_time,
                horizon=horizon,
                target_date=target_date,
                entry_date=entry.trading_date,
                entry_price=float(entry.execution_price(entry_price)),
                entry_bar_id=entry.bar_id,
                status=SignalOutcomeStatus.NO_EXIT,
                missing_reason="NO_LATER_TRADABLE_EXIT_BAR_OR_TERMINAL_VALUE",
                currency=entry.currency,
            )

        exit_date = terminal_action.effective_date if exit_bar is None else exit_bar.trading_date
        actions = self._actions(
            snapshot.listing_id,
            entry_date=entry.trading_date,
            exit_date=exit_date,
        )
        unsupported_actions = [
            action
            for action in actions
            if action.action_type
            in {CorporateActionType.RIGHTS_ISSUE, CorporateActionType.SHARE_ISSUANCE}
        ]
        if unsupported_actions:
            return ForwardReturnObservation(
                observation_id=base_id,
                snapshot_id=snapshot.snapshot_id,
                listing_id=snapshot.listing_id,
                decision_time=snapshot.decision_time,
                horizon=horizon,
                target_date=target_date,
                entry_date=entry.trading_date,
                entry_price=float(entry.execution_price(entry_price)),
                entry_bar_id=entry.bar_id,
                status=SignalOutcomeStatus.INVALID_CORPORATE_ACTION_DATA,
                missing_reason=(
                    "RETURN_ENGINE_REQUIRES_EXPLICIT_RIGHTS_OR_ISSUANCE_TREATMENT:"
                    + ",".join(action.action_id for action in unsupported_actions)
                ),
                currency=entry.currency,
            )
        multiplier = 1.0
        dividends = 0.0
        terminal_value = 0.0
        action_ids: list[str] = []
        for action in actions:
            action_ids.append(action.action_id)
            if action.action_type in {
                CorporateActionType.SPLIT,
                CorporateActionType.CONSOLIDATION,
            }:
                multiplier *= float(action.split_factor)
            elif action.action_type is CorporateActionType.CASH_DIVIDEND:
                dividends += float(action.cash_per_share) * multiplier
            elif action.action_type is CorporateActionType.TERMINAL_VALUE:
                terminal_value += float(action.terminal_value_per_share) * multiplier
        if terminal_action is not None and terminal_action.action_id not in action_ids:
            action_ids.append(terminal_action.action_id)
            terminal_value += float(terminal_action.terminal_value_per_share) * multiplier
        raw_entry = float(entry.execution_price(entry_price))
        # A terminal-value action is already accumulated in
        # ``terminal_value``.  The zero base price here prevents counting it
        # once as an exit quote and again as a cash-flow action.
        raw_exit = float(exit_bar.close) if exit_bar is not None else 0.0
        reported_exit = (
            raw_exit if exit_bar is not None else float(terminal_action.terminal_value_per_share)
        )
        economic_exit = raw_exit * multiplier + terminal_value
        price_result = (economic_exit / raw_entry) - 1.0
        total_result = ((raw_exit * multiplier + dividends + terminal_value) / raw_entry) - 1.0
        observation_id = deterministic_id(
            "forward-return",
            snapshot.snapshot_id,
            horizon,
            entry_price,
            entry.bar_id,
            None if exit_bar is None else exit_bar.bar_id,
            action_ids,
        )
        return ForwardReturnObservation(
            observation_id=observation_id,
            snapshot_id=snapshot.snapshot_id,
            listing_id=snapshot.listing_id,
            decision_time=snapshot.decision_time,
            horizon=horizon,
            target_date=target_date,
            entry_date=entry.trading_date,
            exit_date=exit_date,
            entry_price=raw_entry,
            exit_price=reported_exit,
            price_return=price_result,
            total_return=total_result,
            dividends_per_share=dividends,
            share_multiplier=multiplier,
            terminal_value_per_share=terminal_value,
            entry_bar_id=entry.bar_id,
            exit_bar_id=None if exit_bar is None else exit_bar.bar_id,
            corporate_action_ids=action_ids,
            status=(
                SignalOutcomeStatus.DELISTED_TERMINAL
                if terminal_action is not None and exit_bar is None
                else SignalOutcomeStatus.COMPLETE
            ),
            currency=entry.currency,
        )


def evaluate_forward_return(
    manifest: BacktestDatasetManifest,
    snapshot: DecisionSnapshot,
    horizon: str,
    *,
    entry_price: Literal["open", "close"] = "open",
) -> ForwardReturnObservation:
    """Functional facade for one point-in-time forward-return observation."""

    return ReturnEngine(manifest).forward_return(snapshot, horizon, entry_price=entry_price)


__all__ = [
    "ReturnCalculationError",
    "ReturnEngine",
    "add_horizon",
    "evaluate_forward_return",
    "validate_no_double_count",
]
