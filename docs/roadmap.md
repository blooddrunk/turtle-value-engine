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

### Phase 2.23 — H-share latest-indicator raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_hk_financial_indicator_em` endpoint under a new provider-neutral
`LATEST_INDICATORS` category. The endpoint accepts a five-digit H-share
`symbol` and returns a symbol-scoped latest-indicator row containing per-share,
share-capital, dividend, headline financial and valuation fields. The provider
passes the requested code, retains the complete response as an opaque raw
record, records the symbol-scoped row count and rejects an ambiguous multi-row
response. The published AKShare output does not retain a row-level listing code
or canonical statement period, so the request boundary is the only entity
scope admitted by this slice.

The mixed latest snapshot does not establish a canonical statement entity,
period, unit/scaling, diluted-share scope or valuation methodology. The
normalizer therefore retains structured evidence, marks `revenue`,
`parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as critically
missing and emits `AKSHARE_LATEST_INDICATORS_RAW_ONLY`; it creates no canonical
financial, share, dividend, market-cap, metric or valuation fact. H-share
insider-share coverage remains unresolved because the current AKShare stock
documentation does not define an equivalent H-share insider endpoint. Live
calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.24 — A-share disclosure-notice raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare CNINFO
`stock_zh_a_disclosure_report_cninfo` endpoint under a new provider-neutral
`DISCLOSURE_NOTICES` category. The endpoint accepts a six-digit A-share
`symbol`, the documented `沪深京` market, optional keyword/category filters and
an explicit `YYYYMMDD` date range. It returns listing-bound announcement
metadata: code, short name, title, announcement time and disclosure link.

The provider passes the requested listing and documented filters, validates
the date range and every returned row's explicit listing identity/date, and
retains the complete response as an opaque raw record. The normalizer emits
`AKSHARE_DISCLOSURE_NOTICES_RAW_ONLY`, marks `accounting_opinion` and
`governance_risk_level` as critically missing, and creates no filing-content,
accounting, governance, financial or valuation fact. Announcement titles and
links are discovery metadata only; linked documents remain outside this
slice. H-share disclosure coverage and Phase 3 filing retrieval/parsing remain
unresolved. Live calls remain opt-in; tests use an injected client and a
frozen fixture.

### Phase 2.25 — H-share dividend-event detail raw acquisition contract (COMPLETE)

The remaining H-share disclosure gap was reviewed against the current
documented AKShare stock interfaces. The documentation exposes no general
H-share disclosure-notice counterpart to the A-share CNINFO endpoint, so this
phase does not invent one or promote a company-profile/financial snapshot into
disclosure metadata. It instead adds one adjacent, separately selectable
documented event source: the Tonghuashun
`stock_hk_fhpx_detail_ths` endpoint under the existing `DIVIDENDS` category.

The endpoint accepts a five-digit H-share `symbol` and returns symbol-scoped
historical dividend-event rows with announcement date, plan, ex-date, payment
date, transfer-date range, event type, progress and scrip-dividend context. The
provider selects it only for the explicit provider-neutral request view
`view=event_detail`, validates any non-null event dates, preserves the full
symbol-scoped response and records the request scope for replay. The published
rows do not carry a canonical listing code, so the request boundary is retained
without inventing row-level identity.

The normalizer emits `AKSHARE_HK_DIVIDEND_DETAIL_RAW_ONLY`, marks
`ordinary_dividend_cash` as critically missing and creates no dividend-cash,
payout-ratio, share-count, filing-content or governance fact. Plan strings,
event status and dates do not establish settled amount, ordinary-versus-special
classification or a canonical financial period. General H-share disclosure
retrieval and linked-document parsing remain Phase 3 work. Live calls remain
opt-in; tests use an injected client and a frozen fixture.

### Phase 2.26 — A-share risk-warning-status raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_zh_a_st_em` endpoint under a new provider-neutral
`RISK_WARNING_STATUS` category. The endpoint accepts no request
arguments and returns the current risk-warning-board universe with explicit
listing code/name plus current market-observation fields. The provider
validates every returned row's listing code, filters the universe to the
requested six-digit A-share code, retains the matching rows and records both
upstream and selected row counts.

Risk-warning-board membership is a positive current snapshot, not a dated
status history or a complete assertion about a listing when it is absent from
the response. The normalizer therefore retains the filtered response as
structured evidence, marks `special_treatment` as critically missing and
emits `AKSHARE_RISK_WARNING_STATUS_RAW_ONLY`; it creates no canonical
special-treatment fact and does not infer `special_treatment=False` from
an empty match. H-share risk-warning coverage remains outside this slice. Live
calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.27 — A-share main-shareholder raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Sina
`stock_main_stock_holder` endpoint under a new provider-neutral
`SHAREHOLDER_HOLDINGS` category. The endpoint accepts an A-share `stock` code
and returns all historical main-shareholder rows with holder names, holding
quantities/ratios, share-class labels, as-of dates, announcement dates and
holder context. The provider passes the requested six-digit code, retains the
complete symbol-scoped response and records its row count.

The documented holder rows do not establish beneficial control, a governance
severity, a canonical share class or a company-level diluted-share series.
The normalizer therefore retains structured evidence, marks
`governance_risk_level` as critically missing and emits
`AKSHARE_MAIN_SHAREHOLDERS_RAW_ONLY`; it creates no ownership, share-count,
dilution, buyback, issuance or valuation fact. H-share main-shareholder
coverage and filing-backed ownership interpretation remain outside this
slice. Live calls remain opt-in; tests use an injected client and a frozen
fixture.

### Phase 2.28 — A-share trading-suspension raw acquisition contract (COMPLETE)

The mapping review now covers the documented AKShare Eastmoney
`stock_tfp_em` endpoint under a new provider-neutral `TRADING_SUSPENSIONS`
category. The endpoint accepts an A-share date in `YYYYMMDD` form and returns a
date-bound universe of suspension/resumption rows with explicit listing code,
suspension dates, duration, reason, market and expected resume date. The
provider validates the request and every returned row's listing identity and
nullable event dates, filters the universe to the requested listing and retains
all matching rows as raw evidence.

The event rows describe suspension activity for the requested date, not a
complete listing-status history, special-treatment state or filing-backed
governance conclusion. The normalizer therefore emits
`AKSHARE_TRADING_SUSPENSIONS_RAW_ONLY`, marks `special_treatment` and
`governance_risk_level` as critically missing and creates no canonical status,
governance or accounting fact. H-share trading-suspension coverage remains
outside this slice. Live calls remain opt-in; tests use an injected client and
a frozen fixture.

### Phase 2.29 — A-share restricted-share-release raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare Eastmoney
`stock_restricted_release_queue_em` endpoint under the existing
`SHARE_CAPITAL` category. The endpoint accepts a six-digit A-share `symbol`
and returns the listing's historical restricted-share release batches with
release dates, planned/actual/remaining quantities, market-value context,
lock-up type and pre/post release observations. Because the published
symbol-scoped output omits row-level listing codes, the request scope is
preserved and any optional returned code is checked when present.

The provider selects this endpoint only for the explicit
`view=restricted_release_queue` request, passes the six-digit code and
retains all returned rows. The documented quantities/values and release date
do not by themselves establish one canonical diluted-economic-share
treatment, and planned/actual/remaining states cannot be silently collapsed
into a share-count fact. The normalizer therefore emits
`AKSHARE_RESTRICTED_SHARE_RELEASES_RAW_ONLY`, marks
`normalized_diluted_economic_shares` as critically missing and creates no
canonical share, dilution, issuance, buyback or valuation fact. H-share
restricted-release coverage and filing-backed action classification remain
unresolved. Live calls remain opt-in; tests use an injected client and a
frozen fixture.

### Phase 2.30 — A-share goodwill-impairment raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare Eastmoney
`stock_sy_jz_em` endpoint under a new provider-neutral
`GOODWILL_IMPAIRMENT` category. The endpoint accepts an A-share report-date
`date` in `YYYYMMDD` form and returns a universe of listing rows with goodwill,
goodwill-impairment, ratio, profit, announcement-date and market context. The
provider validates explicit listing identity and nullable announcement dates,
filters to the requested six-digit A-share code, retains all matching rows and
records the requested report period for replay.

The goodwill and impairment amounts are aggregator fields whose accounting
entity, scope, reconciliation and point-in-time semantics still require a
primary filing. The normalizer therefore retains the filtered response as
structured evidence, marks `goodwill` and `impairment` as critically missing
and emits `AKSHARE_GOODWILL_IMPAIRMENT_RAW_ONLY`; it creates no canonical
goodwill, impairment, profit, ratio or business-quality fact. H-share goodwill
coverage and filing-backed impairment review remain outside this slice. Live
calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.31 — A/H ESG-rating raw acquisition contract (COMPLETE)

The mapping review now covers the documented Sina `stock_esg_rate_sina`
endpoint under a new provider-neutral `ESG_RATINGS` category. The official
AKShare documentation describes a no-argument response containing a mixed A/H
universe with component code, rating agency, rating, rating quarter, marker
and `cn`/`hk` market; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_esg_sina.py)
retrieves the paginated multi-agency response. The provider validates each
row's explicit code and market, filters to the requested A/H listing and
retains every matching agency/quarter row with endpoint and row-count
provenance.

Agency ratings use provider-specific scales and may be letters or numeric
values, while `评级季度` is a provider reporting label. Those fields do not
establish a comparable ESG score, governance-risk judgment or strict-v1
Business Quality assessment. The normalizer therefore emits
`AKSHARE_ESG_RATINGS_RAW_ONLY`, marks `governance_risk_level` as critically
missing and creates no canonical ESG, governance, Business Quality, filing,
financial or valuation fact. Live calls remain opt-in; tests use an injected
client and a frozen fixture. See the [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
for the documented interface and fields.

### Phase 2.32 — SSE margin-detail raw acquisition contract (COMPLETE)

The mapping review now covers the documented SSE
`stock_margin_detail_sse` endpoint under a new provider-neutral
`MARGIN_TRADING` category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_sse.py)
define an exact `date` in `YYYYMMDD` form and a full SSE universe of security
rows with explicit security code, security name, financing balances and
financing/short-sale quantities. The provider supports Shanghai A-share
listing identifiers only, validates every returned code and observation date,
filters to all rows for the requested security and preserves row/count/date
provenance.

The response describes customer financing against a security, not the issuer's
reported financial debt, cash or a settled issuer accounting period. The
normalizer therefore retains the structured evidence, marks `financial_debt`
as critically missing and emits `AKSHARE_MARGIN_TRADING_RAW_ONLY`; it creates
no canonical debt, cash, leverage, margin or valuation fact. SZSE margin
detail, market-level margin summaries and filing-backed interpretation remain
outside this slice. Live calls remain opt-in; tests use an injected client and
a frozen fixture.

### Phase 2.33 — A-share external-guarantee raw acquisition contract (COMPLETE)

The mapping review now covers the documented CNINFO
`stock_cg_guarantee_cninfo` endpoint under a new provider-neutral
`EXTERNAL_GUARANTEES` category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_guarantee.py)
define a board/universe `symbol` plus `start_date` and `end_date` in
`YYYYMMDD` form; the documented defaults are `全部`, `20180630` and
`20210927`. The provider calls the documented `symbol="全部"` universe,
requires an explicit A-share code on every returned row, filters to the
requested listing and retains all matching rows with date-range, scope and
row-count provenance.

The response exposes announcement-statistics interval, guarantee count and
amount, parent-company equity and a published guarantee-to-net-assets ratio.
The amount and equity are documented in 万元, but the date-range aggregate
does not settle guarantee purpose, legal status, canonical period/entity scope
or whether the amount is a quasi-debt obligation. The normalizer therefore
retains raw evidence, emits `AKSHARE_EXTERNAL_GUARANTEES_RAW_ONLY`, marks
`material_quasi_debt`, `major_illegal_guarantee` and `governance_risk_level` as
critically missing and creates no canonical guarantee, debt, governance or
ratio fact. H-share coverage and filing-backed illegal-guarantee/governance
review remain outside this slice. Live calls remain opt-in; tests use an
injected client and a frozen fixture.

### Phase 2.34 — A-share individual ownership-pledge detail raw acquisition contract (COMPLETE)

The mapping review now covers the documented Eastmoney
`stock_gpzy_individual_pledge_ratio_detail_em` endpoint under the existing
`OWNERSHIP_PLEDGE` category. It accepts a six-digit A-share `symbol` and
returns symbol-scoped historical important-shareholder pledge rows with
explicit listing code, holder/institution, quantities/ratios, prices,
announcement/start/end dates and status. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define the documented interface and its `SECURITY_CODE` filter.

The provider selects this endpoint only for the explicit request
`view=individual_pledge_detail`, passes the requested code, validates explicit
listing identity and any populated event dates, and retains every row with
listing-scoped provenance. The documented quantities, ratios, prices and
status do not establish a fully diluted share count, settled pledged
cash/debt-equivalent amount, beneficial control or governance judgment. The
normalizer therefore retains raw evidence, emits
`AKSHARE_INDIVIDUAL_PLEDGE_DETAIL_RAW_ONLY`, marks
`governance_risk_level` critically missing and creates no canonical fact.
H-share coverage and filing-backed pledge interpretation remain unresolved.
Live calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.35 — A-share company-litigation raw acquisition contract (COMPLETE)

The mapping review now covers the documented CNINFO
`stock_cg_lawsuit_cninfo` endpoint under a new provider-neutral `LITIGATION`
category. The endpoint accepts a board/universe `symbol` plus `start_date` and
`end_date` in `YYYYMMDD` form; the documented defaults are `全部`, `20180630`
and `20210927`. Its response contains explicit A-share code/name,
announcement-statistics interval, lawsuit count and lawsuit amount, with the
amount documented in 万元. The provider calls the documented `symbol="全部"`
universe, requires an explicit code on every row, filters to the requested
listing and retains all matching rows with range, scope and row-count
provenance.

The date-range aggregate does not establish a canonical event or statement
period, legal status, accounting entity/scope, or whether a reported amount is
a material expected cash obligation. The normalizer therefore retains the
response as structured evidence, emits `AKSHARE_LITIGATION_RAW_ONLY`, marks
`material_quasi_debt` and `governance_risk_level` as critically missing, and
creates no canonical litigation, quasi-debt, governance or valuation fact.
H-share coverage and filing-backed litigation review remain unresolved. Live
calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.36 — A-share CNINFO equity-mortgage raw acquisition contract (COMPLETE)

The mapping review now covers the current documented CNINFO
`stock_cg_equity_mortgage_cninfo` endpoint under the existing
`OWNERSHIP_PLEDGE` category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
defines a `date` parameter with documented default `20210930`, and the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_equity_mortgage.py)
retrieves the CNINFO thematic-statistics response. Its rows contain explicit
A-share code/name, announcement date, pledgor/pledgee, pledge and release
quantities, percentage fields and an opaque pledge-event description.

