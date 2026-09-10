# Provider and Cache Architecture

> Status: Phase 2 foundation, read-only AKShare statement slices, earnings forecasts/quick reports/performance reports/business composition/financial abstract/financial indicators, H-share latest indicators, dividend events/snapshots/detail, A-share disclosure-notice metadata, risk-warning status, trading-suspension, restricted-share-release, goodwill-impairment, ESG-rating, SSE/SZSE/BSE margin-detail, share-capital, individual-info snapshot, corporate-action, external-guarantee, company-litigation, ownership-pledge snapshot/detail, main-shareholder, shareholder-count, A-share actual-controller holding-change, A/H HSGT individual-holdings, SSE/SZSE/BSE insider-share-change, A-share Eastmoney management-holding and A-share top-ten/top-ten-tradable-shareholder/top-ten-tradable-shareholder-detail, Dragon-Tiger market-activity detail/statistics/institution-statistics, A-share Tencent daily-history/latest-trading-day tick, Sina minute-history, A-share/H-share intraday-history, pre-market-history and five-level bid-ask raw slices

This document freezes the boundary between structured-data acquisition and the
deterministic Turtle Value Engine. It does not authorize a live provider or
change any `strict-v1` formula, threshold, schema meaning or gate semantic.

## 1. Invariant and flow

The deterministic engine remains the source of truth:

```text
external provider
    -> raw provider records
    -> normalization / mapping
    -> Evidence + Fact + DataQuality
    -> existing NormalizedCompanyInput
    -> existing deterministic pipeline
```

There is one analysis model: `NormalizedCompanyInput` on the input side and
the existing `CompanyAnalysis` on the output side. A provider must not create
a parallel analysis object, calculate an investment metric, or decide a gate.

Phase 2 adds acquisition and replay infrastructure only. Phase 3 is the
boundary for official filing retrieval and filing-derived evidence.

## 2. Responsibilities and boundaries

### Structured provider adapter

A provider adapter is responsible for:

- accepting a provider-neutral request for one data category and entity;
- calling its upstream service when a live implementation exists;
- returning an opaque `RawProviderRecord`;
- advertising the categories it actually supports;
- preserving provider/source version metadata and the retrieval timestamp;
- translating provider failures into a typed `ProviderError` without
  fabricating a successful response.

An adapter may understand upstream column names, pagination, authentication,
rate limits and response quirks. Those details end at the raw-record boundary.
An adapter must not calculate CDC, net cash, Through Return, valuation,
business-quality scores or hard gates.

### Cache

The cache stores successful raw responses and their acquisition metadata. It
does not store normalized facts as a substitute for the input contract, and
it does not decide whether a response is financially trustworthy. A cache
read is either a validated record, an explicit miss, a stale record when the
caller opted into stale replay, or a typed corruption error.

### Normalization / mapping

The normalizer is the only boundary that knows how an upstream field maps to a
canonical normalized field. It is responsible for:

- mapping provider-specific payloads to the existing `Fact` model;
- creating `Evidence` items that point back to the raw source and request;
- creating conservative `DataQuality` metadata;
- preserving explicit `null` values and listing critical missing fields;
- rejecting ambiguous duplicate field/period mappings;
- returning the existing `NormalizedCompanyInput`.

The provider foundation exposes a normalizer protocol but does not implement
AKShare, Tushare, or any other mapping. The normalizer must not silently apply
an accounting judgment that belongs to a filing review or an accepted
`Adjustment`.

### Deterministic engine

`calculations/`, `gates/`, valuation code and investment-rule profiles consume
canonical normalized inputs and deterministic stage results only. They never
import a provider module or inspect an upstream payload. Their current
nullable and evidence-lineage behavior remains unchanged.

## 3. Provider-neutral categories and capability discovery

The foundation defines independent categories so a later adapter can support
only what it can acquire reliably:

```text
COMPANY_METADATA
LISTING_METADATA
RISK_WARNING_STATUS
TRADING_SUSPENSIONS
MARKET_QUOTE
MARKET_HISTORY
MARKET_ACTIVITY
CAPITAL_FLOW
INCOME_STATEMENT
EARNINGS_FORECAST
EARNINGS_QUICK_REPORT
PERFORMANCE_REPORT
BUSINESS_COMPOSITION
FINANCIAL_ABSTRACT
FINANCIAL_INDICATORS
GOODWILL_IMPAIRMENT
ESG_RATINGS
MARGIN_TRADING
LATEST_INDICATORS
BALANCE_SHEET
CASH_FLOW_STATEMENT
DIVIDENDS
DISCLOSURE_NOTICES
SHARE_CAPITAL
CORPORATE_ACTIONS
EXTERNAL_GUARANTEES
LITIGATION
OWNERSHIP_PLEDGE
INSIDER_SHARE_CHANGES
SHAREHOLDER_HOLDINGS
```

Each request has:

- `category`;
- stable `entity_id` (for example a canonical listing or issuer identity);
- JSON parameters such as period, frequency or date range.

`ProviderCapabilities` is an explicit set, not an optimistic registry. A
request for an unsupported category raises `ProviderCapabilityError` before
the adapter is called. Capability discovery therefore does not require a
network call and can be used to plan a fetch before execution.

The foundation's `StructuredDataProvider` interface has one raw fetch method
plus a convenience category request. Later adapters may dispatch internally
to their quote, history, income, balance-sheet, cash-flow, dividend or
share/corporate-action endpoint. The interface does not require every provider
to implement every category.

## 4. Raw provider representation

`RawProviderRecord` is intentionally provider-neutral while its payload is
intentionally provider-specific. It contains:

```text
provider:       provider_id, provider_version, source_name
request:        category, entity_id, canonical parameters
retrieved_at:   timezone-aware UTC timestamp
raw_payload:    opaque JSON object/array/scalar/null
source_uri:     optional endpoint or source URL
response_metadata: small JSON metadata such as status or upstream request ID
```

The payload is copied and validated as JSON, but no column names or nested
structure are interpreted. Raw records may contain an explicit `null`; a
provider or normalizer must distinguish that from a real numeric zero.

The provider version is part of the cache identity. A mapping or upstream
contract change can therefore create a new cache namespace instead of replaying
bytes under an incompatible adapter version.

## 5. Normalization and provenance

For every normalized fact, the normalizer must establish:

1. canonical `Fact.field` and period;
2. value and unit/currency without an implicit unit conversion;
3. `source_evidence_ids` pointing to evidence in the same input;
4. confidence and estimated status appropriate to the source;
5. a `DataQuality` update when a critical value is absent or unresolved.

For structured data, evidence should use the existing
`STRUCTURED_DATA_VENDOR` source type and retain enough metadata to find the
raw record again. The recommended source mapping is:

- `Source.title`: source name plus provider identifier/version;
- `Source.url`: `source_uri` when available;
- `Source.document_id`: deterministic cache-key digest or upstream response
  identifier;
- `Source.locator`: category, entity identity and request parameters;
- evidence `notes`: retrieval timestamp and any non-sensitive response
  metadata needed for replay.

The raw cache remains the authoritative byte-level provenance. Evidence is the
normalized contract's auditable pointer to it. A re-fetch must not erase the
earlier evidence from an already persisted analysis.

Fact and evidence IDs should be deterministic when their semantic identity is
stable. Use the provider, request identity, canonical field, period and
mapping version as components; do not use list position or wall-clock retrieval
time for a fact ID. The foundation's `deterministic_id` helper exists for this
purpose. IDs for genuinely distinct snapshots may include an explicit snapshot
identity.

## 6. Structured facts versus filing-derived facts

Structured data is suitable for fast, repeatable observations such as a
reported price, reported CFO, reported profit, total cash, reported debt,
dividend amount, or a share count when the provider's period and entity are
unambiguous.

The financial-statement slices are deliberately narrow. The AKShare adapter
may acquire `CASH_FLOW_STATEMENT`, `INCOME_STATEMENT` and `BALANCE_SHEET`
records for A/H listings. Its normalizer maps only report-period rows whose
labels unambiguously represent `reported_cfo`, `acquisition_cash`,
`parent_net_profit`, `consolidated_net_profit`, `book_cash`,
`parent_equity`, `total_equity` or an explicit aggregate
`reported_interest_bearing_debt`. A-share wide records and H-share long-form
item records are handled separately. The documented A-share aggregate
balance endpoint is date-based and returns a universe; the provider selects
the requested listing and carries the exact requested quarter-end date into
the normalized period. That aggregate shape maps only its explicit cash and
total-equity fields. The mapper preserves the reported sign, currency and
null value; it does not scale amounts, split aggregate capex into
PPE/intangible purchases, sum borrowing sub-items into debt, calculate
CDC/financing metrics, or import revenue and provider ratios as canonical
facts.

