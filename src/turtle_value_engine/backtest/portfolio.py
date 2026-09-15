"""Small deterministic event-driven long-only portfolio simulator."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from statistics import pstdev
from typing import Literal

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .contracts import (
    PORTFOLIO_POLICY_CONTRACT_VERSION,
    BacktestDatasetManifest,
    CorporateActionType,
    DecisionSnapshot,
    ExecutionPrice,
    FailureAttribution,
    MissingDataAction,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioPolicy,
    PortfolioSimulationResult,
    PortfolioSnapshot,
    PositionSnapshot,
    SignalEvaluationResult,
    SizingRule,
)
from .dataset import is_available_at, validate_manifest
from .metrics import (
    benchmark_daily_returns_for_snapshots,
    benchmark_results,
    build_failure_attribution,
    calculate_performance_metrics,
)
from .signals import SignalEvaluator


class PortfolioSimulationError(ValueError):
    """Raised when a portfolio policy cannot produce an auditable fill."""


def _timestamp(value: date, *, close: bool = False) -> datetime:
    return datetime.combine(value, time.max if close else time.min, tzinfo=UTC)


def _bar_time(bar, price_field: Literal["open", "close"]) -> datetime | date:
    if price_field == "open" and bar.session_open_at is not None:
        return bar.session_open_at
    if price_field == "close" and bar.session_close_at is not None:
        return bar.session_close_at
    return bar.timestamp or bar.trading_date


def _strictly_after(value: datetime | date, boundary: datetime) -> bool:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise PortfolioSimulationError("market bar timestamp must be timezone-aware")
        return value > boundary
    return value > boundary.date()


def _floor_lot(quantity: float, lot_size: int) -> float:
    if quantity <= 0:
        return 0.0
    return math.floor((quantity + 1e-10) / lot_size) * lot_size


def _fee(policy: PortfolioPolicy, side: Literal["BUY", "SELL"], gross: float) -> float:
    costs = policy.transaction_costs
    bps = costs.commission_bps
    if side == "SELL":
        bps += costs.sell_stamp_duty_bps + costs.transfer_fee_bps
    result = gross * bps / 10_000
    if gross > 0 and result > 0:
        result = max(result, costs.minimum_fee)
    return result


def _policy_hash(policy: PortfolioPolicy) -> str:
    return hashlib.sha256(
        canonical_json_bytes(policy.model_dump(mode="json", warnings=False))
    ).hexdigest()


@dataclass
class _Position:
    listing_id: str
    market: object
    sector: str | None
    currency: str
    quantity: float = 0.0
    average_cost: float = 0.0
    mark_price: float | None = None
    mark_value: float = 0.0
    suspended: bool = False


class PortfolioSimulator:
    """Replay a frozen manifest under one explicitly versioned policy.

    The first policy implementation is intentionally conservative: signals
    become targets at the next eligible bar, target weights are capped without
    redistribution, and missing liquidity means no fabricated fill.
    """

    def __init__(self, manifest: BacktestDatasetManifest) -> None:
        self.manifest = validate_manifest(manifest)
        self._lifecycles = {item.listing_id: item for item in self.manifest.listing_lifecycles}
        self._positions: dict[str, _Position] = {}
        self._cash = 0.0
        self._events: list[PortfolioEvent] = []
        self._turnover = 0.0
        self._last_prices: dict[str, float] = {}
        self._last_bar_ids: dict[str, str] = {}
        self._last_mark_date: date | None = None

    def _lot_size(self, listing_id: str, policy: PortfolioPolicy) -> int:
        market = self._lifecycles[listing_id].market.value
        return policy.lot_size_a if market == "A" else policy.lot_size_h

    def _fx_factor(
        self,
        currency: str,
        value: date,
        policy: PortfolioPolicy,
        *,
        boundary: datetime | None = None,
    ) -> float:
        if currency == policy.base_currency:
            return 1.0
        availability_boundary = boundary or _timestamp(value, close=True)
        candidates = []
        for observation in self.manifest.fx_observations:
            if observation.observation_date > value:
                continue
            if not is_available_at(observation.available_at, availability_boundary):
                continue
            if (
                observation.base_currency == currency
                and observation.quote_currency == policy.base_currency
            ):
                candidates.append(
                    (observation.observation_date, observation.observation_id, observation.rate)
                )
            elif (
                observation.base_currency == policy.base_currency
                and observation.quote_currency == currency
            ):
                candidates.append(
                    (observation.observation_date, observation.observation_id, 1 / observation.rate)
                )
        if not candidates:
            raise PortfolioSimulationError(
                f"no point-in-time FX observation for {currency}/{policy.base_currency} on {value}"
            )
        return sorted(candidates)[-1][2]

    def _bars(self, listing_id: str):
        return self.manifest.bars_for(listing_id)

    def _execution_bar(self, listing_id: str, boundary: datetime, policy: PortfolioPolicy):
        field = "open" if policy.execution_price is ExecutionPrice.NEXT_OPEN else "close"
        for bar in self._bars(listing_id):
            price = bar.execution_price(field)
            if (
                bar.tradable
                and price is not None
                and price > 0
                and _strictly_after(_bar_time(bar, field), boundary)
            ):
                return bar, field
        return None, field

    def _bar_on_or_before(
        self,
        listing_id: str,
        value: date,
        price_field: Literal["open", "close"] = "close",
    ):
        selected = [
            bar
            for bar in self._bars(listing_id)
            if bar.trading_date <= value
            and bar.execution_price(price_field) is not None
            and bar.execution_price(price_field) > 0
        ]
        return selected[-1] if selected else None

    def _execution_bar_on_date(
        self,
        listing_id: str,
        value: date,
        policy: PortfolioPolicy,
    ):
        field = "open" if policy.execution_price is ExecutionPrice.NEXT_OPEN else "close"
        for bar in self._bars(listing_id):
            price = bar.execution_price(field)
            if bar.trading_date == value and bar.tradable and price is not None and price > 0:
                return bar, field
        return None, field

    def _emit(
        self,
        timestamp: datetime,
        event_type: PortfolioEventType,
        *,
        listing_id: str | None = None,
        side: Literal["BUY", "SELL", "NONE"] = "NONE",
        quantity: float = 0.0,
        price: float | None = None,
        gross_value: float = 0.0,
        fees: float = 0.0,
        cash_delta: float = 0.0,
        action_id: str | None = None,
        bar_id: str | None = None,
        reason: str | None = None,
        source_hashes: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        event_id = deterministic_id(
            "portfolio-event",
            timestamp.isoformat(),
            event_type.value,
            listing_id,
            side,
            quantity,
            price,
            gross_value,
            fees,
            cash_delta,
            action_id,
            bar_id,
            reason,
            source_hashes or [],
            metadata or {},
        )
        self._events.append(
            PortfolioEvent(
                event_id=event_id,
                timestamp=timestamp,
                event_type=event_type,
                listing_id=listing_id,
                side=side,
                quantity=quantity,
                price=price,
                gross_value=gross_value,
                fees=fees,
                cash_delta=cash_delta,
                action_id=action_id,
                bar_id=bar_id,
                reason=reason,
                source_hashes=source_hashes or [],
                metadata=metadata or {},
            )
        )

    def _handle_actions(self, value: date, policy: PortfolioPolicy) -> None:
        for listing_id, position in sorted(self._positions.items()):
            if position.quantity <= 0:
                continue
            for action in self.manifest.actions_for(listing_id):
                if action.effective_date != value:
                    continue
                timestamp = _timestamp(value)
                if action.available_at is None:
                    raise PortfolioSimulationError(
                        "corporate action availability is unknown: " + action.action_id
                    )
                if not is_available_at(action.available_at, timestamp):
                    raise PortfolioSimulationError(
                        "corporate action is not available at its effective time: "
                        + action.action_id
                    )
                lifecycle = self._lifecycles[listing_id]
                if action.action_type.value == "CASH_DIVIDEND":
                    factor = self._fx_factor(
                        action.currency or lifecycle.currency,
                        value,
                        policy,
                        boundary=timestamp,
                    )
                    cash = (
                        position.quantity * float(action.cash_per_share) * factor
                        if policy.dividends_to_cash
                        else 0.0
                    )
                    self._cash += cash
                    self._emit(
                        timestamp,
                        PortfolioEventType.DIVIDEND,
                        listing_id=listing_id,
                        quantity=position.quantity,
                        gross_value=cash,
                        cash_delta=cash,
                        action_id=action.action_id,
                        source_hashes=[action.source_hash],
                        reason=(
                            "DIVIDEND_TO_CASH"
                            if policy.dividends_to_cash
                            else "DIVIDEND_NOT_REINVESTED_BY_POLICY"
                        ),
                    )
                elif action.action_type.value in {"SPLIT", "CONSOLIDATION"}:
                    split_factor = float(action.split_factor)
                    position.quantity *= split_factor
                    position.average_cost /= split_factor
                    self._emit(
                        timestamp,
                        PortfolioEventType.SPLIT,
                        listing_id=listing_id,
                        quantity=position.quantity,
                        action_id=action.action_id,
                        source_hashes=[action.source_hash],
                        metadata={"split_factor": split_factor},
                    )
                elif action.action_type.value == "TERMINAL_VALUE":
                    if policy.terminal_value_policy == "NO_VALUE":
                        self._emit(
                            timestamp,
                            PortfolioEventType.SKIP,
                            listing_id=listing_id,
                            quantity=position.quantity,
                            action_id=action.action_id,
                            source_hashes=[action.source_hash],
                            reason="TERMINAL_VALUE_IGNORED_BY_POLICY",
                        )
                    else:
                        factor = self._fx_factor(
                            action.currency or lifecycle.currency,
                            value,
                            policy,
                            boundary=timestamp,
                        )
                        cash = position.quantity * float(action.terminal_value_per_share) * factor
                        self._cash += cash
                        self._emit(
                            timestamp,
                            PortfolioEventType.TERMINAL_VALUE,
                            listing_id=listing_id,
                            quantity=position.quantity,
                            gross_value=cash,
                            cash_delta=cash,
                            action_id=action.action_id,
                            source_hashes=[action.source_hash],
                        )
                    position.quantity = 0.0
                    position.mark_value = 0.0
                elif action.action_type.value == "DELISTING":
                    has_terminal_value = any(
                        item.action_type is CorporateActionType.TERMINAL_VALUE
                        and item.effective_date <= value
                        for item in self.manifest.actions_for(listing_id)
                    )
                    if not has_terminal_value:
                        if policy.terminal_value_policy == "NO_VALUE":
                            self._emit(
                                timestamp,
                                PortfolioEventType.SKIP,
                                listing_id=listing_id,
                                quantity=position.quantity,
                                action_id=action.action_id,
                                source_hashes=[action.source_hash],
                                reason="DELISTING_WRITTEN_OFF_BY_POLICY",
                            )
                            position.quantity = 0.0
                            position.mark_value = 0.0
                        else:
                            raise PortfolioSimulationError(
                                "delisting has no explicit terminal value: " + action.action_id
                            )
                elif action.action_type.value == "RIGHTS_ISSUE":
                    self._handle_rights_issue(position, action, value, policy)
                elif action.action_type.value == "SHARE_ISSUANCE":
                    self._handle_share_issuance(position, action, value, policy)

    def _handle_rights_issue(self, position, action, value: date, policy: PortfolioPolicy) -> None:
        if not hasattr(policy, "rights_issue_policy"):
            raise PortfolioSimulationError("portfolio policy does not define rights-issue handling")
        mode = policy.rights_issue_policy
        if mode == "FAIL":
            raise PortfolioSimulationError(
                f"unsupported rights issue without policy: {action.action_id}"
            )
        if mode == "IGNORE":
            self._emit(
                _timestamp(value),
                PortfolioEventType.SKIP,
                listing_id=position.listing_id,
                action_id=action.action_id,
                reason="RIGHTS_ISSUE_IGNORED_BY_POLICY",
                source_hashes=[action.source_hash],
            )
            return
        ratio = float(action.rights_ratio or 0)
        price = float(action.rights_price or 0)
        if ratio <= 0 or price <= 0:
            raise PortfolioSimulationError(f"rights issue lacks ratio/price: {action.action_id}")
        add_quantity = _floor_lot(
            position.quantity * ratio, self._lot_size(position.listing_id, policy)
        )
        local_cash = add_quantity * price
        factor = self._fx_factor(
            self._lifecycles[position.listing_id].currency,
            value,
            policy,
            boundary=_timestamp(value),
        )
        cash = local_cash * factor
        if cash > self._cash + 1e-9:
            self._emit(
                _timestamp(value),
                PortfolioEventType.SKIP,
                listing_id=position.listing_id,
                action_id=action.action_id,
                reason="RIGHTS_ISSUE_NOT_FUNDED",
                source_hashes=[action.source_hash],
            )
            return
        self._cash -= cash
        position.quantity += add_quantity
        self._emit(
            _timestamp(value),
            PortfolioEventType.CASH_FLOW,
            listing_id=position.listing_id,
            quantity=add_quantity,
            price=price,
            gross_value=cash,
            cash_delta=-cash,
            action_id=action.action_id,
            source_hashes=[action.source_hash],
            reason="RIGHTS_ISSUE_SUBSCRIBED_IF_FUNDED",
        )

    def _handle_share_issuance(
        self, position, action, value: date, policy: PortfolioPolicy
    ) -> None:
        mode = getattr(policy, "share_issuance_policy", "FAIL")
        if mode == "FAIL":
            raise PortfolioSimulationError(
                f"unsupported share issuance without policy: {action.action_id}"
            )
        if mode == "IGNORE":
            self._emit(
                _timestamp(value),
                PortfolioEventType.SKIP,
                listing_id=position.listing_id,
                action_id=action.action_id,
                reason="SHARE_ISSUANCE_IGNORED_BY_POLICY",
                source_hashes=[action.source_hash],
            )
            return
        factor = float(action.split_factor or 0)
        if factor <= 0:
            raise PortfolioSimulationError(f"share issuance lacks share factor: {action.action_id}")
        position.quantity *= factor
        position.average_cost /= factor
        self._emit(
            _timestamp(value),
            PortfolioEventType.SPLIT,
            listing_id=position.listing_id,
            quantity=position.quantity,
            action_id=action.action_id,
            source_hashes=[action.source_hash],
            reason="SHARE_ISSUANCE_APPLIED_AS_FACTOR",
            metadata={"share_factor": factor},
        )

    def _current_price(
        self,
        listing_id: str,
        value: date,
        policy: PortfolioPolicy,
        price_field: Literal["open", "close"] = "close",
    ) -> tuple[float | None, str | None]:
        bar = self._bar_on_or_before(listing_id, value, price_field)
        if bar is None or not bar.tradable:
            return self._last_prices.get(listing_id), self._last_bar_ids.get(listing_id)
        self._last_prices[listing_id] = float(bar.execution_price(price_field))
        self._last_bar_ids[listing_id] = bar.bar_id
        return float(bar.execution_price(price_field)), bar.bar_id

    def _mark(
        self,
        value: date,
        policy: PortfolioPolicy,
        *,
        emit_event: bool = True,
        price_field: Literal["open", "close"] = "close",
        update_previous_nav: bool = True,
    ) -> PortfolioSnapshot:
        gross = 0.0
        positions: list[PositionSnapshot] = []
        missing: list[str] = []
        source_bar_ids: list[str] = []
        for listing_id, position in sorted(self._positions.items()):
            price, bar_id = self._current_price(listing_id, value, policy, price_field)
            position.mark_price = price
            if price is None:
                position.mark_value = 0.0
                position.suspended = True
                if position.quantity > 0:
                    missing.append(listing_id)
            else:
                factor = self._fx_factor(position.currency, value, policy)
                position.mark_value = position.quantity * price * factor
                position.suspended = False
                if bar_id is not None:
                    source_bar_ids.append(bar_id)
            gross += position.mark_value
            positions.append(
                PositionSnapshot(
                    listing_id=listing_id,
                    market=position.market,
                    sector=position.sector,
                    quantity=position.quantity,
                    mark_price=position.mark_price,
                    market_value=position.mark_value,
                    average_cost=position.average_cost,
                    suspended=position.suspended,
                    price_missing=listing_id in missing,
                )
            )
        nav = self._cash + gross
        if nav <= 0:
            raise PortfolioSimulationError(f"portfolio NAV is not positive on {value}")
        previous_nav = getattr(self, "_previous_nav", None)
        daily_return = None if previous_nav is None else nav / previous_nav - 1
        initial_cash = self._initial_cash
        snapshot = PortfolioSnapshot(
            timestamp=_timestamp(value, close=True),
            cash=self._cash,
            gross_exposure=gross / nav,
            net_asset_value=nav,
            positions=positions,
            daily_return=daily_return,
            cumulative_return=nav / initial_cash - 1,
            cash_exposure=self._cash / nav,
            turnover=self._turnover,
            missing_price_listings=missing,
            source_bar_ids=sorted(set(source_bar_ids)),
        )
        if update_previous_nav:
            self._previous_nav = nav
        self._last_mark_date = value
        if emit_event:
            self._emit(
                snapshot.timestamp,
                PortfolioEventType.MARK,
                gross_value=nav,
                cash_delta=0,
                bar_id=None,
                reason="DAILY_PORTFOLIO_MARK",
                source_hashes=sorted(
                    {
                        bar.source_hash
                        for bar in self.manifest.market_bars
                        if bar.bar_id in snapshot.source_bar_ids
                    }
                ),
            )
        return snapshot

    def _available_quantity(
        self, bar, requested: float, price: float, policy: PortfolioPolicy
    ) -> float:
        volume = bar.volume
        amount = bar.amount
        if volume is None:
            if policy.liquidity.missing_data_action is MissingDataAction.FAIL:
                raise PortfolioSimulationError(f"volume is missing for fill bar {bar.bar_id}")
            return 0.0
        if (
            policy.liquidity.min_daily_volume is not None
            and volume < policy.liquidity.min_daily_volume
        ):
            return 0.0
        if policy.liquidity.min_daily_amount is not None:
            if amount is None:
                if policy.liquidity.missing_data_action is MissingDataAction.FAIL:
                    raise PortfolioSimulationError(f"amount is missing for fill bar {bar.bar_id}")
                return 0.0
            if amount < policy.liquidity.min_daily_amount:
                return 0.0
        available = volume * policy.liquidity.max_participation_rate
        if amount is not None:
            available = min(available, amount / price)
        if policy.liquidity.max_order_notional is not None:
            available = min(available, policy.liquidity.max_order_notional / price)
        return min(requested, available)

    def _fill(
        self,
        listing_id: str,
        desired_quantity: float,
        bar,
        price_field: Literal["open", "close"],
        side: Literal["BUY", "SELL"],
        policy: PortfolioPolicy,
    ) -> None:
        raw_price = bar.execution_price(price_field)
        if raw_price is None or raw_price <= 0 or not bar.tradable:
            self._emit(
                _timestamp(bar.trading_date),
                PortfolioEventType.SKIP,
                listing_id=listing_id,
                bar_id=bar.bar_id,
                reason="NO_EXECUTABLE_PRICE",
                source_hashes=[bar.source_hash],
            )
            return
        position = self._positions.setdefault(
            listing_id,
            _Position(
                listing_id=listing_id,
                market=self._lifecycles[listing_id].market,
                sector=self._lifecycles[listing_id].sector,
                currency=self._lifecycles[listing_id].currency,
            ),
        )
        lot_size = self._lot_size(listing_id, policy)
        requested = _floor_lot(desired_quantity, lot_size)
        if requested <= 0:
            return
        executable_price = float(raw_price) * (
            1 + policy.transaction_costs.slippage_bps / 10_000
            if side == "BUY"
            else 1 - policy.transaction_costs.slippage_bps / 10_000
        )
        available = self._available_quantity(bar, requested, executable_price, policy)
        quantity = _floor_lot(available, lot_size)
        if side == "SELL":
            quantity = min(quantity, _floor_lot(position.quantity, lot_size))
        if quantity <= 0:
            self._emit(
                _timestamp(bar.trading_date),
                PortfolioEventType.SKIP,
                listing_id=listing_id,
                bar_id=bar.bar_id,
                reason="LIQUIDITY_NO_FILL",
                source_hashes=[bar.source_hash],
            )
            return
        local_gross = quantity * executable_price
        execution_time = _bar_time(bar, price_field)
        execution_boundary = (
            execution_time
            if isinstance(execution_time, datetime)
            else _timestamp(bar.trading_date, close=price_field == "close")
        )
        fx = self._fx_factor(
            position.currency,
            bar.trading_date,
            policy,
            boundary=execution_boundary,
        )
        gross = local_gross * fx
        fees = _fee(policy, side, gross)
        if side == "BUY":
            total = gross + fees
            if total > self._cash + 1e-9:
                quantity = _floor_lot(
                    self._cash
                    / (executable_price * fx + _fee(policy, side, executable_price * fx)),
                    lot_size,
                )
                if quantity <= 0:
                    return
                local_gross = quantity * executable_price
                gross = local_gross * fx
                fees = _fee(policy, side, gross)
                total = gross + fees
                while quantity > 0 and total > self._cash + 1e-9:
                    quantity = _floor_lot(quantity - lot_size, lot_size)
                    local_gross = quantity * executable_price
                    gross = local_gross * fx
                    fees = _fee(policy, side, gross)
                    total = gross + fees
                if quantity <= 0:
                    timestamp = (
                        execution_time
                        if isinstance(execution_time, datetime)
                        else _timestamp(execution_time)
                    )
                    self._emit(
                        timestamp,
                        PortfolioEventType.SKIP,
                        listing_id=listing_id,
                        bar_id=bar.bar_id,
                        reason="INSUFFICIENT_CASH_AFTER_COSTS",
                        source_hashes=[bar.source_hash],
                    )
                    return
            self._cash -= total
            previous_quantity = position.quantity
            position.quantity += quantity
            position.average_cost = (
                ((position.average_cost * previous_quantity) + total) / position.quantity
                if position.quantity > 0
                else 0
            )
        else:
            self._cash += gross - fees
            position.quantity -= quantity
            if position.quantity <= 1e-9:
                position.quantity = 0.0
                position.average_cost = 0.0
        self._turnover += gross / self._initial_cash
        timestamp_value = execution_time
        timestamp = (
            timestamp_value
            if isinstance(timestamp_value, datetime)
            else _timestamp(timestamp_value)
        )
        self._emit(
            timestamp,
            PortfolioEventType.FILL,
            listing_id=listing_id,
            side=side,
            quantity=quantity,
            price=executable_price,
            gross_value=gross,
            fees=fees,
            cash_delta=-gross if side == "BUY" else gross,
            bar_id=bar.bar_id,
            source_hashes=[bar.source_hash],
        )
        if fees > 0:
            self._emit(
                timestamp,
                PortfolioEventType.FEE,
                listing_id=listing_id,
                side=side,
                gross_value=gross,
                fees=fees,
                cash_delta=-fees,
                bar_id=bar.bar_id,
                source_hashes=[bar.source_hash],
            )

    def _target_snapshots(
        self,
        snapshots: list[DecisionSnapshot],
        execution_date: date,
        policy: PortfolioPolicy,
    ) -> dict[str, DecisionSnapshot]:
        latest: dict[str, DecisionSnapshot] = {}
        for snapshot in snapshots:
            if snapshot.decision_time.date() > execution_date:
                continue
            first_execution_bar, _field = self._execution_bar(
                snapshot.listing_id,
                snapshot.decision_time,
                policy,
            )
            if first_execution_bar is None or first_execution_bar.trading_date > execution_date:
                continue
            if snapshot.final_state not in policy.eligible_states:
                continue
            current = latest.get(snapshot.listing_id)
            if current is None or (
                snapshot.decision_time,
                snapshot.snapshot_id,
            ) > (current.decision_time, current.snapshot_id):
                latest[snapshot.listing_id] = snapshot
        return latest

    def _rebalance(
        self,
        execution_date: date,
        signal_snapshots: list[DecisionSnapshot],
        policy: PortfolioPolicy,
    ) -> None:
        targets = self._target_snapshots(signal_snapshots, execution_date, policy)
        weights: dict[str, float] = {}
        if targets:
            investable_weight = 1 - policy.cash_buffer
            if policy.sizing_rule is SizingRule.EQUAL_RISK:
                inverse_risk = {
                    listing_id: 1 / self._risk_estimate(listing_id, execution_date)
                    for listing_id in targets
                }
                total_inverse_risk = sum(inverse_risk.values())
                raw_weights = {
                    listing_id: investable_weight * value / total_inverse_risk
                    for listing_id, value in inverse_risk.items()
                }
            else:
                base_weight = investable_weight / len(targets)
                raw_weights = {listing_id: base_weight for listing_id in targets}
            sector_counts: dict[str, int] = {}
            for listing_id in targets:
                sector = self._lifecycles[listing_id].sector
                if sector is not None:
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1
            for listing_id in sorted(targets):
                weight = min(raw_weights[listing_id], policy.max_position_weight)
                sector = self._lifecycles[listing_id].sector
                if policy.max_sector_weight is not None and sector is not None:
                    weight = min(
                        weight,
                        policy.max_sector_weight / sector_counts[sector],
                    )
                weights[listing_id] = weight
        nav = self._cash + sum(position.mark_value for position in self._positions.values())
        if nav <= 0:
            return
        self._emit(
            _timestamp(execution_date),
            PortfolioEventType.REBALANCE,
            gross_value=nav,
            reason="LATEST_ELIGIBLE_DECISION_SNAPSHOTS",
            source_hashes=sorted(
                {
                    source_hash
                    for snapshot in targets.values()
                    for source_hash in (snapshot.input_sha256, snapshot.analysis_sha256)
                }
            ),
        )
        for listing_id, position in sorted(self._positions.items()):
            if listing_id not in weights and position.quantity > 0:
                bar, field = self._execution_bar_on_date(listing_id, execution_date, policy)
                if bar is not None:
                    self._fill(listing_id, position.quantity, bar, field, "SELL", policy)
        for listing_id, weight in sorted(weights.items()):
            bar, field = self._execution_bar_on_date(listing_id, execution_date, policy)
            if bar is None:
                self._emit(
                    _timestamp(execution_date),
                    PortfolioEventType.SKIP,
                    listing_id=listing_id,
                    reason="NO_LATER_EXECUTABLE_REBALANCE_BAR",
                )
                continue
            position = self._positions.setdefault(
                listing_id,
                _Position(
                    listing_id=listing_id,
                    market=self._lifecycles[listing_id].market,
                    sector=self._lifecycles[listing_id].sector,
                    currency=self._lifecycles[listing_id].currency,
                ),
            )
            price = float(bar.execution_price(field))
            execution_time = _bar_time(bar, field)
            execution_boundary = (
                execution_time
                if isinstance(execution_time, datetime)
                else _timestamp(execution_date, close=field == "close")
            )
            fx = self._fx_factor(
                position.currency,
                execution_date,
                policy,
                boundary=execution_boundary,
            )
            target_quantity = (nav * weight) / (price * fx)
            delta = target_quantity - position.quantity
            if delta > 0:
                self._fill(listing_id, delta, bar, field, "BUY", policy)
            elif delta < 0:
                self._fill(listing_id, -delta, bar, field, "SELL", policy)

    def _risk_estimate(self, listing_id: str, value: date) -> float:
        closes = [
            float(bar.close)
            for bar in self._bars(listing_id)
            if bar.trading_date <= value and bar.tradable and bar.close is not None
        ][-21:]
        returns = [
            current / previous - 1 for previous, current in zip(closes, closes[1:], strict=False)
        ]
        if len(returns) < 2:
            return 1.0
        result = pstdev(returns)
        return result if result > 0 else 1.0

    @staticmethod
    def _rebalance_due(
        value: date,
        last_rebalance: date | None,
        policy: PortfolioPolicy,
    ) -> bool:
        if last_rebalance is None or policy.rebalance_frequency.value == "DAILY":
            return True
        if policy.rebalance_frequency.value == "WEEKLY":
            return value.isocalendar()[:2] != last_rebalance.isocalendar()[:2]
        return (value.year, value.month) != (last_rebalance.year, last_rebalance.month)

    def run(
        self,
        snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
        policy: PortfolioPolicy,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        benchmark_ids: list[str] | tuple[str, ...] = (),
        signal_evaluation: SignalEvaluationResult | None = None,
    ) -> PortfolioSimulationResult:
        """Run an offline simulation and return only validated persisted output."""

        if not isinstance(policy, PortfolioPolicy):
            raise TypeError("policy must be a PortfolioPolicy")
        policy = PortfolioPolicy.model_validate(policy.model_dump(mode="python", warnings=False))
        if policy.policy_version != PORTFOLIO_POLICY_CONTRACT_VERSION:
            raise PortfolioSimulationError(
                "portfolio simulator only implements the portfolio-policy-v1 contract"
            )
        dates = sorted({bar.trading_date for bar in self.manifest.market_bars})
        if not dates:
            raise PortfolioSimulationError("portfolio simulation requires market bars")
        active_start = start_date or self.manifest.start_date
        active_end = end_date or self.manifest.end_date
        if active_start < self.manifest.start_date or active_end > self.manifest.end_date:
            raise PortfolioSimulationError("simulation range must lie within dataset range")
        if active_end < active_start:
            raise PortfolioSimulationError("simulation end_date must not precede start_date")
        self._cash = float(policy.initial_cash)
        self._initial_cash = float(policy.initial_cash)
        self._events = []
        self._positions = {}
        self._turnover = 0.0
        self._last_prices = {}
        self._last_bar_ids = {}
        self._previous_nav = None
        last_rebalance: date | None = None
        self._emit(
            _timestamp(active_start),
            PortfolioEventType.INITIAL_CASH,
            gross_value=self._cash,
            cash_delta=self._cash,
            reason="POLICY_INITIAL_CASH",
        )
        ordered_snapshots = sorted(
            [snapshot for snapshot in snapshots if snapshot.decision_time.date() <= active_end],
            key=lambda item: (item.decision_time, item.listing_id, item.snapshot_id),
        )
        if len({item.snapshot_id for item in ordered_snapshots}) != len(ordered_snapshots):
            raise PortfolioSimulationError("portfolio snapshots must have unique IDs")
        if len({item.profile_id for item in ordered_snapshots}) > 1:
            raise PortfolioSimulationError("portfolio snapshots must use one rule profile")
        if signal_evaluation is not None:
            if signal_evaluation.manifest_id != self.manifest.dataset_id:
                raise PortfolioSimulationError(
                    "signal evaluation manifest_id does not match portfolio dataset"
                )
            if set(signal_evaluation.snapshot_ids) != {
                item.snapshot_id for item in ordered_snapshots
            }:
                raise PortfolioSimulationError(
                    "signal evaluation snapshots do not match portfolio input snapshots"
                )
        snapshot_validator = SignalEvaluator(self.manifest)
        for snapshot in ordered_snapshots:
            try:
                snapshot_validator.validate_snapshot(snapshot)
            except (KeyError, ValueError) as exc:
                raise PortfolioSimulationError(
                    f"portfolio snapshot is not valid at its decision time: {snapshot.snapshot_id}"
                ) from exc
        schedule: dict[date, list[DecisionSnapshot]] = {}
        for snapshot in ordered_snapshots:
            bar, _field = self._execution_bar(snapshot.listing_id, snapshot.decision_time, policy)
            if bar is not None and active_start <= bar.trading_date <= active_end:
                schedule.setdefault(bar.trading_date, []).append(snapshot)
        snapshots_out: list[PortfolioSnapshot] = []
        for value in [item for item in dates if active_start <= item <= active_end]:
            self._handle_actions(value, policy)
            if value in schedule and self._rebalance_due(value, last_rebalance, policy):
                mark_field = (
                    "open" if policy.execution_price is ExecutionPrice.NEXT_OPEN else "close"
                )
                self._mark(
                    value,
                    policy,
                    emit_event=False,
                    price_field=mark_field,
                    update_previous_nav=False,
                )
                self._rebalance(value, ordered_snapshots, policy)
                last_rebalance = value
            snapshots_out.append(self._mark(value, policy))
        if not snapshots_out:
            snapshots_out.append(self._mark(active_end, policy))
        benchmarks = benchmark_results(
            self.manifest,
            benchmark_ids,
            start_date=active_start,
            end_date=active_end,
        )
        benchmark_cagr = next(
            (item.cagr for item in benchmarks if item.cagr is not None),
            None,
        )
        benchmark_daily_returns = (
            benchmark_daily_returns_for_snapshots(
                self.manifest,
                snapshots_out,
                benchmark_id=benchmark_ids[0],
            )
            if benchmark_ids
            else []
        )
        factor_samples: dict[str, list[float]] = {}
        for snapshot in snapshots_out:
            for position in snapshot.positions:
                weight = position.market_value / snapshot.net_asset_value
                factor_samples.setdefault(f"market:{position.market.value}", []).append(weight)
                if position.sector:
                    factor_samples.setdefault(f"sector:{position.sector}", []).append(weight)
        factor_exposure = {
            key: sum(values) / len(values)
            for key, values in sorted(factor_samples.items())
            if values
        }
        metrics = calculate_performance_metrics(
            snapshots_out,
            initial_nav=self._initial_cash,
            benchmark_cagr=benchmark_cagr,
            benchmark_daily_returns=benchmark_daily_returns,
            turnover=self._turnover,
            expected_observations=len(snapshots_out),
            factor_exposure=factor_exposure,
        )
        failure_attribution = (
            build_failure_attribution(
                signal_evaluation.observations,
                ordered_snapshots,
                manifest=self.manifest,
            )
            if signal_evaluation is not None
            else FailureAttribution()
        )
        fill_events = [
            event for event in self._events if event.event_type is PortfolioEventType.FILL
        ]
        failure_attribution = failure_attribution.model_copy(
            update={
                "cost_liquidity_sensitivity": {
                    "fill_count": float(len(fill_events)),
                    "fee_paid": sum(event.fees for event in fill_events),
                    "turnover_on_initial_cash": self._turnover,
                }
            }
        )
        simulation_id = deterministic_id(
            "portfolio-simulation",
            self.manifest.dataset_id,
            policy.model_dump(mode="json"),
            active_start.isoformat(),
            active_end.isoformat(),
            [item.snapshot_id for item in ordered_snapshots],
            list(benchmark_ids),
        )
        candidate = PortfolioSimulationResult.model_construct(
            contract="portfolio_simulation_result_v1",
            simulation_id=simulation_id,
            manifest_id=self.manifest.dataset_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_sha256=_policy_hash(policy),
            start_date=active_start,
            end_date=active_end,
            events=sorted(self._events, key=lambda item: (item.timestamp, item.event_id)),
            snapshots=snapshots_out,
            metrics=metrics,
            benchmark_results=benchmarks,
            failure_attribution=failure_attribution,
            final_net_asset_value=snapshots_out[-1].net_asset_value,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return PortfolioSimulationResult.model_validate(payload)


def simulate_portfolio(
    manifest: BacktestDatasetManifest,
    snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
    policy: PortfolioPolicy,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    benchmark_ids: list[str] | tuple[str, ...] = (),
    signal_evaluation: SignalEvaluationResult | None = None,
) -> PortfolioSimulationResult:
    """Functional facade for the deterministic portfolio simulator."""

    return PortfolioSimulator(manifest).run(
        snapshots,
        policy,
        start_date=start_date,
        end_date=end_date,
        benchmark_ids=benchmark_ids,
        signal_evaluation=signal_evaluation,
    )


def replay_cash_balance(events: list[PortfolioEvent] | tuple[PortfolioEvent, ...]) -> float:
    """Replay persisted cash deltas as a small independent audit check."""

    ordered = sorted(events, key=lambda item: (item.timestamp, item.event_id))
    return sum(float(event.cash_delta) for event in ordered)


__all__ = [
    "PortfolioSimulationError",
    "PortfolioSimulator",
    "replay_cash_balance",
    "simulate_portfolio",
]
