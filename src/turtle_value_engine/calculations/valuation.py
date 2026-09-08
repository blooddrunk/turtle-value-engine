"""Pure strict-v1 valuation tiers and listing-price calculations."""

from collections.abc import Iterable
from decimal import Decimal

from turtle_value_engine.calculations.facts import FactBook, numeric_value
from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import (
    CDCResult,
    ConfidenceLevel,
    NormalizedCompanyInput,
    ValuationResult,
    ValuationState,
    ValuationTiers,
)
from turtle_value_engine.models.valuation import ValuationInput


class ValuationCalculationError(ValueError):
    """Raised when valuation inputs or the active valuation profile are invalid."""


_TIER_NAMES = ("observation", "acceptable", "turtle_entry", "extreme_safety")


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _worst_confidence(levels: Iterable[ConfidenceLevel]) -> ConfidenceLevel:
    order = {
        ConfidenceLevel.HIGH: 0,
        ConfidenceLevel.MEDIUM: 1,
        ConfidenceLevel.LOW: 2,
    }
    values = list(levels)
    return max(values, key=order.__getitem__) if values else ConfidenceLevel.LOW


def _profile_is_supported(profile: RuleProfile) -> bool:
    valuation = profile.valuation
    if valuation.combine_constraints != "min":
        return False
    if valuation.quality_premium_enabled:
        return False
    if valuation.risk_free_rate_adjustment_enabled:
        return False
    if valuation.net_cash_raises_primary_price_ceiling:
        return False
    if any(name not in valuation.tiers for name in _TIER_NAMES):
        return False

    configs = [valuation.tiers[name] for name in _TIER_NAMES]
    return all(
        earlier.cdc_yield <= later.cdc_yield
        and earlier.recurring_shareholder_cash_yield <= later.recurring_shareholder_cash_yield
        for earlier, later in zip(configs, configs[1:])
    )


def _require_tier_configs(profile: RuleProfile) -> None:
    """Fail explicitly when a hand-built profile cannot produce four tiers."""

    missing = [name for name in _TIER_NAMES if name not in profile.valuation.tiers]
    if missing:
        raise ValuationCalculationError(
            "valuation profile is missing tier configuration: " + ", ".join(missing)
        )


def build_valuation_input_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    *,
    cdc_result: CDCResult | None = None,
    through_return_result: object | None = None,
    net_cash_result: object | None = None,
    non_price_gates_passed: bool | None = None,
    cyclical: bool = False,
) -> ValuationInput:
    """Join normalized facts with already-calculated upstream stage outputs."""

    book = FactBook(normalized_input.facts)
    as_of = f"AS_OF_{normalized_input.as_of.isoformat()}"
    listing_market_cap = numeric_value(
        book.get("listing_equivalent_market_cap", as_of),
        field="listing_equivalent_market_cap",
    )
    if listing_market_cap is None:
        listing_market_cap = numeric_value(
            book.get("current_market_cap", as_of), field="current_market_cap"
        )
    current_price = numeric_value(book.get("current_price", as_of), field="current_price")
    aggregate_market_cap = numeric_value(
        book.get("actual_aggregate_company_market_cap", as_of),
        field="actual_aggregate_company_market_cap",
    )
    shares = numeric_value(
        book.get("normalized_diluted_economic_shares", as_of),
        field="normalized_diluted_economic_shares",
    )

    through_confidence = getattr(through_return_result, "confidence", None)
    cash_confidence = getattr(net_cash_result, "confidence", None)
    levels = [normalized_input.data_quality.confidence]
    if isinstance(through_confidence, ConfidenceLevel):
        levels.append(through_confidence)
    if isinstance(cash_confidence, ConfidenceLevel):
        levels.append(cash_confidence)

    return ValuationInput(
        as_of=normalized_input.as_of,
        valuation_currency=normalized_input.company.reporting_currency,
        listing=normalized_input.company.primary_listing,
        current_price=current_price,
        listing_equivalent_market_cap=listing_market_cap,
        actual_aggregate_company_market_cap=aggregate_market_cap,
        normalized_diluted_economic_shares=shares,
        normalized_parent_core_cdc=(
            None if cdc_result is None else cdc_result.normalized_parent_core_cdc
        ),
        distributable_base=getattr(through_return_result, "distributable_base", None),
        conservative_payout_ratio=getattr(through_return_result, "conservative_payout_ratio", None),
        verified_recurring_buyback_cash=getattr(
            through_return_result, "verified_recurring_buyback_cash", 0
        ),
        buyback_credit_eligible=getattr(through_return_result, "buyback_credit_eligible", None),
        buyback_credit_confidence=through_confidence,
        buyback_history_years=getattr(through_return_result, "buyback_history_years", None),
        buyback_recurring=None,
        net_diluted_share_reduction_verified=None,
        owner_realizable_net_cash=getattr(net_cash_result, "owner_realizable_net_cash", None),
        valuation_net_cash=getattr(net_cash_result, "valuation_net_cash", None),
        non_price_gates_passed=non_price_gates_passed,
        cyclical=cyclical,
        full_cycle_normalization_available=(
            cdc_result is None
            or not any(flag.endswith("NORMALIZATION_UNAVAILABLE") for flag in cdc_result.flags)
        ),
        confidence=_worst_confidence(levels),
    )