Statement currency is accepted only from explicit, valid three-letter
metadata. The normalizer does not infer a statement currency from the listing
market; missing currency remains `null`, and conflicting explicit currencies
within one report period are a normalization error. Reported amount scaling
and unit conversion remain unresolved and are not performed.

Missing report dates, year-only periods, duplicate periods or duplicate
long-form items are normalization errors. This keeps a provider convenience
table from silently becoming a normalized annual history with ambiguous
semantics.

The first share-capital slice is deliberately acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes `stock_zh_a_gbjg_em` as an A-share endpoint that accepts `symbol` and
returns all historical records with `变更日期`, `总股本`, circulation fields and
`变动原因`. The documentation types `总股本` as `int64`, but does not declare a
unit or define a fully diluted economic scope for the count. The provider
therefore passes the six-digit A-share code, retains the complete tabular
payload and row count, and does not select a “latest” row. The normalizer keeps
the raw record's evidence, marks
`normalized_diluted_economic_shares` as critically missing and emits the
`AKSHARE_SHARE_CAPITAL_RAW_ONLY` flag without creating a canonical share fact.
It does not treat `变更日期` as a financial-statement period or `总股本` as
fully diluted shares. H-share share capital and canonical dividend or
capital-action facts remain outside these raw-only slices.

The company-share-change sub-slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_share_changes_cninfo.py)
describe `stock_share_change_cninfo` as a CNINFO endpoint accepting an A-share
`symbol`, `start_date` and `end_date` in `YYYYMMDD` form. It returns dated rows
with total/circulation holdings, share-class holdings and change-reason text.
When a date range is explicitly requested through the `SHARE_CAPITAL` category,
the adapter passes the six-digit code and range, retains every row and records
the effective range and row count. The normalizer validates explicit row
identity, preserves raw evidence, marks
`normalized_diluted_economic_shares` as critically missing and emits
`AKSHARE_SHARE_CAPITAL_CHANGE_RAW_ONLY`; it does not treat the change date as a
financial-statement period or any reported holding as a fully diluted share
count.

The new rights-issue sub-slice extends the raw-only corporate-action boundary.
The current [AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes `stock_allotment_cninfo` as a CNINFO endpoint accepting an A-share
`symbol`, `start_date` and `end_date`, and returning dated plan/result rows with
share quantities, prices, proceeds and other allotment fields. The adapter
passes the six-digit A-share code and the documented `YYYYMMDD` date range,
retains every returned row and records the request range and row count. The
documented fields do not by themselves settle the effective event date,
planned-versus-completed outcome, amount unit/scaling or share-class/dilution
scope, so the normalizer keeps the response as raw evidence and does not create
an issuance, buyback, split or share-count fact.

The earnings-forecast slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_yjyg_em.py)
describe `stock_yjyg_em` as an Eastmoney A-share universe endpoint accepting an
explicit quarterly report date in `YYYYMMDD` form. It returns forecast
indicators, forecast values or ranges, change reasons, forecast types,
prior-period values and announcement dates. The provider validates the exact
quarter-end date, rejects rows without an explicit listing code, filters to the
requested A-share listing and retains all matching rows. Forecast values and
announcement dates are estimates/publication metadata rather than reported
parent or consolidated profit, so the normalizer keeps raw evidence, marks
both reported profit fields as critically missing and emits
`AKSHARE_EARNINGS_FORECAST_RAW_ONLY` without creating a canonical profit,
margin, CDC or valuation fact. H-share forecasts remain outside this slice.

The performance-report slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_yjbb_em.py)
describe `stock_yjbb_em` as an Eastmoney A-share universe endpoint accepting an
explicit quarterly report date in `YYYYMMDD` form, with documented coverage
starting at `20100331`. It returns headline revenue and net-profit values,
per-share indicators, ratios, industry and latest-announcement metadata. The
provider validates the exact quarter-end date, rejects rows without an
explicit listing code, filters to the requested A-share listing and retains
all matching rows. The headline net profit does not identify the admitted
parent/consolidated entity basis, and operating cash flow is per share rather
than a total CFO fact, so the normalizer keeps raw evidence, marks
`parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as critically
missing and emits `AKSHARE_PERFORMANCE_REPORT_RAW_ONLY` without creating a
canonical profit, revenue, margin, CFO, CDC or valuation fact. H-share
performance reports remain outside this slice.

The earnings-quick-report slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_yjyg_em.py)
documents `stock_yjkb_em` as an Eastmoney A-share universe endpoint accepting
an explicit quarterly report date in `YYYYMMDD` form, with documented coverage
starting at `20100331`. It returns headline revenue and net-profit values,
prior-period comparisons, per-share indicators, return on equity, industry and
announcement-date metadata. The provider validates the exact quarter-end date,
rejects rows without an explicit listing code, filters to the requested
A-share listing and retains all matching rows. The headline net profit does
not identify the admitted parent/consolidated entity basis, and the
revenue/per-share fields do not settle the canonical period, unit or
diluted-share scope, so the normalizer keeps raw evidence, marks
`parent_net_profit` and `consolidated_net_profit` as critically missing and
emits `AKSHARE_EARNINGS_QUICK_REPORT_RAW_ONLY` without creating a canonical
profit or revenue fact. H-share quick reports remain outside this slice.

The business-composition slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zygc_em` as an Eastmoney A-share listing-scoped endpoint
accepting a market-prefixed `symbol`. It returns historical product, industry
and geographic composition rows with report dates, revenue/cost/profit amounts,
ratios and margin context. The provider validates explicit row identity and
non-null report dates, retains every row and records row and distinct-period
counts. Because those views overlap and their unit, entity, aggregation and
classification semantics are not settled, the normalizer marks `revenue` and
`core_revenue` as critically missing and emits
`AKSHARE_BUSINESS_COMPOSITION_RAW_ONLY` without creating a canonical revenue,
operating-profit, margin or business-quality fact. H-share composition remains
outside this slice.

The financial-abstract slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_financial_abstract` as a Sina A-share listing-scoped endpoint
accepting a six-digit `symbol` and returning all historical key indicators in
a wide matrix with `选项`, `指标` and report-period columns. The provider
passes the requested code, validates explicit metric identity and date-shaped
period columns, retains the full payload and records row and distinct-period
counts. Because the response mixes amount rows with per-share indicators and
ratios without an admitted canonical entity, unit/scaling, period or
diluted-share basis, the normalizer marks `revenue`,
`parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as critically
missing and emits `AKSHARE_FINANCIAL_ABSTRACT_RAW_ONLY` without creating a
canonical fact.

The financial-indicator slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_financial_analysis_indicator_em` as an Eastmoney A-share
listing-scoped endpoint with an `indicator` choice of `按报告期` or
`按单季度`, and `stock_financial_hk_analysis_indicator_em` as the corresponding
historical H-share endpoint with an `indicator` choice of `年度` or `报告期`.
Both responses include explicit listing identity and report dates, but mix
reported amounts, per-share values and provider-calculated ratios without
establishing one canonical entity, unit/scaling, point-in-time basis or
calculation methodology. The provider passes the market-suffixed A-share
symbol or the five-digit H-share symbol plus the documented indicator mode,
retains the complete response, validates row identity/report dates and records
row, period and mode metadata. The normalizer marks `revenue`,
`parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as critically
missing and emits `AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY` without creating a
canonical fact, metric or valuation input.

