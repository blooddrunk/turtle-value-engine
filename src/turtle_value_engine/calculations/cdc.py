"""Pure deterministic calculations for Core CDC and All-in CDC.

The module intentionally accepts an already normalized ``CDCYearInput``.  It
does not fetch data, infer accounting facts, or apply LLM-proposed
adjustments.  Missing inputs remain missing and prevent the affected metric
from being reported as if the value were zero.
"""

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal

from turtle_value_engine.config import RuleProfile
from turtle_value_engine.models import (
    CDCInput,
    CDCResult,
    CDCYearInput,
    CDCYearResult,
    ConfidenceLevel,
    Fact,
    NormalizedCompanyInput,
)


class CDCCalculationError(ValueError):
    """Raised for an invalid economic classification that cannot be calculated safely."""


_CORE_REQUIRED_FIELDS = (
    "reported_cfo",
    "cash_interest_paid_total",
    "cash_interest_in_cfo",
    "non_recurring_operating_inflows",
    "operating_outflows_misclassified_outside_cfo",
    "ppe_purchase_cash",
    "intangible_purchase_cash",
    "other_operating_long_term_asset_cash",
    "capex_payables_change",
    "lease_principal_outside_cfo",
)

_CDC_FACT_FIELDS = frozenset(CDCYearInput.model_fields) - {"period", "confidence"}
_BOOLEAN_CDC_FACT_FIELDS = frozenset({"capitalized_dev_already_in_capex"})


def _decimal(value: float) -> Decimal:
    """Convert a model number without introducing binary-float arithmetic."""

    return Decimal(str(value))


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _unique(items: Iterable[str]) -> list[str]:
    """Return flags in first-seen order, without duplicate explanations."""

    return list(dict.fromkeys(items))


def _period_sort_key(period: str) -> tuple[int, int | str, str]:
    """Sort common fiscal-period labels chronologically when a year is present."""

    match = re.search(r"(?:19|20)\d{2}", period)
    if match:
        return (0, int(match.group()), period)
    return (1, period, period)


def _worst_confidence(levels: Iterable[ConfidenceLevel]) -> ConfidenceLevel:
    """Return the weakest confidence in a sequence."""

    ordered = {
        ConfidenceLevel.HIGH: 0,
        ConfidenceLevel.MEDIUM: 1,
        ConfidenceLevel.LOW: 2,
    }
    level_list = list(levels)
    if not level_list:
        return ConfidenceLevel.LOW
    return max(level_list, key=ordered.__getitem__)


def _missing_fields(year: CDCYearInput) -> list[str]:
    return [field for field in _CORE_REQUIRED_FIELDS if getattr(year, field) is None]


def _interest_outside_cfo(
    year: CDCYearInput, flags: list[str], profile: RuleProfile
) -> Decimal | None:
    """Resolve interest paid outside CFO exactly once.

    The total and the amount already included in CFO are the authoritative
    inputs.  An optional explicit outside-CFO amount is accepted only as a
    consistency check, which prevents a caller from subtracting interest a
    second time.
    """

    total = year.cash_interest_paid_total
    included = year.cash_interest_in_cfo
    explicit = year.cash_interest_outside_cfo
    if total is None or included is None:
        if total is not None and year.reported_cfo is not None:
            threshold = _decimal(profile.cdc.interest_classification_materiality_vs_reported_cfo)
            cfo_abs = abs(_decimal(year.reported_cfo))
            total_abs = abs(_decimal(total))
            material = total_abs != 0 if cfo_abs == 0 else total_abs >= threshold * cfo_abs
            flags.append(
                "INTEREST_CLASSIFICATION_MATERIALITY_UNRESOLVED"
                if material
                else "INTEREST_CLASSIFICATION_INCOMPLETE"
            )
        else:
            flags.append("INTEREST_CLASSIFICATION_INCOMPLETE")
        return None

    outside = _decimal(total) - _decimal(included)
    if outside < 0:
        flags.append("INTEREST_CLASSIFICATION_INCONSISTENT")
        return None
    if explicit is not None and _decimal(explicit) != outside:
        flags.append("INTEREST_CLASSIFICATION_INCONSISTENT")
        return None
    return outside