The provider selects this endpoint only for the explicit request view
`view=equity_mortgage`, passes the documented date or default, validates every
returned listing code and any populated announcement date, filters the
universe to the requested A-share code and retains every matching row. The
query date is preserved as a request boundary; the multiple announcement
dates and event descriptions do not establish one canonical pledge or
accounting period. The documented quantities and ratios also do not establish
a fully diluted share count, settled pledged cash/debt-equivalent amount,
beneficial control or a governance judgment. The normalizer therefore emits
`AKSHARE_EQUITY_MORTGAGE_RAW_ONLY`, marks `governance_risk_level` as critically
missing and creates no canonical fact. H-share coverage and filing-backed
pledge interpretation remain unresolved. Live calls remain opt-in; tests use
an injected client and a frozen fixture.

### Phase 2.37 — SZSE margin-detail raw acquisition contract (COMPLETE)

The mapping review now covers the documented Shenzhen
`stock_margin_detail_szse` endpoint under the existing `MARGIN_TRADING`
category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
defines an exact `date` in `YYYYMMDD` form and a full SZSE security universe
with explicit security code/name, financing balances and financing/short-sale
quantities. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_szse.py)
passes the requested date to the SZSE report request and returns the published
columns in a tabular response; unlike the SSE detail response, the documented
SZSE rows do not contain a row-level observation date.

The provider supports Shenzhen A-share identifiers, passes the exact
requested date, validates every returned security code, filters the universe
to the requested listing and retains the matching row with endpoint, date and
row-count provenance. The requested date remains the binding observation
boundary in metadata; the adapter does not add a synthetic date field to the
upstream rows.

The response describes customer financing against a security, not the
issuer's reported financial debt, cash or a settled issuer accounting period.
The normalizer therefore retains the structured evidence, marks
`financial_debt` as critically missing and emits
`AKSHARE_MARGIN_TRADING_RAW_ONLY`; it creates no canonical debt, cash,
leverage, margin or valuation fact. Market-level margin summaries and
filing-backed interpretation remain outside this slice. Live
calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.38 — A-share shareholder-count raw acquisition contract (COMPLETE)

The mapping review now covers the documented CNINFO
`stock_hold_num_cninfo` endpoint under the existing
`SHAREHOLDER_HOLDINGS` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) defines an
exact quarter-end `date` in `YYYYMMDD` form, from `20170331` onward, and the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_num_cninfo.py)
returns the full A-share universe with explicit code/name, `变动日期`, current
and prior shareholder counts, count change percentage, current and prior
average holdings and average-holdings change percentage.

The provider selects this endpoint when a `date` parameter is supplied, checks
that the date is a supported exact quarter end and validates every returned
listing code and row date against the request. It filters the full response to
the requested A-share listing and preserves the selected row, requested date,
observation date and upstream/selected row counts as raw provenance. The
existing no-parameter `stock_main_stock_holder` route remains unchanged.

The response's counts, average holdings and change percentages remain raw
structured evidence: they do not establish a canonical shareholder
concentration metric, beneficial-control or governance judgment, or a
company-level diluted-share series. The normalizer emits
`AKSHARE_SHAREHOLDER_COUNTS_RAW_ONLY`, leaves `governance_risk_level`
critically missing and creates no canonical fact. H-share shareholder-count
coverage and filing-backed interpretation remain unresolved. Live calls remain
opt-in; tests use an injected client and a frozen fixture.

### Phase 2.39 — BSE margin-detail raw acquisition contract (COMPLETE)

The mapping review now covers the current documented Beijing Stock Exchange
`stock_margin_detail_bse` endpoint under the existing `MARGIN_TRADING`
category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
defines an exact `date` in `YYYYMMDD` form and a full BSE security universe
with explicit security code/name, financing balances and financing/short-sale
quantities. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_bse.py)
passes the requested date to the BSE detail request, paginates the published
response and returns the documented columns.

The provider supports Beijing A-share identifiers, passes the exact requested
date, validates every returned security code, filters the universe to the
requested listing and retains the matching row with endpoint, request-date and
row-count provenance. The documented BSE rows do not contain a row-level
observation date, so the request date is preserved as the binding observation
boundary in metadata rather than added to the opaque payload.

The response describes customer financing against a security, not the issuer's
reported financial debt, cash or a settled issuer accounting period. The
normalizer therefore retains the structured evidence, marks `financial_debt`
as critically missing and emits `AKSHARE_MARGIN_TRADING_RAW_ONLY`; it creates
no canonical debt, cash, leverage, margin or valuation fact. Market-level
margin summaries and filing-backed interpretation remain unresolved. Live
calls remain opt-in; tests use an injected client and a frozen fixture.

### Phase 2.40 — A/H HSGT individual-holdings raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare Eastmoney
`stock_hsgt_individual_em` endpoint under the existing
`SHAREHOLDER_HOLDINGS` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) defines a
symbol input supporting A-share and H-share listings and publishes dated
holdings, closing price, holding quantity, holding market value, holding-ratio
and change fields. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
dispatches six-digit symbols to the A-share response and five-digit symbols to
the H-share response; it removes the row-level security identity from the
published output, so the request scope is the retained entity boundary.

The provider selects this endpoint only for the explicit request
`view=hsgt_individual`, passes the canonical six- or five-digit listing code,
validates each row's holding date and any optional returned identity, and
retains the complete symbol-scoped response with listing and row-count
provenance. The data is an investor north-/southbound holding snapshot rather
than a complete beneficial-ownership record or company share-capital series.
Its quantities, market values, ratios and change fields therefore do not
establish beneficial control, governance severity, shareholder concentration,
issuer buyback/issuance cash or a fully diluted share count.

The normalizer emits `AKSHARE_HSGT_INDIVIDUAL_HOLDINGS_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no canonical
ownership, concentration, share-count, dilution, buyback, issuance, return or
valuation fact. The documented dataset is bounded by its published coverage
and its A/H field conventions are not collapsed into one canonical metric.
Live calls remain opt-in; tests use injected clients and frozen A/H fixtures.

### Phase 2.41 — A-share actual-controller holding-change raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare CNINFO
`stock_hold_control_cninfo` endpoint under the existing
`SHAREHOLDER_HOLDINGS` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
define an A-share full-universe response selected by `symbol`, with control
scopes `单独控制`, `实际控制人`, `一致行动人`, `家族控制` and `全部`. The
published fields are security identity, `变动日期`, actual/direct controller
names, `控股数量`, `控股比例` and `控制类型`.

The provider selects this endpoint only for the explicit request
`view=control_changes`, defaults to the documented `symbol=全部` universe (or
passes the requested `control_type`), validates every upstream code and change
date, filters the universe to the requested A-share listing and retains the
control scope and row-count provenance. The normalizer emits
`AKSHARE_CONTROL_HOLDINGS_RAW_ONLY`, leaves `governance_risk_level` critically
missing and creates no canonical ownership, control, concentration,
share-count, dilution or valuation fact. Filing-backed legal and point-in-time
interpretation remains a later concern. Live calls remain opt-in; tests use an
injected client and a frozen fixture with cache replay and invalid-scope/
response-validation coverage.

### Phase 2.42 — A-share management-holding raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare Eastmoney
`stock_hold_management_detail_em` endpoint under the existing
`INSIDER_SHARE_CHANGES` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
define a no-argument full management/related-person holding-change universe.
Its published fields are `日期`, `代码`, `名称`, `变动人`, `变动股数`, `成交均价`,
`变动金额`, `变动原因`, `变动比例`, `变动后持股数`, `持股种类`,
`董监高人员姓名`, `职务`, `变动人与董监高的关系`, `开始时持有` and
`结束后持有`.

The provider selects this endpoint only for the explicit request
`view=management_detail`, passes no upstream arguments, validates every
returned listing code and `日期`, filters the full response to the requested
A-share listing and retains endpoint/view and row-count provenance. The
normalizer emits `AKSHARE_MANAGEMENT_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
dilution, buyback, issuance, ownership, return or valuation fact. Live calls
remain opt-in; tests use an injected client and a frozen fixture with cache
replay, invalid-parameter, response-validation and replay-scope coverage.

### Phase 2.43 — A-share individual-info raw share snapshot (COMPLETE)

The mapping review now covers the current documented Eastmoney
[`stock_individual_info_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_info_em.py).
It accepts a six-digit A-share `symbol` and returns an `item/value` snapshot
with `股票代码`, `股票简称`, `总股本`, `流通股`, `总市值`, `流通市值`, `行业`,
`上市时间` and `最新`. The provider selects it only for the explicit
`SHARE_CAPITAL` request `view=individual_info`, passes the six-digit code,
validates the returned code and any populated listing date, and retains the
complete response with listing/view/snapshot provenance.

The documented snapshot does not establish a canonical reporting period,
amount unit/scaling or fully diluted economic-share scope. The normalizer
therefore emits `AKSHARE_INDIVIDUAL_INFO_RAW_ONLY`, marks
`normalized_diluted_economic_shares` as critically missing and creates no
canonical share, market-cap or valuation fact. Live calls remain opt-in; tests
use an injected client and a frozen fixture with cache replay, invalid-
parameter, response-validation and replay-scope coverage.

### Phase 2.44 — A-share individual-fund-flow raw acquisition contract (COMPLETE)

The mapping review now covers the current documented AKShare Eastmoney
[`stock_individual_fund_flow`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_fund_em.py).
It accepts a six-digit A-share `stock` code and a `market` selector of `sh`,
`sz` or `bj`, and returns approximately 100 recent trading-day rows with the
documented date, close-price, return, net-amount and net-percentage columns.
The provider derives the market selector from the requested A-share identity,
passes both documented arguments, validates optional row identity plus exact
observation dates, and records the observed range and listing-scoped
provenance.

The daily investor-flow aggregates and close-price context do not establish
issuer operating cash flow, an accounting period, a canonical liquidity metric
or a valuation fact. The normalizer therefore retains the complete response as
raw evidence, emits `AKSHARE_INDIVIDUAL_FUND_FLOW_RAW_ONLY` and creates no
canonical fact. Live calls remain opt-in; tests use an injected client and a
frozen fixture with cache replay, invalid-parameter, response-validation and
replay-scope coverage.

### Phase 2.45 — A-share top-ten-shareholder raw acquisition contract (COMPLETE)

The mapping review now covers the current Eastmoney
[`stock_gdfx_top_10_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py).
It accepts a market-prefixed A-share `symbol` and an exact quarter-end `date`
such as `20240930`, returning the documented top-ten rows with rank, holder,
share type, holding quantity, total-share ratio and change fields.

The provider selects this boundary only with the explicit
`SHAREHOLDER_HOLDINGS` request `view=top_10`, validates the quarter-end report
date plus rank/holder identity, preserves the request date and symbol scope and
retains the provider's raw row fields without inventing a row-level code or
filing date. The normalizer emits
`AKSHARE_TOP_10_SHAREHOLDERS_RAW_ONLY`, leaves `governance_risk_level`
critically missing and creates no beneficial-control, concentration, share,
dilution or valuation fact. Live calls remain opt-in; tests use an injected
client and a frozen fixture with cache replay, invalid-parameter,
response-validation and replay-scope coverage.

### Phase 2.46 — A-share top-ten-tradable-shareholder raw acquisition contract (COMPLETE)

The mapping review now covers the current Eastmoney
[`stock_gdfx_free_top_10_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py).
It accepts a market-prefixed A-share `symbol` and an exact quarter-end `date`
such as `20240930`, returning the documented top-ten-tradable rows with rank,
holder, holder type, share type, holding quantity, float-share ratio and change
fields.

The provider selects this boundary only with the explicit
`SHAREHOLDER_HOLDINGS` request `view=free_top_10`, validates the quarter-end
date plus rank/holder identity, preserves the request date and symbol scope and
retains the provider's raw row fields without inventing a row-level listing
code or filing date. The normalizer emits
`AKSHARE_FREE_TOP_10_SHAREHOLDERS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no beneficial-control,
concentration, share, dilution or valuation fact. Live calls remain opt-in;
tests use an injected client and a frozen fixture with cache replay,
invalid-parameter, response-validation and replay-scope coverage.

### Phase 2.47 — A-share top-ten-tradable-shareholder detail raw acquisition contract (COMPLETE)

The mapping review now covers the current Eastmoney
[`stock_gdfx_free_holding_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py).
It accepts an exact quarter-end `date` such as `20240930` and returns the
documented full-universe top-ten-tradable-holder detail rows with listing code,
holder identity/type, report period, holding quantity/change, float-market value
and announcement date fields.

The provider selects this boundary only with the explicit
`SHAREHOLDER_HOLDINGS` request `view=free_holding_detail`, passes the upstream
`date`, validates every returned listing code and holder plus the exact report
period and optional announcement date, and filters the universe to the
requested A-share listing. It preserves the raw report-period holding detail
without treating announcement dates as filing contents or canonical ownership,
concentration, share or dilution facts. The normalizer emits
`AKSHARE_FREE_HOLDING_DETAIL_RAW_ONLY`, leaves `governance_risk_level`
critically missing and creates no canonical fact. Live calls remain opt-in;
tests use an injected client and a frozen fixture with cache replay,
invalid-parameter, response-validation and replay-scope coverage.

### Phase 2.48 — A-share Dragon-Tiger market-activity raw acquisition contract (COMPLETE)

The mapping review now covers the current Eastmoney
[`stock_lhb_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py).
It accepts explicit inclusive `start_date` and `end_date` values in `YYYYMMDD`
form and returns the documented full-universe listing-day Dragon-Tiger detail
rows: listing identity, activity labels, close/return context, amount/ratio
fields, turnover/float-market-value context, listing reasons and post-listing
return columns.

The provider selects this boundary under the new provider-neutral
`MARKET_ACTIVITY` category for A-share listings only, validates every returned
listing code and `上榜日` against the requested range, and filters the
full-universe response to the requested listing. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_RAW_ONLY`; no canonical market, issuer cash-flow,
shareholder-return, governance or valuation fact is admitted. Post-listing
returns remain forward-looking raw evidence and are never used as as-of facts.
Live calls remain opt-in; tests use an injected client and a frozen fixture with
cache replay, invalid-parameter, response-validation and replay-scope coverage.

### Phase 2.49 — A-share Dragon-Tiger stock-statistic raw acquisition contract (COMPLETE)

The mapping review now covers the current Eastmoney
[`stock_lhb_stock_statistic_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py).
It accepts an explicit statistic window represented by the documented
`symbol` choices `近一月`, `近三月`, `近六月` and `近一年`, and returns the
full-universe per-listing Dragon-Tiger statistics: recent listing date,
listing count, activity amount aggregates, institution-activity aggregates and
trailing return context.