The H-share latest-indicator slice is a separate acquisition-only snapshot.
The current [AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hk_financial_indicator_em` as the Eastmoney H-share
“latest indicators” endpoint accepting a five-digit `symbol` and returning a
single mixed row of per-share, share-capital, dividend, headline financial and
valuation fields. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_em.py)
selects those output columns without retaining a row-level listing code or a
canonical statement period. The provider therefore passes the symbol, retains
the complete symbol-scoped response and rejects more than one returned row.
The normalizer marks `revenue`, `parent_net_profit`,
`consolidated_net_profit` and `reported_cfo` as critically missing and emits
`AKSHARE_LATEST_INDICATORS_RAW_ONLY` without creating a canonical financial,
share, dividend, market-cap, metric or valuation fact.

The insider-share-change slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes `stock_share_hold_change_sse`, `stock_share_hold_change_szse` and
`stock_share_hold_change_bse` as exchange-specific endpoints accepting a
Shanghai, Shenzhen or Beijing A-share `symbol` and returning listing-scoped
insider/management holding-change rows. The provider passes the six-digit
code, validates explicit company identity and any non-null change/filing dates,
and retains every row. The BSE response documents holding quantities in
ten-thousand shares and average price in yuan. Because holder roles, event
holdings and prices do not establish a company-level diluted-share series or a
governance judgment, the normalizer marks `governance_risk_level` as
critically missing and emits `AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY` without
creating share-count, dilution, governance, buyback or issuance facts. H-share
coverage remains outside this slice.

The A-share disclosure-notice slice is a discovery-only boundary. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_disclosure_report_cninfo` as a CNINFO endpoint accepting
a six-digit A-share `symbol`, the `沪深京` market, optional keyword/category
filters and `YYYYMMDD` start/end dates. Its output is listing-bound
announcement metadata: code, short name, title, announcement time and a link.
The provider passes the request, validates every returned row's listing code
and any explicit announcement date, and retains the response as an opaque raw
record. The normalizer emits
`AKSHARE_DISCLOSURE_NOTICES_RAW_ONLY`, marks `accounting_opinion` and
`governance_risk_level` as critically missing, and does not fetch or parse the
linked document or infer a filing classification. H-share coverage remains
outside this slice.

The A-share risk-warning-status slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_st_em` as a no-argument Eastmoney risk-warning-board
universe endpoint returning code, name and current market-observation fields.
The provider validates explicit codes, filters the universe to the requested
A-share listing and keeps the selected result, including an empty match, as an
opaque raw record. The normalizer emits
`AKSHARE_RISK_WARNING_STATUS_RAW_ONLY`, marks `special_treatment` as critically
missing and does not infer `special_treatment=False` from absence or treat the
current board snapshot as a dated history or filing-backed reason.

The A-share main-shareholder slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_main_stock_holder` as a Sina endpoint accepting a six-digit
`stock` code and returning all historical holder rows with holding quantities,
ratios, share-class labels, as-of dates, announcement dates and holder context.
The provider passes the code, retains the complete symbol-scoped response,
validates any non-null dates and records the row count. The normalizer emits
`AKSHARE_MAIN_SHAREHOLDERS_RAW_ONLY`, marks `governance_risk_level` as
critically missing and does not create ownership, share-count, dilution,
buyback, issuance or valuation facts; beneficial-control and filing-backed
governance interpretation remain outside this slice.

The A-share trading-suspension slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_tfp_em` as an Eastmoney endpoint accepting a `YYYYMMDD`
`date` and returning a suspension/resumption universe with listing codes,
event dates, duration, reason, market and expected resume date. The provider
validates the request and nullable event dates, filters the universe to the
requested A-share listing and retains every matching row. The normalizer emits
`AKSHARE_TRADING_SUSPENSIONS_RAW_ONLY`, marks `special_treatment` and
`governance_risk_level` as critically missing and does not create a canonical
status, governance or accounting fact; a complete status history and
filing-backed interpretation remain outside this slice.

The A-share goodwill-impairment slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sy_jz_em` as an Eastmoney endpoint accepting a required
`YYYYMMDD` report `date` and returning listing rows with goodwill,
goodwill-impairment, ratio, profit, announcement-date and market context. The
provider validates explicit listing codes and nullable announcement dates,
filters the universe to the requested A-share listing and records the requested
report period in response metadata. The normalizer emits
`AKSHARE_GOODWILL_IMPAIRMENT_RAW_ONLY`, marks `goodwill` and `impairment` as
critically missing and does not create canonical accounting or provider-metric
facts; primary-filing entity, scope and reconciliation review remain outside
this slice.

The A/H ESG-rating slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_esg_rate_sina` as a no-argument Sina response containing
component code, rating agency, rating, rating quarter, marker and `cn`/`hk`
market fields across a mixed A/H universe. The provider validates the explicit
code/market identity, filters to the requested listing and retains all matching
agency/quarter rows. The normalizer emits
`AKSHARE_ESG_RATINGS_RAW_ONLY`, marks `governance_risk_level` as critically
missing and does not create a canonical ESG score, governance or Business
Quality fact because agencies use different scales and quarters are provider
reporting labels.

The SSE margin-detail slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_margin_detail_sse` as an endpoint accepting an exact
`YYYYMMDD` `date` and returning a full SSE security universe with explicit
security codes, financing balances and financing/short-sale quantities. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_sse.py)
passes the requested date to the SSE detail request and renames the published
columns. The provider supports Shanghai A-share identifiers only, validates
the explicit code and date on every row, filters to the requested listing and
retains every matching row with date and row-count provenance. These are
security-level investor financing observations rather than issuer accounting
debt or cash, so the normalizer marks `financial_debt` as critically missing,
emits `AKSHARE_MARGIN_TRADING_RAW_ONLY` and creates no canonical debt, cash,
margin, leverage or valuation fact.

The corresponding SZSE slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_margin_detail_szse` as an endpoint accepting an exact
`YYYYMMDD` `date` and returning a full Shenzhen security universe with
explicit security code/name, financing balances and financing/short-sale
quantities. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_szse.py)
passes the requested date to the SZSE report request and returns the published
columns; unlike the SSE response, the documented SZSE rows do not contain a
row-level observation date. The provider validates every code, filters to the
requested Shenzhen listing and retains the request date in response metadata
without adding a synthetic payload field. The normalizer emits
`AKSHARE_MARGIN_TRADING_RAW_ONLY`, marks `financial_debt` as critically
missing and creates no canonical debt, cash, leverage or valuation fact.

The corresponding BSE slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_margin_detail_bse` as an endpoint accepting an exact
`YYYYMMDD` `date` and returning a full Beijing Stock Exchange security universe
with explicit security code/name, financing balances and financing/short-sale
quantities in yuan and shares. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_bse.py)
passes the requested date to the BSE detail request, paginates the published
response and returns the documented columns. Unlike the SSE response, the
documented BSE rows do not contain a row-level observation date. The provider
validates every code, filters to the requested Beijing A-share listing and
retains the request date in response metadata without adding a synthetic
payload field. The normalizer emits `AKSHARE_MARGIN_TRADING_RAW_ONLY`, marks
`financial_debt` as critically missing and creates no canonical debt, cash,
leverage, margin or valuation fact.

The A-share external-guarantee slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_guarantee.py)
document `stock_cg_guarantee_cninfo` as a CNINFO company-governance endpoint
with a board/universe selector and `YYYYMMDD` start/end dates. The adapter
calls the documented `symbol="全部"` universe, validates every explicit
`证券代码`, filters to the requested A-share listing and preserves all
matching rows plus the requested range, upstream symbol and row counts. Its
guarantee count/amount, parent-company equity and published ratio are raw
date-range aggregate evidence; the documented 万元 units and aggregate
interval do not settle a quasi-debt amount, guarantee purpose, legal status,
canonical period/entity scope or governance judgment. The normalizer emits
`AKSHARE_EXTERNAL_GUARANTEES_RAW_ONLY`, marks
`material_quasi_debt`, `major_illegal_guarantee` and
`governance_risk_level` as critically missing and creates no canonical fact.
H-share coverage and filing-backed review remain unresolved.

The A-share company-litigation slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_lawsuit.py)
document `stock_cg_lawsuit_cninfo` as a CNINFO company-governance endpoint with
a board/universe selector and `YYYYMMDD` start/end dates. The adapter calls the
documented `symbol="全部"` universe, validates every explicit `证券代码`,
filters to the requested A-share listing and preserves all matching rows plus
the requested range, upstream symbol and row counts. Its lawsuit count/amount
and announcement-statistics interval are raw date-range aggregate evidence;
the documented 万元 amount and interval do not settle a canonical event or
statement period, legal status, accounting entity/scope, material quasi-debt
amount or governance judgment. The normalizer emits
`AKSHARE_LITIGATION_RAW_ONLY`, marks `material_quasi_debt` and
`governance_risk_level` as critically missing and creates no canonical fact.
H-share coverage and filing-backed litigation review remain unresolved.

