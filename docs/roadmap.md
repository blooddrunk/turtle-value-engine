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

### Future Phase 2 deliverables

```text
src/turtle_value_engine/providers/
  base.py
  models.py
  errors.py
  cache.py
  normalization.py
  akshare.py       # Phase 2.2 market + Phase 2.3–2.41 structured slices
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

Phase 2.41 completes the next documented structured-data boundary while
keeping share-change, repurchase and rights-issue period, status, unit and
economic-scope questions unresolved, and keeping ownership-pledge holder,
governance and economic-scope questions unresolved. The A-share
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