The provider selects this boundary under the existing provider-neutral
`MARKET_ACTIVITY` category only with `view=stock_statistic`, maps the explicit
`period` to the upstream `symbol`, validates every returned listing code and
`最近上榜日`, and filters the full-universe response to the requested A-share
listing. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_STATISTICS_RAW_ONLY`; no issuer cash-flow,
shareholder-return, governance, canonical market or valuation fact is
admitted. The statistic window and trailing returns remain provider context,
not as-of calculation inputs. Live calls remain opt-in; tests use an injected
client and a frozen fixture with cache replay, invalid-parameter,
response-validation and replay-scope coverage.

### Phase 2.50 — A-share Dragon-Tiger institution-statistic raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney
[`stock_lhb_jgstatistic_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py).
It accepts an explicit statistic window represented by the documented `symbol`
choices `近一月`, `近三月`, `近六月` and `近一年`, and returns full-universe
per-listing institution-seat tracking rows with Dragon-Tiger amount/count
fields and trailing return context.

The provider selects this boundary under the existing provider-neutral
`MARKET_ACTIVITY` category only with `view=institution_statistic`, maps the
explicit `period` to the upstream `symbol`, validates every returned listing
code and filters the full-universe response to the requested A-share listing.
The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_STATISTICS_RAW_ONLY`; no issuer
cash-flow, shareholder-return, governance, canonical market or valuation fact
is admitted. The statistic window and trailing returns remain provider
context, not as-of calculation inputs. Live calls remain opt-in; tests use an
injected client and a frozen fixture with cache replay, invalid-parameter,
response-validation and replay-scope coverage.

### Phase 2.51 — A-share five-level bid-ask raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney
[`stock_bid_ask_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ask_bid_em.py).
It accepts a six-digit A-share `symbol` and returns the documented fixed
36-row `item`/`value` response: five ask levels, five bid levels and intraday
quote context.

The provider selects this boundary under the existing provider-neutral
`MARKET_QUOTE` category only with explicit `view=bid_ask` for Shanghai and
Shenzhen A-share listings. It passes the normalized listing code, validates
the exact item vocabulary and numeric/null values, preserves the full
listing-scoped response and records view/symbol/current-snapshot replay scope.
The normalizer emits `AKSHARE_BID_ASK_RAW_ONLY`; the order-book and quote
context do not become canonical current-price, liquidity or valuation facts
because the response has no stable observation timestamp. Live calls remain
opt-in; tests use an injected client and a frozen fixture with cache replay,
invalid-parameter, response-validation and replay-scope coverage.

### Phase 2.52 — A-share intraday-history raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney
[`stock_zh_a_hist_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py).
It accepts a six-digit A-share `symbol`, explicit `start_date` and `end_date`
datetimes, a documented interval of `1`, `5`, `15`, `30` or `60` minutes and
an adjustment choice of empty string, `qfq` or `hfq`. The official response
shape differs for the one-minute interval (`均价`) and the other intervals
(change, amplitude and turnover fields).

The provider selects this endpoint only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=intraday`, passes the normalized
listing code and effective range/interval/adjustment, validates the
period-specific field set, finite numeric values, ascending timestamps and
requested range, and records the complete listing-scoped response plus its
replay scope. The normalizer emits
`AKSHARE_INTRADAY_HISTORY_RAW_ONLY`; minute-bar interval, adjustment mode and
the documented recent-data limitation do not establish the canonical daily
history contract or a valuation input. Live calls remain opt-in; tests use
injected clients and frozen fixtures with cache replay, invalid-parameter,
response-validation and replay-scope coverage.

### Phase 2.53 — A-share pre-market-history raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney
[`stock_zh_a_hist_pre_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py).
It accepts a six-digit A-share `symbol` plus `start_time` and `end_time`
time-of-day bounds, and returns the most recent trading day's minute rows
including pre-market observations. The response contains timestamp, OHLC,
volume, turnover and latest-price fields.

The provider selects this endpoint only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=pre_market`, passes the normalized
listing code and effective time window, validates the exact response shape,
finite numeric values, one trading date, ascending timestamps and requested
time range, and records the complete listing-scoped response plus its replay
scope. The normalizer emits
`AKSHARE_PRE_MARKET_HISTORY_RAW_ONLY`; the latest-day time-of-day snapshot does
not establish the canonical daily history contract or a valuation input. Live
calls remain opt-in; tests use an injected client and a frozen fixture with
cache replay, invalid-parameter, response-validation and replay-scope
coverage.

### Phase 2.54 — A-share Sina minute-history raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Sina
[`stock_zh_a_minute`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py).
It accepts a market-prefixed A-share `symbol`, a documented minute interval of
`1`, `5`, `15`, `30` or `60`, and an adjustment mode of empty string, `qfq` or
`hfq`. The response contains timestamped `day`, OHLC, volume and amount rows
for a recent provider window.

The provider selects this endpoint only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=sina_minute`, derives the
market-prefixed symbol from the requested listing, validates the exact response
shape, finite numeric/null values and strictly ascending timestamps, and
records the complete listing-scoped response plus its interval, adjustment and
recent-window replay scope. The normalizer emits
`AKSHARE_SINA_MINUTE_HISTORY_RAW_ONLY`; the provider-window minute bars do not
establish the canonical daily history contract or a valuation input. Live calls
remain opt-in; tests use an injected client and a frozen fixture with cache
replay, invalid-parameter, response-validation and replay-scope coverage.

### Phase 2.55 — A-share Tencent daily-history acquisition contract (COMPLETE)

The mapping review now covers the distinct Tencent
[`stock_zh_a_hist_tx`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_tx.py).
It accepts a market-prefixed or six-digit A-share `symbol`, `start_date`
defaulting to `19000101`, `end_date` defaulting to `20500101`, and an
adjustment mode of empty string, `qfq` or `hfq`. The response contains dated
OHLC rows plus `volume` in shares, decimal `turnover` and `amount` in yuan.

The provider selects this endpoint only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=tencent_daily`, derives the
market-prefixed symbol, applies and records the effective date/adjustment
scope, validates the exact response shape, finite numeric/null values,
strictly ascending dates and inclusive requested range, and preserves the
complete raw response for replay. Because the response is a dated daily
series, the normalizer maps the existing daily-history extension facts with
`shares` volume and `CNY` amount units; the provider turnover ratio remains
raw evidence and does not introduce a new canonical metric or valuation input.
Live calls remain opt-in; tests use an injected client and a frozen fixture
with cache replay, invalid-parameter, response-validation and replay-scope
coverage.

### Phase 2.56 — A-share Tencent latest-trading-day tick acquisition contract (COMPLETE)

The mapping review now covers the distinct Tencent historical-tick endpoint
documented as
[`stock_zh_a_tick_tx`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current official source as
[`stock_zh_a_tick_tx_js`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_tick_tx.py).
It accepts one market-prefixed A-share `symbol` and returns the latest
available trading day's time-only trade rows. The documented output contains
trade time, price, price change, volume in lots, amount in yuan and a buy/sell
marker; the current source names the amount column `成交金额` while the
documentation table labels it `成交额`.

The provider selects this callable only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=tencent_tick`, derives the
market-prefixed symbol, validates one exact documented/source amount-column
variant, finite numeric/null values, integer volume/amount values, recognized
trade sides and non-decreasing time order, and records the complete
listing-scoped response plus its time-only replay scope. The normalizer emits
`AKSHARE_TENCENT_TICK_RAW_ONLY`; because the response has no trading date and
only represents a latest-day tick snapshot, it creates no canonical daily
history, liquidity or valuation fact. Live calls remain opt-in; tests use an
injected client and a frozen fixture with cache replay, invalid-parameter,
response-validation and replay-scope coverage.

### Phase 2.57 — H-share intraday-history raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney H-share minute-history
endpoint documented as
[`stock_hk_hist_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current official source in
[`stock_hist_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py).
It accepts an unprefixed six-digit H-share `symbol`, an explicit
`start_date`/`end_date` datetime range, a `period` of `1`, `5`, `15`, `30` or
`60`, and an adjustment mode of empty string, `qfq` or `hfq`. Period `1`
returns `时间`, OHLC, `成交量`, `成交额` and `最新价`; the other documented
periods return `时间`, OHLC, change fields, `成交量`, `成交额`, `振幅` and
`换手率`.

The provider selects this callable only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=hk_intraday`, passes the
unprefixed H-share code and effective range/interval/adjustment, validates the
exact period-specific fields, finite numeric/null values, strict timestamp
ordering and inclusive range, and records the listing, symbol, request scope,
schema mode and `shares`/`HKD_per_share`/`HKD` units for replay. The normalizer
emits `AKSHARE_HK_INTRADAY_HISTORY_RAW_ONLY`; recent H-share minute bars remain
raw evidence and do not become canonical daily-history, liquidity or valuation
facts. Live calls remain opt-in; tests use an injected client and frozen
period-specific fixtures with cache replay, invalid-parameter,
response-validation, raw-only and replay-scope coverage.

### Phase 2.58 — A-share chip-distribution raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney chip-distribution endpoint
documented as
[`stock_cyq_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_cyq_em.py).
It accepts an A-share six-digit `symbol` and an adjustment mode of empty string,
`qfq` or `hfq`, and returns the latest approximately 90 trading days using the
exact fields `日期`, `获利比例`, `平均成本`, `90成本-低`, `90成本-高`, `90集中度`,
`70成本-低`, `70成本-高` and `70集中度`.

The provider selects this callable only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=chip_distribution`, passes the
unprefixed A-share code and adjustment mode, validates the exact response shape,
finite numeric/null values, ISO dates in strict ascending order and the maximum
90-row window, and records the listing, symbol, adjustment, row limit and
observed date bounds for replay. The normalizer emits
`AKSHARE_CHIP_DISTRIBUTION_RAW_ONLY`; provider-defined benefit, cost and
concentration values remain raw evidence and create no canonical daily-history,
liquidity, concentration or valuation fact. Live calls remain opt-in; tests use
an injected client and a frozen fixture with cache replay, invalid-parameter,
response-validation, raw-only and replay-scope coverage.

### Phase 2.59 — A-share market-participation desire raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney market-participation-desire
endpoint documented as
[`stock_comment_detail_scrd_desire_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py).
It accepts an A-share six-digit `symbol` and returns the exact fields `交易日期`,
`股票代码`, `参与意愿`, `5日平均参与意愿`, `参与意愿变化` and `5日平均变化`;
the current implementation requests a maximum 30-row window and orders the
response by `交易日期`.

The provider selects this callable only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=participation_desire`, passes the
unprefixed A-share code, validates the exact response shape, listing identity,
finite numeric/null values, strict ascending ISO dates and the maximum 30-row
window, and records the listing, symbol, row limit and observed date bounds for
replay. The normalizer emits
`AKSHARE_MARKET_PARTICIPATION_DESIRE_RAW_ONLY`; provider-defined participation
scores and changes remain raw evidence and create no canonical market,
issuer-cash-flow, shareholder-return, governance or valuation fact. Live calls
remain opt-in; tests use an injected client and a frozen fixture with cache
replay, invalid-parameter, response-validation, raw-only and replay-scope
coverage.

### Phase 2.60 — A-share Eastmoney intraday-trade raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney intraday-trade endpoint
documented as
[`stock_intraday_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_em.py).
It accepts an A-share six-digit `symbol` and returns the latest trading day's
time-only fields `时间`, `成交价`, `手数` and `买卖盘性质`, including pre-market
observations.

The provider selects this callable only under the existing provider-neutral
`MARKET_HISTORY` category with explicit `view=intraday_trades`, passes the
unprefixed A-share code, validates the exact response shape, finite numeric/null
prices, integer/null lot counts, recognized trade sides and non-decreasing
times, and records the listing, symbol, latest-day snapshot, time-only date
binding and observed time bounds for replay. The normalizer emits
`AKSHARE_INTRADAY_TRADES_RAW_ONLY`; without a trading date, provider trade
prices and lot counts remain raw evidence and create no canonical daily-history,
liquidity, order-flow or valuation fact. Live calls remain opt-in; tests use an
injected client and a frozen fixture with cache replay, invalid-parameter,
response-validation, raw-only and replay-scope coverage.

### Phase 2.61 — A-share Eastmoney stock hot-rank raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney stock-popularity endpoint
documented as
[`stock_hot_rank_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py).
It accepts no upstream arguments and returns the current-trading-day top-100
A-share popularity rows with `当前排名`, market-prefixed `代码`, `股票名称`,
`最新价`, `涨跌额` and `涨跌幅`.

The provider selects this callable only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=hot_rank`, validates the exact
field set, A-share listing identity, unique strictly ascending ranks, finite
numeric/null quote fields and the maximum 100-row window, and filters the full
universe to the requested listing while retaining the current-day, retrieval-
only date boundary in response metadata. The normalizer emits
`AKSHARE_HOT_RANK_RAW_ONLY`; popularity ordering and quote context remain raw
evidence and create no canonical market, issuer-cash-flow, shareholder-return,
governance or valuation fact. Live calls remain opt-in; tests use an injected
client and a frozen fixture with cache replay, invalid-parameter,
response-validation, raw-only and replay-scope coverage.

### Phase 2.62 — A+H Eastmoney quote-comparison raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney A+H comparison endpoint
documented as
[`stock_zh_ah_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hsgt_em.py).
It accepts no upstream arguments and returns the full A+H comparison snapshot
with the exact fields `序号`, `名称`, `H股代码`, `最新价-HKD`, `H股-涨跌幅`,
`A股代码`, `最新价-RMB`, `A股-涨跌幅`, `比价` and `溢价`; the documentation
describes the quote as delayed by 15 minutes.

The provider selects this callable only under the existing provider-neutral
`MARKET_QUOTE` category with explicit `view=ah_comparison`, validates the exact
field set, five-/six-digit H/A codes, unique strictly ascending sequence and
finite numeric/null price, change, ratio and premium values, and filters the
full response by the requested A- or H-share code. It records the side-specific
code field, units, delayed current-day snapshot, retrieval-only date binding
and filtered row counts for replay. The normalizer emits
`AKSHARE_AH_COMPARISON_RAW_ONLY`; cross-market values remain raw evidence
because the response has no stable observation timestamp and does not establish
canonical current price, FX, comparison, valuation or calculation facts. Live
calls remain opt-in; tests use an injected client and a frozen fixture with
cache replay, invalid-parameter, response-validation, raw-only and replay-scope
coverage.

### Phase 2.63 — A-share Eastmoney dividend-distribution detail raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney A-share dividend-distribution
detail endpoint documented as
[`stock_fhps_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_fhps_em.py).
It accepts a six-digit A-share `symbol` and returns the exact 19 fields
`报告期`, `业绩披露日期`, distribution and cash-ratio fields, per-share
indicators, `总股本`, and announcement/record/ex-rights/progress dates.

The provider selects this callable only under the existing provider-neutral
`DIVIDENDS` category with explicit `view=event_detail`, passes the unprefixed
A-share code, validates the exact field set, strictly ascending report periods,
valid optional event dates, finite numeric/null values, non-negative integer
share counts and string/null status fields, and records the upstream symbol,
row counts, historical-detail scope and row-date binding for replay. The
normalizer emits `AKSHARE_A_DIVIDEND_DETAIL_RAW_ONLY`; distribution ratios,
event plans, per-share indicators and share-count context remain raw evidence
because they do not establish settled ordinary dividend cash or a canonical
payout denominator. Live calls remain opt-in; tests use an injected client and
a frozen fixture with cache replay, invalid-parameter, response-validation,
raw-only and replay-scope coverage.

### Phase 2.64 — A-share CNINFO IPO-summary raw acquisition contract (COMPLETE)

The mapping review now covers the distinct CNINFO A-share IPO-summary endpoint
documented as
[`stock_ipo_summary_cninfo`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ipo_summary_cninfo.py).
It accepts a six-digit A-share `symbol` and returns the exact fields
`股票代码`, `招股公告日期`, `中签率公告日`, `每股面值`, `总发行数量`,
`发行前每股净资产`, `摊薄发行市盈率`, `募集资金净额`, `上网发行日期`,
`上市日期`, `发行价格`, `发行费用总额`, `发行后每股净资产`,
`上网发行中签率` and `主承销商`.

The provider selects this callable only under the existing provider-neutral
`CORPORATE_ACTIONS` category with explicit `view=ipo_summary`, passes the
unprefixed A-share code, requires one exact symbol-matching row, validates
optional dates, finite numeric/null fields and string/null underwriter text,
and records the view, symbol, row counts, historical scope and row-date
binding for replay. The normalizer emits
`AKSHARE_IPO_SUMMARY_RAW_ONLY`, marks `share_issuance_cash` critically missing
and creates no canonical issuance, dilution or share fact. Live calls remain
opt-in; tests use an injected client and frozen fixture coverage for cache
replay, invalid requests, response validation, raw-only normalization and
replayed-scope validation.

### Phase 2.65 — A-share Eastmoney new-stock-board raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney A-share new-stock-board
endpoint documented as
[`stock_zh_a_new_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_special.py).
It accepts no upstream arguments and returns the exact fields `序号`, `代码`,
`名称`, `最新价`, `涨跌幅`, `涨跌额`, `成交量`, `成交额`, `振幅`, `最高`, `最低`,
`今开`, `昨收`, `量比`, `换手率`, `市盈率-动态` and `市净率`.

The provider selects this callable only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=new_stock`, validates the exact
field set, six-digit A-share identity, unique positive sequence numbers,
finite numeric/null quote fields and non-empty names, and filters the current
trading-day universe to the requested listing. The normalizer emits
`AKSHARE_NEW_STOCKS_RAW_ONLY`; the retrieval-only quote snapshot does not
establish a dated listing, return, valuation, governance or canonical market
fact. Live calls remain opt-in; tests use an injected client and a frozen
fixture with cache replay, invalid-parameter, response-validation, raw-only
and replay-scope coverage.

### Phase 2.66 — A-share Eastmoney individual-notice raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney A-share individual-notice
endpoint documented as
[`stock_individual_notice_report`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py).
It accepts the listing `security`, category `symbol` (default `全部`) and
optional `begin_date`/`end_date` bounds, and returns the exact fields `代码`,
`名称`, `公告标题`, `公告类型`, `公告日期` and `网址`.

The provider selects this callable only under the existing provider-neutral
`DISCLOSURE_NOTICES` category with explicit `view=individual_notice`, maps the
category and optional `YYYYMMDD` request bounds to the official upstream names,
validates the exact six-field response, six-digit requested-listing identity,
non-empty text, valid dates/URLs and inclusive range, and records the upstream
listing scope and replay metadata. The normalizer emits
`AKSHARE_INDIVIDUAL_NOTICES_RAW_ONLY`, marks `accounting_opinion` and
`governance_risk_level` critically missing and creates no filing-derived fact.
Live calls remain opt-in; tests use an injected client and a frozen fixture with
cache replay, invalid-parameter, response-validation, raw-only and
replay-scope coverage.

### Phase 2.67 — A-share Eastmoney market-focus raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney A-share market-focus
endpoint documented as
[`stock_comment_detail_scrd_focus_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py).
It accepts a six-digit `symbol`, requests a 30-row latest trading-day window,
and returns the exact fields `交易日` and `用户关注指数`.

The provider selects this callable only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=focus`, passes the unprefixed
listing code, validates the exact two-field response, strict ascending ISO
dates, finite numeric/null values and the official 30-row maximum, and records
the symbol, latest-window scope and observed date bounds for replay. The
normalizer emits `AKSHARE_MARKET_FOCUS_RAW_ONLY`; provider-defined user-attention
scores remain raw evidence and create no canonical market, issuer-cash-flow,
shareholder-return, governance or valuation fact. Live calls remain opt-in;
tests use an injected client and a frozen fixture with cache replay, invalid-
parameter, response-validation, raw-only and replay-scope coverage.

### Phase 2.68 — A-share Eastmoney institution-participation raw acquisition contract (COMPLETE)

The mapping review now covers the distinct Eastmoney A-share institution-
participation endpoint documented as
[`stock_comment_detail_zlkp_jgcyd_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
and implemented by the current [official source](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py).
It accepts a six-digit `symbol`, retrieves the symbol's historical series and
returns the exact fields `交易日` and `机构参与度`; the implementation publishes
the participation value in percent.

The provider selects this callable only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=institution_participation`, passes
the unprefixed listing code, validates the exact two-field response, strict
ascending ISO dates and finite numeric/null percentage values, and records the
symbol, value unit and observed date bounds for replay. The normalizer emits
`AKSHARE_MARKET_INSTITUTION_PARTICIPATION_RAW_ONLY`; provider-defined
institution-participation percentages remain raw evidence and create no
canonical market, issuer-cash-flow, shareholder-return, governance or valuation
fact. Live calls remain opt-in; tests use an injected client and a frozen
fixture with cache replay, invalid-parameter, response-validation, raw-only and
replay-scope coverage.

### Phase 2.69 — A-share Eastmoney limit-up-pool raw acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zt_pool_em` as the Eastmoney A-share limit-up-pool endpoint;
the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
confirms that it accepts a required `YYYYMMDD` `date` for recent data and
returns the exact 16 fields `序号`, `代码`, `名称`, `涨跌幅`, `最新价`, `成交额`,
`流通市值`, `总市值`, `换手率`, `封板资金`, `首次封板时间`, `最后封板时间`,
`炸板次数`, `涨停统计`, `连板数` and `所属行业`.

The provider selects this callable only under `MARKET_ACTIVITY` with explicit
`view=limit_up_pool`, passes the requested trading date unchanged, validates the
full response before filtering it to the requested A-share listing, and binds
the request date, observation-date interpretation, exact fields, six-digit
codes, strictly ascending rank, `HHMMSS` lock times, `days/ct` statistics and
finite numeric/null values into replay metadata. Empty listing matches remain
valid while preserving upstream and selected row counts.

The normalizer emits `AKSHARE_LIMIT_UP_POOL_RAW_ONLY`; quote, limit-up activity,
provider ranking and market-cap fields remain structured evidence only and do
not establish issuer cash flow, shareholder return, governance, valuation or a
canonical market metric. No calculation, gate, pipeline, CLI or input-loader
contract is changed. Live calls remain opt-in; tests use an injected client and
a frozen fixture with cache replay, invalid-request, response-validation,
raw-only and replay-scope coverage.

### Phase 2.70 — A-share Eastmoney latest stock-hot-rank raw acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hot_rank_latest_em` as the Eastmoney A-share latest-rank
endpoint; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py)
confirms that it accepts a market-prefixed `symbol` and returns the exact
`item`/`value` table for `marketType`, `marketAllCount`, `calcTime`, `innerCode`,
`srcSecurityCode`, `rank`, `rankChange`, `hisRankChange`, `hisRankChange_rank`
and `flag`.

The provider selects this callable only under `MARKET_ACTIVITY` with explicit
`view=hot_rank_latest`, passes the requested market-prefixed A-share symbol,
validates the exact ten-row response, item uniqueness, symbol identity,
`calcTime` timestamp and integer/null values, and binds the upstream symbol,
current-day latest-rank scope, row counts and row-derived observation time into
replay metadata.

The normalizer emits `AKSHARE_HOT_RANK_LATEST_RAW_ONLY`; provider popularity
rank and timing remain structured evidence only and do not establish issuer
cash flow, shareholder return, governance, valuation or a canonical market
metric. No calculation, gate, pipeline, CLI or input-loader contract is
changed. Live calls remain opt-in; tests use an injected client and a frozen
fixture with cache replay, invalid-request, response-validation, raw-only and
replay-scope coverage.

### Phase 2.71 — A-share Xueqiu individual-spot quote acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_individual_spot_xq` as a symbol-scoped Xueqiu A-share quote
endpoint; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_xq.py)
confirms a market-prefixed `symbol`, optional Xueqiu token/timeout arguments
and a two-column `item`/`value` response containing the mapped `现价` and
`时间` items.

The provider selects this callable only under `MARKET_QUOTE` with explicit
`view=xueqiu_spot`, derives and passes the requested market-prefixed A-share
symbol, deliberately excludes credentials and timeout controls from the
provider request/cache identity, validates the documented item allowlist,
unique item/value rows, code identity, finite numeric values and quote
timestamp, and records the symbol-scoped current-quote replay metadata.

The existing canonical quote contract maps only `现价` to `current_price` and
`时间` to `market_quote_timestamp`; all other Xueqiu fields remain opaque raw
evidence. No calculation, gate, pipeline, CLI or input-loader contract is
changed. Live calls remain opt-in; tests use an injected client and a frozen
fixture with cache replay, invalid-request, response-validation, canonical
mapping and replay-scope coverage.

### Phase 2.72 — A-share Xueqiu company-profile raw acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_individual_basic_info_xq` as a symbol-scoped Xueqiu A-share
company-profile endpoint; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_basic_info_xq.py)
confirms a market-prefixed `symbol`, optional Xueqiu token/timeout arguments
and an `item`/`value` profile response.

The provider selects this callable only under `COMPANY_METADATA` with explicit
`view=xueqiu_basic_info`, derives and passes the requested market-prefixed
A-share symbol, deliberately excludes credentials and timeout controls from
the provider request/cache identity, validates the exact two-field response,
documented item allowlist, required profile identifiers, scalar values, the
documented `affiliate_industry` object and finite numeric date/asset/personnel/
issuance fields, and records the symbol-scoped company-profile snapshot for
replay.

The normalizer emits `AKSHARE_XUEQIU_BASIC_INFO_RAW_ONLY`; descriptive,
registration, personnel, control and provider-specific date fields remain raw
evidence and do not become canonical company or listing facts. No calculation,
gate, pipeline, CLI or input-loader contract is changed. Live calls remain
opt-in; tests use an injected client and a frozen fixture with cache replay,
invalid-request, response-validation, raw-only and replay-scope coverage.

### Phase 2.73 — A-share CNINFO company-profile raw acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_profile_cninfo` as a symbol-scoped CNINFO A-share
company-profile endpoint; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_cninfo.py)
passes the six-digit `symbol` as `scode` and returns the documented 26 profile
fields.