The A-share individual ownership-pledge detail sub-slice is also
acquisition-only. The current [AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
document `stock_gpzy_individual_pledge_ratio_detail_em` as a symbol-scoped
Eastmoney detail response. The adapter selects it only with
`view=individual_pledge_detail`, passes the six-digit code, validates explicit
row codes and populated announcement/start/end dates, and retains every row.
Holder/institution identity, quantities/ratios, prices, status and event dates
remain raw evidence: they do not establish beneficial control, a fully diluted
share count, settled pledged cash/debt-equivalent amount or a governance
judgment. The normalizer emits
`AKSHARE_INDIVIDUAL_PLEDGE_DETAIL_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no canonical fact.

When a statement row includes an explicit security code, the normalizer also
checks it against the requested listing and rejects a mismatch. Statement
endpoints that omit a row-level code remain bound to their listing-scoped
request; the normalizer does not invent an entity code for them.

The adapter version and mapping version are part of the cache/fact identity,
so an endpoint or mapping contract change cannot replay a prior snapshot under
an incompatible mapping. The explicit statement-row entity guard is a
normalizer-only mapping change; it bumps the mapping version while leaving the
raw adapter/cache version unchanged.

It is not permission to infer economic classifications that are absent from
the provider response. Examples that remain outside automatic Phase 2
normalization include:

- restricted or pledged cash and cash upstreamability;
- supplier finance, recourse factoring, lease-principal classification and
  other debt equivalents;
- one-off operating inflows and core/non-core profit classification;
- formal payout-policy interpretation and genuine recurring net share
  reduction;
- accounting opinions, illegal guarantees and governance risk;
- customer/channel/supplier dependency and structural disruption;
- the eight Business Quality dimension judgments.

The field matrix in `docs/data/provider-field-matrix.md` is the controlling
allowlist for this distinction. A structured provider may supply a raw hint
for a filing-required item, but the Phase 2 normalizer must keep the canonical
fact `null` or mark it unresolved until the required source and review exist.
It must never promote a headline field into a strict-v1 economic fact merely
because the provider uses a confident label.

If structured sources disagree, retain both source records/evidence and emit
an explicit data-quality issue. Do not silently choose the most favorable
value and do not overwrite a deterministic metric from the provider layer.

## 7. Missing and null values

The following states are distinct:

| State | Meaning | Normalized treatment |
| --- | --- | --- |
| field absent from response | provider did not return the field | no invented value; record the field as unavailable when it is critical |
| field present with `null` | provider explicitly has no value | preserve `Fact.value = null` and its evidence |
| numeric `0` | source reported an actual zero | preserve zero and its evidence |
| unresolved classification | raw amount exists but economic meaning is unknown | keep the canonical classified fact `null`; add a data-quality note/evidence |
| ambiguous duplicate | more than one value maps to the same field/period | fail normalization for that mapping; never use “last row wins” |

No adapter, cache reader or normalizer may use zero as a missing-data default.
The existing calculation and gate modules then apply their established
nullable behavior and may return `SPECIAL_REVIEW` or an unavailable metric.

## 8. Failure and isolation behavior

Provider requests are isolated by category and entity. A quote failure must
not invalidate an already acquired balance-sheet raw record; conversely, a
cached quote must not make a failed balance-sheet request look successful. The
orchestration layer should carry per-request errors and only assemble a
normalized input from records it can account for.

Failure rules are:

- unsupported category -> `ProviderCapabilityError`;
- transport, authentication, quota or upstream request failure -> typed
  `ProviderError` with retryability classified by the adapter;
- invalid response type or request/provider identity mismatch ->
  `ProviderResponseError`;
- ambiguous or invalid raw-to-fact mapping -> `ProviderNormalizationError`;
- no provider error is converted to an empty payload, zero or a successful
  `Fact`;
- a live provider failure does not write to the cache;
- cache corruption is an explicit `CacheCorruptionError`, not a cache miss;
- an offline cache miss is an explicit `CacheMissError`;
- a cache write failure is an explicit `CacheWriteError`.

The cache-aware helper defaults to re-raising live provider errors. Replaying
a stale cached record after a provider failure requires an explicit caller
option and returns a replay mode so a report can disclose that it is not live.
Offline mode never calls a provider.

## 9. Cache semantics and filesystem layout

The Phase 2 cache is a filesystem of JSON envelopes, not a database. A cache
key is a canonical JSON digest of:

```text
provider
provider_version
category
entity_id
request parameters
```

The readable path is:

```text
<cache-root>/<provider>/<category>/<sha256>.json
```

The envelope separately stores:

```json
{
  "cache_format_version": 1,
  "provider": {"id": "...", "version": "...", "source_name": "..."},
  "request": {"category": "...", "entity_id": "...", "parameters": {}},
  "retrieved_at": "2026-09-09T00:00:00Z",
  "raw_payload": {},
  "source_uri": null,
  "response_metadata": {}
}
```

Parameter object order does not change a key. Provider version does. The
retrieval timestamp is metadata, not an accidental request identity.

Writes serialize and validate the complete envelope, write a temporary file in
the destination directory, flush and fsync it, then use an atomic replace. If
serialization, provider acquisition or replacement fails, the previous valid
file is left in place. Temporary files are not treated as cache entries. A
corrupted or incomplete existing file is never silently repaired, deleted or
interpreted as valid data by a read.

The current implementation stores the latest valid snapshot for an exact
provider/request-version key. If historical snapshots are needed, a future
version must add an explicit immutable snapshot index; it must not overload the
normalized input or silently change replay semantics.

## 10. Freshness, replay and rate-limit protection

The cache has no automatic network behavior. A caller may supply a maximum age:

- a fresh entry can be replayed when it matches the key;
- a stale entry is treated as unavailable unless stale replay is explicitly
  allowed;
- `offline=True` never falls through to a provider;
- provider-failure fallback is opt-in and reported as cache replay.

This supports reproducible tests and development, protects upstream rate
limits, and makes offline analysis possible without making a stale value look
like a live observation. Cache freshness does not prove financial correctness
or filing-level reliability.

## 11. Retry boundaries

Only a concrete provider adapter may retry its own idempotent read operation.
Retries must be bounded and respect the provider's rate-limit/authentication
rules. The adapter should not retry authentication failures, unsupported
categories, malformed requests or deterministic response-validation errors.

The cache performs no network retries. The normalizer performs no provider
retries. The deterministic pipeline performs no provider retries and should
not be rerun as a substitute for resolving missing facts.

## 12. Phase 2.2–2.58 AKShare adapter

The first concrete adapter is intentionally limited to read-only metadata,
market observations, three documented financial-statement slices, raw-only
earnings-forecast, earnings-quick-report, performance-report,
business-composition and financial-abstract categories, A/H financial-indicator
raw slices, raw-only dividend event/snapshot/detail, corporate-action,
external-guarantee and company-litigation categories,
four A-share share-capital raw slices, three A-share ownership-pledge raw views,
an H-share latest-indicator raw slice, an A-share disclosure-notice raw slice,
an A-share risk-warning-status, trading-suspension, goodwill-impairment,
ESG-rating, SSE/SZSE/BSE margin-detail, external-guarantee, company-litigation,
main-shareholder/shareholder-count/actual-controller holding-change/HSGT
individual-holdings raw slices, A-share Eastmoney individual-fund-flow,
top-ten-shareholder/top-ten-tradable-shareholder/top-ten-tradable-shareholder-detail,
Dragon-Tiger detail/statistics/institution-statistics market-activity,
SSE/SZSE/BSE insider-share-change, A-share Eastmoney management-holding,
A-share Eastmoney chip-distribution, Tencent daily-history and latest-trading-day tick, Sina minute-history,
A-share/H-share intraday-history, pre-market-history and five-level bid-ask raw
slices. It
advertises exactly these capabilities:

| Category | A-share endpoint | H-share endpoint | Normalized output |
| --- | --- | --- | --- |
| `COMPANY_METADATA` | `stock_info_a_code_name` | `stock_hk_company_profile_em` (with conservative metadata-list fallbacks) | company metadata extension facts; nullable `Company` context enrichment only |
| `LISTING_METADATA` | `stock_info_a_code_name` | `stock_hk_security_profile_em` (with conservative listing-list fallbacks) | listing code/name/date/exchange and other explicit metadata facts |
| `RISK_WARNING_STATUS` | `stock_zh_a_st_em` (no parameters) | — | current A-share risk-warning-board membership as raw structured evidence only; no canonical `special_treatment` fact |
| `TRADING_SUSPENSIONS` | `stock_tfp_em` (exact `date`) | — | requested-date A-share suspension/resumption rows as raw structured evidence only; no canonical status or governance fact |
| `MARKET_QUOTE` | `stock_zh_a_spot_em`; `stock_bid_ask_em` (`view=bid_ask`, Shanghai/Shenzhen A-share only) | `stock_hk_spot_em` | selected-listing `current_price` plus quote timestamp; bid/ask view retained raw-only |
| `MARKET_HISTORY` | `stock_zh_a_hist` (daily history); `stock_cyq_em` (`view=chip_distribution`, latest 90 trading days and adjustment; A-share only); `stock_zh_a_hist_tx` (`view=tencent_daily`, explicit date range/adjustment; A-share only); `stock_zh_a_tick_tx_js` (`view=tencent_tick`, latest-trading-day time-only ticks; A-share only); `stock_zh_a_minute` (`view=sina_minute`, explicit interval/adjustment; A-share only); `stock_zh_a_hist_min_em` (`view=intraday`, explicit datetime range/interval/adjustment; A-share only); `stock_zh_a_hist_pre_min_em` (`view=pre_market`, explicit time-of-day range; A-share only) | `stock_hk_daily`; `stock_hk_hist_min_em` (`view=hk_intraday`, explicit datetime range/interval/adjustment; H-share only) | dated daily OHLCV/turnover extension facts from standard and Tencent daily history; chip-distribution, Tencent tick, Sina minute, A-share/H-share intraday and latest-day pre-market rows as raw structured evidence only |
| `MARKET_ACTIVITY` | `stock_lhb_detail_em` (inclusive `start_date`/`end_date`; A-share only); `stock_lhb_stock_statistic_em` (`view=stock_statistic`, explicit `period`; A-share only); `stock_lhb_jgstatistic_em` (`view=institution_statistic`, explicit `period`; A-share only) | — | A-share Dragon-Tiger detail, per-listing statistics or institution-seat statistics rows filtered to the requested listing as raw structured evidence only; no issuer cash-flow, shareholder-return, governance, market or valuation fact |
| `CAPITAL_FLOW` | `stock_individual_fund_flow` (A-share) | — | recent daily investor-flow rows as raw structured evidence only; no issuer cash-flow, liquidity or valuation fact |
| `CASH_FLOW_STATEMENT` | `stock_cash_flow_sheet_by_report_em` (Sina fallback) | `stock_financial_hk_report_em` | explicit `reported_cfo` and `acquisition_cash` lines |
| `INCOME_STATEMENT` | `stock_profit_sheet_by_report_em` (Sina fallback) | `stock_financial_hk_report_em` | explicit `parent_net_profit` and `consolidated_net_profit` lines |
| `EARNINGS_FORECAST` | `stock_yjyg_em` | — | A-share quarterly forecast rows as raw structured evidence only; no reported-profit fact |
| `EARNINGS_QUICK_REPORT` | `stock_yjkb_em` | — | A-share quarterly quick-report rows as raw structured evidence only; no canonical profit or revenue fact |
| `PERFORMANCE_REPORT` | `stock_yjbb_em` | — | A-share quarterly headline performance rows as raw structured evidence only; no canonical profit or CFO fact |
| `BUSINESS_COMPOSITION` | `stock_zygc_em` | — | A-share historical main-business composition rows as raw structured evidence only; no canonical revenue, margin or business-quality fact |
| `FINANCIAL_ABSTRACT` | `stock_financial_abstract` | — | A-share historical key-indicator matrix as raw structured evidence only; no canonical revenue, profit or CFO fact |
| `FINANCIAL_INDICATORS` | `stock_financial_analysis_indicator_em` | `stock_financial_hk_analysis_indicator_em` | A/H historical financial-indicator rows as raw structured evidence only; no canonical revenue, profit, CFO, metric or valuation input |
| `GOODWILL_IMPAIRMENT` | `stock_sy_jz_em` (exact `date`) | — | A-share report-date goodwill/impairment rows as raw structured evidence only; no canonical goodwill or impairment fact |
| `ESG_RATINGS` | `stock_esg_rate_sina` (no parameters) | `stock_esg_rate_sina` (no parameters) | mixed A/H agency, rating, quarter and marker rows as raw structured evidence only; no canonical ESG score, governance or Business Quality fact |
| `MARGIN_TRADING` | `stock_margin_detail_sse` (exact `date`; Shanghai A-share), `stock_margin_detail_szse` (exact `date`; Shenzhen A-share) and `stock_margin_detail_bse` (exact `date`; Beijing A-share) | — | requested-date SSE/SZSE/BSE security-level margin rows as raw structured evidence only; no issuer debt/cash/leverage/valuation fact |
| `EXTERNAL_GUARANTEES` | `stock_cg_guarantee_cninfo` (`symbol=全部`, date range; A-share only) | — | A-share date-range external-guarantee universe filtered to the requested listing as raw evidence only; no canonical quasi-debt, illegal-guarantee or governance fact |
| `LITIGATION` | `stock_cg_lawsuit_cninfo` (`symbol=全部`, date range; A-share only) | — | A-share date-range company-litigation universe filtered to the requested listing as raw evidence only; no canonical litigation, quasi-debt or governance fact |
| `LATEST_INDICATORS` | — | `stock_hk_financial_indicator_em` | H-share symbol-scoped latest-indicator row as raw structured evidence only; no canonical financial, share, dividend, market-cap, metric or valuation input |
| `BALANCE_SHEET` | `stock_zcfz_em` / `stock_zcfz_bj_em` (detailed report-period and Sina fallbacks) | `stock_financial_hk_report_em` | explicit `book_cash`, equity totals and aggregate interest-bearing debt when labeled |
| `DIVIDENDS` | `stock_dividend_cninfo`; `stock_fhps_em` (explicit report date) | `stock_hk_dividend_payout_em`; `stock_hk_fhpx_detail_ths` (`view=event_detail`) | raw structured evidence only; no canonical dividend cash or payout ratio |
| `DISCLOSURE_NOTICES` | `stock_zh_a_disclosure_report_cninfo` (`market=沪深京`, optional filters/date range) | — | listing-bound announcement metadata as raw structured evidence only; no filing-content, accounting or governance fact |
| `CORPORATE_ACTIONS` | `stock_repurchase_em` (no parameters); `stock_allotment_cninfo` (date-range request) | — | A-share repurchase or rights-issue rows; raw structured evidence only; no canonical buyback, issuance or dilution fact |
| `SHARE_CAPITAL` | `stock_zh_a_gbjg_em` (no parameters); `stock_share_change_cninfo` (explicit date range); `stock_restricted_release_queue_em` (`view=restricted_release_queue`); `stock_individual_info_em` (`view=individual_info`) | — | raw historical response or current item/value snapshot and provenance only; no canonical share/dilution fact |
| `OWNERSHIP_PLEDGE` | `stock_gpzy_pledge_ratio_em` (exact `date`); `stock_gpzy_individual_pledge_ratio_detail_em` (`view=individual_pledge_detail`); `stock_cg_equity_mortgage_cninfo` (`view=equity_mortgage`, `date`) | — | date-bound snapshot, symbol-scoped detail or CNINFO pledge-event rows as raw structured evidence only; no canonical governance, share, cash or debt-equivalent fact |
| `INSIDER_SHARE_CHANGES` | `stock_share_hold_change_sse` (Shanghai); `stock_share_hold_change_szse` (Shenzhen); `stock_share_hold_change_bse` (Beijing); `stock_hold_management_detail_em` (`view=management_detail`, no upstream arguments, full universe filtered to requested A-share) | — | listing-scoped exchange rows or management/related-person holding-change rows as raw structured evidence only; no canonical share, dilution, governance, buyback or issuance fact |
| `SHAREHOLDER_HOLDINGS` | `stock_main_stock_holder` (`stock`); `stock_hold_num_cninfo` (exact quarter-end `date`); `stock_hold_control_cninfo` (`view=control_changes`, optional `control_type`); `stock_gdfx_top_10_em` (`view=top_10`, exact quarter-end `date`); `stock_gdfx_free_top_10_em` (`view=free_top_10`, exact quarter-end `date`); `stock_gdfx_free_holding_detail_em` (`view=free_holding_detail`, exact quarter-end `date`); `stock_hsgt_individual_em` (`view=hsgt_individual`) | `stock_hsgt_individual_em` (`view=hsgt_individual`) | A-share main-shareholder/shareholder-count/actual-controller/top-ten/top-ten-tradable/top-ten-tradable-detail holding-change or A/H HSGT investor-holding rows as raw structured evidence only; no canonical ownership, concentration, share, dilution or governance fact |

The adapter accepts common stable A/H identifiers such as `SH600000`,
`000001.SZ`, `A:600000`, `HK00700`, `700.HK` and `H:00700`. A-share daily
history passes the supported period, date-range and adjustment parameters to
AKShare. The A-share `stock_zh_a_hist_min_em` view passes an explicit datetime
range, one of the documented minute intervals and adjustment mode, validates
the period-specific response shape and retains the response as raw evidence;
it does not promote minute bars into canonical daily history or valuation
inputs.
The H-share `stock_hk_hist_min_em` view passes the six-digit H-share code,
explicit datetime range, one of the documented minute intervals and adjustment
mode to the Eastmoney endpoint. Period `1` rows must contain `时间`, OHLC,
`成交量`, `成交额` and `最新价`; the other documented intervals must contain
`时间`, OHLC, change fields, `成交量`, `成交额`, `振幅` and `换手率`. The adapter
binds the inclusive range, strict timestamp order, listing scope and
`shares`/`HKD_per_share`/`HKD` units into replay metadata. The normalizer keeps
these recent H-share minute bars as raw evidence only; they do not establish
canonical daily history or valuation inputs.
The A-share `stock_cyq_em` view passes the unprefixed six-digit listing code and
the documented empty-string, `qfq` or `hfq` adjustment mode to the latest-chip-
distribution endpoint. The adapter validates the exact `日期`, `获利比例`,
`平均成本`, `90成本-低`, `90成本-高`, `90集中度`, `70成本-低`, `70成本-高`
and `70集中度` fields, finite numeric/null values, ISO dates in strict ascending
order and the documented maximum of 90 rows. The normalizer keeps these
provider-derived benefit/cost/concentration observations as raw evidence only;
they do not establish canonical daily history or valuation inputs.
The A-share `stock_zh_a_hist_tx` view passes the market-prefixed symbol and
effective date range and adjustment mode to the documented Tencent endpoint,
whose official defaults are `19000101` and `20500101` with no adjustment. The
adapter binds the exact dated row shape and inclusive range to the request,
records `shares` volume and `CNY` amount units, and maps only the existing
dated daily-history extension facts; the provider's decimal turnover ratio
remains raw evidence because the existing `historical_turnover` contract is an
amount field.
The A-share `stock_zh_a_tick_tx_js` view passes the market-prefixed symbol to
the documented Tencent latest-trading-day tick callable. The adapter requires
the explicit `tencent_tick` view, validates the time-only trade rows and one
known amount-column spelling (`成交金额` or `成交额`), records `lots` volume,
`CNY_per_share` price, `CNY` amount, recognized trade sides and non-decreasing
time order, and preserves the exact amount spelling for replay. Because the
response has no trading date, the normalizer retains it as raw evidence only.
The current H-share daily endpoint returns a full history, so the normalizer
applies an explicitly requested date range deterministically after replay;
the raw record remains the upstream response.

The `akshare` package is optional and loaded only at the first live fetch.
Tests inject a client object and use frozen JSON fixtures. The existing
`fetch_with_cache` helper remains the only cache boundary: `offline=True`
never calls AKShare, and a failed live request is never written as a snapshot.

The normalizer emits `Fact` and `Evidence` objects inside the existing
`NormalizedCompanyInput`. For the earnings-forecast, earnings-quick-report,
performance-report, business-composition, financial-abstract,
financial-indicator, latest-indicator, dividend event/detail, disclosure-notice,
risk-warning-status, trading-suspension, restricted-share-release,
goodwill-impairment, ESG-rating, margin-trading, corporate-action,
external-guarantee, company-litigation, share-capital, ownership-pledge,
main-shareholder, shareholder-count, top-ten-shareholder,
top-ten-tradable-shareholder, top-ten-tradable-shareholder-detail,
insider-share-change, management-holding,
individual-info, individual-fund-flow, chip-distribution, Tencent latest-trading-day tick, Sina minute-history, A-share/H-share intraday-history, pre-market-history and
five-level bid-ask
raw slices it emits
raw-record evidence only and explicit unresolved flags where needed; it does
not emit canonical forecast-profit, revenue, margin, dividend, buyback,
issuance, dilution, share, governance, pledged-cash, quasi-debt,
illegal-guarantee, debt-equivalent, current-price, liquidity or valuation facts.
The Tencent daily-history slice is the dated-series exception in this group:
after replay-scope validation, it maps its dated OHLC, shares volume and CNY
amount into the existing daily-history extension facts. Its raw turnover ratio
does not expand that canonical contract or become a valuation input.
The Tencent latest-trading-day tick slice remains raw evidence because its
time-only trade observations have no trading date and therefore cannot
establish a canonical daily-history period, cross-frequency liquidity measure
or valuation input. Its explicit view, derived symbol, amount-column variant,
units and time ordering remain part of the replay scope.
The chip-distribution slice remains raw evidence because its provider-derived
benefit, cost and concentration fields describe a rolling latest-90-trading-day
window rather than the canonical daily-history contract. Its explicit view,
unprefixed listing symbol, adjustment mode, exact field set, row limit and
observed date bounds remain part of the replay scope.
Margin-trading rows remain raw evidence because security-level investor
financing balances and quantities are not issuer accounting debt or cash.
Shareholder-count rows remain raw evidence because quarter-end shareholder
counts, average holdings and change percentages do not establish a canonical
concentration metric, governance judgment or company-level diluted-share
series. HSGT individual-holdings rows remain raw evidence because
north-/southbound investor holdings, market values, ratios and dated changes do
not establish beneficial control, concentration, issuer corporate-action cash
or a company-level diluted-share series; the request scope is retained because
the official response drops row-level security identity.
Management-holding rows remain raw evidence because transaction quantities,
prices, roles, relationships and beginning/ending holdings do not establish a
company-level diluted-share series, beneficial ownership, issuer corporate-action
cash or a governance-risk judgment.
It never maps provider headline market cap,
listing-years inferred from history length, unlisted financial-statement lines,
total liabilities as interest-bearing debt, filing classifications, or any
CDC/net-cash/Through Return/valuation/gate result. The statement slices
preserve exact periods and explicit nulls and reject ambiguous duplicate
periods/items.

Open mapping questions intentionally left for later review are: an explicit
A-share first-trading date and listing-status source, point-in-time treatment
of delayed/closed quote timestamps, FX and A/H cross-listing share equivalence,
whether the H-share full-history endpoint can be replaced by a bounded range
endpoint without changing replay semantics, field-name coverage across all
A/H balance-sheet variants, consolidated-versus-standalone statement basis,
currency/unit scaling, the absence of parent-equity and interest-bearing-debt
aggregates in the documented A-share quarterly balance shape, and
point-in-time publication semantics. For the share-capital raw slices, the
remaining questions are the unit represented by `总股本` and the CNINFO numeric
holdings, whether each `变更日期` is an effective legal change date or a
point-in-time observation date, whether `公告日期` or `变动日期` is the
accepted event period, the treatment of options/convertibles and other
dilution, the economic relationship between A/H classes, and whether the
change-reason text can be used to classify buybacks, issuance or splits. For
the corporate-action raw slice, the planned-versus-completed status, cumulative
amount scope and
announcement-date versus cash-period semantics remain unresolved. None of
those classifications is admitted automatically.
The period/total-cash/ordinary-versus-special classification needed to
normalize dividend event rows also remains open. Missing or conflicting
statement currency metadata is handled conservatively as described above, but
a null currency still requires later source review before cross-currency
calculations. For the rights-issue slice, planned-versus-completed outcome,
effective-date basis, amount unit/scaling and share-class/dilution semantics
remain unresolved; no capital-action classification is admitted automatically.
For the ownership-pledge slices, the exact observation date and ratio are
retained for the requested A-share snapshot, while the individual detail view
also retains holder/institution, quantity, price, status and event-date rows.
The CNINFO equity-mortgage view retains every listing-filtered pledge-event
row, its query date, announcement date, pledgor/pledgee, quantities and
ratios. The query date is not promoted to an event or accounting period.
Affected-holder identity, controlling-owner status, governance severity,
pledged-cash accessibility, diluted-share treatment and debt-equivalent
classification remain unresolved; no governance-risk conclusion is admitted
automatically.
For the A-share external-guarantee slice, the date-range aggregate versus an
event or reporting period, guarantee purpose and legal status, the unit and
entity scope of the parent-equity denominator, and the treatment of the
published ratio as evidence rather than a governance metric remain unresolved;
no quasi-debt, illegal-guarantee or governance classification is admitted
automatically.
For the A-share company-litigation slice, the date-range aggregate versus an
event or statement period, lawsuit amount completeness, legal status,
accounting entity/scope and materiality threshold remain unresolved; no
litigation, quasi-debt or governance classification is admitted automatically.
For the A-share individual-fund-flow slice, the investor bucket definitions,
amount units, percentage denominators, netting scope and point-in-time meaning
remain provider-specific; its close price and return columns remain market
context rather than canonical quote/history replacements. No issuer cash-flow,
liquidity or valuation classification is admitted automatically.
For the A-share Dragon-Tiger market-activity slice, the full-universe date
range, listing code, `上榜日`, activity amounts and post-listing return columns
remain provider fields. The provider validates every code and inclusive event
date before filtering the response to the requested listing; the normalizer
retains the result as raw evidence only. No issuer cash-flow,
shareholder-return, governance, canonical market or valuation classification is
admitted automatically, and post-listing returns are not used as as-of facts.
For the A-share Dragon-Tiger stock-statistic slice, the full-universe listing
code, `最近上榜日`, selected statistic window, activity counts, amount
aggregates and trailing return columns remain provider fields. The provider
validates every code and recent listing date, records the explicit statistic
window and filters the response to the requested listing; the normalizer
retains the result as raw evidence only. No issuer cash-flow,
shareholder-return, governance, canonical market or valuation classification is
admitted automatically.
For the A-share Dragon-Tiger institution-statistic slice, the full-universe
listing code, selected statistic window, institution activity counts/amounts
and trailing return columns remain provider fields. The provider validates
every code, records the explicit institution-statistic window and filters the
response to the requested listing; the normalizer retains the result as raw
evidence only. No issuer cash-flow, shareholder-return, governance, canonical
market or valuation classification is admitted automatically.
For the A-share five-level bid-ask slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ask_bid_em.py)
define `stock_bid_ask_em` with a six-digit `symbol` and a fixed `item`/`value`
response containing five ask levels, five bid levels and quote-context rows.
The provider selects it only under `MARKET_QUOTE` with explicit
`view=bid_ask` for Shanghai/Shenzhen A-share listings, passes the normalized
listing code, validates the exact documented 36-item vocabulary and records
the listing, view and current-snapshot scope in response metadata. The
normalizer emits `AKSHARE_BID_ASK_RAW_ONLY` and retains the snapshot as raw
evidence; because the response has no stable observation timestamp, its latest
price, volumes, turnover and quote-context values do not replace the
canonical current-price fact or become liquidity/valuation inputs.
For the A-share intraday-history slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
define `stock_zh_a_hist_min_em` with a six-digit `symbol`, explicit datetime
range, minute interval and adjustment mode. The provider selects it only
under `MARKET_HISTORY` with `view=intraday`, validates the period-specific
columns, finite numeric/null values, ascending timestamps and range binding,
and records the effective request scope. The normalizer emits
`AKSHARE_INTRADAY_HISTORY_RAW_ONLY`; minute-bar OHLC, volume, turnover and
provider context do not replace canonical daily history or become valuation
inputs.
For the H-share intraday-history slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
define `stock_hk_hist_min_em` with a six-digit `symbol`, `period` `1`, `5`,
`15`, `30` or `60`, adjustment mode ``, `qfq` or `hfq`, and explicit
`start_date`/`end_date` datetimes. The documented period-1 response uses
`最新价`; the other period responses use `涨跌幅`, `涨跌额`, `振幅` and
`换手率` instead. The provider selects it only under `MARKET_HISTORY` with
explicit `view=hk_intraday`, validates the exact period-specific fields,
finite numeric/null values, strictly ascending timestamps and inclusive range,
and records the effective H-share symbol/range/interval/adjustment and
`shares`/`HKD_per_share`/`HKD` unit scope. The normalizer emits
`AKSHARE_HK_INTRADAY_HISTORY_RAW_ONLY`; these recent minute bars remain raw
evidence and do not replace canonical daily history or become valuation inputs.
For the A-share pre-market-history slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
define `stock_zh_a_hist_pre_min_em` with a six-digit `symbol` and explicit
`start_time`/`end_time` time-of-day bounds. The provider validates the exact
latest-trading-day row shape, finite numeric/null values, one trading date,
ascending timestamps and time-range binding, and records the effective
listing/time-window scope. The normalizer emits
`AKSHARE_PRE_MARKET_HISTORY_RAW_ONLY`; its latest-day minute rows do not replace
canonical daily history or become valuation inputs.
For the A-share Tencent daily-history slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_tx.py)
define `stock_zh_a_hist_tx` with a market-prefixed or six-digit `symbol`,
documented `19000101`/`20500101` date defaults and empty-string, `qfq` or `hfq`
adjustment modes. The provider selects it only under `MARKET_HISTORY` with
explicit `view=tencent_daily`, validates the exact dated OHLC/volume/turnover/
amount fields, finite numeric/null values, ascending dates and inclusive range
binding, and records the listing, symbol, dates, adjustment and unit scope. The
normalizer maps the existing daily-history extension fields with `shares`
volume and `CNY` amount units; the provider turnover ratio remains raw-only.
For the A-share Sina minute-history slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py)
define `stock_zh_a_minute` with a market-prefixed `symbol`, a `period` of `1`,
`5`, `15`, `30` or `60`, and an adjustment mode of empty string, `qfq` or
`hfq`. The provider selects it only under `MARKET_HISTORY` with explicit
`view=sina_minute`, validates the exact `day`/OHLCV/amount row shape, finite
numeric/null values and strictly ascending timestamps, and records the
effective listing, interval, adjustment and recent-window scope. The
normalizer emits `AKSHARE_SINA_MINUTE_HISTORY_RAW_ONLY`; this recent provider
window does not replace canonical daily history or become a valuation input.
For the A-share dividend-distribution snapshot, the explicit June-30 or
December-31 report date and listing-filtered rows are retained, but ratio units,
settled cash status, ordinary-versus-special classification and payout
denominator remain unresolved; no dividend-cash or payout-ratio fact is
admitted automatically.
For the A-share earnings-forecast slice, the exact quarter-end report date and
listing-filtered rows are retained, but forecast ranges, forecast type,
publication timing and reported-profit entity semantics remain unresolved; no
parent or consolidated net-profit fact is admitted automatically.
For the A-share performance-report slice, the exact quarter-end report date
and listing-filtered rows are retained, but the headline net-profit entity
basis and per-share operating-cash-flow denominator remain unresolved; no
parent, consolidated net-profit or reported-CFO fact is admitted automatically.
For the A-share earnings-quick-report slice, the exact quarter-end report date
and listing-filtered rows are retained, but the headline profit/revenue
presentation, entity basis, units and diluted-share semantics remain unresolved;
no parent, consolidated net-profit or revenue fact is admitted automatically.
For the A-share business-composition slice, the listing-scoped historical rows
and report dates are retained, but product/industry/geographic overlap,
aggregation, units, entity basis and core-business classification remain
unresolved; no revenue, core-revenue, operating-profit or margin fact is
admitted automatically.
For the A-share financial-abstract slice, the listing-scoped historical matrix
and report-period columns are retained, but the mixed amount/per-share/ratio
rows do not establish canonical entity, unit/scaling, period or diluted-share
semantics; no revenue, parent/consolidated net-profit or reported-CFO fact is
admitted automatically.
For the H-share financial-indicator slice, the listing-scoped historical rows
and explicit `年度`/`报告期` mode are retained, but its amount, per-share and
provider-ratio fields do not settle canonical entity, unit/scaling,
point-in-time or calculation semantics; no revenue, parent/consolidated
net-profit or reported-CFO fact is admitted automatically. H-share
insider-share coverage remains unresolved because the current AKShare stock
documentation does not define an equivalent H-share insider endpoint. For the
H-share latest-indicator slice, the symbol-scoped row is retained, but its
absence of a canonical period and row-level identity, together with mixed
amount, per-share, capital, dividend and valuation semantics, leaves entity,
unit/scaling, diluted-share and calculation questions unresolved; no canonical
financial, share, dividend, market-cap, metric or valuation fact is admitted
automatically.
For the A-share disclosure-notice slice, listing-bound announcement code,
title, timestamp and link are retained, but announcement metadata does not
establish filing contents, an accounting opinion, a governance-risk judgment or
any canonical financial period; no filing-derived fact is admitted
automatically. The current AKShare documentation has no general H-share
disclosure-notice endpoint. The separately selected H-share dividend-event
detail response retains its dates, plan and status as raw evidence only; it
does not establish settled ordinary dividend cash or replace Phase 3 filing
retrieval/parsing.
The [AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hk_fhpx_detail_ths` as a symbol-scoped Tonghuashun dividend
detail response with announcement/ex/payment dates, plan, type, progress and
scrip context. It is selected only by the explicit `view=event_detail` request
selector; its response does not establish general H-share filing coverage or
row-level listing identity.

For the A-share risk-warning-status slice, the documented current-trading-day
universe and its listing-filtered result are retained as raw evidence only.
The presence of a row is not converted into a canonical special-treatment
fact, and the absence of a row is not converted into an explicit false value;
dated status history and the filing-backed reason remain unresolved.

For the A-share main-shareholder slice, the documented symbol-scoped historical
holder rows and their dates are retained as raw evidence only. Holder names,
quantities, ratios and share-class labels do not establish beneficial control,
materiality, a company-level diluted-share series or a filing-backed
governance conclusion.

For the A-share shareholder-count slice, the documented
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_num_cninfo.py)
define `stock_hold_num_cninfo` with an exact quarter-end `date` from
`20170331` onward. The provider validates each returned code and `变动日期`,
filters the full CNINFO universe to the requested A-share listing and retains
the current/prior shareholder counts, average holdings and change percentages
as raw evidence. A date-bearing `SHAREHOLDER_HOLDINGS` request selects this
endpoint; a request without `date` continues to select
`stock_main_stock_holder`. The normalizer emits
`AKSHARE_SHAREHOLDER_COUNTS_RAW_ONLY`, leaves `governance_risk_level` missing
and does not calculate concentration, beneficial-control, governance or
diluted-share facts.

