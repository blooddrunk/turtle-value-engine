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

### Phase 2.2 — First structured provider adapter (COMPLETE)

The read-only `AKShareProvider` now sits behind the foundation and supports
`COMPANY_METADATA`, `LISTING_METADATA`, `MARKET_QUOTE` and
`MARKET_HISTORY` for A/H listing identifiers. It lazily loads the optional
AKShare dependency, converts tabular responses to JSON-safe opaque raw
records, selects the requested listing row, preserves source/version metadata
and uses the existing cache/replay helper without writing on provider
failure.

`AKShareNormalizer` maps only provider-neutral metadata, quote and history
facts into the existing `NormalizedCompanyInput` contract. It creates
structured-data evidence, preserves nulls, rejects ambiguous periods and
records unresolved quote/history coverage. It does not map financial
statements, filing-derived classifications, provider headline market caps or
any deterministic metric.

The deterministic tests use injected clients and frozen fixtures. Live
integration is explicitly opt-in with `TVE_RUN_AKSHARE_LIVE=1` and is not part
of ordinary CI.

### Phase 2.3 — First financial-statement mapping slice (COMPLETE)

The AKShare adapter now supports read-only `CASH_FLOW_STATEMENT` acquisition
for A-share and H-share listings using documented market-specific endpoints.
Deterministic fixtures cover the A-share wide-row and H-share long-row shapes.
The normalizer maps only explicit `reported_cfo` and `acquisition_cash` lines
with exact report periods and reported currency. It preserves explicit nulls,
rejects ambiguous periods/items, and does not map aggregate capex into
PPE/intangible fields or calculate CDC/financing metrics.

The adapter and mapping versions are bumped so old raw-cache namespaces are
not replayed under the new endpoint/mapping contract. Live calls remain
opt-in; ordinary CI uses injected clients and frozen fixtures.

Unresolved mapping questions are intentionally deferred: A/H field-level
coverage for all statement variants, parent-versus-consolidated attribution,
cash-flow classification of interest/leases, capex component separation and
all filing-derived adjustments require primary disclosures or a later mapping
review.

### Phase 2.4 — Income-statement mapping slice (COMPLETE)

The AKShare adapter now supports read-only `INCOME_STATEMENT` acquisition for
A-share and H-share listings. The A-share report-period endpoint is normalized
from wide rows and the H-share endpoint from long-form statement items. Only
explicit `parent_net_profit` and `consolidated_net_profit` lines are mapped;
revenue, operating profit, margins, provider ratios and filing-derived
classifications remain outside this slice. Exact report periods, reported
currency and explicit nulls are preserved, and ambiguous periods/items are
rejected.

The adapter and mapping versions are bumped so this endpoint contract has a
separate cache/fact namespace. Tests use injected clients and frozen fixtures;
live integration remains explicitly opt-in. Unresolved income-mapping
questions are owned by the Phase 2 mapping review: field-name coverage across
all A/H statement variants, the precise parent/consolidated entity basis,
currency/unit scaling, and point-in-time publication semantics.

### Phase 2.5 — Balance-sheet mapping slice (COMPLETE)

The AKShare adapter now supports read-only `BALANCE_SHEET` acquisition for
A-share and H-share listings. The A-share detailed report-period endpoint is
normalized from wide rows and the H-share endpoint from long-form statement
items. The slice maps only explicit `book_cash`, `parent_equity`,
`total_equity` and an explicit aggregate `reported_interest_bearing_debt`
when the upstream label has that same economic meaning. It does not rename
`total_liabilities`, sum short- or long-term borrowing rows, or infer
restricted cash, lease debt, minority attribution or upstreamability.

