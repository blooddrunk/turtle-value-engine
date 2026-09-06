# Framework Overview

## Objective

`turtle-value-engine` converts a conservative value-investing philosophy into an auditable decision engine for A-share and H-share companies.

The system is designed to answer five questions in order:

1. **Can the company survive?**
2. **Does the business really generate cash?**
3. **Does economic value actually reach shareholders?**
4. **Is the business model durable enough for historical cash generation to remain relevant?**
5. **Is the current price low enough to provide a sufficient margin of safety?**

## Decision pipeline

```text
Market universe
  ↓
Stage 0 — eligibility / data quality
  ↓
Gate 1 — balance-sheet safety
  ↓
Gate 2 — real cash generation (CDC)
  ↓
Gate 3 — shareholder-through return
  ↓
Gate 4 — evidence-based business quality
  ↓
Valuation engine
  ↓
PASS / WATCH / FAIL / SPECIAL_REVIEW
```

## Non-negotiable design rule

The framework is **gate-based, not score-first**.

A company that fails a critical gate must not enter the normal candidate pool merely because other indicators are excellent.

Examples:

- High dividend yield does not compensate for structurally negative cash generation.
- Large cash balances do not compensate for severe governance risk.
- A great business does not compensate for an unacceptable purchase price.
- A cheap valuation does not compensate for a structurally deteriorating business.

Scores are used only to rank companies that have already passed the relevant hard gates.

## Core quantitative pillars

### 1. Owner Net Cash Ratio

```text
OwnerRealizableNetCash / MarketCap
```

Interpretation:

> Of every 100 units of market value paid for the company, how much can conservatively be treated as high-quality net cash attributable and realistically accessible to ordinary shareholders?

This is the **stock of safety**.

### 2. CDC Yield

```text
NormalizedParentCoreCDC / MarketCap
```

Interpretation:

> Of every 100 units of market value, how much owner-distributable cash does the existing business normally generate each year?

This is the **flow of economic cash generation**.

### 3. Through Return

```text
DividendThroughReturn + NormalizedNetShareReduction
```

Interpretation:

> How much of the business's economic output is conservatively expected to become shareholder return through ordinary cash distributions and genuine net reduction in diluted shares?

This is the **shareholder realization rate**.

### 4. Business Quality

An evidence-based 8-dimension model covering:

- demand durability
- cyclicality
- pricing power
- competitive moat
- capital efficiency
- customer / supplier / channel dependency
- regulatory and external-policy risk
- predictability and business-model simplicity

This is the **durability test** for historical cash generation.

## Typical strict-mode profile

A highly attractive candidate may look roughly like:

```text
Owner Net Cash Ratio       >= 50%
CDC Yield                  >= 10%
Through Return             >= 5%
Business Score             >= 32 / 40
Evidence Confidence        HIGH
```

These are strategy parameters rather than universal financial truths. They must remain configurable and should eventually be validated through historical testing.

## Result states

### PASS

All relevant hard gates pass and valuation meets the selected strategy threshold.

### WATCH

Business quality and financial safety may be acceptable, but valuation or another non-terminal condition is not yet attractive enough.

### FAIL

A critical rule fails, such as unreliable reporting, unsustainable cash generation, excessive refinancing dependency or severe governance problems.

### SPECIAL_REVIEW

The deterministic model is not reliable enough for the situation, for example:

- major restructuring
- exceptional dividend
- very large acquisition or disposal
- cyclical peak/trough
- material accounting anomaly
- privatization / control change
- unusual holding-company or VIE cash restrictions

## Responsibility boundary

### Deterministic code owns

- financial arithmetic
- normalization formulas
- thresholds
- hard-gate decisions based on numeric rules
- historical series
- scoring aggregation
- target-market-cap and target-price calculations

### LLM / research agent owns

- reading annual reports and notes
- extracting evidence from narrative disclosures
- identifying restricted or trapped cash
- interpreting capital-allocation events
- classifying business-model durability
- identifying one-off accounting effects
- finding supporting and contradicting evidence

The LLM must not silently overwrite deterministic calculations.

## Evidence contract

Every material qualitative conclusion should preserve:

```text
claim
supporting evidence
counter-evidence
source
period
evidence class
confidence
unresolved questions
```

Unknown values remain `null`. The agent must not invent missing financial figures.

## Sector treatment

The default framework is intended for ordinary non-financial operating companies.

Special models are required for at least:

- banks
- insurers
- brokers
- trusts
- REITs
- property developers
- highly cyclical commodity businesses

The default debt/cash logic must not be applied mechanically to these sectors.