For the A-share actual-controller holding-change slice, the current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
define `stock_hold_control_cninfo` with `symbol` selecting the documented
control scope and the published fields `证券代码`, `证券简称`, `变动日期`,
`实际控制人名称`, `控股数量`, `控股比例`, `直接控制人名称` and `控制类型`.
The provider selects it only with `view=control_changes`, defaults to the
documented `symbol=全部` universe, validates the explicit code and change date
before filtering to the requested A-share listing, and retains the control
scope in request/response provenance. The normalizer emits
`AKSHARE_CONTROL_HOLDINGS_RAW_ONLY`, leaves `governance_risk_level` critically
missing and creates no canonical ownership, control, share-count, dilution or
valuation fact: controller names and holding changes need filing-backed legal
and point-in-time interpretation.

For the A/H HSGT individual-holdings slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
define `stock_hsgt_individual_em` with a symbol input supporting A-share and
H-share listings. The provider selects it only with the explicit
`view=hsgt_individual` selector, passes the six- or five-digit code, validates
holding dates and retains the full symbol-scoped response. The implementation
dispatches A/H paths by symbol width and removes row-level security identity,
so no listing code is invented in the payload. Holdings, values, ratios and
change fields are investor-position evidence only; the normalizer emits
`AKSHARE_HSGT_INDIVIDUAL_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no ownership,
concentration, share-count, dilution, buyback, issuance, return or valuation
fact.

For the A-share management-holding slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
define `stock_hold_management_detail_em` as a no-argument Eastmoney universe
with `日期`, `代码`, `名称`, transaction quantity/price/amount/reason/ratio,
holding type, management name/position/relationship and beginning/ending
holdings. The provider selects it only with `view=management_detail`, validates
the explicit code and change date on every upstream row, filters the universe to
the requested A-share listing and records the upstream/selected row counts.
The normalizer emits `AKSHARE_MANAGEMENT_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and does not infer ownership,
share-count, dilution, buyback, issuance, return or valuation facts.

