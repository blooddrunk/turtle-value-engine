# Development Roadmap

> Repository: `blooddrunk/turtle-value-engine`
>
> Goal: turn the strict Turtle value-investing specification into an auditable deterministic engine first, then add data adapters, LLM-assisted evidence analysis and unattended monitoring.

## Phase 0 — Freeze the contracts

Status: mostly complete.

Deliverables:

- strategy specifications under `docs/spec/`;
- `rules/strict-v1.yaml`;
- evidence and CompanyAnalysis JSON Schemas;
- valuation result schema;
- runtime/automation architecture.

Exit criteria:

- formulas and hard-gate semantics are explicit;
- no critical investment rule exists only in chat history;
- machine-readable thresholds exist.

---

## Phase 1 — Deterministic calculation engine (COMPLETE)

No network, no LLM, no live market data.

Status: complete. The deterministic offline pipeline and `tve analyze` CLI
are implemented and tested. CDC, net cash, Through Return, valuation tiers,
offline evidence-backed Business-quality scoring and the fixed hard-gate
primitives are composed into a schema-valid `CompanyAnalysis`.

The analyze command does not invent Business Quality judgments. Unless an
explicit structured assessment is supplied through the Python pipeline API,
that gate remains `NOT_EVALUATED`, valuation remains indicative and the final
decision disables automatic investment output.

### Deliverables

Python package and CLI with modules approximately equivalent to:

```text
src/turtle_value_engine/
  models/
  config/
  calculations/
    business_quality.py
    cdc.py
    net_cash.py
    through_return.py
    valuation.py
  gates/
    eligibility.py
    balance_sheet.py
    cdc.py
    through_return.py
    business_quality.py
    governance.py
  pipeline.py
  cli.py
```

CLI minimum:

```text
tve analyze --input fixtures/company.json --profile strict-v1
```

The engine must:

1. load and validate normalized input;
2. load `strict-v1` parameters;
3. compute deterministic metrics;
4. evaluate hard gates;
5. compute valuation tiers when eligible;
6. output valid `CompanyAnalysis` JSON.

The CLI is intentionally offline-only. Provider adapters, network access,
LLM-assisted evidence analysis and automatic Business Quality assessment are
later-phase boundaries.

### Fixtures

Create synthetic cases:

- `healthy_cash_cow`;
- `high_dividend_bad_cashflow`;
- `cash_rich_dying_business`;
- `excellent_business_too_expensive`;
- `leveraged_dividend_trap`;
- `negative_ev_governance_risk`;
- `cyclical_peak_false_cheap`;
- `share_dilution_offsets_buyback`.

The committed baseline lives under `fixtures/` and is validated by
`schemas/normalized-input.schema.json`. Scenario expectations are kept in a
separate metadata file so they cannot be mistaken for input facts or already
validated engine outputs.

### Tests

At minimum:

- formula unit tests;
- threshold boundary tests;
- missing-data behavior;
- confidence propagation;
- hard-gate precedence;
- valuation monotonicity;
- no double-counting of capitalized development;
- no double-counting of lease/interest cash flows;
- buyback/dilution normalization;
- schema validation.

### Exit criteria

For frozen inputs, outputs are reproducible and independent of any LLM.

---

## Phase 2 — Structured data adapters (CURRENT ACTIVE MILESTONE)

Goal: make the deterministic engine usable on real companies without introducing document-reading complexity yet.

### Initial sources

Preferred prototype stack:

```text
AKShare        -> A/H quotes, history, convenient public-data aggregation
Tushare Pro    -> optional richer A-share structured fundamentals
BaoStock       -> optional A-share historical/backtest data
local cache    -> reproducibility and rate-limit protection
```

### Phase 2.1 — Provider and cache foundation (COMPLETE)

The provider-neutral acquisition boundary, raw-response filesystem cache,
capability model, error-isolation rules, provider field matrix and CI
guardrails are now frozen. No live provider is included in this sub-phase.

### Phase 2.2 — First structured provider adapter (NEXT)

Implement one narrowly scoped adapter behind the foundation, beginning with
read-only A/H quote and history acquisition. Validate its raw records,
provenance, cache/replay behavior and normalized mapping against frozen
fixtures before adding financial statement categories. Do not treat the
adapter as a source for filing-derived classifications listed in the provider
field matrix.

### Future Phase 2 deliverables

```text
src/turtle_value_engine/providers/
  base.py
  models.py
  errors.py
  cache.py
  normalization.py
  akshare.py       # future Phase 2.2 adapter
  tushare.py       # future optional adapter
  baostock.py      # future optional adapter
```

