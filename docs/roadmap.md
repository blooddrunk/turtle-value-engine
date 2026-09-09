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

### Phase 2.11 — A-share ownership-pledge snapshot raw contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_gpzy_pledge_ratio_em` endpoint under the provider-neutral
`OWNERSHIP_PLEDGE` category. The endpoint requires an A-share `date` in
`YYYYMMDD` form and returns a date-specific universe snapshot with pledge ratio,
pledged shares/value, pledge counts, share-class pledge counts, one-year
performance and industry-code context. The provider validates the exact
trading date and explicit listing identity, filters the universe to the
requested A-share code and retains the matching row as raw evidence.

The documented ratio and counts do not identify the affected holder or
controlling-shareholder status, establish governance severity, settle units or
cash accessibility, or define a debt-equivalent fact. The normalizer therefore
emits `AKSHARE_OWNERSHIP_PLEDGE_RAW_ONLY`, marks `governance_risk_level` as
critically missing and creates no governance, pledged-cash, debt-equivalent or
valuation fact. H-share pledge coverage and filing-backed governance
interpretation remain unresolved. Live calls remain opt-in; tests use an
injected client and a frozen fixture.

### Phase 2.12 — A-share dividend-distribution snapshot raw contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_fhps_em` endpoint under the existing provider-neutral `DIVIDENDS`
category. The endpoint accepts an explicit A-share report date in `YYYYMMDD`
form, limited to the documented June 30 or December 31 periods, and returns a
universe snapshot with distribution ratios, multiple event/announcement dates,
progress and per-share context. The provider validates the report date and
explicit listing identity, filters the universe to the requested A-share code
and retains the matching rows as raw evidence.

The documented ratios and status do not establish a settled total cash amount,
declared-versus-paid state, ordinary-versus-special classification or the
canonical payout denominator. The normalizer therefore emits
`AKSHARE_DIVIDEND_SNAPSHOT_RAW_ONLY`, marks `ordinary_dividend_cash` as
critically missing and creates no dividend-cash, payout-ratio, split, dilution
or share-count fact. The existing no-parameter A/H dividend endpoints remain
unchanged. Live calls remain opt-in; tests use an injected client and a frozen
fixture.

This slice left the next Phase 2 task as a focused mapping review of one
documented structured-data or corporate-action boundary. Phase 2.13 below
covers that next boundary; no additional share, dividend, buyback, split or
issuance fact is admitted until its period, unit, entity, status and economic
scope are explicit.

This mapping-review hardening keeps statement currency provenance conservative
across all three slices: only explicit valid three-letter codes are accepted,
missing currency is preserved as `null` rather than inferred from the listing
market, and conflicting currencies within one report period are rejected. Unit
scaling and consolidated-versus-standalone presentation basis remain open
questions for a later review.

### Phase 2.13 — A-share earnings-forecast raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_yjyg_em` endpoint under a new provider-neutral `EARNINGS_FORECAST`
category. The endpoint accepts an A-share quarterly report date in `YYYYMMDD`
form, from the documented `20081231` start date, and returns a universe of
forecast rows containing listing identity, forecast indicators, forecast
values/ranges, change reasons, forecast type, prior-period values and
announcement dates. The provider validates the exact quarter-end request,
rejects rows without explicit listing identity, filters to the requested
six-digit A-share code and retains all matching rows.

Forecast values and announcement dates do not establish reported parent or
consolidated net profit for the requested statement period. The normalizer
therefore retains the filtered response as structured evidence, marks
`parent_net_profit` and `consolidated_net_profit` as critically missing and
emits `AKSHARE_EARNINGS_FORECAST_RAW_ONLY`; it creates no canonical profit,
margin, CDC or valuation fact. H-share earnings forecasts remain outside this
slice. Live calls remain opt-in; tests use an injected client and a frozen
fixture.

