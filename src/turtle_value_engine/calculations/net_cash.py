"""Pure deterministic net-cash and balance-sheet safety calculations."""

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
from turtle_value_engine.models.net_cash import NetCashInput, NetCashResult


class NetCashCalculationError(ValueError):
    """Raised when normalized net-cash facts cannot be projected safely."""


_CASH_FIELDS = (
    "hard_cash",
    "near_cash",
    "liquid_financial_assets",
    "strategic_investments",
)
_DEBT_FIELDS = (
    "lease_debt",
    "supplier_finance",
    "recourse_factoring",
    "debt_like_hybrids",
    "material_quasi_debt",
)
_AS_OF_NUMERIC_FIELDS = (
    "book_cash",
    "reported_interest_bearing_debt",
    "hard_cash",
    "near_cash",
    "liquid_financial_assets",
    "strategic_investments",
    "restricted_cash",
    "pledged_deposits",
    "financial_debt",
    "lease_debt",
    "supplier_finance",
    "recourse_factoring",
    "debt_like_hybrids",
    "material_quasi_debt",
    "subsidiary_cash",
    "subsidiary_debt",
    "subsidiary_ownership",
    "upstreamability_factor",
    "debt_due_within_one_year",
    "normalized_ebitda",
    "cash_interest_expense",
    "minority_profit",
    "minority_equity",
    "total_equity",
    "cash_governance_factor",
)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _profile_governance_factor(input_data: NetCashInput, profile: RuleProfile) -> float | None:
    if input_data.cash_governance_factor is not None:
        return input_data.cash_governance_factor
    factors = profile.net_cash.cash_governance_factor
    by_class = {
        "STRONG": factors.strong,
        "SOUND": factors.sound,
        "WEAK_DISTRIBUTION": factors.weak_distribution,
        "POOR_CAPITAL_ALLOCATION": factors.poor_capital_allocation,
        "SEVERE_GOVERNANCE": factors.severe_governance_max,
    }
    return (
        None
        if input_data.cash_governance_class is None
        else by_class[input_data.cash_governance_class]
    )


def _weighted_cash(
    input_data: NetCashInput, profile: RuleProfile, flags: list[str]
) -> Decimal | None:
    missing = [field for field in _CASH_FIELDS if getattr(input_data, field) is None]
    if missing:
        flags.extend(f"MISSING_NET_CASH_FIELD:{field}" for field in missing)
        return None

    weights = profile.net_cash.cash_weights
    values = {
        "hard_cash": weights.hard_cash,
        "near_cash": weights.near_cash,
        "liquid_financial_assets": weights.liquid_financial_assets,
        "strategic_investments": weights.strategic_investments,
    }
    return sum(
        (
            _decimal(getattr(input_data, field)) * _decimal(weight)
            for field, weight in values.items()
        ),
        Decimal("0"),
    )


def _financial_debt(input_data: NetCashInput, flags: list[str]) -> Decimal | None:
    if input_data.financial_debt is not None:
        return _decimal(input_data.financial_debt)
    if input_data.reported_interest_bearing_debt is not None:
        flags.append("FINANCIAL_DEBT_FALLBACK_TO_REPORTED")
        return _decimal(input_data.reported_interest_bearing_debt)
    flags.append("MISSING_NET_CASH_FIELD:financial_debt")
    return None


def _debt_equivalent(
    financial_debt: Decimal | None, input_data: NetCashInput, flags: list[str]
) -> Decimal | None:
    missing = [field for field in _DEBT_FIELDS if getattr(input_data, field) is None]
    if financial_debt is None:
        return None
    if missing:
        flags.extend(f"MISSING_NET_CASH_FIELD:{field}" for field in missing)
        return None
    return financial_debt + sum(
        (_decimal(getattr(input_data, field)) for field in _DEBT_FIELDS),
        Decimal("0"),
    )