For the A-share individual-info slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_info_em.py)
define `stock_individual_info_em` as a symbol-scoped Eastmoney `item/value`
snapshot containing code/name, total and float shares, market values, latest
price, industry and listing date. The provider selects it only with
`SHARE_CAPITAL` `view=individual_info`, passes the six-digit code, validates the
returned code and populated `上市时间`, and retains every row with explicit
listing/view/snapshot provenance. The normalizer emits
`AKSHARE_INDIVIDUAL_INFO_RAW_ONLY`, marks
`normalized_diluted_economic_shares` critically missing and creates no
canonical share, market-cap or valuation fact because the snapshot's period,
unit and fully diluted economic scope remain unresolved.

For the A-share trading-suspension slice, the documented requested-date
universe and its listing-filtered result are retained as raw evidence only.
Suspension dates, duration and reasons do not establish a complete
special-treatment status, an accounting classification or a filing-backed
governance conclusion.

For the A-share restricted-share-release slice, the documented
`stock_restricted_release_queue_em` response is selected only with the explicit
`view=restricted_release_queue` selector and is retained as a symbol-scoped raw
response. Its release dates, planned/actual/remaining quantities, market-value
context and lock-up types do not establish a canonical diluted-economic-share
treatment or a share-count event. Optional row-level codes are checked when
present because the documented symbol-scoped response may omit them; H-share
coverage and filing-backed release interpretation remain unresolved.