### Phase 2.14 — A-share performance-report raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_yjbb_em` endpoint under a new provider-neutral `PERFORMANCE_REPORT`
category. The endpoint accepts an A-share quarterly report date in `YYYYMMDD`
form, from the documented `20100331` start date, and returns a universe of
headline performance rows containing listing identity, revenue and net-profit
headlines, per-share indicators, ratios, industry and latest-announcement
metadata. The provider validates the exact quarter-end request, rejects rows
without explicit listing identity, filters to the requested six-digit A-share
code and retains all matching rows.

The headline net-profit field does not establish the accepted
parent-versus-consolidated entity basis, and operating cash flow is reported
per share rather than as a total CFO fact. The normalizer therefore retains
the filtered response as structured evidence, marks `parent_net_profit`,
`consolidated_net_profit` and `reported_cfo` as critically missing and emits
`AKSHARE_PERFORMANCE_REPORT_RAW_ONLY`; it creates no canonical profit,
revenue, margin, CFO, CDC or valuation fact. H-share performance reports
remain outside this slice. Live calls remain opt-in; tests use an injected
client and a frozen fixture.

### Phase 2.15 — A-share earnings-quick-report raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_yjkb_em` endpoint under a new provider-neutral
`EARNINGS_QUICK_REPORT` category. The endpoint accepts an A-share quarterly
report date in `YYYYMMDD` form, from the documented `20100331` start date, and
returns a universe of quick-report rows containing listing identity, headline
revenue and net-profit values, prior-period comparisons, per-share indicators,
ratios, industry and announcement-date metadata. The provider validates the
exact quarter-end request, rejects rows without explicit listing identity,
filters to the requested six-digit A-share code and retains all matching rows.

The headline net-profit field does not establish the accepted
parent-versus-consolidated entity basis, and the revenue/per-share fields do
not settle the canonical period, unit or diluted-share scope. The normalizer
therefore retains the filtered response as structured evidence, marks
`parent_net_profit` and `consolidated_net_profit` as critically missing and
emits `AKSHARE_EARNINGS_QUICK_REPORT_RAW_ONLY`; it creates no canonical
profit, revenue, margin, CFO, CDC or valuation fact. H-share quick reports
remain outside this slice. Live calls remain opt-in; tests use an injected
client and a frozen fixture.

### Phase 2.16 — A-share business-composition raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_zygc_em` endpoint under a new provider-neutral
`BUSINESS_COMPOSITION` category. The endpoint accepts a market-prefixed A-share
`symbol` and returns all historical main-business composition rows with report
dates, classification type, constituent business, revenue/cost/profit amounts,
ratios and gross-margin context. The provider passes the canonical listing
identifier, validates explicit listing identity and parseable report dates,
retains the complete listing-scoped response and records row and distinct
report-period counts.

The product, industry and geographic views overlap and do not establish one
canonical revenue or core-revenue series. Their units, entity basis, aggregation
rules and classification semantics therefore remain unresolved. The normalizer
retains structured evidence, marks `revenue` and `core_revenue` as critically
missing and emits `AKSHARE_BUSINESS_COMPOSITION_RAW_ONLY`; it creates no
canonical revenue, operating-profit, margin or business-quality fact. H-share
business composition remains outside this slice. Live calls remain opt-in;
tests use an injected client and a frozen fixture.

### Phase 2.17 — A-share financial-abstract raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Sina
`stock_financial_abstract` endpoint under a new provider-neutral
`FINANCIAL_ABSTRACT` category. The endpoint accepts a six-digit A-share
`symbol` and returns the issuer's historical key-indicator matrix with
`选项`, `指标` and report-period columns. The provider passes the requested
listing code, retains the complete listing-scoped response as an opaque raw
record, validates explicit metric identity and date-shaped period columns, and
records row and distinct-period counts.