def _economic_gross_capex(year: CDCYearInput, flags: list[str]) -> Decimal | None:
    """Calculate gross operating capex, including signed capex payables change."""

    capex_fields = (
        "ppe_purchase_cash",
        "intangible_purchase_cash",
        "other_operating_long_term_asset_cash",
        "capex_payables_change",
    )
    if any(getattr(year, field) is None for field in capex_fields):
        flags.append("CAPEX_INPUT_INCOMPLETE")
        return None

    development_outside = year.capitalized_development_cash_outside_capex
    if year.capitalized_dev_already_in_capex is True:
        # The input model rejects a non-zero outside amount in this state.  A
        # zero/absent value is deliberately not added a second time.
        if development_outside in (None, 0):
            flags.append("CAPITALIZED_DEVELOPMENT_ALREADY_INCLUDED")
        development_outside = None
    elif development_outside is not None:
        # CDCYearInput requires an explicit False when this amount is supplied.
        # Keeping this branch explicit makes the no-double-counting invariant
        # visible at the arithmetic boundary.
        flags.append("CAPITALIZED_DEVELOPMENT_ADDED_OUTSIDE_CAPEX")

    total = sum(
        (_decimal(getattr(year, field)) for field in capex_fields),
        Decimal("0"),
    )
    if development_outside is not None:
        total += _decimal(development_outside)
    return total


def _parent_economic_share(year: CDCYearInput, flags: list[str]) -> Decimal | None:
    """Use explicit ownership attribution or clamp the documented proxy ratio."""

    if year.parent_economic_share is not None:
        return _decimal(year.parent_economic_share)

    if year.parent_net_profit is None or year.consolidated_net_profit is None:
        flags.append("PARENT_ATTRIBUTION_UNAVAILABLE")
        return None

    consolidated = _decimal(year.consolidated_net_profit)
    if consolidated == 0:
        flags.append("PARENT_ATTRIBUTION_UNAVAILABLE")
        return None

    raw_share = _decimal(year.parent_net_profit) / consolidated
    clamped_share = min(Decimal("1"), max(Decimal("0"), raw_share))
    if clamped_share != raw_share:
        flags.append("PARENT_ECONOMIC_SHARE_CLAMPED")
    return clamped_share


def _capex_payables_warning(
    year: CDCYearInput, core_cdc: Decimal | None, flags: list[str], profile: RuleProfile
) -> None:
    """Flag a capex-payables adjustment material to the calculated CDC."""

    change = year.capex_payables_change
    if change is None or core_cdc is None:
        return

    threshold = _decimal(profile.cdc.capex_payables_materiality_vs_core_cdc)
    change_abs = abs(_decimal(change))
    core_abs = abs(core_cdc)
    material = change_abs != 0 if core_abs == 0 else change_abs > threshold * core_abs
    if material:
        flags.append("CAPEX_PAYABLES_MATERIAL_ADJUSTMENT")


def _working_capital_warning(year: CDCYearInput, flags: list[str], profile: RuleProfile) -> None:
    """Flag a working-capital release large enough to distort reported CFO."""

    contribution = year.working_capital_contribution
    cfo = year.reported_cfo
    if contribution is None or cfo is None:
        return

    threshold = _decimal(profile.cdc.working_capital_distortion_threshold)
    contribution_abs = abs(_decimal(contribution))
    cfo_abs = abs(_decimal(cfo))
    distorted = contribution_abs != 0 if cfo_abs == 0 else contribution_abs > threshold * cfo_abs
    if distorted:
        flags.append("WORKING_CAPITAL_DISTORTION")


