"""Materialize explicitly accepted economic adjustments into input facts.

The deterministic engine consumes a ``NormalizedCompanyInput`` snapshot.  An
adjustment proposal is not part of that snapshot's calculation semantics until
an allowed actor has accepted it and this module has performed the explicit,
fail-closed materialization step.  The source input is never modified in
place; effective facts retain the source fact id/value and the accepted
adjustment ids that produced them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TypeAlias

from pydantic import ValidationError

from turtle_value_engine.models import Adjustment, Fact, NormalizedCompanyInput
from turtle_value_engine.models.common import AdjustmentStatus, ApprovedBy
from turtle_value_engine.models.contracts import NORMALIZED_NUMERIC_FACT_FIELDS
from turtle_value_engine.providers.normalization import deterministic_id


class EffectiveInputError(ValueError):
    """Raised when an accepted adjustment cannot be applied unambiguously."""


# Calculation outputs and diagnostic projections must not be edited through
# this boundary.  The remaining canonical numeric fields are source-side
# inputs consumed by CDC, net cash, Through Return, eligibility or valuation.
_DERIVED_NUMERIC_FIELDS = frozenset(
    {
        "core_cdc",
        "normalized_core_cdc",
        "normalized_parent_core_cdc",
        "cdc_yield",
        "positive_years_5y",
        "cumulative_core_cdc_5y",
        "all_in_cdc",
        "all_in_cdc_5y",
        "strict_cash",
        "owner_accessible_cash",
        "debt_equivalent",
        "financial_net_cash",
        "obligation_adjusted_net_cash",
        "owner_debt_equivalent",
        "book_net_cash",
        "strict_net_cash",
        "owner_realizable_net_cash",
        "valuation_net_cash",
        "adjusted_ev",
        "ex_cash_cdc_yield",
        "owner_net_cash_ratio",
        "liquidity_coverage",
        "stress_coverage",
        "net_debt_to_ebitda",
        "interest_coverage",
        "normalized_parent_profit",
        "distributable_base",
        "payout_policy_floor",
        "conservative_payout_ratio",
        "dividend_through_return",
        "normalized_net_share_reduction",
        "through_return",
        "special_return",
    }
)

EFFECTIVE_ADJUSTMENT_FIELDS = frozenset(
    NORMALIZED_NUMERIC_FACT_FIELDS - _DERIVED_NUMERIC_FIELDS
)

AdjustmentInput: TypeAlias = Adjustment | Mapping[str, object]


def _as_adjustment(value: AdjustmentInput) -> Adjustment:
    if isinstance(value, Adjustment):
        return value
    if isinstance(value, Mapping):
        try:
            return Adjustment.model_validate(value)
        except (TypeError, ValueError, ValidationError) as exc:
            raise EffectiveInputError(f"invalid adjustment: {exc}") from exc
    raise TypeError("adjustments must contain Adjustment models or JSON objects")


def _same_value(left: object, right: object) -> bool:
    """Compare scalar values without coercing booleans or strings."""

    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        left_float = float(left)
        right_float = float(right)
        return math.isfinite(left_float) and math.isfinite(right_float) and left == right
    return left == right


def _merge_adjustments(
    normalized_input: NormalizedCompanyInput,
    supplied: Sequence[AdjustmentInput] | None,
) -> list[Adjustment]:
    """Merge workflow-replayed adjustments without accepting ID conflicts."""

    merged: list[Adjustment] = list(normalized_input.adjustments)
    by_id = {adjustment.id: adjustment for adjustment in merged}
    for raw_adjustment in supplied or ():
        adjustment = _as_adjustment(raw_adjustment)
        previous = by_id.get(adjustment.id)
        if previous is not None:
            if previous.model_dump(mode="json") != adjustment.model_dump(mode="json"):
                raise EffectiveInputError(
                    f"adjustment ID {adjustment.id!r} represents conflicting content"
                )
            continue
        merged.append(adjustment)
        by_id[adjustment.id] = adjustment
    return merged


def _validate_adjustment_evidence(
    normalized_input: NormalizedCompanyInput,
    adjustments: Sequence[Adjustment],
) -> None:
    """Reject workflow records that point outside this input snapshot."""

    known_evidence_ids = {evidence.id for evidence in normalized_input.evidence_index}
    for adjustment in adjustments:
        missing = sorted(set(adjustment.source_evidence_ids) - known_evidence_ids)
        if missing:
            raise EffectiveInputError(
                f"adjustment {adjustment.id!r} references undefined evidence ID(s): "
                + ", ".join(missing)
            )


def _validate_normalized_fact_keys(
    normalized_input: NormalizedCompanyInput,
) -> None:
    """Fail closed when a normalizer emits duplicate field/period facts."""

    seen: set[tuple[str, str]] = set()
    for fact in normalized_input.facts:
        key = (fact.field, fact.period)
        if key in seen:
            raise EffectiveInputError(
                f"normalized input contains duplicate fact {fact.field!r}/{fact.period!r}"
            )
        seen.add(key)


def _target_fact(
    facts: Sequence[Fact],
    adjustment: Adjustment,
) -> Fact:
    candidates = [fact for fact in facts if fact.field == adjustment.target_field]
    if adjustment.target_period is not None:
        candidates = [fact for fact in candidates if fact.period == adjustment.target_period]
        if not candidates:
            raise EffectiveInputError(
                f"adjustment {adjustment.id!r} has no target fact for "
                f"{adjustment.target_field!r}/{adjustment.target_period!r}"
            )
    elif len(candidates) > 1:
        if adjustment.input_value is None:
            raise EffectiveInputError(
                f"adjustment {adjustment.id!r} needs target_period because "
                f"{adjustment.target_field!r} has multiple periods"
            )
        matches = [
            fact for fact in candidates if _same_value(fact.value, adjustment.input_value)
        ]
        if len(matches) != 1:
            detail = "no matching source fact" if not matches else "multiple matching source facts"
            raise EffectiveInputError(
                f"adjustment {adjustment.id!r} has {detail} for stale/ambiguous "
                f"input_value on {adjustment.target_field!r}"
            )
        candidates = matches
    if not candidates:
        raise EffectiveInputError(
            f"adjustment {adjustment.id!r} has no source fact for {adjustment.target_field!r}"
        )
    fact = candidates[0]
    if adjustment.input_value is not None and not _same_value(
        fact.value, adjustment.input_value
    ):
        raise EffectiveInputError(
            f"adjustment {adjustment.id!r} is stale: input_value does not match "
            f"source fact {fact.id!r}"
        )
    return fact


def _effective_fact(
    fact: Fact,
    adjustments: Sequence[Adjustment],
) -> Fact:
    """Create one immutable effective fact with complete local lineage."""

    proposed_values = {adjustment.proposed_adjusted_value for adjustment in adjustments}
    if len(proposed_values) != 1:
        raise EffectiveInputError(
            "conflicting accepted adjustments target "
            f"{fact.field!r}/{fact.period!r}"
        )
    proposed_value = next(iter(proposed_values))
    if proposed_value is None:
        raise EffectiveInputError(
            "accepted adjustment "
            f"{adjustments[0].id!r} has no proposed_adjusted_value"
        )

    prior_ids = list(fact.applied_adjustment_ids)
    adjustment_ids = list(dict.fromkeys([*prior_ids, *(item.id for item in adjustments)]))
    source_fact_id = fact.source_fact_id or fact.id
    source_value = fact.source_value if fact.source_fact_id is not None else fact.value
    source_evidence_ids = list(
        dict.fromkeys(
            [
                *fact.source_evidence_ids,
                *(evidence_id for item in adjustments for evidence_id in item.source_evidence_ids),
            ]
        )
    )
    confidence_values = [
        fact.confidence,
        *(item.confidence for item in adjustments if item.confidence is not None),
    ]
    effective_id = deterministic_id(
        "fact-effective",
        source_fact_id,
        fact.field,
        fact.period,
        adjustment_ids,
        proposed_value,
    )
    payload = fact.model_dump(mode="python", warnings=False)
    payload.update(
        {
            "id": effective_id,
            "value": proposed_value,
            "source_evidence_ids": source_evidence_ids,
            "confidence": min(confidence_values),
            "source_fact_id": source_fact_id,
            "source_value": source_value,
            "applied_adjustment_ids": adjustment_ids,
        }
    )
    try:
        return Fact.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise EffectiveInputError(
            f"accepted adjustment produced an invalid effective fact: {exc}"
        ) from exc


def materialize_effective_input(
    normalized_input: NormalizedCompanyInput,
    accepted_adjustments: Sequence[AdjustmentInput] | None = None,
) -> NormalizedCompanyInput:
    """Return a new input with only explicitly accepted adjustments applied.

    Proposed and rejected adjustments remain in the returned audit list but
    are ignored by calculation.  Accepted adjustments must target a canonical
    numeric source fact, carry an explicit proposed value, have a current
    ``input_value`` when supplied, and be approved by HUMAN or RULE_ENGINE.
    """

    if not isinstance(normalized_input, NormalizedCompanyInput):
        raise TypeError("normalized_input must be a NormalizedCompanyInput")
    adjustments = _merge_adjustments(normalized_input, accepted_adjustments)
    _validate_adjustment_evidence(normalized_input, adjustments)
    _validate_normalized_fact_keys(normalized_input)
    accepted = [
        adjustment
        for adjustment in adjustments
        if adjustment.status is AdjustmentStatus.ACCEPTED
    ]
    if any(
        adjustment.approved_by not in {ApprovedBy.HUMAN, ApprovedBy.RULE_ENGINE}
        for adjustment in accepted
    ):
        raise EffectiveInputError("accepted adjustments require HUMAN or RULE_ENGINE approval")

    groups: dict[tuple[str, str], list[Adjustment]] = {}
    for adjustment in accepted:
        if adjustment.target_field not in EFFECTIVE_ADJUSTMENT_FIELDS:
            raise EffectiveInputError(
                f"adjustment target field {adjustment.target_field!r} is not an allowed "
                "source-side numeric fact"
            )
        if adjustment.proposed_adjusted_value is None:
            raise EffectiveInputError(
                f"accepted adjustment {adjustment.id!r} has no proposed_adjusted_value"
            )
        # Idempotent replay: an already materialized fact carries the exact
        # adjustment id and must not be compared to its original input value.
        if any(
            adjustment.id in fact.applied_adjustment_ids
            for fact in normalized_input.facts
            if fact.field == adjustment.target_field
            and (adjustment.target_period is None or fact.period == adjustment.target_period)
        ):
            continue
        fact = _target_fact(normalized_input.facts, adjustment)
        groups.setdefault((fact.field, fact.period), []).append(adjustment)

    if not groups:
        return normalized_input.model_copy(update={"adjustments": adjustments})

    by_key = {(fact.field, fact.period): fact for fact in normalized_input.facts}
    for key, group in groups.items():
        by_key[key] = _effective_fact(by_key[key], sorted(group, key=lambda item: item.id))

    facts = [by_key[(fact.field, fact.period)] for fact in normalized_input.facts]
    flags = list(normalized_input.flags)
    if "ACCEPTED_ADJUSTMENTS_MATERIALIZED" not in flags:
        flags.append("ACCEPTED_ADJUSTMENTS_MATERIALIZED")
    payload = normalized_input.model_dump(mode="python", warnings=False)
    payload.update({"facts": facts, "adjustments": adjustments, "flags": flags})
    try:
        return NormalizedCompanyInput.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise EffectiveInputError(f"effective normalized input is invalid: {exc}") from exc


def materialize_accepted_adjustments(
    normalized_input: NormalizedCompanyInput,
    accepted_adjustments: Sequence[AdjustmentInput] | None = None,
) -> NormalizedCompanyInput:
    """Compatibility name for callers that emphasize the approval boundary."""

    return materialize_effective_input(normalized_input, accepted_adjustments)


__all__ = [
    "AdjustmentInput",
    "EFFECTIVE_ADJUSTMENT_FIELDS",
    "EffectiveInputError",
    "materialize_accepted_adjustments",
    "materialize_effective_input",
]