Provider output must map into normalized `Fact` records through the frozen
normalization boundary; provider-specific field names must not leak into
calculation modules.

### Exit criteria

- fetch real A/H price and basic financial inputs;
- run first-pass screening;
- source and timestamp every imported fact;
- tolerate provider failure without corrupting cached datasets.

---

## Phase 3 — Official filing and evidence layer

Goal: convert screening results into auditable deep analysis.

### Sources

```text
A shares -> CNINFO / exchange filings / company announcements
H shares -> HKEXnews / company reports and announcements
```

### Deliverables

- filing discovery;
- document download/cache;
- metadata and filing IDs;
- annual/interim report extraction;
- evidence store;
- adjustment proposal workflow.

LLM can assist with:

- locating restricted cash;
- lease/interest classification;
- acquisition details;
- payout policy;
- governance risks;
- customer concentration;
- business-quality evidence.

LLM cannot directly overwrite engine-computed values.

### Exit criteria

A final PASS/WATCH/FAIL result can be traced from decision -> gate -> metric -> adjustment -> fact -> source filing.

---

## Phase 4 — Business-quality agents and Skill interface

### ChatGPT Skill

Create a thin Skill that teaches ChatGPT to:

- locate the repository specification;
- request/retrieve company data;
- invoke or consume engine output;
- conduct Bull / Skeptic / Adjudicator evidence analysis;
- explain results consistently;
- never recompute deterministic metrics ad hoc.

Do not copy the entire specification into `SKILL.md`; reference repository/spec resources or compact bundled references.

### Agent roles

```text
Research/Data Agent
Business Quality Analyst
Skeptic Analyst
Adjudicator
Report Composer
```

### Exit criteria

Interactive command such as:

> Analyze China Mobile / 贵州茅台 using strict-v1.

produces an evidence-backed report consistent with deterministic engine output.

---

## Phase 5 — Backtesting and calibration

Do not tune strict-v1 thresholds before the deterministic engine and point-in-time data semantics are stable.

Requirements:

- survivorship-bias-aware universe where possible;
- filing publication date / point-in-time availability;
- no future financial data leakage;
- dividends, corporate actions and delistings;
- transaction costs and liquidity assumptions;
- A/H listing-specific prices;
- explicit benchmark set.

Metrics:

```text
CAGR
max drawdown
volatility
Sharpe / Sortino
turnover
hit rate
factor exposure
sector concentration
failure-mode attribution
```

Threshold changes require a new versioned profile rather than silently rewriting `strict-v1`.

---

## Phase 6 — Watchlist and event-driven re-analysis

### Watchlist state

Persist:

```text
company
listing
last_analysis_commit/version
last_filing_seen
last_event_cursor
last_result
open_questions
```

### Event monitor

Detect events such as:

- annual/interim reports;
- earnings warnings;
- dividend changes;
- buybacks / issuance;
- acquisitions / disposals;
- audit-opinion changes;
- regulatory penalties;
- material litigation;
- controlling-shareholder events.

Map events to:

```text
NO_REANALYSIS
PARTIAL_REANALYSIS
FULL_REANALYSIS
URGENT_MANUAL_REVIEW
```

### Runtime options

- GitHub Actions for deterministic scheduled jobs;
- Hermes cron for self-hosted unattended CLI + agent workflows;
- ChatGPT Scheduled for user-facing monitoring/research alerts where supported.

---

## Phase 7 — Controlled evolution

The system may improve procedures, but may not autonomously mutate the investment rule core.

### Automatically learnable

- source mappings;
- document-locator heuristics;
- company-specific accounting quirks;
- known payout policies;
- watchlist state;
- extraction heuristics;
- agent workflow skills.

### Protected core

- formulas;
- hard-gate semantics;
- rule profiles;
- schemas;
- valuation definitions.

Core changes require:

```text
proposal -> evaluation -> tests -> point-in-time validation/backtest -> PR -> human approval
```

This is the project's definition of safe “self-evolution.”

---

# Current milestone

Phase 2 is active. Phase 1 remains frozen: changes to formulas, hard-gate
semantics, schemas or `strict-v1` thresholds require a separately reviewed,
versioned change.

The exact next task is **Phase 2.2: implement the first read-only AKShare
quote/history adapter**, with a focused normalization contract and recorded
live-provider integration tests kept out of ordinary network-independent PR
CI. Financial-statement mappings should follow only after the quote/history
boundary is verified.