The provider selects this callable only under `COMPANY_METADATA` with explicit
`view=cninfo_profile`, passes the unprefixed six-digit A-share code, validates
the exact single-row field set, A-share code identity, scalar/null values and
valid date-or-null profile values, and records the symbol-scoped current company-profile
snapshot for replay.

The normalizer emits `AKSHARE_CNINFO_PROFILE_RAW_ONLY`; descriptive,
registration, contact and provider-specific date fields remain raw evidence
and do not become canonical company or listing facts. No calculation, gate,
pipeline, CLI or input-loader contract is changed. Live calls remain opt-in;
tests use an injected client and a frozen fixture with cache replay,
invalid-request, response-validation, raw-only and replay-scope coverage.

### Phase 2.74 — A-share Tonghuashun main-business-introduction raw acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zyjs_ths` as a symbol-scoped Tonghuashun A-share
main-business-introduction endpoint; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_zyjs_ths.py)
passes the six-digit `symbol` to the upstream operate page and returns the
documented five fields `股票代码`, `主营业务`, `产品类型`, `产品名称` and `经营范围`.

The provider selects this callable only under `COMPANY_METADATA` with explicit
`view=business_intro`, passes the unprefixed six-digit A-share code, validates
the exact single-row field set, A-share code identity and string/null values,
and records the symbol-scoped current business-introduction snapshot for
replay.

The normalizer emits `AKSHARE_BUSINESS_INTRO_RAW_ONLY`; descriptive business,
product and operating-scope text remains raw evidence and does not become
canonical revenue, core-business or Business Quality facts. No calculation,
gate, pipeline, CLI or input-loader contract is changed. Live calls remain
opt-in; tests use an injected client and a frozen fixture with cache replay,
invalid-request, response-validation, raw-only and replay-scope coverage. No
H-share counterpart is added because the selected documented slice is
A-share-only.