Exact report dates, reported currency and explicit nulls are preserved, and
ambiguous periods/items are rejected. The adapter and mapping versions are
bumped so this endpoint contract has a separate cache/fact namespace. Tests
use injected clients and frozen fixtures; live integration remains explicitly
opt-in. Unresolved balance-sheet mapping questions are owned by the Phase 2
mapping review: field-name coverage across all A/H statement variants, the
consolidated-versus-standalone entity basis, currency/unit scaling,
interest-bearing-debt aggregate availability, and point-in-time publication
semantics.

### Phase 2.6 — Verified A-share balance endpoint contract (COMPLETE)

The mapping review now covers the current documented AKShare aggregate
balance endpoint, `stock_zcfz_em` (and `stock_zcfz_bj_em` for Beijing-listed
shares). These endpoints accept an exact quarter-end `statement_date`, return
an A-share universe, and expose only a limited aggregate shape. The provider
selects the requested listing before creating the raw record and the
normalizer uses the requested statement date rather than the announcement
date as the point-in-time period. The documented aggregate fields map only
`book_cash` and `total_equity`; `负债-总负债` is deliberately not promoted to
debt, and parent equity remains missing when it is not reported. The existing
detailed report-period endpoint remains a compatibility fallback when the
installed AKShare client exposes it.

The adapter and mapping versions are bumped for this endpoint contract.
Offline tests cover date validation, row selection, exact periods, explicit
missing fields and the no-total-liabilities rule. Live calls remain opt-in.

### Phase 2.7 — Dividend event acquisition boundary (COMPLETE)

The AKShare adapter now exposes the documented A-share `stock_dividend_cninfo`
and H-share `stock_hk_dividend_payout_em` endpoints through the same
read-only provider boundary. Their historical rows are retained in opaque
raw records and structured-data evidence. The normalizer deliberately emits
no `ordinary_dividend_cash`, `special_dividend_cash` or `payout_ratio`: the
A-share feed reports per-10-share plans and announcement/payment dates, while
the H-share feed reports plan strings and fiscal years. Neither shape alone
establishes a total cash amount, ordinary-versus-special policy
classification, or a single accepted period basis.

Offline fixtures cover both markets, endpoint arguments, replay metadata and
the no-fabrication behavior. Live calls remain opt-in. The next Phase 2 task
is a similarly narrow review of A-share share-capital history; H-share share
class equivalence and diluted-share treatment remain unresolved.

### Phase 2.8 — A-share share-capital raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare A-share
share-capital endpoint, `stock_zh_a_gbjg_em`. The endpoint accepts a `symbol`
and returns all historical capital-structure records with `变更日期`, `总股本`,
circulation fields and `变动原因`. The provider passes the requested six-digit
A-share code, retains the complete response as an opaque raw record and records
the returned row count for replay diagnostics.

The official documentation types `总股本` as `int64`, but does not declare an
explicit unit or a fully diluted economic scope. The change-date semantics,
options/convertibles, A/H class relationship and change-reason classification
are therefore unresolved. The normalizer records the raw evidence and an
explicit `AKSHARE_SHARE_CAPITAL_RAW_ONLY` flag, marks
`normalized_diluted_economic_shares` as missing and emits no canonical share,
dilution, buyback, issuance or split fact. H-share share capital remains
outside this slice. Live calls remain opt-in; tests use an injected client and
a frozen fixture.

### Phase 2.9 — A-share repurchase raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare A-share
`stock_repurchase_em` endpoint. It accepts no request arguments and returns an
all-company response containing planned and completed repurchase fields,
repurchase-start dates and latest-announcement dates. The provider filters the
universe to the requested A-share code before creating the raw record, retains
all matching rows rather than selecting an arbitrary latest row, records both
upstream and selected row counts, and rejects any universe row without an
explicit listing code. A listing with no matching row produces an empty raw
snapshot rather than an invented zero.