For the A-share goodwill-impairment slice, the documented `stock_sy_jz_em`
report-date universe and its listing-filtered result are retained as raw
evidence only. `商誉` and `商誉减值` are aggregator amounts whose accounting
entity, statement scope, report-period basis and reconciliation to a primary
filing remain unresolved; provider ratios and `净利润` inherit the same raw
boundary. `公告日期` is publication metadata, not an admitted report or
recognition date, so no canonical goodwill, impairment or profit fact is
emitted automatically. H-share coverage and filing-backed impairment review
remain unresolved.

For the A/H ESG-rating slice, the documented `stock_esg_rate_sina` mixed
universe and its listing-filtered result are retained as raw evidence only.
`评级机构` scales and `评级` values can differ across agencies, and
`评级季度` is a provider reporting label rather than a canonical statement
period. `标识` remains opaque provider context, so no comparable ESG score,
governance-risk level or Business Quality fact is emitted automatically.

For the A-share external-guarantee slice, the documented
`stock_cg_guarantee_cninfo` universe and its requested-code result are retained
as raw evidence only. `公告统计区间` is an aggregate announcement interval,
while `担保金额`, `归属于母公司所有者权益` and
`担保金融占净资产比例` do not by themselves establish settled quasi-debt,
the guarantee's legal/purpose classification, a canonical denominator or a
governance-risk judgment. No material-quasi-debt, illegal-guarantee or
governance fact is emitted automatically; H-share coverage and filing-backed
review remain unresolved.