### Phase 2.75 — A-share Eastmoney ownership-pledge market-profile raw acquisition contract (COMPLETE)

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gpzy_profile_em` as an A-share Eastmoney market-wide
historical ownership-pledge profile; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
accepts no upstream arguments and returns the exact eight fields `交易日期`,
`A股质押总比例`, `质押公司数量`, `质押笔数`, `质押总股数`, `质押总市值`,
`沪深300指数` and `涨跌幅`. The implementation converts its percent ratio to
a fraction by dividing by 100 before returning the table, so the adapter
preserves that source-returned scale and records it explicitly.

The provider selects this callable only under `OWNERSHIP_PLEDGE` with explicit
`view=market_profile`, passes no upstream arguments, validates the exact row
shape and strictly ascending `交易日期` values, and retains the complete
market-wide response. The requested A-share listing is provenance context only:
the response has no issuer identity, so no listing-row filtering or entity-row
selection is claimed. The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_PROFILE_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical pledge,
governance, cash, debt-equivalent or share fact. No H-share counterpart or
calculation, gate, pipeline, CLI or input-loader contract is added. Live calls
remain opt-in; tests use an injected client and a frozen fixture with cache
replay, invalid-request, strict-response, raw-only and replay-scope coverage.

### Phase 2.76 — A-share Eastmoney goodwill market-profile raw acquisition contract (COMPLETE)

The mapping review now covers the next distinct documented AKShare Eastmoney
goodwill view, `stock_sy_profile_em`, under the existing
`GOODWILL_IMPAIRMENT` category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes a no-argument A-share market overview returning all historical rows;
the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
returns the exact eight fields `报告期`, `商誉`, `商誉减值`, `净资产`,
`商誉占净资产比例`, `商誉减值占净资产比例`, `净利润规模` and
`商誉减值占净利润比例`, with amount columns in yuan and provider ratios.

The provider selects this callable only with explicit `view=market_profile`,
passes no upstream arguments, validates the exact row shape, finite
numeric/null values and strictly ascending report periods, and retains the
complete market-wide response. The requested A-share listing is provenance
context only: the response has no issuer identity, so no row filtering or
entity selection is claimed. The normalizer emits
`AKSHARE_GOODWILL_PROFILE_RAW_ONLY`, marks `goodwill` and `impairment` as
critically missing and creates no canonical accounting, profit, ratio or
business-quality fact. Aggregate values mix annual and interim report periods
and require primary-filing entity, scope and reconciliation review. H-share
goodwill coverage remains outside this slice. Live calls remain opt-in; tests
use an injected client and a frozen fixture with cache replay, invalid-request,
strict-response, raw-only and replay-scope coverage.

### Phase 2.77 — A-share Eastmoney goodwill-impairment forecast raw acquisition contract (COMPLETE)

The mapping review now covers the next distinct documented AKShare Eastmoney
goodwill view, `stock_sy_yq_em`, under the existing
`GOODWILL_IMPAIRMENT` category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes a required report-date `date` and the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
filters `REPORT_DATE` before returning the exact 14 fields `序号`, `股票代码`,
`股票简称`, `业绩变动原因`, `最新商誉报告期`, `最新一期商誉`, `上年商誉`,
`预计净利润-下限`, `预计净利润-上限`, `业绩变动幅度-下限`,
`业绩变动幅度-上限`, `上年度同期净利润`, `公告日期` and `交易市场`.
The documented amount fields are primarily yuan and the change-range fields
are percent values; both remain provider-reported raw context.

The provider selects this callable only with explicit
`view=impairment_forecast`, passes the validated `date=YYYYMMDD`, validates
the complete universe's exact schema, positive ascending sequence, nullable
dates/numbers and text fields, then filters to the requested A-share code.
Replay metadata distinguishes the request-period filter from the separate
`最新商誉报告期` field and records the market-wide upstream scope plus
provider row filtering. The normalizer emits
`AKSHARE_GOODWILL_FORECAST_RAW_ONLY`, marks `goodwill` and `impairment` as
critically missing and creates no canonical forecast, profit, accounting,
ratio or Business Quality fact. Provider expectations and goodwill context
still require primary-filing entity, period and reconciliation review; H-share
goodwill coverage remains outside this slice. Live calls remain opt-in; tests
use an injected client and a frozen fixture with cache replay, invalid-request,
strict-response, raw-only and replay-scope coverage.

### Phase 2.78 — A-share Sina intraday-trade raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Sina
`stock_intraday_sina` endpoint under the existing `MARKET_HISTORY` category.
The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
defines a market-prefixed `symbol` and required `date` in `YYYYMMDD` form; the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_sina.py)
returns the exact seven fields `symbol`, `name`, `ticktime`, `price`, `volume`,
`prev_price` and `kind` for large intraday orders on the requested trading day.
The documented kind examples are `U`, `D` and `E`.

The provider selects this callable only with explicit `view=intraday_sina`,
derives the lower-case market-prefixed symbol from the requested A-share
listing, passes the validated date unchanged, and rejects H-share requests or
extra parameters. It validates the exact response shape, requested symbol,
non-empty names, `HH:MM:SS` times in non-decreasing order, recognized kind
values and finite numeric/null price/volume fields with integer/null volume.
Replay metadata binds the requested date to the listing-scoped response while
recording that the rows themselves expose only time-of-day observations.

The normalizer emits `AKSHARE_SINA_INTRADAY_RAW_ONLY`, marks `market_history`
as critically missing and creates no canonical daily-history, liquidity,
order-flow or valuation fact: even with a requested date, the row schema does
not carry a row-level trading date or a supported canonical mapping. Live calls
remain opt-in; tests use an injected client and a frozen fixture with cache
replay, invalid-request, exact-schema, response-validation, raw-only and
replay-scope coverage. No calculation, gate, pipeline, CLI or input-loader
contract changes.

### Phase 2.79 — A-share Eastmoney goodwill-detail raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_sy_em` endpoint under the existing `GOODWILL_IMPAIRMENT` category. The
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
define a required `date=YYYYMMDD` report-date filter and the exact ten fields
`序号`, `股票代码`, `股票简称`, `商誉`, `商誉占净资产比例`, `净利润`,
`净利润同比`, `上年商誉`, `公告日期` and `交易市场`. Amounts are primarily
in yuan and ratios remain provider-reported values.

The provider selects this callable only with explicit
`view=goodwill_detail`, supports A-share listings only, passes the validated
date unchanged, validates the complete market-wide response before selecting
the requested listing, and records request-period, provider-filter, sequence,
unit and exact-field replay metadata. It rejects missing or unexpected fields,
non-positive/non-ascending sequence values, invalid populated dates, non-finite
or non-numeric numeric values and invalid text values. No matching listing is
retained as an empty raw snapshot.

The normalizer emits `AKSHARE_GOODWILL_DETAIL_RAW_ONLY`, marks `goodwill` and
`impairment` as critically missing and creates no canonical accounting, profit,
ratio or Business Quality fact: aggregator amounts, ratios, profit context and
announcement metadata require primary-filing entity, accounting scope and
reconciliation review. H-share goodwill coverage remains outside this slice.
Live calls remain opt-in; tests use an injected client and a frozen fixture with
cache replay, invalid-request, exact-schema, response-validation, raw-only and
replay-scope coverage. No calculation, gate, pipeline, CLI or input-loader
contract changes.

### Phase 2.80 — A-share Eastmoney market-wide notice raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_notice_report` endpoint under the existing `DISCLOSURE_NOTICES` category.
The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py)
define the category choices for `symbol`, a required `date=YYYYMMDD` and the
exact six fields `代码`, `名称`, `公告标题`, `公告类型`, `公告日期` and `网址`.

The provider selects this callable only with explicit `view=market_notice`,
supports A-share listings only, passes the selected category and validated date
to the upstream function, validates the complete market-wide response before
selecting the requested listing, and records the request date, row date,
provider-filter and market-universe scope for replay. It rejects missing or
unexpected fields, non-six-digit codes, blank text, invalid URLs and any row
whose `公告日期` does not match the requested date. An empty listing selection
is retained as an explicit empty raw snapshot.

The normalizer emits `AKSHARE_MARKET_NOTICES_RAW_ONLY`, marks
`accounting_opinion` and `governance_risk_level` as critically missing and
creates no filing-content, accounting or governance fact: date-bound notice
metadata identifies announcement candidates but does not establish their
contents, audit language or governance severity. H-share notice coverage
remains outside this slice. Live calls remain opt-in; tests use an injected
client and a frozen fixture with cache replay, invalid-request, exact-schema,
response-validation, raw-only and replay-scope coverage. No calculation, gate,
pipeline, CLI or input-loader contract changes.

### Phase 2.81 — A-share Eastmoney shareholder-meeting raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_gddh_em` endpoint under the existing `DISCLOSURE_NOTICES` category. The
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gddh_em.py)
define a no-argument current-published-data call and the exact twelve fields
`代码`, `简称`, `股东大会名称`, `召开开始日`, `股权登记日`, `现场登记日`,
`网络投票时间-开始日`, `网络投票时间-结束日`, `决议公告日`, `公告日`,
`序列号` and `提案`.

The provider selects this callable only with explicit
`view=shareholder_meeting`, supports A-share listings only, validates the
complete market-wide response before selecting the requested listing, retains
all matching rows and records field-order, event-date, provider-filter and
selected/upstream-count metadata for replay. Nullable dates and proposal text
are preserved, and an empty listing selection is retained as an explicit raw
snapshot. No report-period or corporate-action date is inferred.

The normalizer emits `AKSHARE_SHAREHOLDER_MEETINGS_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no canonical fact:
meeting dates, proposals and announcement context do not establish a
filing-backed governance judgment or corporate-action interpretation. H-share
meeting coverage remains outside this slice. Live calls remain opt-in; tests use
an injected client and a frozen fixture with cache replay, invalid-request,
exact-schema, response-validation, raw-only and replay-scope coverage. No
calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.82 — H-share Eastmoney latest stock-hot-rank raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_hk_hot_rank_latest_em` endpoint under the existing `MARKET_ACTIVITY`
category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_hot_rank_em.py)
define a symbol-scoped H-share latest-rank call using an unprefixed five-digit
`symbol`, `marketType=000003` and the exact ten `item`/`value` items
`marketType`, `marketAllCount`, `calcTime`, `innerCode`, `srcSecurityCode`,
`rank`, `rankChange`, `hisRankChange`, `hisRankChange_rank` and `flag`.

The provider selects this callable only with explicit `view=hot_rank_latest`,
passes the requested H-share code such as `00700`, validates the exact response
shape, item uniqueness, H-share identity, `calcTime` and integer/null values,
and records the endpoint, symbol format, provider market type, current-day
latest-rank scope, row counts and row-derived observation time for replay. The
normalizer emits `AKSHARE_HK_HOT_RANK_LATEST_RAW_ONLY` and creates no canonical
fact: popularity rank and provider timing remain raw evidence only. H-share
latest-rank response handling stays outside calculations, gates, pipeline, CLI
and input-loader contracts. Live calls remain opt-in; tests use the official-doc
fixture with cache replay, market-specific request/response validation,
raw-only normalization and replay-scope coverage.

### Phase 2.83 — A-share Eastmoney limit-down-pool raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_zt_pool_dtgc_em` endpoint under the existing `MARKET_ACTIVITY` category.
The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
define a recent-data A-share limit-down-pool call with required `date=YYYYMMDD`
and the exact fields `序号`, `代码`, `名称`, `涨跌幅`, `最新价`, `成交额`,
`流通市值`, `总市值`, `动态市盈率`, `换手率`, `封单资金`, `最后封板时间`,
`板上成交额`, `连续跌停`, `开板次数` and `所属行业`.

The provider selects this callable only with explicit `view=limit_down_pool`,
passes the requested date unchanged, validates the complete upstream universe
before filtering by six-digit A-share code, and records the endpoint, source
URI, requested/observed dates, row counts, provider filtering, rank field and
strict ordering for cache replay. Validation rejects missing or extra fields,
invalid codes, duplicate codes or ranks, non-ascending ranks, empty text,
invalid `HHMMSS` lock times, non-finite values and non-integer activity
counters. The checked-in fixture is a frozen real response snapshot for
20260910.

The normalizer emits `AKSHARE_LIMIT_DOWN_POOL_RAW_ONLY` and creates no
canonical fact: quote, limit-down activity, provider ranking and market-cap
fields remain raw evidence and do not establish issuer cash flow, shareholder
return, governance, valuation or a canonical market metric. Live calls remain
opt-in; tests cover explicit request validation, exact response schema,
listing filtering including an empty selection, raw-only normalization,
cache/raw replay and replay-scope metadata. No calculation, gate, pipeline,
CLI or input-loader contract changes.

### Phase 2.84 — A-share Eastmoney shareholder-count-detail raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_zh_a_gdhs_detail_em` endpoint under the existing
`SHAREHOLDER_HOLDINGS` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdhs.py)
define a six-digit A-share `symbol`, the `RPT_HOLDERNUM_DET` report and the
provider-neutral `view=holder_count_detail` selector. The adapter freezes the
15-field response schema, including cut-off/announcement date semantics,
integer count/share-base fields, provider-defined percent/value fields, code
and name identity, and ascending row order by `股东户数统计截止日`. The
upstream request is frozen to `reportName=RPT_HOLDERNUM_DET`,
`sortColumns=END_DATE`, descending source order with adapter-side ascending
output, `pageSize=500` pagination, `quoteColumns=f2,f3`, `source=WEB`,
`client=WEB` and the exact `SECURITY_CODE="{symbol}"` filter. Percent fields,
integer holder/share-base fields and provider-reported raw value scales remain
explicitly distinct; no currency conversion is inferred.

The request passes only the upstream `symbol`, relies on Eastmoney's listing
filter and records upstream scope, view, row counts and row-derived date range.
Validation rejects missing/extra/reordered fields, identity mismatches,
invalid dates, non-decreasing-order violations, wrong numeric types,
non-finite values and invalid non-negative ranges. The checked-in fixture is a
real 61-row official response snapshot for `600000` covering
`2013-03-07` through `2026-06-30`. The normalizer emits
`AKSHARE_SHAREHOLDER_COUNT_DETAIL_RAW_ONLY` and creates no canonical fact;
holder counts, capital-change context and market-value fields do not establish
concentration, governance, valuation or a diluted-share series. Tests cover
positive fetch, request/field/type/range/date failures, raw-only normalization,
cache replay and replay-scope rejection. No calculation, gate, pipeline, CLI or
input-loader contract changes.

### Phase 2.85 — A-share CNINFO management-holding-detail raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_hold_management_detail_cninfo` endpoint under the existing
`INSIDER_SHARE_CHANGES` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
define `symbol` choices `增持` and `减持`, a CNINFO `p_sysapi1030` request and a
rolling near-one-year full universe. The adapter freezes the provider-neutral
`view=cninfo_management_detail` plus explicit `direction` contract, maps
direction to upstream `symbol`, validates the exact 16-field output order,
six-digit codes, dates, finite numeric/null values and non-negative holdings,
price and market-value ranges, and filters the universe to the requested
A-share listing. Direction, rolling-window scope, units, source field order,
row counts and observed cut-off-date bounds are retained for cache replay. The
checked-in fixture contains eight rows copied from an official `增持` response,
including selected and non-selected codes.

