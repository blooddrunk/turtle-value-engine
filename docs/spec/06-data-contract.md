# 06 — Unified Data Contract

> Status: strict-v1 architecture specification

## 1. Purpose

This module defines how raw facts, LLM-proposed adjustments, deterministic metrics, gate results and final valuation decisions move through the system.

The core rule is:

```text
Fact -> Adjustment -> Metric -> Gate -> Decision
```

No stage may silently overwrite the previous one.

---

## 2. Why this separation matters

A value-investing agent mixes two fundamentally different jobs:

1. **deterministic financial calculation**;
2. **judgment under incomplete disclosure**.

If these are mixed inside a single LLM answer, the analysis becomes difficult to reproduce and audit.

Therefore the engine uses explicit layers.

---

## 3. Fact layer

A `Fact` is a sourced piece of information before strategy interpretation.

Examples:

```text
reported_cfo = 9.2bn CNY
restricted_cash = 1.1bn CNY
lease_principal_paid = 0.4bn CNY
formal_payout_floor = 50%
2025 gross margin = 43.2%
```

Every Fact must record:

- field name;
- value;
- fiscal period;
- unit/currency where relevant;
- evidence IDs;
- whether it is estimated;
- confidence.

If a value cannot be found, use `null`. Do not invent it.

---

## 4. Evidence layer

Evidence is stored separately from facts because one source item may support multiple facts and judgments.

Evidence distinguishes:

```text
SUPPORT
COUNTER
CONTEXT
```

and strength:

```text
E3  audited / formal primary data
E2  formal operating disclosure
E1  credible independent secondary evidence
E0  inference only
```

Business-quality scoring should reference evidence IDs instead of duplicating long text.

---

## 5. Adjustment layer

An Adjustment explains why economic analysis differs from a raw accounting or database fact.

Examples:

```text
remove one-off government grant from CFO
reclassify supplier finance as debt
apply 80% weight to liquid bond assets
reduce subsidiary cash for minority ownership
apply 50% upstreamability factor
normalize a distorted working-capital year
```

Adjustment types are explicitly enumerated.

### Critical boundary

An LLM may create:

```text
status = PROPOSED
proposed_by = LLM
```

but it must not silently mutate the final metric.

A proposed LLM adjustment only becomes effective after deterministic validation or explicit human approval:

```text
status = ACCEPTED
approved_by = RULE_ENGINE | HUMAN
```

This is one of the most important safety rails in the architecture.

---

## 6. Metric layer

Metrics are calculated by deterministic code using Facts plus accepted Adjustments.

Examples:

```text
Adjusted CFO
Core CDC
Normalized Parent Core CDC
CDC Yield
Strict Net Cash
Owner Realizable Net Cash
Stress Coverage
Distributable Base
Through Return
```

LLMs may explain metrics but may not override their numeric result.

---

## 7. Gate layer

Each strategy domain is evaluated independently:

```text
Universe
Balance Sheet
CDC
Through Return
Business Quality
Governance / Data Quality
```

A gate contains individual rule results with stable `rule_id` values.

Example:

```json
{
  "status": "FAIL",
  "rules": [
    {
      "rule_id": "CDC.CONTINUITY.POSITIVE_YEARS",
      "status": "FAIL",
      "actual": 2,
      "threshold": 4
    }
  ],
  "blocking_reasons": [
    "Core CDC was positive in only 2 of the last 5 years."
  ]
}
```

The engine must be able to explain exactly which rule blocked a company.

---

## 8. Business-quality layer

Business Quality is structurally different from pure financial metrics because judgment is unavoidable.

For each of the eight dimensions, store:

```text
dimension
score
supporting_evidence_ids
counter_evidence_ids
confidence
reasoning_summary
```

The LLM output is therefore a structured judgment record, not free-form investment prose.

Final score and critical-dimension constraints are then checked deterministically against `rules/strict-v1.yaml`.

---

## 9. Valuation layer

Valuation consumes only validated upstream metrics and the active rule profile.

It must not fetch new fundamental facts itself.

Inputs include:

```text
Normalized Parent Core CDC
Distributable Base
Conservative Payout Ratio
Verified Recurring Buyback Cash
Valuation Net Cash
Normalized Diluted Economic Shares
Listing price / FX conversion
```

Outputs conform to:

```text
schemas/valuation-result.schema.json
```

---

## 10. Decision layer

The final decision is a derived result, not another independent opinion.

The decision engine considers:

1. blocking hard gates;
2. manual-review flags;
3. data/evidence confidence;
4. current valuation state.

A high valuation score can never override a failed upstream hard gate.

Typical states:

```text
FAIL
SPECIAL_REVIEW
WATCH
TOO_EXPENSIVE_FOR_STRICT_MODEL
ACCEPTABLE
TURTLE_ENTRY
EXTREME_SAFETY
```

---

## 11. Auto-decision permission

The final object includes:

```text
auto_decision_allowed
```

It must be `false` when any critical condition requires manual review, including examples such as:

- LOW critical-input confidence;
- material unresolved NCI attribution;
- material unknown restricted cash;
- cyclical normalization unavailable;
- multi-class economic rights unresolved;
- major governance allegation requiring verification;
- LLM-proposed material adjustment not yet accepted.

The system may still calculate indicative metrics, but must not issue a normal automated investment state.

---

## 12. Source-of-truth rule

The authoritative order is:

```text
raw source evidence
-> extracted Facts
-> accepted Adjustments
-> deterministic Metrics
-> deterministic Gates
-> Valuation
-> Decision
```

Human-readable reports are generated from this object.

Reports must never become the source of truth for later calculations.

---

## 13. Versioning

Every analysis records:

```text
schema_version
profile_id
as_of
```

This makes historical results reproducible after rules change.

Example:

```text
schema_version = 1.0.0
profile_id     = strict-v1
as_of          = 2026-09-06
```

A future `strict-v2` must not silently alter historical `strict-v1` results.

---

## 14. Canonical schema files

```text
schemas/normalized-input.schema.json
schemas/evidence.schema.json
schemas/company-analysis.schema.json
schemas/valuation-result.schema.json
```

`normalized-input.schema.json` is the frozen input-side contract. It contains
only `schema_version`, analysis/company identity, `data_quality`, `facts`,
`evidence_index`, explicit `adjustments` and input-side flags. It must not
contain `metrics`, `gates`, `business_quality`, `valuation` or `decision`.

Within `company`, `primary_listing` is the required canonical listing/issuer
identifier and `other_listings` preserves additional A/H share listings
without merging their prices into the input facts.

`company-analysis.schema.json` remains the top-level output contract.

The input model validates cross-object integrity that standard JSON Schema
cannot express portably: evidence IDs are unique, and every fact or
adjustment evidence reference must resolve to an item in `evidence_index`.
Known normalized fact names also have field-specific numeric, boolean or enum
value checks; missing values remain explicit `null` values and are never
filled with zero.

---

## 15. Next implementation boundary

Once this contract is stable, implementation should begin with a deterministic calculation core rather than an LLM agent.

Recommended first modules:

```text
src/domain/
src/calculations/
src/gates/
src/valuation/
```

The first executable milestone should accept a manually prepared `CompanyAnalysis` fact/evidence payload and calculate:

```text
Core CDC
Normalized CDC
Net Cash metrics
Through Return
Gate statuses
Valuation tiers
Final deterministic state
```

Only after that baseline passes unit tests should automatic annual-report extraction and LLM business-quality agents be connected.