The documentation identifies planned and completed monetary fields in yuan,
but the response does not establish one settled cash-flow period: completed
amounts can be cumulative, the latest announcement is an update date, and
planned and completed status are different economic states. The normalizer
therefore retains the filtered raw evidence, sets `buyback_cash` in the
critical-missing inventory and emits `AKSHARE_CORPORATE_ACTIONS_RAW_ONLY`; it
does not emit buyback cash, recurrence, net share reduction or any valuation
credit. H-share repurchase data and filing-backed action classification remain
outside this slice. Live calls remain opt-in; tests use an injected client and
a frozen fixture.

### Phase 2.10 — A-share rights-issue corporate-action raw contract (COMPLETE)

The mapping review now covers the current documented AKShare CNINFO
`stock_allotment_cninfo` endpoint under the provider-neutral
`CORPORATE_ACTIONS` category. The endpoint accepts an A-share `symbol` plus
`start_date` and `end_date` strings in `YYYYMMDD` form and returns historical
rights-issue plan/result rows with multiple dates, share quantities, prices,
proceeds and fees. The provider passes the requested six-digit code and date
range, retains the complete response as an opaque raw record and records its
row count and effective request range.

The documented response does not establish one canonical event period,
planned-versus-completed outcome, amount unit/scaling, or fully diluted
share-class scope. The normalizer therefore emits structured evidence only,
sets `share_issuance_cash` as critically missing and emits
`AKSHARE_ALLOTMENT_RAW_ONLY`; it creates no canonical issuance, dilution,
buyback, split or share-count fact. H-share corporate actions and
filing-backed interpretation remain unresolved. Live calls remain opt-in;
tests use an injected client and a frozen fixture.

This slice leaves the next documented structured-data review open; no
additional dividend, buyback, split, issuance or diluted-share fact is admitted
until its period, unit and economic scope are explicit.

### Phase 2.11 — A-share company share-change raw contract (COMPLETE)

The mapping review now covers the current documented AKShare CNINFO
`stock_share_change_cninfo` endpoint under the provider-neutral
`SHARE_CAPITAL` category. The endpoint accepts an A-share `symbol` plus
`start_date` and `end_date` strings in `YYYYMMDD` form and returns historical
company-share-change rows with change/announcement dates, total and
circulation holdings, share-class holdings and change reasons. The provider
uses this endpoint only when a date range is explicitly requested, passes the
six-digit code and range, retains every returned row and records the range and
row count.

The documented numeric fields do not define a unit or fully diluted economic
scope, and the response dates do not establish one canonical event period.
The normalizer therefore validates explicit row identity, emits structured
evidence only, sets `normalized_diluted_economic_shares` as critically missing
and emits `AKSHARE_SHARE_CAPITAL_CHANGE_RAW_ONLY`; it creates no canonical
share, issuance, buyback or split fact. The existing no-parameter
`stock_zh_a_gbjg_em` raw slice remains unchanged. H-share share capital and
filing-backed action classification remain unresolved. Live calls remain
opt-in; tests use an injected client and a frozen fixture.

The next Phase 2 task remains a focused mapping review of one documented
structured-data or corporate-action boundary. No additional share, dividend,
buyback, split or issuance fact is admitted until its period, unit, entity,
status and economic scope are explicit.

This mapping-review hardening keeps statement currency provenance conservative
across all three slices: only explicit valid three-letter codes are accepted,
missing currency is preserved as `null` rather than inferred from the listing
market, and conflicting currencies within one report period are rejected. Unit
scaling and consolidated-versus-standalone presentation basis remain open
questions for a later review.

### Future Phase 2 deliverables

```text
src/turtle_value_engine/providers/
  base.py
  models.py
  errors.py
  cache.py
  normalization.py
  akshare.py       # Phase 2.2 market + Phase 2.3–2.11 structured slices
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

Phase 2.11 completes the next documented structured-data boundary while
keeping share-change, repurchase and rights-issue period, status, unit and
economic-scope questions unresolved. Phase 2 remains active; the next
documented category must still be reviewed before its fields can enter the
canonical contract.
Filing-derived classifications remain a Phase 3 concern.