The normalizer emits `AKSHARE_CNINFO_MANAGEMENT_HOLDINGS_RAW_ONLY` and creates
no canonical fact: management person/role/relationship, transaction quantity,
price, value, percentage and reason/source fields remain raw evidence and do not
establish a diluted-share series, settled transaction cash or governance
judgment. Tests cover positive fetch and filtering, explicit view/direction and
market/parameter rejection, exact field order, type/date/range response
failures, raw-only normalization, cache replay and replay-scope rejection. No
calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.86 — H-share Eastmoney historical stock-hot-rank raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_hk_hot_rank_detail_em` endpoint under the existing `MARKET_ACTIVITY`
category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_hot_rank_em.py)
define an explicit H-share historical-rank call with an unprefixed five-digit
`symbol`, provider `marketType=000003` and the exact output fields `时间`, `排名`
and `证券代码`.

The provider selects this callable only with explicit
`view=hk_hot_rank_detail`, supports H-share listings only, passes the requested
five-digit symbol, validates the complete symbol-scoped response before retaining
all rows and records the upstream symbol, market type, source field order,
row counts, strict date ordering and observed date bounds for cache replay. It
rejects missing, extra or reordered fields, invalid dates, duplicate or
descending dates, wrong H-share identity and non-positive/non-integer ranks.
The checked-in official response fixture for `00700` contains 120 rows covering
`2026-05-15` through `2026-09-11`; no universe-level selected/non-selected row
filter is applicable because the upstream request is already symbol-scoped.

The normalizer emits `AKSHARE_HK_HOT_RANK_DETAIL_RAW_ONLY` and creates no
canonical fact: date-bound popularity rank and provider security identity remain
raw evidence only and do not establish issuer cash flow, shareholder return,
governance, valuation or a canonical market metric. Tests cover explicit request
and market validation, exact response shape, date/identity/rank failures,
raw-only normalization, cache replay and replay-scope rejection. No calculation,
gate, pipeline, CLI or input-loader contract changes.

### Phase 2.87 — A-share Eastmoney A+B quote-comparison raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_zh_ab_comparison_em` endpoint under the existing `MARKET_QUOTE`
category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
define a no-argument A/B comparison universe with the exact output fields
`序号`, `B股代码`, `B股名称`, `最新价B`, `涨跌幅B`, `A股代码`, `A股名称`,
`最新价A`, `涨跌幅A` and `比价`; the implementation divides the published
quote/change/ratio values by 100 before returning the table.

The provider selects this callable only with explicit `view=ab_comparison`,
supports A-share listings only, validates the complete universe and official
field order before filtering by the requested A-share code, and records the
retrieval-only current-trading-day scope, field order, provider-reported
per-share values, percent/ratio units and row counts for cache replay. The
checked-in fixture preserves three official documentation sample rows with
one selected and two non-selected A-share codes. The endpoint does not
document the B-share currency, so no currency is invented.

The normalizer emits `AKSHARE_AB_COMPARISON_RAW_ONLY` and creates no canonical
fact: cross-share-class prices, changes and ratio remain raw evidence and do
not establish current price, currency, comparison, valuation or calculation
inputs. Tests cover explicit request and market/parameter validation, complete
response validation before filtering, raw-only normalization, cache replay and
replay-scope rejection. No calculation, gate, pipeline, CLI or input-loader
contract changes.

### Phase 2.88 — A-share Eastmoney historical stock-hot-rank raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_hot_rank_detail_em` endpoint under the existing `MARKET_ACTIVITY`
category. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py)
define a symbol-scoped A-share historical-rank call with market-prefixed
`symbol=SZ000665`, `marketType=""` and the exact output fields `时间`, `排名`,
`证券代码`, `新晋粉丝` and `铁杆粉丝` in source order. The official adapter
obtains the rank and follower-rate components from its historical sources and
divides the published percent rates by 100 into fractions.

The provider selects this callable only with explicit
`view=hot_rank_detail`, passes the requested market-prefixed symbol, validates
the complete symbol-scoped payload before retaining it, and records the
documented Eastmoney source URI
`https://guba.eastmoney.com/rank/stock?code=000665`, source field order, rate
units/scaling, row counts and observed date bounds for cache replay. It rejects
missing/extra/reordered fields, invalid or duplicate/descending dates, a
non-matching market-prefixed A-share identity, non-positive/non-integer ranks
and non-finite or out-of-range follower ratios. The checked-in official
snapshot contains 366 rows from `2025-09-11` through `2026-09-11`; because the
upstream request is already listing-scoped, no selected/non-selected universe
filter is applicable.

The normalizer emits `AKSHARE_HOT_RANK_DETAIL_RAW_ONLY` and creates no
canonical fact: date-bound popularity rank and follower ratios remain raw
evidence only and do not establish issuer cash flow, shareholder return,
governance, valuation or a canonical market metric. Tests cover explicit
request and market/parameter validation, complete response validation,
raw-only normalization, cache replay and replay-scope rejection. No
calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.89 — A-share Eastmoney IPO-yield raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_dxsyl_em` endpoint under the existing `CORPORATE_ACTIONS` category with
explicit `view=ipo_yield`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_dxsyl_em.py)
define a no-argument Eastmoney A-share IPO-yield universe at
`https://data.eastmoney.com/xg/xg/dxsyl.html` with the exact 17-field order
`序号`, `股票代码`, `股票简称`, `发行价`, `最新价`, `网上-发行中签率`,
`网上-有效申购股数`, `网上-有效申购户数`, `网上-超额认购倍数`, `网下-配售中签率`,
`网下-有效申购股数`, `网下-有效申购户数`, `网下-配售认购倍数`, `总发行数量`,
`开盘溢价`, `首日涨幅` and `上市日期`.

The provider validates the complete upstream response before filtering to the
requested six-digit A-share code. It preserves the source order, provider
numeric/null values, row-level listing dates, documented percent/household
units, source URI and full/selected row counts in replay metadata. The checked-in
fixture contains three official response rows for `688801`, `301689` and
`301699`, with one selected row and two non-selected rows. The normalizer emits
`AKSHARE_IPO_YIELD_RAW_ONLY`, marks `share_issuance_cash` critically missing
and creates no issuance, dilution, price, return or listing-date fact because
the endpoint does not establish a settled issuance-cash period, unit or
diluted-share scope. Tests cover request/market validation, exact schema and
field order, complete-universe validation before filtering, raw-only
normalization, cache replay and replay-scope rejection. No calculation, gate,
pipeline, CLI or input-loader contract changes.

### Phase 2.90 — A-share Eastmoney block-trade detail raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_dzjy_mrmx` endpoint under the existing `MARKET_ACTIVITY` category with
explicit `view=block_trade_detail`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_dzjy_em.py)
define the A-share full-universe request parameters `symbol="A股"`,
`start_date` and `end_date`, returning the exact 13-field order `序号`, `交易日期`,
`证券代码`, `证券简称`, `涨跌幅`, `收盘价`, `成交价`, `折溢率`, `成交量`, `成交额`,
`成交额/流通市值`, `买方营业部` and `卖方营业部`.

The provider validates every upstream row before filtering by the requested
six-digit A-share code. It enforces the documented date-range binding, exact
field order, six-digit security identity, strictly ascending sequence numbers,
valid observation dates, finite numeric/null values and non-empty security and
brokerage text. It records the Eastmoney source URI, upstream symbol, request
dates, source field order, documented units (`涨跌幅`/`成交额/流通市值` as
percent, `成交量` as shares and `成交额` as CNY), unresolved price/discount
units and full/selected row counts for cache replay. The checked-in fixture
contains three source rows for `2026-09-10`, with two selected trades for
`001335` and one non-selected `001309` trade.

The normalizer emits `AKSHARE_BLOCK_TRADE_RAW_ONLY` and creates no canonical
fact: date-bound trade prices, quantities, amounts, discount/premium and
brokerage context do not establish issuer cash flow, shareholder return,
governance, valuation or a canonical market metric. Tests cover explicit
request and market/parameter validation, complete-universe validation before
filtering, raw-only normalization, cache replay and replay-scope rejection. No
calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.91 — H-share Eastmoney main-board quote raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_hk_main_board_spot_em` endpoint under the existing `MARKET_QUOTE`
category with explicit `view=hk_main_board`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
define a no-argument Eastmoney H-share main-board universe at
`https://quote.eastmoney.com/center/gridlist.html#hk_mainboard` with the exact
12-field order `序号`, `代码`, `名称`, `最新价`, `涨跌额`, `涨跌幅`, `今开`, `最高`,
`最低`, `昨收`, `成交量` and `成交额`. The documented units are HKD per share
for prices/change amount, percent for change, shares for volume and HKD for
turnover.

The provider validates the complete upstream response before filtering to the
requested five-digit H-share code. It enforces the official field order,
strictly ascending positive sequence numbers, unique five-digit identities,
non-empty names and finite numeric/null values, and records the main-board
scope, source URI, units, source field order and full/selected row counts for
cache replay. The checked-in fixture freezes three source-shaped rows with one
selected listing.

The official documentation describes this as a 15-minute-delayed realtime
snapshot and does not provide a stable observation timestamp. The normalizer
therefore emits `AKSHARE_HK_MAIN_BOARD_QUOTE_RAW_ONLY`, marks `current_price`
critically missing and creates no canonical quote fact. Tests cover explicit
request and market/parameter validation, exact schema and field order,
complete-universe validation before filtering, raw-only normalization, cache
replay and replay-scope rejection. No calculation, gate, pipeline, CLI or
input-loader contract changes.

### Phase 2.92 — SSE daily-deal overview raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_sse_deal_daily` endpoint under the existing `MARKET_ACTIVITY` category
with explicit `view=sse_deal_daily` and a required `date=YYYYMMDD`. The [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define the SSE requested-trading-day overview and its final six-field order
`单日情况`, `股票`, `主板A`, `主板B`, `科创板`, `股票回购`. The implementation
also defines the eight metric rows, orders them as `挂牌数`, `市价总值`,
`流通市值`, `成交金额`, `成交量`, `平均市盈率`, `换手率` and `流通换手率`,
and supports dates from `20211227` onward.

The provider validates the complete market-level response before retention,
including exact field order, exact metric order and finite numeric-or-null
values. It passes only the documented date to the no-symbol upstream call and
records the SSE market scope, requested/observation date, field/metric order,
the fact that no numeric units are documented, and non-listing row counts for
cache replay. The checked-in fixture preserves the official documentation
sample, including its explicit null average P/E value.

The normalizer emits `AKSHARE_SSE_DEAL_DAILY_RAW_ONLY` and creates no canonical
fact: exchange-wide aggregate counts, amounts, turnover, valuation and board
breakdowns do not establish a requested listing's quote, issuer cash flow,
shareholder return, governance, valuation or canonical market metric. Tests
cover request/date validation, exact response shape and values, raw-only
normalization, replay-scope rejection and cache replay. No calculation, gate,
pipeline, CLI or input-loader contract changes.

### Phase 2.93 — SSE market-summary raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare `stock_sse_summary`
endpoint under the existing `MARKET_ACTIVITY` category with explicit
`view=sse_summary`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define a no-argument Shanghai Stock Exchange market summary with the eight
metrics `流通股本`, `总市值`, `平均市盈率`, `上市公司`, `上市股票`, `流通市值`,
`报告时间` and `总股本`. The implementation emits the source-shaped field
order `项目`, `股票`, `主板`, `科创板`; the adapter preserves that order and
requires a consistent valid report date in the `报告时间` row.

The provider validates the complete market-level response before retention,
including exact field and metric order, finite numeric-or-null values and the
embedded report-date scope. It passes no arguments to the upstream callable and
records the Shanghai Stock Exchange scope, source field/metric order, absence of
documented numeric units and non-listing row counts for cache replay.

The normalizer emits `AKSHARE_SSE_SUMMARY_RAW_ONLY` and creates no canonical
fact: exchange-wide market/board aggregates do not establish a requested
listing's quote, issuer cash flow, shareholder return, governance, valuation or
canonical market metric. Tests cover explicit request validation, exact response
shape/ordering/types, raw-only normalization, replay-scope rejection and cache
replay. No calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.94 — SZSE market-summary raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_szse_summary` endpoint under the existing `MARKET_ACTIVITY` category
with explicit `view=szse_summary` and a required `date=YYYYMMDD`. The [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define the Shenzhen Stock Exchange securities-category report and its final
five-field order `证券类别`, `数量`, `成交金额`, `总市值` and `流通市值`.
The implementation passes the requested date to the SZSE report request and
converts the numeric columns without filling missing market values.

The provider validates every returned category row before retention, including
exact field order, non-empty unique category labels, the required `股票`
category, non-negative integer security counts and finite non-negative numeric
or null values. It passes only the normalized date to the upstream callable and
records the Shenzhen market scope, request/observation date, returned category
order, source field order, documented `数量`/`成交金额` units, undocumented
market-value units and non-listing row counts for cache replay. The checked-in
fixture preserves the official documentation sample, including null market
values for categories where the source does not report them.

The normalizer emits `AKSHARE_SZSE_SUMMARY_RAW_ONLY` and creates no canonical
fact: exchange-wide security-category counts, transaction amounts and market
values do not establish a requested listing's quote, issuer cash flow,
shareholder return, governance, valuation or canonical market metric. Tests
cover explicit request/date validation, exact fields and ordering, category
and numeric validation, raw-only normalization, replay-scope rejection and
cache replay. No calculation, gate, pipeline, CLI or input-loader contract
changes.

### Phase 2.95 — SZSE area-summary raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare
`stock_szse_area_summary` endpoint under the existing `MARKET_ACTIVITY`
category with explicit `view=szse_area_summary` and required monthly
`date=YYYYMM`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define a Shenzhen Stock Exchange region-ranked report with the source-shaped
base fields `序号`, `地区`, `总交易额`, `占市场`, `股票交易额`, `基金交易额` and
`债券交易额`; the documentation also adds `优先股交易额` and `期权交易额`
from 2025 onward. The adapter accepts either exact documented field order and
retains the requested month as request-bound provenance.

The provider validates the complete area-ranked response before retention,
including positive strictly ascending ranks, unique non-empty region labels,
finite non-negative numeric-or-null values and exact base/extended field
ordering. It passes only the normalized month to the upstream callable and
records the Shenzhen scope, requested/observation month, documented CNY and
percentage units, source field order and non-listing row counts for cache
replay. The checked-in fixture freezes the documented base-column sample, and
tests also exercise the extended 2025 shape.

The normalizer emits `AKSHARE_SZSE_AREA_SUMMARY_RAW_ONLY` and creates no
canonical fact: region-level monthly transaction aggregates do not establish
a requested listing's quote, issuer cash flow, shareholder return, governance,
valuation or canonical market metric. Tests cover explicit request/month
validation, exact base and extended fields/order/types, raw-only normalization,
replay-scope rejection and cache replay. No calculation, gate, pipeline, CLI
or input-loader contract changes.

### Phase 2.96 — SZSE sector-summary raw acquisition contract (COMPLETE)

The mapping review now covers the next distinct documented AKShare
`stock_szse_sector_summary` endpoint under the existing `MARKET_ACTIVITY`
category with explicit `view=szse_sector_summary`, `symbol=当月` or `当年` and
monthly `date=YYYYMM`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define the nine-field Shenzhen industry-trading response and the separate
month/year-to-date tables selected by `symbol`.

The provider validates the complete source field order, requires the source
`合计` row to lead the unique industry order, rejects non-finite or negative
numeric values and preserves the selector, request/observation month,
documented CNY/share/transaction/percentage units and non-listing row counts
for replay. The checked-in fixture freezes three source-shaped industry rows.
The normalizer emits `AKSHARE_SZSE_SECTOR_SUMMARY_RAW_ONLY` and creates no
canonical fact: exchange-wide industry transaction aggregates do not establish
a requested listing's quote, issuer cash flow, shareholder return, governance,
valuation or canonical market metric. Tests cover selector/month validation,
exact response fields/order/types, raw-only normalization, replay-scope
rejection and cache replay. No calculation, gate, pipeline, CLI or input-loader
contract changes.

### Phase 2.97 — A-share Eastmoney industry-board raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_board_industry_name_em` endpoint under the existing `MARKET_ACTIVITY`
category with explicit `view=industry_board`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_industry_em.py)
define a no-argument current snapshot of all A-share industry boards with the
12 source-shaped fields `排名`, `板块名称`, `板块代码`, `最新价`, `涨跌额`,
`涨跌幅`, `总市值`, `换手率`, `上涨家数`, `下跌家数`, `领涨股票` and
`领涨股票-涨跌幅`.