The response mixes amount rows such as revenue and profit with per-share
indicators and ratios. Its wide presentation does not establish the canonical
entity, unit/scaling, period or diluted-share basis required by the normalized
contract. The normalizer therefore retains structured evidence, marks
`revenue`, `parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as
critically missing and emits `AKSHARE_FINANCIAL_ABSTRACT_RAW_ONLY`; it creates
no canonical fact, metric or valuation input. H-share financial abstracts
remain outside this slice. Live calls remain opt-in; tests use an injected
client and a frozen fixture.

### Phase 2.18 — A-share financial-indicator raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_financial_analysis_indicator_em` endpoint under a new provider-neutral
`FINANCIAL_INDICATORS` category. The endpoint accepts a market-suffixed A-share
`symbol` and the documented `indicator` choice of `按报告期` or `按单季度`; it
returns explicit listing identity, report dates, amount fields, per-share
indicators and provider-calculated ratios. The provider passes the requested
listing and indicator mode, retains the complete listing-scoped response as an
opaque raw record, validates explicit listing identity and parseable report
dates, and records row, period and indicator metadata.

The mixed response does not establish one canonical statement entity,
unit/scaling, point-in-time availability basis or ratio calculation
methodology. The normalizer therefore retains structured evidence, marks
`revenue`, `parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as
critically missing and emits `AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY`; it
creates no canonical fact, metric or valuation input. H-share financial
indicators remain outside this slice. Live calls remain opt-in; tests use an
injected client and a frozen fixture.

### Phase 2.19 — SSE insider share-change raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare SSE
`stock_share_hold_change_sse` endpoint under a new provider-neutral
`INSIDER_SHARE_CHANGES` category. The endpoint accepts a Shanghai A-share
`symbol` and returns listing-scoped rows with company code, holder and role,
share class, currency label, before/after holdings, change quantity and price,
change reason, change date and filing date. The provider passes the six-digit
code, retains every returned row as an opaque raw record and validates explicit
listing identity plus any supplied event dates.

The documented holdings and transaction prices describe insider events, not a
company-level fully diluted share series, and they do not by themselves
establish governance severity or a canonical buyback/issuance cash flow. The
normalizer therefore retains structured evidence, marks
`governance_risk_level` as critically missing and emits
`AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY`; it creates no share-count, dilution,
governance, buyback or issuance fact. Beijing coverage is handled by Phase 2.21
below. H-share coverage, holder interpretation and filing-backed governance
analysis remain outside this slice. Shenzhen coverage is handled by Phase 2.20
below. Live calls remain opt-in; tests use an injected client and a frozen
fixture.

### Phase 2.20 — SZSE insider share-change raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Shenzhen
`stock_share_hold_change_szse` endpoint under the existing provider-neutral
`INSIDER_SHARE_CHANGES` category. The endpoint accepts a Shenzhen A-share
`symbol` and returns listing-scoped rows with security identity, insider and
related-person roles, change dates, changed quantities, prices, change ratios,
and same-day holdings. The provider passes the six-digit code, retains every
returned row as an opaque raw record, validates explicit listing identity and
any supplied change dates, and records the listing-scoped response metadata.

The documented quantities are reported in ten-thousand shares and the change
ratio in thousandths, but the response still describes insider events rather
than a company-level fully diluted share series. The normalizer therefore
retains structured evidence, marks `governance_risk_level` as critically
missing and emits `AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY`; it creates no
share-count, dilution, governance, buyback or issuance fact. H-share
insider-share coverage, holder interpretation and filing-backed governance
analysis remain outside this slice. Live calls remain opt-in; tests use an
injected client and a frozen fixture.

### Phase 2.21 — BSE insider share-change raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Beijing Stock Exchange
`stock_share_hold_change_bse` endpoint under the existing provider-neutral
`INSIDER_SHARE_CHANGES` category. The endpoint accepts a Beijing A-share
`symbol` and returns listing-scoped rows with security identity, insider name
and role, change date, before/after holdings, changed quantity, average price
and change reason. The provider passes the six-digit code, retains every
returned row as an opaque raw record, validates explicit listing identity and
any supplied change dates, and records the listing-scoped response metadata.

The documented holding quantities are reported in ten-thousand shares and the
average price in yuan, but the response still describes insider events rather
than a company-level fully diluted share series. The normalizer therefore
retains structured evidence, marks `governance_risk_level` as critically
missing and emits `AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY`; it creates no
share-count, dilution, governance, buyback or issuance fact. H-share coverage,
holder interpretation and filing-backed governance analysis remain unresolved.
Live calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.22 — H-share financial-indicator raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_financial_hk_analysis_indicator_em` endpoint under the existing
provider-neutral `FINANCIAL_INDICATORS` category. The endpoint accepts a
five-digit H-share `symbol` and the documented `年度` or `报告期` mode; it
returns explicit listing identity, report dates, amount fields, per-share
indicators, provider-calculated ratios and currency labels. The provider
passes the requested listing code and mode, retains the complete
listing-scoped response as an opaque raw record, validates explicit listing
identity and parseable report dates, and records row, period and indicator
metadata.