def _verified_buyback_cash(
    inputs: ValuationInput, profile: RuleProfile, flags: list[str]
) -> Decimal:
    amount = _decimal(inputs.verified_recurring_buyback_cash)
    if amount == 0:
        return Decimal("0")
    config = profile.valuation.buyback_cash_credit
    if not config.enabled:
        flags.append("BUYBACK_CREDIT_DISABLED")
        return Decimal("0")
    if inputs.buyback_credit_eligible is not True:
        flags.append("BUYBACK_CREDIT_NOT_VERIFIED")
        return Decimal("0")
    if config.require_high_confidence and (
        inputs.buyback_credit_confidence is not ConfidenceLevel.HIGH
    ):
        flags.append("BUYBACK_CREDIT_LOW_CONFIDENCE")
        return Decimal("0")
    if (
        inputs.buyback_history_years is None
        or inputs.buyback_history_years < config.min_history_years
    ):
        flags.append("BUYBACK_CREDIT_HISTORY_INCOMPLETE")
        return Decimal("0")
    if inputs.buyback_recurring is False:
        flags.append("BUYBACK_CREDIT_NOT_RECURRING")
        return Decimal("0")
    if (
        config.require_net_diluted_share_reduction
        and inputs.net_diluted_share_reduction_verified is False
    ):
        flags.append("BUYBACK_CREDIT_REJECTED_DILUTION")
        return Decimal("0")
    return amount


def _tier_result(
    name: str,
    profile: RuleProfile,
    normalized_cdc: Decimal | None,
    recurring_cash: Decimal | None,
    shares: Decimal | None,
    owner_cash: Decimal | None,
    valuation_cash: Decimal | None,
) -> dict[str, object]:
    config = profile.valuation.tiers[name]
    cap: Decimal | None = None
    if normalized_cdc is not None and recurring_cash is not None:
        if normalized_cdc > 0 and recurring_cash > 0:
            cdc_cap = normalized_cdc / _decimal(config.cdc_yield)
            return_cap = recurring_cash / _decimal(config.recurring_shareholder_cash_yield)
            cap = min(cdc_cap, return_cap)
    price = None if cap is None or shares is None else cap / shares
    return {
        "cdc_hurdle": config.cdc_yield,
        "return_hurdle": config.recurring_shareholder_cash_yield,
        "market_cap": _float(cap),
        "price": _float(price),
        "owner_net_cash_ratio": (
            None if cap is None or owner_cash is None else _float(owner_cash / cap)
        ),
        "valuation_net_cash_ratio": (
            None if cap is None or valuation_cash is None else _float(valuation_cash / cap)
        ),
    }


def _classify_market_cap(current_market_cap: Decimal, tiers: ValuationTiers) -> ValuationState:
    if tiers.extreme_safety.market_cap is not None and current_market_cap <= _decimal(
        tiers.extreme_safety.market_cap
    ):
        return ValuationState.EXTREME_SAFETY
    if tiers.turtle_entry.market_cap is not None and current_market_cap <= _decimal(
        tiers.turtle_entry.market_cap
    ):
        return ValuationState.TURTLE_ENTRY
    if tiers.acceptable.market_cap is not None and current_market_cap <= _decimal(
        tiers.acceptable.market_cap
    ):
        return ValuationState.ACCEPTABLE
    if tiers.observation.market_cap is not None and current_market_cap <= _decimal(
        tiers.observation.market_cap
    ):
        return ValuationState.WATCH
    return ValuationState.TOO_EXPENSIVE_FOR_STRICT_MODEL