The provider validates the complete source field order, positive ascending
ranks, unique board names/codes, finite numeric-or-null values and documented
percentage units. It records the source board ordering, no-argument request
scope and non-listing row counts for replay. The checked-in fixture freezes
three source-shaped board rows. The normalizer emits
`AKSHARE_INDUSTRY_BOARD_RAW_ONLY` and creates no canonical fact: a current
industry-board snapshot does not establish a requested listing's quote, issuer
cash flow, shareholder return, governance, valuation or canonical market
metric. Tests cover explicit view/A-share validation, exact response
fields/order/types, raw-only normalization, replay-scope rejection and cache
replay. No calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.98 — A-share Eastmoney executive/shareholder-change raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_ggcg_em` endpoint under the existing `INSIDER_SHARE_CHANGES` category
with explicit `view=executive_share_changes` and `direction` values `全部`,
`股东增持` or `股东减持`. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdzjc_em.py)
define a direction-filtered full A-share universe with 16 source-shaped fields
covering security identity, latest quote context, holder, direction,
quantity/ratio fields and start/end/announcement dates.

The provider passes the documented direction selector, validates the complete
source field order, six-digit codes, direction scope, finite numeric/null
values, non-negative holding quantities/ratios and nullable event dates, then
filters the full response to the requested A-share listing. It records the
direction, source field order, documented 万股/% units, undocumented latest-price
unit, event-date bounds, upstream page size and upstream/selected row counts
for replay. The checked-in fixture freezes four source-shaped rows across
Shanghai, Shenzhen and Beijing listings. The normalizer emits
`AKSHARE_EXECUTIVE_SHARE_CHANGES_RAW_ONLY` and creates no canonical fact:
direction-filtered holder changes, quote context and event dates do not
establish a company-level diluted-share series, settled transaction cash,
governance judgment or shareholder-return fact. Tests cover explicit
view/direction/A-share validation, exact response fields/order/types,
direction-filtering, raw-only normalization, replay-scope rejection and cache
replay. No calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 2.99 — A-share Eastmoney management-person raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_hold_management_person_em` endpoint under the existing
`INSIDER_SHARE_CHANGES` category with explicit `view=management_person` and a
non-empty executive `name`. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
define a symbol-and-person-scoped A-share response with the exact 16
source-shaped fields for change date, security/person identity, transaction
quantity/price/amount/reason/ratio, holding type, role/relationship and
beginning/ending holdings.

The provider passes the six-digit A-share `symbol` and requested `name`,
validates the exact source field order, listing/person identity, ISO change
dates, finite numeric/null values and non-negative price/holding fields, then
retains the upstream symbol-and-person scope and observed date bounds for
replay. Numeric units remain explicitly `not_documented` because the official
contract does not settle them. The checked-in fixture freezes four
source-shaped rows across two listings and two people. The normalizer emits
`AKSHARE_MANAGEMENT_PERSON_RAW_ONLY` and creates no canonical share, dilution,
transaction-cash, governance or shareholder-return fact. Tests cover explicit
view/name/A-share validation, exact response fields/order/types, identity and
range failures, raw-only normalization, replay-scope rejection and cache
replay. No calculation, gate, pipeline, CLI or input-loader contract changes.

### Phase 3.00 — A-share Eastmoney Dragon-Tiger institution-daily raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_lhb_jgmmtj_em` endpoint under the existing `MARKET_ACTIVITY` category
with explicit `view=institution_daily` and inclusive `start_date`/
`end_date` parameters. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
define a date-filtered full A-share universe and the exact 16 source-shaped
fields `序号`, `代码`, `名称`, `收盘价`, `涨跌幅`, `买方机构数`, `卖方机构数`,
`机构买入总额`, `机构卖出总额`, `机构买入净额`, `市场总成交额`,
`机构净买额占总成交额比`, `换手率`, `流通市值`, `上榜原因` and `上榜日期`.

The provider validates the complete response before filtering it to the
requested A-share listing. It enforces exact field order, six-digit code
identity, ISO row dates inside the requested range, strictly ascending source
sequence, finite numeric/null values, non-negative price/count/amount/turnover
fields and unique listing/date identities. It records the documented CNY
amount and 亿元 market-value units, marks every other numeric unit
`not_documented`, and preserves full/selected row counts and observed date
bounds for replay. The checked-in fixture freezes three source-shaped rows
across two listings and two dates.

The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_DAILY_RAW_ONLY` and creates no canonical
cash-flow, shareholder-return, governance, valuation or market fact: the
institution counts and aggregate trading context are provider evidence, not
issuer accounting or a canonical market metric. Tests cover explicit
view/date/A-share validation, exact source shape and types, identity/date/
numeric failures, provider filtering, raw-only normalization, replay-scope
rejection and cache replay. No calculation, gate, pipeline, CLI or input-loader
contract changes. This numbered 3.00 increment remains structured acquisition;
the top-level Phase 3 filing/evidence deliverables below are still unimplemented.

### Phase 3.01 — A-share Eastmoney institutional-research statistics raw acquisition contract (COMPLETE)

The mapping review now covers the distinct documented AKShare Eastmoney
`stock_jgdy_tj_em` endpoint under the existing `MARKET_ACTIVITY` category
with explicit `view=institution_research` and a `date=YYYYMMDD` start cutoff.
The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
define a full A-share response with the exact 11 source-shaped fields `序号`,
`代码`, `名称`, `最新价`, `涨跌幅`, `接待机构数量`, `接待方式`, `接待人员`,
`接待地点`, `接待日期` and `公告日期`.

The provider validates the complete response before filtering it to the
requested A-share listing. It enforces exact field order, six-digit code
identity, valid ISO research-visit and announcement dates, the official strict
`公告日期 > date` boundary, strictly ascending source sequence, finite
numeric/null values, integer institution counts, non-negative price/count
fields and unique listing/research-date/announcement-date identities. It
records the documented percentage unit, leaves the price and institution-count
units `not_documented`, and preserves the requested cutoff, both date-field
bounds, source order and full/selected row counts for replay. The checked-in
fixture freezes three source-shaped rows across two listings.

The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_RAW_ONLY` and creates no
canonical cash-flow, shareholder-return, governance, valuation or market fact:
research visits, institution counts and quote context remain provider evidence.
Tests cover explicit view/date/A-share validation, exact response fields/order/
types, identity/date/numeric failures, provider filtering, raw-only
normalization, replay-scope rejection and cache replay. No calculation, gate,
pipeline, CLI or input-loader contract changes. This numbered 3.01 increment
remains structured acquisition; the top-level Phase 3 filing/evidence
deliverables below are still unimplemented.

### Future structured-provider deliverables