def build_cdc_input_from_facts(
    facts: Sequence[Fact],
    *,
    current_market_cap: float | None = None,
    cyclical: bool = False,
    default_confidence: ConfidenceLevel | None = None,
) -> CDCInput:
    """Build typed CDC input from the repository's flat Fact layer.

    Only fields understood by the CDC contract are consumed.  A duplicate
    ``field``/``period`` pair is rejected instead of silently choosing one
    source.  A missing CDC fact is left as ``None`` on the corresponding year,
    so the calculation stage can surface the missing-data flag.
    """

    facts_by_key: dict[tuple[str, str], Fact] = {}
    periods: set[str] = set()
    for fact in facts:
        if fact.field == "current_market_cap":
            continue
        if fact.field not in _CDC_FACT_FIELDS:
            continue
        key = (fact.field, fact.period)
        if key in facts_by_key:
            raise CDCCalculationError(
                f"duplicate normalized fact for field={fact.field!r}, period={fact.period!r}"
            )
        facts_by_key[key] = fact
        periods.add(fact.period)

    if not periods:
        raise CDCCalculationError("no CDC facts found in normalized input")

    years: list[CDCYearInput] = []
    for period in sorted(periods, key=_period_sort_key):
        values: dict[str, object] = {
            "period": period,
            "confidence": default_confidence,
        }
        for field in _CDC_FACT_FIELDS:
            fact = facts_by_key.get((field, period))
            if fact is None:
                continue
            value = fact.value
            if field in _BOOLEAN_CDC_FACT_FIELDS:
                if value is not None and not isinstance(value, bool):
                    raise CDCCalculationError(
                        f"CDC fact {field!r} in {period!r} must be boolean or null"
                    )
                values[field] = value
            else:
                if value is not None and isinstance(value, (bool, str)):
                    raise CDCCalculationError(
                        f"CDC fact {field!r} in {period!r} must be numeric or null"
                    )
                values[field] = None if value is None else float(value)
        years.append(CDCYearInput(**values))

    if current_market_cap is None:
        market_cap_facts = [fact for fact in facts if fact.field == "current_market_cap"]
        if len(market_cap_facts) > 1:
            raise CDCCalculationError(
                "current_market_cap must be supplied once, not repeated across facts"
            )
        if market_cap_facts:
            value = market_cap_facts[0].value
            if value is None or isinstance(value, (bool, str)):
                raise CDCCalculationError("current_market_cap fact must be numeric")
            current_market_cap = float(value)

    return CDCInput(
        years=years,
        current_market_cap=current_market_cap,
        cyclical=cyclical,
    )


def build_cdc_input_from_normalized_input(
    normalized_input: NormalizedCompanyInput,
    *,
    current_market_cap: float | None = None,
    cyclical: bool = False,
) -> CDCInput:
    """Project a normalized CompanyAnalysis input into the CDC fact contract."""

    return build_cdc_input_from_facts(
        normalized_input.facts,
        current_market_cap=current_market_cap,
        cyclical=cyclical,
        default_confidence=normalized_input.data_quality.confidence,
    )