For the A-share company-litigation slice, the documented
`stock_cg_lawsuit_cninfo` universe and its requested-code result are retained
as raw evidence only. `公告统计区间` is an aggregate announcement interval,
while `诉讼次数` and `诉讼金额` do not by themselves establish a complete
liability, material expected cash obligation, canonical accounting period or
governance-risk judgment. No litigation, quasi-debt or governance fact is
emitted automatically; H-share coverage and filing-backed review remain
unresolved.

For the A-share individual ownership-pledge detail slice, the documented
`stock_gpzy_individual_pledge_ratio_detail_em` response and its requested-code
result are retained as raw evidence only. Its holder/institution identity,
quantities/ratios, prices, status and event dates do not establish beneficial
control, a fully diluted share count, settled pledged cash/debt-equivalent
amount or a governance judgment. No share, cash, debt-equivalent or governance
fact is emitted automatically; `governance_risk_level` remains critically
missing and H-share coverage plus filing-backed pledge interpretation remain
unresolved.

For the A-share CNINFO equity-mortgage slice, the documented
[`stock_cg_equity_mortgage_cninfo`](https://akshare.akfamily.xyz/data/stock/stock.html)
response and its requested-code result are retained as raw evidence only. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_equity_mortgage.py)
uses a CNINFO thematic-statistics response. Its query date, announcement date,
pledgor/pledgee, quantities, ratios and event description do not establish a
canonical pledge period, fully diluted share count, settled pledged
cash/debt-equivalent amount or a governance judgment. No share, cash,
debt-equivalent or governance fact is emitted automatically;
`governance_risk_level` remains critically missing and H-share coverage plus
filing-backed pledge interpretation remain unresolved.

For the A-share top-ten-shareholder slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
define `stock_gdfx_top_10_em` with a market-prefixed `symbol` and an exact
quarter-end `date`. The provider selects it only with
`SHAREHOLDER_HOLDINGS` plus `view=top_10`, passes the requested symbol and
report date, validates rank/holder identity plus any optional row code, and
retains the complete symbol-scoped response with report-period provenance. It
does not invent a row-level code or filing date. The normalizer emits
`AKSHARE_TOP_10_SHAREHOLDERS_RAW_ONLY`, leaves `governance_risk_level`
critically missing and creates no beneficial-control, concentration, share,
dilution or valuation fact.

For the A-share top-ten-tradable-shareholder slice, the current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
define `stock_gdfx_free_top_10_em` with a market-prefixed `symbol` and an exact
quarter-end `date`. The provider selects it only with
`SHAREHOLDER_HOLDINGS` plus `view=free_top_10`, passes the requested symbol and
report date, validates rank/holder identity plus any optional row code, and
retains the complete symbol-scoped response with report-period provenance. It
does not invent a row-level code or filing date. The normalizer emits
`AKSHARE_FREE_TOP_10_SHAREHOLDERS_RAW_ONLY`, leaves `governance_risk_level`
critically missing and creates no beneficial-control, concentration, share,
dilution or valuation fact.

For the A-share top-ten-tradable-shareholder detail slice, the current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
define `stock_gdfx_free_holding_detail_em` as a full A-share universe endpoint
accepting an exact quarter-end `date`. The provider selects it only with
`SHAREHOLDER_HOLDINGS` plus `view=free_holding_detail`, passes the requested
report date, validates every explicit listing code and report-period value plus
holder identity and optional announcement dates, and filters the universe to
the requested listing. It retains the report-period holding detail,
quantity/change, float-market-value and announcement fields as raw evidence
without treating them as filing dates or canonical ownership, concentration,
share, dilution or governance facts. The normalizer emits
`AKSHARE_FREE_HOLDING_DETAIL_RAW_ONLY` and leaves `governance_risk_level`
critically missing.

## 13. Deliberate non-goals

This foundation plus the Phase 2.2–2.58 slices does not include:

- Tushare, BaoStock or any other additional provider;
- automatic network scheduling, credentials or retry orchestration outside an adapter;
- official filing retrieval or PDF parsing;
- LLM evidence extraction or Business Quality scoring;
- a normalized-data database, web service, scheduler or event monitor;
- additional financial-statement categories beyond the documented slices or
  economic classifications inside the adapter;
- financial calculations inside provider classes.

Future provider categories must be added one at a time behind these
interfaces and validated against frozen normalized fixtures before being used
in screening.
