"""Pure deterministic shareholder-through-return calculations."""

from collections.abc import Iterable, Sequence
from decimal import Decimal

from turtle_value_engine.calculations.facts import (
    FactBook,
    boolean_value,
    enum_value,
    numeric_value,
)
from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import ConfidenceLevel, Fact, NormalizedCompanyInput
from turtle_value_engine.models.through_return import (
    ThroughReturnInput,
    ThroughReturnResult,
    ThroughReturnYearInput,
)


class ThroughReturnCalculationError(ValueError):
    """Raised when normalized payout or share facts are internally invalid."""


_YEAR_NUMERIC_FIELDS = (
    "parent_net_profit",
    "ordinary_dividend_cash",
    "special_dividend_cash",
    "formal_payout_floor",
    "payout_ratio",
    "fully_diluted_shares",
    "share_split_factor",
    "buyback_cash",
    "share_issuance_cash",
)
_AS_OF_NUMERIC_FIELDS = ("formal_payout_floor",)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _median(values: Sequence[float]) -> Decimal:
    ordered = sorted(_decimal(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _percentile(values: Sequence[float], fraction: Decimal) -> Decimal:
    """Calculate a linear-interpolated percentile without binary float math."""

    ordered = sorted(_decimal(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _history(
    years: Sequence[ThroughReturnYearInput], history_years: int
) -> list[ThroughReturnYearInput]:
    return sorted(years, key=lambda year: _period_key(year.period))[-history_years:]


def _period_key(period: str) -> tuple[int, int | str, str]:
    import re

    match = re.search(r"(?:19|20)\d{2}", period)
    if match:
        return (0, int(match.group()), period)
    return (1, period, period)


def build_through_return_input_from_facts(
    facts: Sequence[Fact],
    *,
    as_of_period: str | None = None,
    normalized_parent_core_cdc: float | None = None,
    current_market_cap: float | None = None,
    default_confidence: ConfidenceLevel | None = None,
) -> ThroughReturnInput:
    """Project annual payout/share facts and AS_OF policy facts."""

    book = FactBook(facts)
    as_of = as_of_period or book.as_of_period("1970-01-01")
    periods = [
        period for period in book.periods(_YEAR_NUMERIC_FIELDS) if not period.startswith("AS_OF_")
    ]
    if not periods:
        raise ThroughReturnCalculationError("no annual Through Return facts found")

    years: list[ThroughReturnYearInput] = []
    evidence: dict[str, list[str]] = {}
    for period in periods:
        values: dict[str, object] = {"period": period}
        for field in _YEAR_NUMERIC_FIELDS:
            reference = book.get(field, period)
            values[field] = numeric_value(reference, field=field)
            if reference is not None:
                evidence[f"{field}@{period}"] = list(reference.evidence_ids)
        years.append(ThroughReturnYearInput(**values))

    policy_reference = book.get("payout_policy_formal", as_of)
    formal = boolean_value(policy_reference, field="payout_policy_formal")
    if policy_reference is not None:
        evidence["payout_policy_formal"] = list(policy_reference.evidence_ids)

    confidence_reference = book.get("payout_policy_confidence", as_of)
    policy_confidence_value = enum_value(confidence_reference, field="payout_policy_confidence")
    policy_confidence = (
        None if policy_confidence_value is None else ConfidenceLevel(policy_confidence_value)
    )
    if confidence_reference is not None:
        evidence["payout_policy_confidence"] = list(confidence_reference.evidence_ids)

    floor_reference = book.get("formal_payout_floor", as_of)
    formal_floor = numeric_value(floor_reference, field="formal_payout_floor")
    if floor_reference is not None:
        evidence["formal_payout_floor"] = list(floor_reference.evidence_ids)

    market_cap_reference = None
    if current_market_cap is None:
        market_cap_reference = book.get("listing_equivalent_market_cap", as_of)
        current_market_cap = numeric_value(
            market_cap_reference,
            field="listing_equivalent_market_cap",
        )
    if current_market_cap is None:
        market_cap_reference = book.get("current_market_cap", as_of)
        current_market_cap = numeric_value(market_cap_reference, field="current_market_cap")
    if market_cap_reference is not None:
        evidence["current_market_cap"] = list(market_cap_reference.evidence_ids)

    recurring_reference = book.get("buyback_recurring", as_of)
    reduction_reference = book.get("net_diluted_share_reduction_verified", as_of)
    confidence = default_confidence or ConfidenceLevel.HIGH
    return ThroughReturnInput(
        years=years,
        normalized_parent_core_cdc=normalized_parent_core_cdc,
        current_market_cap=current_market_cap,
        payout_policy_formal=formal,
        payout_policy_confidence=policy_confidence,
        formal_payout_floor=formal_floor,
        buyback_recurring=boolean_value(recurring_reference, field="buyback_recurring"),
        net_diluted_share_reduction_verified=boolean_value(
            reduction_reference, field="net_diluted_share_reduction_verified"
        ),
        confidence=confidence,
        source_evidence_ids=evidence,
    )


def build_through_return_input_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    *,
    normalized_parent_core_cdc: float | None = None,
    current_market_cap: float | None = None,
) -> ThroughReturnInput:
    """Project a frozen normalized input without applying proposed adjustments."""

    return build_through_return_input_from_facts(
        normalized_input.facts,
        as_of_period=f"AS_OF_{normalized_input.as_of.isoformat()}",
        normalized_parent_core_cdc=normalized_parent_core_cdc,
        current_market_cap=current_market_cap,
        default_confidence=normalized_input.data_quality.confidence,
    )


def _normalized_profit(
    years: Sequence[ThroughReturnYearInput], profile: RuleProfile, flags: list[str]
) -> Decimal | None:
    history_years = profile.through_return.history_years
    if len(years) < history_years:
        flags.append("INSUFFICIENT_THROUGH_RETURN_HISTORY")
        return None
    history = _history(years, history_years)
    values = [year.parent_net_profit for year in history]
    if any(value is None for value in values):
        flags.append("NORMALIZED_PARENT_PROFIT_UNAVAILABLE")
        return None
    method = profile.through_return.profit_normalization_method
    if method != "average_3y":
        raise ThroughReturnCalculationError(f"unsupported profit normalization method: {method}")
    average_years = profile.through_return.profit_average_years
    if len(history) < average_years:
        flags.append("NORMALIZED_PARENT_PROFIT_UNAVAILABLE")
        return None
    return sum(
        (_decimal(value) for value in values[-average_years:] if value is not None),
        Decimal("0"),
    ) / Decimal(average_years)


def _payout_ratio(
    inputs: ThroughReturnInput,
    profile: RuleProfile,
    history: Sequence[ThroughReturnYearInput],
    flags: list[str],
) -> tuple[Decimal | None, Decimal | None]:
    payout_values = [year.payout_ratio for year in history]
    if any(value is None for value in payout_values):
        flags.append("PAYOUT_HISTORY_INCOMPLETE")
        return None, inputs.formal_payout_floor

    values = [value for value in payout_values if value is not None]
    floor = inputs.formal_payout_floor
    if floor is None:
        annual_floors = [year.formal_payout_floor for year in history]
        if annual_floors and annual_floors[-1] is not None:
            floor = annual_floors[-1]

    formal_high_confidence = (
        inputs.payout_policy_formal is True
        and inputs.payout_policy_confidence is ConfidenceLevel.HIGH
        and floor is not None
    )
    if formal_high_confidence:
        method = profile.through_return.payout_ratio.formal_policy_method
        if method != "min_policy_floor_5y_median":
            raise ThroughReturnCalculationError(f"unsupported formal payout method: {method}")
        return min(_decimal(floor), _median(values)), _decimal(floor)

    if (
        inputs.payout_policy_formal is True
        and inputs.payout_policy_confidence is not ConfidenceLevel.HIGH
    ):
        flags.append("PAYOUT_POLICY_NOT_HIGH_CONFIDENCE")
    method = profile.through_return.payout_ratio.no_policy_method
    if method != "p25_5y":
        raise ThroughReturnCalculationError(f"unsupported no-policy payout method: {method}")
    return _percentile(values, Decimal("0.25")), floor


def _share_reduction(
    history: Sequence[ThroughReturnYearInput], profile: RuleProfile, flags: list[str]
) -> Decimal | None:
    required_deltas = profile.through_return.normalized_buyback_years
    if len(history) < required_deltas + 1:
        flags.append("NET_SHARE_REDUCTION_HISTORY_INCOMPLETE")
        return None
    share_values: list[Decimal] = []
    for year in history[-(required_deltas + 1) :]:
        if year.fully_diluted_shares is None:
            flags.append("NET_SHARE_REDUCTION_UNAVAILABLE")
            return None
        factor = year.share_split_factor
        share_values.append(
            _decimal(year.fully_diluted_shares)
            * (Decimal("1") if factor is None else _decimal(factor))
        )

    reductions: list[float] = []
    for previous, current in zip(share_values, share_values[1:]):
        if previous <= 0:
            flags.append("NET_SHARE_REDUCTION_UNAVAILABLE")
            return None
        reductions.append(float(-(current - previous) / previous))
    return _median(reductions)


def _verified_buyback_cash(
    inputs: ThroughReturnInput,
    profile: RuleProfile,
    history: Sequence[ThroughReturnYearInput],
    distributable_base: Decimal | None,
    normalized_reduction: Decimal | None,
    flags: list[str],
) -> tuple[Decimal, bool, int | None]:
    config = profile.valuation.buyback_cash_credit
    cash_values = [year.buyback_cash for year in history]
    available = sum(value is not None for value in cash_values)
    history_years = available if available else None
    if not config.enabled:
        return Decimal("0"), False, history_years
    if inputs.buyback_recurring is not True:
        if inputs.buyback_recurring is None:
            flags.append("BUYBACK_CREDIT_ELIGIBILITY_UNRESOLVED")
        return Decimal("0"), False, history_years
    if inputs.net_diluted_share_reduction_verified is not True:
        if inputs.net_diluted_share_reduction_verified is False:
            flags.append("BUYBACK_CREDIT_REJECTED_DILUTION")
        else:
            flags.append("BUYBACK_CREDIT_SHARE_REDUCTION_VERIFICATION_MISSING")
        return Decimal("0"), False, history_years
    if config.require_high_confidence and inputs.confidence is not ConfidenceLevel.HIGH:
        flags.append("BUYBACK_CREDIT_LOW_CONFIDENCE")
        return Decimal("0"), False, history_years
    if available < config.min_history_years or any(value is None for value in cash_values):
        flags.append("BUYBACK_CREDIT_HISTORY_INCOMPLETE")
        return Decimal("0"), False, history_years
    if config.require_net_diluted_share_reduction and (
        normalized_reduction is None or normalized_reduction <= 0
    ):
        flags.append("BUYBACK_CREDIT_REJECTED_NET_DILUTION")
        return Decimal("0"), False, history_years
    if distributable_base is None or distributable_base <= 0:
        flags.append("BUYBACK_CREDIT_NOT_COVERED_BY_DISTRIBUTABLE_BASE")
        return Decimal("0"), False, history_years
    credit = _median([value for value in cash_values if value is not None])
    if credit > distributable_base:
        flags.append("BUYBACK_CREDIT_NOT_COVERED_BY_DISTRIBUTABLE_BASE")
        return Decimal("0"), False, history_years
    return credit, True, history_years


def calculate_through_return(
    inputs: ThroughReturnInput, profile: RuleProfile
) -> ThroughReturnResult:
    """Calculate distributable base, conservative payout and shareholder return."""

    flags: list[str] = []
    history_years = profile.through_return.history_years
    history = _history(inputs.years, history_years)
    if len(history) < history_years:
        flags.append("INSUFFICIENT_THROUGH_RETURN_HISTORY")

    normalized_profit = _normalized_profit(inputs.years, profile, flags)
    normalized_cdc = (
        None
        if inputs.normalized_parent_core_cdc is None
        else _decimal(inputs.normalized_parent_core_cdc)
    )
    if normalized_cdc is None:
        flags.append("NORMALIZED_PARENT_CORE_CDC_UNAVAILABLE")

    distributable_base = (
        None
        if normalized_profit is None or normalized_cdc is None
        else min(normalized_profit, normalized_cdc)
    )
    if distributable_base is None:
        flags.append("DISTRIBUTABLE_BASE_UNAVAILABLE")

    payout_ratio, payout_floor = _payout_ratio(inputs, profile, history, flags)
    if payout_ratio is None:
        flags.append("CONSERVATIVE_PAYOUT_RATIO_UNAVAILABLE")

    recurring_dividend_cash = (
        None
        if distributable_base is None or payout_ratio is None
        else distributable_base * payout_ratio
    )
    dividend_return = None
    if recurring_dividend_cash is not None and inputs.current_market_cap is not None:
        dividend_return = recurring_dividend_cash / _decimal(inputs.current_market_cap)
    elif recurring_dividend_cash is not None:
        flags.append("DIVIDEND_THROUGH_RETURN_UNAVAILABLE")

    normalized_reduction = _share_reduction(history, profile, flags)
    through_return = (
        None
        if dividend_return is None or normalized_reduction is None
        else dividend_return + normalized_reduction
    )
    if through_return is None:
        flags.append("THROUGH_RETURN_UNAVAILABLE")

    special_values = [year.special_dividend_cash for year in history]
    special_return = None
    if special_values and all(value is not None for value in special_values):
        special_return = sum(
            (_decimal(value) for value in special_values if value is not None),
            Decimal("0"),
        )
    else:
        flags.append("SPECIAL_RETURN_UNAVAILABLE")

    if distributable_base is not None:
        ordinary_dividends = [year.ordinary_dividend_cash for year in history]
        if any(
            dividend is not None
            and (
                distributable_base <= 0 and dividend > 0 or _decimal(dividend) > distributable_base
            )
            for dividend in ordinary_dividends
        ):
            flags.append("UNSUSTAINABLE_PAYOUT_WARNING")
    if any(year.payout_ratio is not None and year.payout_ratio > 1 for year in history):
        flags.append("UNSUSTAINABLE_PAYOUT_WARNING")

    buyback_cash, buyback_eligible, buyback_history = _verified_buyback_cash(
        inputs,
        profile,
        history,
        distributable_base,
        normalized_reduction,
        flags,
    )

    confidence = inputs.confidence
    if (
        normalized_profit is None
        or distributable_base is None
        or payout_ratio is None
        or dividend_return is None
        or normalized_reduction is None
        or through_return is None
    ):
        confidence = ConfidenceLevel.LOW

    return ThroughReturnResult(
        normalized_parent_profit=_float(normalized_profit),
        normalized_parent_core_cdc=_float(normalized_cdc),
        distributable_base=_float(distributable_base),
        payout_policy_floor=_float(payout_floor),
        conservative_payout_ratio=_float(payout_ratio),
        dividend_through_return=_float(dividend_return),
        normalized_net_share_reduction=_float(normalized_reduction),
        through_return=_float(through_return),
        special_return=_float(special_return),
        verified_recurring_buyback_cash=float(buyback_cash),
        buyback_credit_eligible=buyback_eligible,
        buyback_history_years=buyback_history,
        source_evidence_ids=inputs.source_evidence_ids,
        flags=_unique(flags),
        policy_confidence=inputs.payout_policy_confidence,
        confidence=confidence,
    )