def calculate_year_cdc(year: CDCYearInput, profile: RuleProfile) -> CDCYearResult:
    """Calculate one year's adjusted CFO, Core CDC and All-in CDC.

    Formulae implemented from ``docs/spec/01-cdc.md``:

    ``AdjustedCFO = ReportedCFO - InterestOutsideCFO - NonRecurringInflows
    + OperatingOutflowsMisclassifiedOutsideCFO``

    ``CoreCDC = AdjustedCFO - EconomicGrossCapEx - LeasePrincipalOutsideCFO``

    ``AllInCDC = CoreCDC - AcquisitionCash - StrategicInvestmentCash``
    """

    flags: list[str] = []
    missing = _missing_fields(year)
    if missing:
        flags.extend(f"MISSING_CDC_FIELD:{field}" for field in missing)

    interest_outside = _interest_outside_cfo(year, flags, profile)
    economic_capex = _economic_gross_capex(year, flags)
    share = _parent_economic_share(year, flags)
    _working_capital_warning(year, flags, profile)

    adjusted_cfo: Decimal | None = None
    if (
        year.reported_cfo is not None
        and interest_outside is not None
        and year.non_recurring_operating_inflows is not None
        and year.operating_outflows_misclassified_outside_cfo is not None
    ):
        adjusted_cfo = (
            _decimal(year.reported_cfo)
            - interest_outside
            - _decimal(year.non_recurring_operating_inflows)
            + _decimal(year.operating_outflows_misclassified_outside_cfo)
        )

    core_cdc: Decimal | None = None
    if (
        adjusted_cfo is not None
        and economic_capex is not None
        and year.lease_principal_outside_cfo is not None
    ):
        core_cdc = adjusted_cfo - economic_capex - _decimal(year.lease_principal_outside_cfo)

    _capex_payables_warning(year, core_cdc, flags, profile)
    parent_core_cdc = None if core_cdc is None or share is None else core_cdc * share

    all_in_cdc: Decimal | None = None
    if (
        core_cdc is not None
        and year.acquisition_cash is not None
        and year.strategic_investment_cash is not None
    ):
        all_in_cdc = (
            core_cdc - _decimal(year.acquisition_cash) - _decimal(year.strategic_investment_cash)
        )
    elif core_cdc is not None:
        flags.append("ALL_IN_CDC_INPUT_INCOMPLETE")

    confidence = year.confidence or ConfidenceLevel.LOW
    if missing or "INTEREST_CLASSIFICATION_INCOMPLETE" in flags or core_cdc is None:
        confidence = ConfidenceLevel.LOW
    elif share is None or parent_core_cdc is None:
        confidence = ConfidenceLevel.LOW

    return CDCYearResult(
        period=year.period,
        reported_cfo=year.reported_cfo,
        interest_outside_cfo=_float(interest_outside),
        adjusted_cfo=_float(adjusted_cfo),
        economic_gross_capex=_float(economic_capex),
        lease_principal_outside_cfo=year.lease_principal_outside_cfo,
        core_cdc=_float(core_cdc),
        parent_economic_share=_float(share),
        parent_core_cdc=_float(parent_core_cdc),
        all_in_cdc=_float(all_in_cdc),
        working_capital_contribution=year.working_capital_contribution,
        flags=_unique(flags),
        confidence=confidence,
    )