def _owner_accessible_cash(
    strict_cash: Decimal | None,
    input_data: NetCashInput,
    profile: RuleProfile,
    flags: list[str],
) -> Decimal | None:
    if strict_cash is None:
        return None

    # The C0--C3 inputs are already unrestricted/classified buckets.  The
    # separate restriction fields are still required to establish that no
    # additional cash trap was omitted from the classification.
    if input_data.restricted_cash is None:
        flags.append("RESTRICTED_CASH_UNRESOLVED")
        return None
    if input_data.pledged_deposits is None:
        flags.append("PLEDGED_DEPOSITS_UNRESOLVED")
        return None
    if input_data.cash_authenticity_verified is False:
        flags.append("CASH_AUTHENTICITY_UNVERIFIED")
        return None
    if input_data.cash_upstreamability_verified is False:
        flags.append("CASH_UPSTREAMABILITY_UNVERIFIED")
        return None
    if input_data.cash_authenticity_verified is None:
        flags.append("CASH_AUTHENTICITY_VERIFICATION_MISSING")
    if input_data.cash_upstreamability_verified is None:
        flags.append("CASH_UPSTREAMABILITY_VERIFICATION_MISSING")

    subsidiary_fields = ("subsidiary_cash", "subsidiary_debt", "subsidiary_ownership")
    subsidiary_complete = all(getattr(input_data, field) is not None for field in subsidiary_fields)
    factor = input_data.upstreamability_factor
    if subsidiary_complete:
        if factor is None:
            factor = profile.net_cash.upstreamability_factors.fully_accessible
            flags.append("SUBSIDIARY_UPSTREAMABILITY_DEFAULTED_TO_CONFIGURED_ACCESSIBLE")
        standalone_cash = strict_cash - _decimal(input_data.subsidiary_cash)
        subsidiary_cash = _decimal(input_data.subsidiary_cash)
        ownership = _decimal(input_data.subsidiary_ownership)
        return standalone_cash + subsidiary_cash * ownership * _decimal(factor)

    if factor is None:
        flags.append("UPSTREAMABILITY_UNRESOLVED")
        return None
    return strict_cash * _decimal(factor)


def _owner_debt_equivalent(
    debt_equivalent: Decimal | None,
    input_data: NetCashInput,
    flags: list[str],
) -> Decimal | None:
    """Attribute a disclosed subsidiary debt component to the owner."""

    if debt_equivalent is None:
        return None
    subsidiary_fields = ("subsidiary_cash", "subsidiary_debt", "subsidiary_ownership")
    if not all(getattr(input_data, field) is not None for field in subsidiary_fields):
        return debt_equivalent

    subsidiary_debt = _decimal(input_data.subsidiary_debt)
    if subsidiary_debt > debt_equivalent:
        flags.append("SUBSIDIARY_DEBT_EXCEEDS_CONSOLIDATED_DEBT")
        return None
    parent_debt = debt_equivalent - subsidiary_debt
    return parent_debt + subsidiary_debt * _decimal(input_data.subsidiary_ownership)


def _coverage(
    numerator: Decimal | None,
    denominator: float | None,
    flags: list[str],
    flag_prefix: str,
) -> Decimal | None:
    if numerator is None or denominator is None:
        flags.append(f"{flag_prefix}_UNAVAILABLE")
        return None
    denominator_decimal = _decimal(denominator)
    if denominator_decimal == 0:
        flags.append(f"{flag_prefix}_NOT_APPLICABLE")
        return None
    return numerator / denominator_decimal


def build_net_cash_input_from_facts(
    facts: Sequence[Fact],
    *,
    as_of_period: str | None = None,
    current_market_cap: float | None = None,
    normalized_parent_core_cdc: float | None = None,
    default_confidence: ConfidenceLevel | None = None,
) -> NetCashInput:
    """Project one AS_OF fact period into the net-cash input boundary."""

    book = FactBook(facts)
    period = as_of_period or book.as_of_period("1970-01-01")

    values: dict[str, object] = {}
    evidence: dict[str, list[str]] = {}
    for field in _AS_OF_NUMERIC_FIELDS:
        reference = book.get(field, period)
        values[field] = numeric_value(reference, field=field)
        if reference is not None:
            evidence[field] = list(reference.evidence_ids)

    for field in ("cash_authenticity_verified", "cash_upstreamability_verified"):
        reference = book.get(field, period)
        values[field] = boolean_value(reference, field=field)
        if reference is not None:
            evidence[field] = list(reference.evidence_ids)

    reference = book.get("cash_governance_class", period)
    values["cash_governance_class"] = enum_value(reference, field="cash_governance_class")
    if reference is not None:
        evidence["cash_governance_class"] = list(reference.evidence_ids)

    market_cap_reference = None
    if current_market_cap is None:
        market_cap_reference = book.get("listing_equivalent_market_cap", period)
        current_market_cap = numeric_value(
            market_cap_reference,
            field="listing_equivalent_market_cap",
        )
    if current_market_cap is None:
        market_cap_reference = book.get("current_market_cap", period)
        current_market_cap = numeric_value(
            market_cap_reference,
            field="current_market_cap",
        )
    if market_cap_reference is not None:
        evidence["current_market_cap"] = list(market_cap_reference.evidence_ids)

    confidence = default_confidence or ConfidenceLevel.HIGH
    return NetCashInput(
        **values,
        current_market_cap=current_market_cap,
        normalized_parent_core_cdc=normalized_parent_core_cdc,
        confidence=confidence,
        source_evidence_ids=evidence,
    )