def calculate_valuation(inputs: ValuationInput, profile: RuleProfile) -> ValuationResult:
    """Calculate strict-v1 whole-company return caps and cash diagnostics."""

    _require_tier_configs(profile)
    flags: list[str] = []
    supported_profile = _profile_is_supported(profile)
    if not supported_profile:
        flags.append("VALUATION_PROFILE_INVALID")

    normalized_cdc = (
        None
        if inputs.normalized_parent_core_cdc is None
        else _decimal(inputs.normalized_parent_core_cdc)
    )
    distributable_base = (
        None if inputs.distributable_base is None else _decimal(inputs.distributable_base)
    )
    payout_ratio = (
        None
        if inputs.conservative_payout_ratio is None
        else _decimal(inputs.conservative_payout_ratio)
    )

    recurring_dividend_cash = (
        None
        if distributable_base is None or payout_ratio is None
        else distributable_base * payout_ratio
    )
    if inputs.recurring_dividend_cash is not None and recurring_dividend_cash is not None:
        if _decimal(inputs.recurring_dividend_cash) != recurring_dividend_cash:
            flags.append("DIVIDEND_CASH_INCONSISTENT")
    elif recurring_dividend_cash is None:
        flags.append("RECURRING_DIVIDEND_CASH_UNAVAILABLE")

    verified_buyback_cash = _verified_buyback_cash(inputs, profile, flags)
    recurring_shareholder_cash = (
        None
        if normalized_cdc is None or distributable_base is None or recurring_dividend_cash is None
        else min(
            normalized_cdc,
            distributable_base,
            recurring_dividend_cash + verified_buyback_cash,
        )
    )
    if recurring_shareholder_cash is None:
        flags.append("RECURRING_SHAREHOLDER_CASH_UNAVAILABLE")
    elif recurring_dividend_cash is not None and (
        recurring_shareholder_cash < recurring_dividend_cash + verified_buyback_cash
    ):
        flags.append("RECURRING_SHAREHOLDER_CASH_CAPPED")

    non_positive_operating_base = (
        normalized_cdc is not None
        and normalized_cdc <= 0
        or distributable_base is not None
        and distributable_base <= 0
        or recurring_shareholder_cash is not None
        and recurring_shareholder_cash <= 0
    )
    if non_positive_operating_base:
        flags.append("NON_POSITIVE_OPERATING_BASE")

    owner_cash = (
        None
        if inputs.owner_realizable_net_cash is None
        else _decimal(inputs.owner_realizable_net_cash)
    )
    valuation_cash = (
        None if inputs.valuation_net_cash is None else _decimal(inputs.valuation_net_cash)
    )
    if (
        valuation_cash is None
        and owner_cash is not None
        and inputs.cash_governance_factor is not None
    ):
        valuation_cash = owner_cash * _decimal(inputs.cash_governance_factor)
    if valuation_cash is None:
        flags.append("VALUATION_NET_CASH_UNAVAILABLE")

    adjusted_ev = None
    if inputs.listing_equivalent_market_cap is not None and valuation_cash is not None:
        adjusted_ev = _decimal(inputs.listing_equivalent_market_cap) - valuation_cash
    else:
        flags.append("ADJUSTED_EV_UNAVAILABLE")

    ex_cash_cdc_yield = None
    if adjusted_ev is not None:
        if adjusted_ev <= 0:
            flags.append("NET_NET_SPECIAL_CASE")
        elif normalized_cdc is not None:
            ex_cash_cdc_yield = normalized_cdc / adjusted_ev
        else:
            flags.append("EX_CASH_CDC_YIELD_UNAVAILABLE")
    elif normalized_cdc is not None:
        flags.append("EX_CASH_CDC_YIELD_UNAVAILABLE")

    asset_supported_market_cap = None
    if valuation_cash is not None and normalized_cdc is not None and normalized_cdc > 0:
        operating_hurdle = _decimal(profile.valuation.tiers["turtle_entry"].cdc_yield)
        asset_supported_market_cap = valuation_cash + normalized_cdc / operating_hurdle
    else:
        flags.append("ASSET_SUPPORTED_MARKET_CAP_UNAVAILABLE")

    tier_values = {
        name: _tier_result(
            name,
            profile,
            normalized_cdc,
            recurring_shareholder_cash,
            (
                None
                if inputs.normalized_diluted_economic_shares is None
                else _decimal(inputs.normalized_diluted_economic_shares)
            ),
            owner_cash,
            valuation_cash,
        )
        for name in _TIER_NAMES
    }
    tiers = ValuationTiers(**tier_values)

    caps = [getattr(tiers, name).market_cap for name in _TIER_NAMES]
    if supported_profile and all(cap is not None for cap in caps):
        if any(previous < current for previous, current in zip(caps, caps[1:])):
            flags.append("VALUATION_PROFILE_INVALID")

    critical_missing = (
        normalized_cdc is None
        or distributable_base is None
        or payout_ratio is None
        or inputs.normalized_diluted_economic_shares is None
        or recurring_shareholder_cash is None
    )
    if critical_missing:
        flags.append("VALUATION_CRITICAL_INPUT_MISSING")
    if inputs.cyclical and not inputs.full_cycle_normalization_available:
        flags.append("CYCLICAL_VALUATION_UNAVAILABLE")
    if inputs.non_price_gates_passed is False:
        flags.append("NON_PRICE_GATES_NOT_PASSED")
    elif inputs.non_price_gates_passed is None:
        flags.append("NON_PRICE_GATES_UNRESOLVED")
    if inputs.confidence is ConfidenceLevel.LOW:
        flags.append("MANUAL_REVIEW_REQUIRED")

    if (
        supported_profile
        and not critical_missing
        and inputs.listing_equivalent_market_cap is not None
        and all(cap is not None for cap in caps)
        and not (inputs.cyclical and not inputs.full_cycle_normalization_available)
        and inputs.non_price_gates_passed is True
        and adjusted_ev is not None
        and adjusted_ev > 0
        and inputs.confidence is not ConfidenceLevel.LOW
    ):
        current_state = _classify_market_cap(_decimal(inputs.listing_equivalent_market_cap), tiers)
    elif (
        critical_missing
        or non_positive_operating_base
        or adjusted_ev is not None
        and adjusted_ev <= 0
    ):
        current_state = ValuationState.NO_NORMAL_VALUATION
    elif inputs.non_price_gates_passed is False:
        current_state = ValuationState.SPECIAL_REVIEW
    else:
        current_state = ValuationState.SPECIAL_REVIEW

    current_market_cap = (
        None
        if inputs.listing_equivalent_market_cap is None
        else _decimal(inputs.listing_equivalent_market_cap)
    )

    def _mos(tier_name: str) -> float | None:
        cap = getattr(tiers, tier_name).market_cap
        if current_market_cap is None or cap is None or cap == 0:
            return None
        return _float(Decimal("1") - current_market_cap / _decimal(cap))

    confidence = inputs.confidence
    if critical_missing or not supported_profile:
        confidence = ConfidenceLevel.LOW

    return ValuationResult(
        as_of=inputs.as_of,
        valuation_currency=inputs.valuation_currency,
        listing=inputs.listing,
        current_price=inputs.current_price,
        listing_equivalent_market_cap=inputs.listing_equivalent_market_cap,
        actual_aggregate_company_market_cap=inputs.actual_aggregate_company_market_cap,
        normalized_diluted_economic_shares=inputs.normalized_diluted_economic_shares,
        normalized_parent_core_cdc=_float(normalized_cdc),
        distributable_base=_float(distributable_base),
        recurring_dividend_cash=_float(recurring_dividend_cash),
        verified_recurring_buyback_cash=_float(verified_buyback_cash) or 0,
        recurring_shareholder_cash=_float(recurring_shareholder_cash),
        owner_realizable_net_cash=_float(owner_cash),
        valuation_net_cash=_float(valuation_cash),
        adjusted_ev=_float(adjusted_ev),
        ex_cash_cdc_yield=_float(ex_cash_cdc_yield),
        asset_supported_market_cap=_float(asset_supported_market_cap),
        tiers=tiers,
        current_valuation_state=current_state,
        mos_acceptable=_mos("acceptable"),
        mos_turtle=_mos("turtle_entry"),
        mos_extreme=_mos("extreme_safety"),
        flags=_unique(flags),
        confidence=confidence,
    )