```text
src/turtle_value_engine/providers/
  base.py
  models.py
  errors.py
  cache.py
  normalization.py
  akshare.py       # Phase 2.2 market + Phase 2.3–3.01 structured slices
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

Phase 2 remains active for structured-provider coverage. The numbered Phase
3.01 increment is also acquisition-only; the top-level Phase 3 filing/evidence
layer remains unimplemented. Phase 1 remains frozen: changes to formulas,
hard-gate semantics, schemas or `strict-v1` thresholds require a separately
reviewed, versioned change.

Phase 2.94 completes the next documented structured-data boundary by adding
the A-share `stock_szse_summary` Shenzhen Stock Exchange market-summary view.
Its requested-date security-category rows are validated as raw-only evidence;
documented quantity/transaction-amount units and undocumented market-value
units remain explicit replay metadata, and no listing-level or canonical market
fact is inferred.
Phase 2.95 adds the documented A-share `stock_szse_area_summary` Shenzhen Stock
Exchange region-ranked monthly view. Its base and 2025 extended source field
variants are validated with strict rank/region/order checks; CNY and percentage
units remain explicit replay metadata, and no listing-level or canonical market
fact is inferred.
Phase 2.96 adds the documented A-share `stock_szse_sector_summary` Shenzhen
Stock Exchange industry-trading view. Its explicit `当月`/`当年` selector and
monthly source-shaped nine-field response are validated with strict
field/industry/order/type checks; CNY, share, transaction and percentage units
remain explicit replay metadata, and no listing-level or canonical market fact
is inferred.
Phase 2.97 adds the documented A-share Eastmoney
`stock_board_industry_name_em` current industry-board snapshot. Its explicit
`industry_board` view and source-shaped 12-field ranked board response are
validated with strict field/order/identity/type checks; percentage units and
undocumented price/market-value units remain explicit replay metadata, and no
listing-level or canonical market fact is inferred.
Phase 2.98 adds the documented A-share Eastmoney `stock_ggcg_em`
executive/shareholder-change view. Its explicit `executive_share_changes` view
and `全部`/`股东增持`/`股东减持` direction selector are validated against the
16-field full-universe response before provider filtering; documented 万股/%
units, the undocumented latest-price unit, event-date bounds and replay row
counts remain explicit metadata, and no listing-level share, dilution, cash,
governance or shareholder-return fact is inferred.
Phase 2.99 adds the documented A-share Eastmoney
`stock_hold_management_person_em` management-person view under
`INSIDER_SHARE_CHANGES`. Its explicit `management_person` view passes the
six-digit symbol and executive name to the symbol/person-scoped endpoint and
validates the exact 16-field response, identity, dates, numeric ranges and
replay scope. Numeric units remain `not_documented`, and the raw-only
normalizer flag creates no listing-level share, dilution, cash, governance or
shareholder-return fact.
Phase 3.00 adds the documented A-share Eastmoney
`stock_lhb_jgmmtj_em` institution-daily Dragon-Tiger view under
`MARKET_ACTIVITY`. Its explicit `institution_daily` view and inclusive date
range are validated against the 16-field full-universe response before provider
filtering; documented CNY/亿元 monetary units, undocumented quote/count/ratio
units, exact row identity/date/sequence checks and replay scope remain explicit
metadata. The raw-only normalizer flag creates no issuer cash-flow,
shareholder-return, governance, valuation or canonical market fact.
Phase 3.01 adds the documented A-share Eastmoney
`stock_jgdy_tj_em` institutional-research statistics view under
`MARKET_ACTIVITY`. Its explicit `institution_research` view and start
`date=YYYYMMDD` cutoff are validated against the 11-field full-universe
response before provider filtering; the official strict announcement-date
boundary, two date fields, integer institution counts, documented percentage
unit, undocumented price/count units, exact row identity/sequence checks and
replay scope remain explicit metadata. The raw-only normalizer flag creates no
issuer cash-flow, shareholder-return, governance, valuation or canonical market
fact.
Phase 2.75 completes the next documented structured-data boundary by adding
the A-share `stock_gpzy_profile_em` market-wide historical ownership-pledge
view. Its no-argument eight-field response is validated as an ascending raw
date series, preserves the source percent-to-fraction ratio scaling and does
not claim listing-level rows or facts. The milestone continues to keep
share-change, repurchase and rights-issue period, status, unit and
economic-scope questions unresolved, and keeps ownership-pledge holder,
governance and economic-scope questions unresolved. Phase 2.76 adds the
documented A-share `stock_sy_profile_em` goodwill market-profile view under
`GOODWILL_IMPAIRMENT`. Its no-argument eight-field history is strictly ordered
by `报告期`, records CNY/provider-ratio context and remains raw-only because
aggregate annual/interim values do not establish listing accounting scope;
`goodwill` and `impairment` remain critically missing pending primary-filing
reconciliation. The milestone keeps H-share goodwill coverage and issuer-level
accounting interpretation unresolved. Phase 2.77 adds the next documented
A-share `stock_sy_yq_em` goodwill-impairment forecast view under
`GOODWILL_IMPAIRMENT` with explicit `view=impairment_forecast` and a required
`date=YYYYMMDD`. Its exact 14-field date-filtered universe is validated before
listing selection, with positive ascending sequence, nullable dates/numbers,
text checks, documented CNY/percent units and request-period/provider-filter
replay metadata. The
normalizer emits `AKSHARE_GOODWILL_FORECAST_RAW_ONLY`, leaves `goodwill` and
`impairment` critically missing and creates no canonical forecast, profit,
accounting or ratio fact pending primary-filing scope and reconciliation. H-
share goodwill coverage remains unresolved. The A-share
Sina `stock_intraday_sina` response is a requested-date, listing-scoped large-
order snapshot whose exact `symbol`/`name`/`ticktime`/`price`/`volume`/
`prev_price`/`kind` schema is validated with non-decreasing time order and
`U`/`D`/`E` kind codes. Because the rows are time-only even though the request
date is explicit, the normalizer emits `AKSHARE_SINA_INTRADAY_RAW_ONLY`, leaves
`market_history` critically missing and creates no canonical daily-history,
liquidity, order-flow or valuation fact; the requested date, derived symbol,
units and observed time bounds remain part of the replay scope. The A-share
Eastmoney `stock_sy_em` goodwill-detail response is a distinct requested-date,
market-wide universe whose exact ten-field schema, positive ascending sequence,
listing identity, nullable announcement date, numeric/null fields and text
fields are validated before provider filtering. With explicit
`view=goodwill_detail`, the normalizer emits
`AKSHARE_GOODWILL_DETAIL_RAW_ONLY`, leaves `goodwill` and `impairment`
critically missing and creates no canonical accounting, profit, ratio or
Business Quality fact; CNY/provider-ratio units and request-period/provider-
filter scope remain replay metadata pending primary-filing reconciliation. The
A-share
Tencent daily-history response is the dated-series exception among the recent
market-history slices: it maps the existing daily-history extension facts,
preserves volume as `shares` and amount as `CNY`, and retains its market-
prefixed symbol, date range, adjustment and raw turnover ratio as replayable
provider context. The A-share
Tencent latest-trading-day tick response remains raw-only because its
time-only trade rows have no trading date and do not establish canonical daily
history, liquidity or valuation facts; `view=tencent_tick`, the derived
market-prefixed symbol, recognized amount-column variant and time ordering
remain part of its replayable acquisition boundary. The A-share
Sina minute-history response remains raw-only because its recent provider
window, minute interval and adjustment mode do not establish canonical daily
history or a valuation input; `view=sina_minute`, the market-prefixed symbol,
interval and adjustment remain part of its replayable acquisition boundary.
The A-share market-participation-desire response remains raw-only because its
provider-defined participation scores/change fields and latest 30-trading-day
window do not establish a canonical market metric, issuer cash flow,
shareholder return, governance or valuation fact; `view=participation_desire`,
the unprefixed symbol, exact field set, row limit and observed date bounds
remain part of its replayable acquisition boundary.
The A-share Eastmoney intraday-trade response remains raw-only because its
latest-trading-day `时间`, `成交价`, `手数` and `买卖盘性质` rows have no trading
date and do not establish canonical daily history, liquidity, order flow or
valuation facts; `view=intraday_trades`, the unprefixed symbol, exact field set,
time ordering and observed time bounds remain part of its replayable
acquisition boundary.
The H-share intraday-history response remains raw-only because its recent
minute-bar window, period-specific schema, adjustment mode and HKD market
context do not establish canonical daily history or a valuation input;
`view=hk_intraday`, the unprefixed H-share symbol, datetime range, interval,
adjustment and `shares`/`HKD_per_share`/`HKD` units remain part of its replayable
acquisition boundary.
The A-share chip-distribution response remains raw-only because its
provider-defined benefit, cost and concentration fields describe a rolling
latest-90-trading-day window rather than the canonical daily-history contract;
`view=chip_distribution`, the unprefixed A-share symbol, adjustment mode, exact
field set, 90-row limit and observed date bounds remain part of its replayable
acquisition boundary.
The A+H Eastmoney quote-comparison response remains raw-only because its
15-minute-delayed cross-market prices, changes, ratio and premium have no
stable observation timestamp and do not establish canonical current price, FX,
comparison, valuation or calculation facts. The explicit
`view=ah_comparison`, no-argument endpoint, exact ten-field response,
five-/six-digit code identities, side-specific filtering, units and
retrieval-only snapshot remain part of its replayable acquisition boundary.
The A-share dividend-distribution detail response remains raw-only because its
historical report periods, event dates, distribution ratios, per-share
indicators and share-count context do not establish settled ordinary dividend
cash or a canonical payout denominator. The explicit `view=event_detail`,
unprefixed symbol, exact 19-field response, ascending report-period ordering,
row-date binding and symbol-scoped historical-detail snapshot remain part of
its replayable acquisition boundary.
The A-share CNINFO IPO-summary response remains raw-only because its offering
dates, proceeds, fees, quantities and underwriter context do not establish a
settled issuance-cash period, dilution or a canonical share fact. The explicit
`view=ipo_summary`, unprefixed symbol, exact 15-field response, symbol-scoped
historical scope and row-date binding remain part of its replayable acquisition
boundary.
The A-share Eastmoney new-stock-board response remains raw-only because its
current-trading-day quote universe does not establish a dated listing, return,
valuation, governance or canonical market fact. The explicit
`view=new_stock`, no-argument upstream request, exact 17-field response,
six-digit code validation, provider filtering, unique sequence validation and
retrieval-only date binding remain part of its replayable acquisition boundary.
The A-share Eastmoney individual-notice response remains raw-only because its
announcement title/type/date/link metadata does not establish filing contents,
an accounting opinion or a governance-risk judgment. The explicit
`view=individual_notice`, `security`/category/date-bound request mapping, exact
six-field response, six-digit code validation, upstream listing scope,
inclusive date-range checks and symbol-scoped history/range replay metadata
remain part of its replayable acquisition boundary.
The A-share Eastmoney market-focus response remains raw-only because its
provider-defined user-attention scores and recent trading-day window do not
establish a canonical market metric, issuer cash flow, shareholder return,
governance or valuation fact. The explicit `view=focus`, unprefixed symbol,
exact two-field response, strict date ordering, official 30-row limit and
symbol-scoped observed-date replay metadata remain part of its acquisition
boundary.
The A-share Eastmoney institution-participation response remains raw-only
because its provider-defined percentages and historical trading-day series do
not establish a canonical market metric, issuer cash flow, shareholder return,
governance or valuation fact. The explicit
`view=institution_participation`, unprefixed symbol, exact two-field response,
strict date ordering, percent unit and symbol-scoped observed-date replay
metadata remain part of its acquisition boundary.
The A-share Eastmoney latest stock-hot-rank response remains raw-only because
its symbol-scoped popularity rank and provider timing do not establish a
canonical market metric, issuer cash flow, shareholder return, governance or
valuation fact. The explicit `view=hot_rank_latest`, market-prefixed symbol,
exact ten-row `item`/`value` response, `calcTime` row timestamp and replay
metadata remain part of its acquisition boundary.
The A-share Xueqiu individual-spot response uses the existing canonical quote
contract narrowly: `view=xueqiu_spot`, the derived market-prefixed symbol,
exact `item`/`value` row shape, `代码` identity, `现价` price item, `时间`
timestamp and replay metadata remain part of its acquisition boundary; all
other Xueqiu fields remain raw evidence.
The A-share Xueqiu company-profile response remains raw-only because its
descriptive, registration, personnel, control and provider-specific date
fields do not establish canonical company or listing facts. The explicit
`view=xueqiu_basic_info`, derived market-prefixed symbol, exact `item`/`value`
row shape, documented item allowlist, required profile identifiers, scalar and
finite numeric value rules, and symbol-scoped company-profile replay metadata
remain part of its acquisition boundary.
The A-share CNINFO company-profile response remains raw-only because its
descriptive, registration, contact and provider-specific date fields do not
establish canonical company or listing facts. The explicit
`view=cninfo_profile`, unprefixed six-digit symbol, exact 26-field row shape,
A-share code identity, scalar/null and valid date-or-null rules, and symbol-scoped
company-profile replay metadata remain part of its acquisition boundary.
The A-share Tonghuashun main-business-introduction response remains raw-only
because its business, product and operating-scope descriptions do not establish
canonical revenue, core-business or Business Quality facts. The explicit
`view=business_intro`, unprefixed six-digit symbol, exact five-field row shape,
A-share code identity, string/null rules and symbol-scoped current snapshot
replay metadata remain part of its acquisition boundary.

dividend-distribution snapshot remains raw-only because its ratios, status and
multiple dates do not establish settled ordinary cash or a canonical payout
denominator. Phase 2 remains active; future documented categories must be
reviewed before their fields can enter the canonical contract. The A-share
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

The A-share top-ten-shareholder report-period rows remain raw-only because
holder rank, quantities, ratios and report-date context do not establish
beneficial control, a canonical concentration metric or a company-level
diluted-share series. The explicit `view=top_10` and quarter-end `date` remain
part of the replayable acquisition boundary.

The A-share top-ten-tradable-shareholder report-period rows remain raw-only
because holder rank, quantities, float-share ratios and report-date context do
not establish beneficial control, a canonical concentration metric or a
company-level diluted-share series. The explicit `view=free_top_10` and
quarter-end `date` remain part of the replayable acquisition boundary.

The A-share top-ten-tradable-shareholder detail universe remains raw-only
because its report-period holder rows, quantities, change fields,
float-market values and announcement dates do not establish beneficial control,
a canonical concentration metric, a company-level diluted-share series or a
filing-backed governance conclusion. The explicit
`view=free_holding_detail` and quarter-end `date` remain part of the replayable
acquisition boundary.

The A-share Dragon-Tiger stock-statistic response remains raw-only because its
per-listing activity counts, amount aggregates, recent listing date and
trailing returns are a provider-window summary rather than issuer accounting,
shareholder-return, governance or canonical market facts. The explicit
`view=stock_statistic` and `period` remain part of the replayable acquisition
boundary.

The A-share Dragon-Tiger institution-statistic response remains raw-only
because its per-listing institution-seat counts, amount aggregates and
trailing returns are a provider-window summary rather than issuer accounting,
shareholder-return, governance or canonical market facts. The explicit
`view=institution_statistic` and `period` remain part of the replayable
acquisition boundary.

The A-share five-level bid-ask response remains raw-only because its order-book
levels and intraday quote context have no stable observation timestamp and do
not establish the canonical current-price, liquidity or valuation inputs. The
explicit `view=bid_ask` and derived listing symbol remain part of the
replayable acquisition boundary.

The A-share `stock_zh_a_hist_min_em` response is retained under
`AKSHARE_INTRADAY_HISTORY_RAW_ONLY` because its period-specific minute bars,
adjustment mode and recent-data limitation do not establish canonical daily
history or valuation inputs. The explicit `view=intraday`, datetime range,
interval, adjustment and listing symbol remain part of the replayable
acquisition boundary.

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
calculation methodology. The H-share latest-indicator response is retained
under a separate raw-only snapshot boundary because its mixed per-share,
capital, dividend, headline financial and valuation fields do not establish a
canonical period, entity, unit or diluted-share basis. H-share insider-share
coverage remains unresolved. The A-share disclosure-notice response is retained
under a separate raw-only discovery boundary because its listing-bound title,
timestamp and link do not establish filing contents, an accounting opinion or a
governance-risk judgment; linked-document retrieval and parsing remain Phase 3
work. The current AKShare documentation has no general H-share
disclosure-notice endpoint; the separately selected H-share dividend-event
detail response is retained under `AKSHARE_HK_DIVIDEND_DETAIL_RAW_ONLY` and
does not replace Phase 3 disclosure retrieval or parsing.
The documented A-share risk-warning-board response is retained under
`AKSHARE_RISK_WARNING_STATUS_RAW_ONLY` because its current-trading-day
universe membership does not establish dated status history or an explicit
`special_treatment=False` result for listings absent from the response.
The documented A-share main-shareholder response is retained under
`AKSHARE_MAIN_SHAREHOLDERS_RAW_ONLY` because its historical holder names,
quantities, ratios and share-class labels do not establish beneficial control,
a company-level diluted-share series or a filing-backed governance conclusion.
The documented A-share trading-suspension response is retained under
`AKSHARE_TRADING_SUSPENSIONS_RAW_ONLY` because its requested-date suspension
events, dates and reasons do not establish a complete special-treatment status
or a filing-backed governance conclusion.
The documented A-share restricted-share-release response is retained under
`AKSHARE_RESTRICTED_SHARE_RELEASES_RAW_ONLY` because its release dates,
quantities, market values and lock-up types do not establish canonical
diluted-economic-share treatment or a share-count event. H-share coverage and
filing-backed release interpretation remain unresolved.
The documented A-share goodwill-impairment response is retained under
`AKSHARE_GOODWILL_IMPAIRMENT_RAW_ONLY` because its goodwill and impairment
amounts, ratios, profit and announcement dates do not establish the canonical
accounting entity, report-period scope or a filing-backed reconciliation. H-share
coverage and filing-backed impairment interpretation remain unresolved.
The documented A-share goodwill-impairment forecast response is retained under
`AKSHARE_GOODWILL_FORECAST_RAW_ONLY` because its expected-profit ranges,
change-rate bounds, prior-year profit, goodwill context and announcement date
remain provider evidence rather than filing-backed canonical forecast, profit,
goodwill or impairment facts. The request's `REPORT_DATE` filter is preserved
as replay metadata, while `最新商誉报告期` remains a separate provider field;
H-share coverage and primary-filing reconciliation remain unresolved.
The documented Sina A/H ESG-rating response is retained under
`AKSHARE_ESG_RATINGS_RAW_ONLY` because agency-specific scales, rating values,
provider quarter labels and markers do not establish a comparable ESG score,
governance-risk level or Business Quality judgment. The provider validates and
filters the mixed universe by explicit code plus `cn`/`hk` market while
retaining all matching agency/quarter rows; no canonical ESG, governance,
financial or valuation fact is admitted.

The documented SSE, SZSE and BSE margin-detail responses are retained under
`AKSHARE_MARGIN_TRADING_RAW_ONLY` because their security-level investor
financing balances, quantities and transaction flows do not establish issuer
financial debt, cash, leverage or a canonical margin fact; `financial_debt`
remains critically missing. The SSE response carries its exact observation
date in each row, while the documented SZSE and BSE responses bind the exact
request date only through the request and response metadata; none is an issuer
accounting period.

The documented A/H `stock_hsgt_individual_em` response is retained under
`AKSHARE_HSGT_INDIVIDUAL_HOLDINGS_RAW_ONLY` because its symbol-scoped
north-/southbound investor holdings, quantities, market values, ratios and
dated changes do not establish beneficial control, governance severity,
shareholder concentration, issuer corporate-action cash or a company-level
diluted-share series. Its official implementation removes row-level security
identity from the published output, so the explicit request scope is retained
without inventing a row-level listing code. `governance_risk_level` remains
critically missing and no ownership, share, buyback, issuance, return or
valuation fact is emitted.

The documented A-share `stock_hold_control_cninfo` response is retained under
`AKSHARE_CONTROL_HOLDINGS_RAW_ONLY` because its controller names, holding
quantities, ratios, provider control categories and change dates do not by
themselves establish filing-backed legal control, governance severity,
canonical ownership/concentration or a company-level diluted-share series.
`governance_risk_level` remains critically missing and no canonical fact is
emitted; the explicit `view=control_changes` and control-scope selector remain
part of the replayable acquisition boundary.

The documented A-share external-guarantee response is retained under
`AKSHARE_EXTERNAL_GUARANTEES_RAW_ONLY` because its date-range aggregate,
parent-equity denominator and published ratio do not establish a settled
quasi-debt amount, legal guarantee status, canonical period/entity scope or a
governance judgment. It leaves `material_quasi_debt`,
`major_illegal_guarantee` and `governance_risk_level` critically missing; H-share
coverage and filing-backed review remain unresolved.

The documented A-share individual ownership-pledge detail response is retained
under `AKSHARE_INDIVIDUAL_PLEDGE_DETAIL_RAW_ONLY` because its holder,
institution, quantity, ratio, price, status and event-date fields do not
establish a fully diluted share count, settled pledged cash/debt-equivalent
amount, beneficial control or a governance judgment. It leaves
`governance_risk_level` critically missing; H-share coverage and filing-backed
pledge interpretation remain unresolved.

The documented A-share company-litigation response is retained under
`AKSHARE_LITIGATION_RAW_ONLY` because its date-range lawsuit count, amount and
aggregate interval do not establish a canonical event/statement period, legal
status, accounting scope, material quasi-debt amount or governance judgment.
It leaves `material_quasi_debt` and `governance_risk_level` critically missing;
H-share coverage and filing-backed litigation review remain unresolved.

The documented A-share CNINFO equity-mortgage response is retained under
`AKSHARE_EQUITY_MORTGAGE_RAW_ONLY` because its query date, announcement dates,
pledgor/pledgee, quantities, ratios and event descriptions do not establish a
canonical pledge period, fully diluted share count, settled pledged
cash/debt-equivalent amount, beneficial control or a governance judgment. It
leaves `governance_risk_level` critically missing; H-share coverage and
filing-backed pledge interpretation remain unresolved.