def build_net_cash_input_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    *,
    normalized_parent_core_cdc: float | None = None,
    current_market_cap: float | None = None,
) -> NetCashInput:
    """Project a frozen normalized input without applying proposed adjustments."""

    return build_net_cash_input_from_facts(
        normalized_input.facts,
        as_of_period=f"AS_OF_{normalized_input.as_of.isoformat()}",
        current_market_cap=current_market_cap,
        normalized_parent_core_cdc=normalized_parent_core_cdc,
        default_confidence=normalized_input.data_quality.confidence,
    )


def calculate_net_cash(inputs: NetCashInput, profile: RuleProfile) -> NetCashResult:
    """Calculate book, strict and owner-realizable net cash plus coverage."""

    flags: list[str] = []
    strict_cash = _weighted_cash(inputs, profile, flags)
    financial_debt = _financial_debt(inputs, flags)
    debt_equivalent = _debt_equivalent(financial_debt, inputs, flags)

    book_net_cash = None
    if inputs.book_cash is not None and inputs.reported_interest_bearing_debt is not None:
        book_net_cash = _decimal(inputs.book_cash) - _decimal(inputs.reported_interest_bearing_debt)
    else:
        flags.append("BOOK_NET_CASH_UNAVAILABLE")

    financial_net_cash = (
        None if strict_cash is None or financial_debt is None else strict_cash - financial_debt
    )
    obligation_adjusted_net_cash = (
        None
        if strict_cash is None or financial_debt is None or inputs.lease_debt is None
        else strict_cash - financial_debt - _decimal(inputs.lease_debt)
    )
    if obligation_adjusted_net_cash is None and inputs.lease_debt is None:
        flags.append("OBLIGATION_ADJUSTED_NET_CASH_UNAVAILABLE")

    strict_net_cash = (
        None if strict_cash is None or debt_equivalent is None else strict_cash - debt_equivalent
    )
    owner_accessible_cash = _owner_accessible_cash(strict_cash, inputs, profile, flags)
    owner_debt_equivalent = _owner_debt_equivalent(debt_equivalent, inputs, flags)
    owner_realizable_net_cash = (
        None
        if owner_accessible_cash is None or owner_debt_equivalent is None
        else owner_accessible_cash - owner_debt_equivalent
    )

    owner_net_cash_ratio = None
    if owner_realizable_net_cash is not None and inputs.current_market_cap is not None:
        owner_net_cash_ratio = owner_realizable_net_cash / _decimal(inputs.current_market_cap)
    elif inputs.current_market_cap is None:
        flags.append("OWNER_NET_CASH_RATIO_UNAVAILABLE")

    governance_factor = _profile_governance_factor(inputs, profile)
    valuation_net_cash = (
        None
        if owner_realizable_net_cash is None or governance_factor is None
        else owner_realizable_net_cash * _decimal(governance_factor)
    )
    if valuation_net_cash is None:
        flags.append("VALUATION_NET_CASH_UNAVAILABLE")

    adjusted_ev = None
    if inputs.current_market_cap is not None and valuation_net_cash is not None:
        adjusted_ev = _decimal(inputs.current_market_cap) - valuation_net_cash
    else:
        flags.append("ADJUSTED_EV_UNAVAILABLE")

    ex_cash_cdc_yield = None
    if adjusted_ev is not None:
        if adjusted_ev <= 0:
            flags.append("NET_NET_SPECIAL_CASE")
        elif inputs.normalized_parent_core_cdc is not None:
            ex_cash_cdc_yield = _decimal(inputs.normalized_parent_core_cdc) / adjusted_ev
        else:
            flags.append("EX_CASH_CDC_YIELD_UNAVAILABLE")
    elif inputs.normalized_parent_core_cdc is not None:
        flags.append("EX_CASH_CDC_YIELD_UNAVAILABLE")

    liquidity_coverage = _coverage(
        None
        if owner_accessible_cash is None or inputs.normalized_parent_core_cdc is None
        else owner_accessible_cash + _decimal(inputs.normalized_parent_core_cdc),
        inputs.debt_due_within_one_year,
        flags,
        "LIQUIDITY_COVERAGE",
    )
    stress_numerator = (
        None
        if owner_accessible_cash is None or inputs.normalized_parent_core_cdc is None
        else owner_accessible_cash
        + _decimal(inputs.normalized_parent_core_cdc)
        * _decimal(profile.net_cash.stress.cdc_retention_factor)
    )
    stress_coverage = _coverage(
        stress_numerator,
        inputs.debt_due_within_one_year,
        flags,
        "STRESS_COVERAGE",
    )

    net_debt_to_ebitda = None
    if (
        strict_cash is not None
        and debt_equivalent is not None
        and inputs.normalized_ebitda is not None
    ):
        if inputs.normalized_ebitda > 0:
            net_debt_to_ebitda = (debt_equivalent - strict_cash) / _decimal(
                inputs.normalized_ebitda
            )
        else:
            flags.append("NET_DEBT_TO_EBITDA_UNAVAILABLE")
    else:
        flags.append("NET_DEBT_TO_EBITDA_UNAVAILABLE")

    interest_coverage = None
    if inputs.normalized_ebitda is not None and inputs.cash_interest_expense is not None:
        if inputs.cash_interest_expense == 0:
            flags.append("INTEREST_COVERAGE_NOT_APPLICABLE")
        else:
            interest_coverage = _decimal(inputs.normalized_ebitda) / _decimal(
                inputs.cash_interest_expense
            )
    else:
        flags.append("INTEREST_COVERAGE_UNAVAILABLE")

    if (
        inputs.debt_due_within_one_year is not None
        and owner_accessible_cash is not None
        and inputs.normalized_parent_core_cdc is not None
        and _decimal(inputs.debt_due_within_one_year)
        > owner_accessible_cash + _decimal(inputs.normalized_parent_core_cdc)
    ):
        flags.append("REFINANCING_DEPENDENCY")

    confidence = inputs.confidence
    critical_flags = {
        "CASH_AUTHENTICITY_VERIFICATION_MISSING",
        "CASH_UPSTREAMABILITY_VERIFICATION_MISSING",
    }
    critical_missing = (
        strict_cash is None
        or debt_equivalent is None
        or owner_realizable_net_cash is None
        or inputs.normalized_parent_core_cdc is None
        or any(flag in critical_flags for flag in flags)
    )
    if critical_missing:
        confidence = ConfidenceLevel.LOW

    return NetCashResult(
        book_cash=inputs.book_cash,
        strict_cash=_float(strict_cash),
        owner_accessible_cash=_float(owner_accessible_cash),
        financial_debt=_float(financial_debt),
        lease_debt=inputs.lease_debt,
        debt_equivalent=_float(debt_equivalent),
        book_net_cash=_float(book_net_cash),
        financial_net_cash=_float(financial_net_cash),
        obligation_adjusted_net_cash=_float(obligation_adjusted_net_cash),
        strict_net_cash=_float(strict_net_cash),
        owner_realizable_net_cash=_float(owner_realizable_net_cash),
        owner_debt_equivalent=_float(owner_debt_equivalent),
        valuation_net_cash=_float(valuation_net_cash),
        adjusted_ev=_float(adjusted_ev),
        ex_cash_cdc_yield=_float(ex_cash_cdc_yield),
        source_evidence_ids=inputs.source_evidence_ids,
        owner_net_cash_ratio=_float(owner_net_cash_ratio),
        liquidity_coverage=_float(liquidity_coverage),
        stress_coverage=_float(stress_coverage),
        net_debt_to_ebitda=_float(net_debt_to_ebitda),
        interest_coverage=_float(interest_coverage),
        flags=_unique(flags),
        confidence=confidence,
    )