def _standard_normalized(values: list[float]) -> float | None:
    """Apply ``min(3Y average, 5Y median)`` to five or more observations."""

    if len(values) < 5:
        return None
    last_five = [_decimal(value) for value in values[-5:]]
    last_three = last_five[-3:]
    average_three = sum(last_three, Decimal("0")) / Decimal(len(last_three))
    ordered_five = sorted(last_five)
    median_five = ordered_five[len(ordered_five) // 2]
    return _float(min(average_three, median_five))


def _full_cycle_normalized(values: list[float], minimum_years: int) -> float | None:
    """Use the median across the supplied full-cycle observations."""

    if len(values) < minimum_years:
        return None
    ordered = sorted(_decimal(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        result = ordered[middle]
    else:
        result = (ordered[middle - 1] + ordered[middle]) / Decimal("2")
    return _float(result)


def _normalize(values: list[float], profile: RuleProfile, cyclical: bool) -> float | None:
    if cyclical:
        if profile.cdc.normalization.cyclical_method != "full_cycle_median":
            raise CDCCalculationError(
                "unsupported cyclical CDC normalization method: "
                f"{profile.cdc.normalization.cyclical_method}"
            )
        return _full_cycle_normalized(values, profile.cdc.normalization.cyclical_min_years)
    if profile.cdc.normalization.standard_method != "min_3y_average_5y_median":
        raise CDCCalculationError(
            "unsupported standard CDC normalization method: "
            f"{profile.cdc.normalization.standard_method}"
        )
    return _standard_normalized(values)


def calculate_cdc(inputs: CDCInput, profile: RuleProfile) -> CDCResult:
    """Calculate the multi-year CDC series and configured normalization."""

    year_results = [calculate_year_cdc(year, profile) for year in inputs.years]
    flags = [flag for result in year_results for flag in result.flags]
    continuity = profile.cdc.continuity
    lookback_years = continuity.lookback_years
    lookback_results = year_results[-lookback_years:]

    if len(lookback_results) < lookback_years:
        flags.append("INSUFFICIENT_CDC_HISTORY")

    core_values = [result.core_cdc for result in lookback_results]
    all_in_values = [result.all_in_cdc for result in lookback_results]

    positive_years = None
    cumulative_core = None
    if all(value is not None for value in core_values):
        numeric_core = [value for value in core_values if value is not None]
        positive_years = sum(value > 0 for value in numeric_core)
        cumulative_core = sum(numeric_core)
    else:
        flags.append("CORE_CDC_HISTORY_INCOMPLETE")

    normalization_results = year_results if inputs.cyclical else lookback_results
    normalization_core_values = [result.core_cdc for result in normalization_results]
    normalization_parent_values = [result.parent_core_cdc for result in normalization_results]

    normalized_core = None
    if all(value is not None for value in normalization_core_values):
        normalized_core = _normalize(
            [value for value in normalization_core_values if value is not None],
            profile,
            inputs.cyclical,
        )
    if normalized_core is None:
        flags.append("NORMALIZED_CORE_CDC_UNAVAILABLE")
        if (
            inputs.cyclical
            and len(normalization_core_values) < profile.cdc.normalization.cyclical_min_years
        ):
            flags.append("CYCLICAL_NORMALIZATION_UNAVAILABLE")

    normalized_parent = None
    if all(value is not None for value in normalization_parent_values):
        normalized_parent = _normalize(
            [value for value in normalization_parent_values if value is not None],
            profile,
            inputs.cyclical,
        )
    if normalized_parent is None:
        flags.append("NORMALIZED_PARENT_CORE_CDC_UNAVAILABLE")
        if (
            inputs.cyclical
            and len(normalization_parent_values) < profile.cdc.normalization.cyclical_min_years
        ):
            flags.append("CYCLICAL_PARENT_NORMALIZATION_UNAVAILABLE")

    all_in_cdc_5y = None
    if len(all_in_values) == lookback_years and all(value is not None for value in all_in_values):
        all_in_cdc_5y = sum(value for value in all_in_values if value is not None)
        acquisition_values = [year.acquisition_cash for year in inputs.years[-lookback_years:]]
        if all(value is not None for value in acquisition_values):
            total_acquisition_cash = sum(value or 0 for value in acquisition_values)
            if total_acquisition_cash > (cumulative_core or 0):
                flags.append("CAPITAL_ALLOCATION_WARNING")
    else:
        flags.append("ALL_IN_CDC_HISTORY_INCOMPLETE")

    cdc_yield = None
    if normalized_parent is not None and inputs.current_market_cap is not None:
        cdc_yield = normalized_parent / inputs.current_market_cap
    elif inputs.current_market_cap is not None:
        flags.append("CDC_YIELD_UNAVAILABLE")

    latest = year_results[-1]
    flags = _unique(flags)
    confidence = _worst_confidence(result.confidence for result in year_results)
    if normalized_parent is None or len(lookback_results) < lookback_years:
        confidence = ConfidenceLevel.LOW

    return CDCResult(
        reported_cfo=latest.reported_cfo,
        adjusted_cfo=latest.adjusted_cfo,
        economic_gross_capex=latest.economic_gross_capex,
        lease_principal_outside_cfo=latest.lease_principal_outside_cfo,
        core_cdc=latest.core_cdc,
        parent_core_cdc=latest.parent_core_cdc,
        normalized_core_cdc=normalized_core,
        normalized_parent_core_cdc=normalized_parent,
        cdc_yield=cdc_yield,
        all_in_cdc=latest.all_in_cdc,
        positive_years_5y=positive_years,
        cumulative_core_cdc_5y=cumulative_core,
        all_in_cdc_5y=all_in_cdc_5y,
        year_results=year_results,
        flags=flags,
        confidence=confidence,
    )