The mixed response does not establish one canonical statement entity,
unit/scaling, point-in-time availability basis or ratio calculation
methodology. The normalizer therefore retains structured evidence, marks
`revenue`, `parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as
critically missing and emits `AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY`; it
creates no canonical fact, metric or valuation input. H-share insider-share
coverage remains unresolved because the current AKShare stock documentation
does not define an equivalent H-share insider endpoint. Live calls remain
opt-in; tests use an injected client and a frozen fixture.

### Future Phase 2 deliverables

```text
src/turtle_value_engine/providers/
  base.py
  models.py
  errors.py
  cache.py
  normalization.py
  akshare.py       # Phase 2.2 market + Phase 2.3–2.22 structured slices
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

Phase 2.22 completes the next documented structured-data boundary while
keeping share-change, repurchase and rights-issue period, status, unit and
economic-scope questions unresolved, and keeping ownership-pledge holder,
governance and economic-scope questions unresolved. The A-share
dividend-distribution snapshot remains raw-only because its ratios, status and
multiple dates do not establish settled ordinary cash or a canonical payout
denominator. Phase 2 remains active; the next documented category must still
be reviewed before its fields can enter the canonical contract. The A-share
earnings-forecast snapshot remains raw-only because forecast ranges, forecast
type and announcement dates do not establish reported parent or consolidated
profit for the requested period. Filing-derived classifications remain a
Phase 3 concern. The A-share performance-report snapshot remains raw-only
because its headline net profit has no admitted parent/consolidated basis and
its operating cash flow is per share rather than a canonical reported CFO
total. The A-share earnings-quick-report snapshot remains raw-only because its
headline profit and revenue comparisons, per-share indicators and announcement
date do not establish the canonical entity, unit, diluted-share or filing
period semantics.

The A-share business-composition snapshot remains raw-only because its
overlapping product, industry and geographic rows do not establish a canonical
revenue or core-revenue series; aggregation, unit, entity and classification
semantics remain unresolved. Filing-derived business-quality judgments remain
a later-phase concern.

The A-share financial-abstract matrix remains raw-only because its amount,
per-share and ratio rows use a wide historical presentation without an
admitted canonical entity, unit, period or diluted-share basis. Filing-derived
statement facts and analytical classifications remain outside this slice.
The A-share financial-indicator response remains raw-only because its reported
amounts, per-share values and provider ratios do not establish the canonical
entity, unit, point-in-time basis or calculation methodology. Filing-derived
statement facts and analytical classifications remain outside this slice.
The documented SSE insider-share-change response is also raw-only because
holder roles, holdings, transaction prices and event dates do not establish a
company-level diluted-share series or a governance-risk judgment. The documented
SZSE insider-share-change response is retained under the same raw-only
boundary: its change quantities, prices, units and event dates do not establish
a company-level diluted-share series or a governance-risk judgment.
The documented BSE insider-share-change response is retained under the same
raw-only boundary: its holding quantities, prices and event dates do not
establish a company-level diluted-share series or a governance-risk judgment.
The H-share financial-indicator response is retained under the same raw-only
boundary: its amounts, per-share values, provider ratios and currency label do
not establish a canonical statement entity, unit, point-in-time basis or
calculation methodology. H-share insider-share coverage remains unresolved.
