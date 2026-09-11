# Provider and Cache Architecture

> Status: Phase 2 foundation and Phase 3.21 structured acquisition, read-only AKShare statement slices, earnings forecasts/quick reports/performance reports/business composition/financial abstract/financial indicators, H-share latest indicators, A-share disclosure-notice metadata including the Eastmoney individual-notice, market-wide notice and shareholder-meeting views, risk-warning status, trading-suspension, restricted-share-release, goodwill-impairment detail/goodwill-detail/impairment-forecast/market-profile/industry-data, ESG-rating, SSE/SZSE/BSE margin-detail, share-capital, individual-info snapshot, corporate-action including IPO-summary and Eastmoney IPO-yield, external-guarantee, company-litigation, ownership-pledge snapshot/detail/company-distribution/bank-distribution/industry-data/market-profile/important-shareholder-detail, main-shareholder, shareholder-count/shareholder-count-detail, A-share actual-controller holding-change, A/H HSGT individual-holdings, SSE/SZSE/BSE insider-share-change, A-share Eastmoney/CNINFO management-holding and executive/shareholder-change, A-share top-ten/top-ten-tradable-shareholder/top-ten-tradable-shareholder-detail, Dragon-Tiger market-activity detail/statistics/institution-statistics/institution-daily/institutional-research/institutional-research-detail/market-participation-desire/market-focus/institution-participation/block-trade-detail/hot-rank/latest-hot-rank/A-share historical-hot-rank/limit-up-pool/limit-down-pool/H-share latest-hot-rank/H-share historical-hot-rank/new-stock-board, A+B/A+H quote-comparison, A-share Eastmoney/Sina intraday-trade, Tencent daily-history/latest-trading-day tick, Sina minute-history, A-share/H-share intraday-history, pre-market-history and five-level bid-ask raw slices, SSE/SZSE market-summary, SZSE area-summary/sector-summary and Eastmoney industry-board, stock-account-statistics and Legu market-activity/congestion/equity-bond-spread/Buffett-index/A-share PE/PB-history, index-PE/index-PB, market-PE/market-PB, A-share Eastmoney valuation-comparison and A/H Baidu valuation-history raw slices

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

Phase 2 and the numbered Phase 3.21 increment add structured acquisition and
replay infrastructure only. The top-level Phase 3 filing/evidence work remains
the boundary for official filing retrieval and filing-derived evidence.

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

The A-share goodwill market-profile slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sy_profile_em` as a no-argument Eastmoney market overview
returning historical `报告期` rows with goodwill, goodwill impairment, net
assets, net-profit scale and provider ratios. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
returns eight exact fields, with amount columns in yuan. The provider selects
this endpoint only with explicit `view=market_profile`, validates the exact
schema, finite numeric/null values and strictly ascending report periods, and
records the market-wide A-share scope plus CNY/provider-ratio context. The
requested listing is provenance context only because the response has no
issuer identity; the normalizer emits
`AKSHARE_GOODWILL_PROFILE_RAW_ONLY`, leaves `goodwill` and `impairment`
critically missing and creates no canonical fact because the aggregate history
mixes annual/interim periods and requires primary-filing entity, scope and
reconciliation review.

For the A-share goodwill-industry slice, the documented `stock_sy_hy_em`
response is retained as raw evidence only. Its date-filtered market-wide rows
contain industry names, company counts, goodwill, net-assets, a provider ratio
and net-profit aggregates; the wrapper drops the report date and change-rate
columns, so the requested `date=YYYYMMDD` remains the explicit report-period
binding. The adapter validates the six-field order, unique industry identity,
non-increasing ratio ordering, finite values, non-negative integer company
counts and the fixed `RPT_GOODWILL_INDUSTATISTICS` all-page/sort/filter
contract. It records CNY amount context, undocumented count/ratio units and
source/drop metadata, while preserving signed profit values. The normalizer
emits `AKSHARE_GOODWILL_INDUSTRY_DATA_RAW_ONLY`, leaves `goodwill` and
`impairment` critically missing and creates no canonical accounting, profit,
ratio or Business Quality fact. H-share coverage and primary-filing issuer
scope/reconciliation remain unresolved.

The A-share goodwill-impairment forecast slice is also acquisition-only. The
current [AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sy_yq_em` as the dated Eastmoney goodwill-impairment forecast
detail view; the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
filters by a required `YYYYMMDD` report date and returns 14 fields covering
listing identity, goodwill context, expected-profit/range values, announcement
date and market; the documented amount fields are primarily yuan and the
change-range fields are percent values. The provider selects it only with explicit
`view=impairment_forecast`, validates the complete universe's exact schema,
positive ascending sequence, nullable dates/numbers and text fields, then
filters to the requested A-share code. Replay metadata records the request
period, market-wide upstream scope and provider row filtering. The normalizer
emits `AKSHARE_GOODWILL_FORECAST_RAW_ONLY`, leaves `goodwill` and `impairment`
critically missing and creates no canonical accounting, forecast, profit or
ratio fact because provider expectations and goodwill context require
primary-filing entity, period and reconciliation review.

The A-share goodwill-detail slice is also acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sy_em` as a date-filtered Eastmoney response; the [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
returns the exact ten fields `序号`, `股票代码`, `股票简称`, `商誉`,
`商誉占净资产比例`, `净利润`, `净利润同比`, `上年商誉`, `公告日期` and
`交易市场`. The provider selects it only with explicit
`view=goodwill_detail`, passes the required report date, validates the complete
A-share universe's sequence, identity, nullable date/numeric fields and text
schema, then filters the requested listing. Amounts are retained with
`amount_unit=CNY` and ratios with `ratio_unit=provider_reported_ratio`; replay
metadata records the request-period and provider-filter scope. The normalizer
emits `AKSHARE_GOODWILL_DETAIL_RAW_ONLY`, leaves `goodwill` and `impairment`
critically missing and creates no canonical accounting, profit, ratio or
Business Quality fact pending primary-filing scope and reconciliation review.

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

## 12. Phase 2.2–3.21 AKShare adapter

The first concrete adapter is intentionally limited to read-only metadata,
market observations, three documented financial-statement slices, raw-only
earnings-forecast, earnings-quick-report, performance-report,
business-composition and financial-abstract categories, A/H financial-indicator
raw slices, raw-only dividend event/snapshot/detail including the A-share
Eastmoney distribution-detail view, corporate-action including the A-share
CNINFO IPO-summary and Eastmoney IPO-yield views,
external-guarantee and company-litigation categories,
four A-share share-capital raw slices, eight A-share ownership-pledge raw views,
an H-share latest-indicator raw slice, an A-share disclosure-notice raw slice
including the Eastmoney individual-notice, market-wide notice and
shareholder-meeting views,
an A-share risk-warning-status, trading-suspension, goodwill-impairment
detail/goodwill-detail/impairment-forecast/market-profile/industry-data,
ESG-rating, SSE/SZSE/BSE margin-detail, external-guarantee, company-litigation,
main-shareholder/shareholder-count/actual-controller holding-change/HSGT
individual-holdings raw slices, A-share Eastmoney individual-fund-flow,
top-ten-shareholder/top-ten-tradable-shareholder/top-ten-tradable-shareholder-detail,
Dragon-Tiger detail/statistics/institution-statistics/block-trade-detail and
market-participation-desire/market-focus/institution-participation/
stock-hot-rank/latest-stock-hot-rank/A-share-historical-stock-hot-rank/
limit-up-pool/limit-down-pool/new-stock-board market-activity, SSE/SZSE
market-summary, SZSE area-summary/sector-summary and Eastmoney industry-board raw slices, the A+H quote-comparison and
Xueqiu individual-spot quote,
A-share Xueqiu, CNINFO and Tonghuashun company-profile,
SSE/SZSE/BSE insider-share-change, A-share Eastmoney management-holding,
management-person and executive/shareholder-change,
A-share Eastmoney intraday-trade/chip-distribution, Tencent daily-history and latest-trading-day tick, Sina minute-history,
A-share/H-share intraday-history, pre-market-history and five-level bid-ask raw
slices, and the H-share Eastmoney main-board quote raw slice. It
advertises exactly these capabilities:

| Category | A-share endpoint | H-share endpoint | Normalized output |
| --- | --- | --- | --- |
| `COMPANY_METADATA` | `stock_info_a_code_name`; `stock_individual_basic_info_xq` (`view=xueqiu_basic_info`, symbol-scoped A-share profile); `stock_profile_cninfo` (`view=cninfo_profile`, symbol-scoped A-share profile); `stock_zyjs_ths` (`view=business_intro`, symbol-scoped A-share main-business introduction) | `stock_hk_company_profile_em` (with conservative metadata-list fallbacks) | company metadata extension facts and nullable `Company` context enrichment from the existing metadata endpoint; Xueqiu, CNINFO and Tonghuashun profiles remain raw-only |
| `LISTING_METADATA` | `stock_info_a_code_name` | `stock_hk_security_profile_em` (with conservative listing-list fallbacks) | listing code/name/date/exchange and other explicit metadata facts |
| `RISK_WARNING_STATUS` | `stock_zh_a_st_em` (no parameters) | — | current A-share risk-warning-board membership as raw structured evidence only; no canonical `special_treatment` fact |
| `TRADING_SUSPENSIONS` | `stock_tfp_em` (exact `date`) | — | requested-date A-share suspension/resumption rows as raw structured evidence only; no canonical status or governance fact |
| `MARKET_QUOTE` | `stock_zh_a_spot_em`; `stock_bid_ask_em` (`view=bid_ask`, Shanghai/Shenzhen A-share only); `stock_individual_spot_xq` (`view=xueqiu_spot`, symbol-scoped A-share quote); `stock_zh_ah_spot_em` (`view=ah_comparison`, full A+H universe filtered by requested A/H side); `stock_zh_ab_comparison_em` (`view=ab_comparison`, full A+B universe filtered by requested A-share side) | `stock_hk_spot_em`; `stock_hk_main_board_spot_em` (`view=hk_main_board`, full H-share main-board universe filtered by requested H-share); `stock_zh_ah_spot_em` (`view=ah_comparison`, full A+H universe filtered by requested H-share side) | selected-listing `current_price` plus quote timestamp; Xueqiu current price/timestamp use the existing quote contract while other Xueqiu fields, bid/ask, H-share main-board, A+B and A+H comparison views remain raw-only |
| `MARKET_HISTORY` | `stock_zh_a_hist` (daily history); `stock_intraday_em` (`view=intraday_trades`, latest-trading-day time-only trades; A-share only); `stock_intraday_sina` (`view=intraday_sina`, requested-date time-only large-order rows; A-share only); `stock_cyq_em` (`view=chip_distribution`, latest 90 trading days and adjustment; A-share only); `stock_zh_a_hist_tx` (`view=tencent_daily`, explicit date range/adjustment; A-share only); `stock_zh_a_tick_tx_js` (`view=tencent_tick`, latest-trading-day time-only ticks; A-share only); `stock_zh_a_minute` (`view=sina_minute`, explicit interval/adjustment; A-share only); `stock_zh_a_hist_min_em` (`view=intraday`, explicit datetime range/interval/adjustment; A-share only); `stock_zh_a_hist_pre_min_em` (`view=pre_market`, explicit time-of-day range; A-share only) | `stock_hk_daily`; `stock_hk_hist_min_em` (`view=hk_intraday`, explicit datetime range/interval/adjustment; H-share only) | dated daily OHLCV/turnover extension facts from standard and Tencent daily history; Eastmoney/Sina intraday-trade, chip-distribution, Tencent tick, Sina minute, A-share/H-share intraday and latest-day pre-market rows as raw structured evidence only |
| `MARKET_ACTIVITY` | `stock_zh_a_new_em` (`view=new_stock`, current-trading-day new-stock universe; A-share only); `stock_comment_detail_scrd_desire_em` (`view=participation_desire`, latest 30 trading days; A-share only); `stock_comment_detail_scrd_focus_em` (`view=focus`, latest 30 trading days; A-share only); `stock_comment_detail_zlkp_jgcyd_em` (`view=institution_participation`, symbol-scoped historical series; A-share only); `stock_hot_rank_em` (`view=hot_rank`, current-trading-day top 100; A-share only); `stock_hot_rank_latest_em` (`view=hot_rank_latest`, symbol-scoped latest rank; A-share only); `stock_hot_rank_detail_em` (`view=hot_rank_detail`, symbol-scoped recent historical dates; A-share only); `stock_zt_pool_em` (`view=limit_up_pool`, requested `date` limit-up pool; A-share only); `stock_zt_pool_dtgc_em` (`view=limit_down_pool`, requested `date` limit-down pool; A-share only); `stock_lhb_detail_em` (inclusive `start_date`/`end_date`; A-share only); `stock_lhb_stock_statistic_em` (`view=stock_statistic`, explicit `period`; A-share only); `stock_lhb_jgstatistic_em` (`view=institution_statistic`, explicit `period`; A-share only); `stock_dzjy_mrmx` (`view=block_trade_detail`, A-share `symbol="A股"` and inclusive date range; full universe filtered to requested listing); `stock_lhb_jgmmtj_em` (`view=institution_daily`, inclusive date range; full universe filtered to requested listing); `stock_jgdy_tj_em` (`view=institution_research`, strict `公告日期` after requested `date`; full universe filtered to requested listing); `stock_jgdy_detail_em` (`view=institution_research_detail`, strict `调研日期` after requested `date`; full universe filtered to requested listing); `stock_board_industry_name_em` (`view=industry_board`, current industry-board snapshot; A-share only); `stock_szse_sector_summary` (`view=szse_sector_summary`, requested `symbol=当月` or `当年` and `date=YYYYMM` industry summary; A-share only); `stock_szse_area_summary` (`view=szse_area_summary`, requested `date=YYYYMM` region-ranked market summary; A-share only); `stock_szse_summary` (`view=szse_summary`, requested `date=YYYYMMDD` security-category market summary; A-share only); `stock_sse_summary` (`view=sse_summary`, latest market summary; A-share only); `stock_sse_deal_daily` (`view=sse_deal_daily`, requested `date=YYYYMMDD` overview; A-share only); `stock_account_statistics_em` (`view=account_statistics`, no upstream arguments, market-wide monthly history; A-share only); `stock_market_activity_legu` (`view=market_activity_legu`, no upstream arguments, current snapshot; A-share only); `stock_a_congestion_lg` (`view=congestion`, no upstream arguments, latest-four-year market history; A-share only); `stock_ebs_lg` (`view=equity_bond_spread`, no upstream arguments, all historical market context; A-share only); `stock_buffett_index_lg` (`view=buffett_index`, no upstream arguments, all historical market-capitalization/GDP context; A-share only); `stock_a_ttm_lyr` (`view=ttm_lyr`, no upstream arguments, all historical A-share TTM/LYR PE context; A-share only); `stock_a_all_pb` (`view=all_pb`, no upstream arguments, all historical A-share PB context; A-share only); `stock_index_pe_lg` (`view=index_pe`, required `symbol` in the 12 documented index choices, all historical index-level PE context; A-share only); `stock_index_pb_lg` (`view=index_pb`, required `symbol` in the 12 documented index choices, all historical index-level PB context; A-share only); `stock_market_pe_lg` (`view=market_pe`, required `symbol` in `上证`/`深证`/`创业板`/`科创版`, all historical board/index PE context; A-share only); `stock_market_pb_lg` (`view=market_pb`, required `symbol` in `上证`/`深证`/`创业板`/`科创版`, all historical board/index PB context; A-share only); `stock_zh_valuation_baidu` (`view=valuation_baidu`, listing-scoped indicator/period history; A-share only) | `stock_hk_hot_rank_latest_em` (`view=hot_rank_latest`, symbol-scoped latest rank; H-share only); `stock_hk_hot_rank_detail_em` (`view=hk_hot_rank_detail`, symbol-scoped historical dates; H-share only); `stock_hk_valuation_baidu` (`view=valuation_baidu_hk`, listing-scoped indicator/period history; H-share only) | A-share/H-share latest stock-popularity rank, A-share/H-share historical stock-popularity rank and the existing A-share new-stock-board, market-participation-desire, market-focus, institution-participation, limit-up-pool, limit-down-pool, Dragon-Tiger detail, per-listing statistics, institution-seat statistics, institution-daily, institutional-research, institutional-research-detail or block-trade detail rows plus Eastmoney industry-board, SSE/SZSE market-summary, SZSE area-summary/sector-summary, market-wide stock-account-statistics, Legu market-activity, congestion, equity-bond-spread, Buffett-index, TTM/LYR PE, PB, index-PE, index-PB, market-PE, market-PB and A/H Baidu valuation-history aggregates retained as raw structured evidence only; no issuer cash-flow, shareholder-return, governance, market or valuation fact |
| `MARKET_ACTIVITY` (valuation comparison) | `stock_zh_valuation_comparison_em` (`view=valuation_comparison`, A-share listing-scoped peer table) | — | target, industry-summary and ranked-peer valuation-comparison rows retained as raw structured evidence only; no canonical valuation or accounting fact |
| `CAPITAL_FLOW` | `stock_individual_fund_flow` (A-share) | — | recent daily investor-flow rows as raw structured evidence only; no issuer cash-flow, liquidity or valuation fact |
| `CASH_FLOW_STATEMENT` | `stock_cash_flow_sheet_by_report_em` (Sina fallback) | `stock_financial_hk_report_em` | explicit `reported_cfo` and `acquisition_cash` lines |
| `INCOME_STATEMENT` | `stock_profit_sheet_by_report_em` (Sina fallback) | `stock_financial_hk_report_em` | explicit `parent_net_profit` and `consolidated_net_profit` lines |
| `EARNINGS_FORECAST` | `stock_yjyg_em` | — | A-share quarterly forecast rows as raw structured evidence only; no reported-profit fact |
| `EARNINGS_QUICK_REPORT` | `stock_yjkb_em` | — | A-share quarterly quick-report rows as raw structured evidence only; no canonical profit or revenue fact |
| `PERFORMANCE_REPORT` | `stock_yjbb_em` | — | A-share quarterly headline performance rows as raw structured evidence only; no canonical profit or CFO fact |
| `BUSINESS_COMPOSITION` | `stock_zygc_em` | — | A-share historical main-business composition rows as raw structured evidence only; no canonical revenue, margin or business-quality fact |
| `FINANCIAL_ABSTRACT` | `stock_financial_abstract` | — | A-share historical key-indicator matrix as raw structured evidence only; no canonical revenue, profit or CFO fact |
| `FINANCIAL_INDICATORS` | `stock_financial_analysis_indicator_em` | `stock_financial_hk_analysis_indicator_em` | A/H historical financial-indicator rows as raw structured evidence only; no canonical revenue, profit, CFO, metric or valuation input |
| `GOODWILL_IMPAIRMENT` | `stock_sy_yq_em` (`view=impairment_forecast`, exact `date`; listing-filtered forecast detail); `stock_sy_profile_em` (`view=market_profile`, no upstream arguments; market-wide history); `stock_sy_hy_em` (`view=industry_data`, exact `date`; market-wide industry aggregates); `stock_sy_em` (`view=goodwill_detail`, exact `date`; listing-filtered detail); `stock_sy_jz_em` (exact `date`; listing-filtered detail) | — | A-share goodwill/impairment forecast, market-profile, industry-data, goodwill-detail and report-date detail rows as raw structured evidence only; no canonical goodwill or impairment fact |
| `ESG_RATINGS` | `stock_esg_rate_sina` (no parameters) | `stock_esg_rate_sina` (no parameters) | mixed A/H agency, rating, quarter and marker rows as raw structured evidence only; no canonical ESG score, governance or Business Quality fact |
| `MARGIN_TRADING` | `stock_margin_detail_sse` (exact `date`; Shanghai A-share), `stock_margin_detail_szse` (exact `date`; Shenzhen A-share) and `stock_margin_detail_bse` (exact `date`; Beijing A-share) | — | requested-date SSE/SZSE/BSE security-level margin rows as raw structured evidence only; no issuer debt/cash/leverage/valuation fact |
| `EXTERNAL_GUARANTEES` | `stock_cg_guarantee_cninfo` (`symbol=全部`, date range; A-share only) | — | A-share date-range external-guarantee universe filtered to the requested listing as raw evidence only; no canonical quasi-debt, illegal-guarantee or governance fact |
| `LITIGATION` | `stock_cg_lawsuit_cninfo` (`symbol=全部`, date range; A-share only) | — | A-share date-range company-litigation universe filtered to the requested listing as raw evidence only; no canonical litigation, quasi-debt or governance fact |
| `LATEST_INDICATORS` | — | `stock_hk_financial_indicator_em` | H-share symbol-scoped latest-indicator row as raw structured evidence only; no canonical financial, share, dividend, market-cap, metric or valuation input |
| `BALANCE_SHEET` | `stock_zcfz_em` / `stock_zcfz_bj_em` (detailed report-period and Sina fallbacks) | `stock_financial_hk_report_em` | explicit `book_cash`, equity totals and aggregate interest-bearing debt when labeled |
| `DIVIDENDS` | `stock_dividend_cninfo`; `stock_fhps_em` (explicit report date); `stock_fhps_detail_em` (`view=event_detail`) | `stock_hk_dividend_payout_em`; `stock_hk_fhpx_detail_ths` (`view=event_detail`) | raw structured evidence only; no canonical dividend cash or payout ratio |
| `DISCLOSURE_NOTICES` | `stock_zh_a_disclosure_report_cninfo` (`market=沪深京`, optional filters/date range); `stock_individual_notice_report` (`view=individual_notice`, optional category/date range); `stock_notice_report` (`view=market_notice`, category/date-bound A-share universe); `stock_gddh_em` (`view=shareholder_meeting`, no upstream arguments, full universe filtered to requested A-share) | — | listing-bound CNINFO/Eastmoney announcement metadata or shareholder-meeting rows as raw structured evidence only; no filing-content, accounting, governance or corporate-action fact |
| `CORPORATE_ACTIONS` | `stock_repurchase_em` (no parameters); `stock_allotment_cninfo` (date-range request); `stock_ipo_summary_cninfo` (`view=ipo_summary`, symbol-scoped); `stock_dxsyl_em` (`view=ipo_yield`, no upstream arguments, full universe filtered to requested A-share) | — | A-share repurchase, rights-issue, IPO-summary or IPO-yield rows; raw structured evidence only; no canonical buyback, issuance, dilution, price, return or listing-date fact |
| `SHARE_CAPITAL` | `stock_zh_a_gbjg_em` (no parameters); `stock_share_change_cninfo` (explicit date range); `stock_restricted_release_queue_em` (`view=restricted_release_queue`); `stock_individual_info_em` (`view=individual_info`) | — | raw historical response or current item/value snapshot and provenance only; no canonical share/dilution fact |
| `OWNERSHIP_PLEDGE` | `stock_gpzy_distribute_statistics_bank_em` (`view=bank_distribution`, market-wide bank pledge-institution distribution, no upstream arguments); `stock_gpzy_distribute_statistics_company_em` (`view=company_distribution`, market-wide pledge-institution distribution, no upstream arguments); `stock_gpzy_industry_data_em` (`view=industry_data`, market-wide pledge-industry snapshot, no upstream arguments); `stock_gpzy_profile_em` (`view=market_profile`, market-wide historical A-share profile, no upstream arguments); `stock_gpzy_pledge_ratio_detail_em` (`view=market_pledge_detail`, market-wide important-shareholder detail, no upstream arguments); `stock_gpzy_pledge_ratio_em` (exact `date`); `stock_gpzy_individual_pledge_ratio_detail_em` (`view=individual_pledge_detail`); `stock_cg_equity_mortgage_cninfo` (`view=equity_mortgage`, `date`) | — | market-wide bank/company/industry pledge-institution snapshots, historical profile, important-shareholder detail, date-bound snapshot, symbol-scoped detail or CNINFO pledge-event rows as raw structured evidence only; no canonical governance, share, cash or debt-equivalent fact |
| `INSIDER_SHARE_CHANGES` | `stock_share_hold_change_sse` (Shanghai); `stock_share_hold_change_szse` (Shenzhen); `stock_share_hold_change_bse` (Beijing); `stock_hold_management_detail_em` (`view=management_detail`, no upstream arguments, full universe filtered to requested A-share); `stock_hold_management_person_em` (`view=management_person`, symbol-and-person scoped); `stock_ggcg_em` (`view=executive_share_changes`, explicit direction, full universe filtered to requested A-share) | — | listing-scoped exchange rows or management/management-person/executive/shareholder holding-change rows as raw structured evidence only; no canonical share, dilution, governance, buyback or issuance fact |
| `SHAREHOLDER_HOLDINGS` | `stock_main_stock_holder` (`stock`); `stock_hold_num_cninfo` (exact quarter-end `date`); `stock_zh_a_gdhs_detail_em` (`view=holder_count_detail`); `stock_hold_control_cninfo` (`view=control_changes`, optional `control_type`); `stock_gdfx_top_10_em` (`view=top_10`, exact quarter-end `date`); `stock_gdfx_free_top_10_em` (`view=free_top_10`, exact quarter-end `date`); `stock_gdfx_free_holding_detail_em` (`view=free_holding_detail`, exact quarter-end `date`); `stock_hsgt_individual_em` (`view=hsgt_individual`) | `stock_hsgt_individual_em` (`view=hsgt_individual`) | A-share main-shareholder/shareholder-count/shareholder-count-detail/actual-controller/top-ten/top-ten-tradable/top-ten-tradable-detail holding-change or A/H HSGT investor-holding rows as raw structured evidence only; no canonical ownership, concentration, share, dilution or governance fact |

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
The A-share `stock_comment_detail_scrd_desire_em` view passes the unprefixed
six-digit listing code to the documented Eastmoney participation report. The
adapter validates the exact six-field response, listing identity, finite
numeric/null values, strictly ascending ISO dates and the official 30-row
maximum, and binds the explicit view, symbol, listing, row limit and observed
date bounds into replay metadata. The normalizer keeps provider-defined
participation scores and changes as raw evidence only; they do not establish a
canonical market metric, issuer cash flow, shareholder return, governance or
valuation input.
The A-share `stock_hot_rank_em` view passes no upstream arguments to the
documented Eastmoney stock-popularity endpoint. Its current-trading-day
response contains market-prefixed `代码`, `当前排名`, `股票名称`, `最新价`,
`涨跌额` and `涨跌幅`; the adapter validates exact fields, unique ascending
ranks, finite numeric/null quote values and the 100-row maximum, filters the
full universe to the requested listing and binds the no-row-date snapshot only
to retrieval provenance. The normalizer emits
`AKSHARE_HOT_RANK_RAW_ONLY`; popularity ordering and quote context remain raw
evidence and do not become a canonical market metric, issuer cash flow,
shareholder return, governance or valuation input.
The A-share `stock_hot_rank_latest_em` view passes the market-prefixed symbol to
the documented Eastmoney latest stock-popularity endpoint. Its current official
implementation returns the exact `item`/`value` rows for `marketType`,
`marketAllCount`, `calcTime`, `innerCode`, `srcSecurityCode`, `rank`,
`rankChange`, `hisRankChange`, `hisRankChange_rank` and `flag`. The adapter
validates the exact ten-row shape, item uniqueness, symbol identity, timestamp
and integer/null value rules, then records the upstream symbol, current-day
latest-rank scope and row-derived `calcTime` for replay. The normalizer emits
`AKSHARE_HOT_RANK_LATEST_RAW_ONLY`; provider popularity rank and timing remain
raw evidence and do not become a canonical market metric, issuer cash flow,
shareholder return, governance or valuation input.
The H-share `stock_hk_hot_rank_latest_em` view uses the same explicit
`view=hot_rank_latest` boundary but is a separate documented Eastmoney endpoint.
It passes the unprefixed five-digit H-share code, requires provider
`marketType=000003`, validates the `HK|` security identity and the documented
H-share `innerCode` form, and records its H-share endpoint, symbol format,
latest-rank scope, row counts and row-derived `calcTime` for replay. The
normalizer emits `AKSHARE_HK_HOT_RANK_LATEST_RAW_ONLY`; the popularity rank and
provider timing remain raw evidence and do not become a canonical market,
issuer cash-flow, shareholder-return, governance or valuation input.
The H-share `stock_hk_hot_rank_detail_em` view is a separate documented
symbol-scoped historical-rank endpoint selected only with
`view=hk_hot_rank_detail`. It passes the unprefixed five-digit code, validates
the complete three-field `时间`/`排名`/`证券代码` response in official field
order, strict ascending ISO-date order and requested-code identity, and records
`marketType=000003`, source field order, row counts and observed date bounds for
replay. The normalizer emits `AKSHARE_HK_HOT_RANK_DETAIL_RAW_ONLY`; dated
provider popularity rank remains raw evidence and does not become a canonical
market, issuer cash-flow, shareholder-return, governance or valuation input.
The A-share `stock_individual_spot_xq` view passes the market-prefixed symbol to
the documented Xueqiu individual-spot endpoint. The current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) documents the
`item`/`value` response and optional token/timeout arguments, while the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_xq.py)
maps the quote's `现价` and `时间` items. The adapter accepts only the explicit
`view=xueqiu_spot` request selector, deliberately does not persist credentials
or timeout controls in the request/cache identity, validates the documented
item allowlist, unique item/value rows, requested A-share code, finite numeric
values and timestamp, and records the symbol-scoped current-quote snapshot for
replay. The normalizer maps only `现价` to the existing `current_price` fact and
`时间` to `market_quote_timestamp`; all other Xueqiu fields remain opaque raw
evidence and do not enter calculations, gates, pipeline, CLI or input-loader
contracts.
The A-share `stock_individual_basic_info_xq` view passes the market-prefixed
symbol to the documented Xueqiu company-profile endpoint. The current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents the `item`/`value` response and optional token/timeout arguments, while
the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_basic_info_xq.py)
confirms the CN company-profile callable and symbol parameter. The adapter
accepts only the explicit `view=xueqiu_basic_info` selector, deliberately keeps
credentials and timeout controls out of request/cache identity, validates the
documented item allowlist, required profile identifiers, scalar values, the
documented `affiliate_industry` object and numeric date/asset/personnel/
issuance fields, and records the symbol-scoped profile snapshot for replay.
The normalizer emits
`AKSHARE_XUEQIU_BASIC_INFO_RAW_ONLY`; descriptive, registration, personnel and
provider-specific date fields do not become canonical company or listing facts.
The response remains outside calculations, gates, pipeline, CLI and input-loader
contracts.

The A-share `stock_profile_cninfo` view passes the unprefixed six-digit listing
code to the documented CNINFO company-profile endpoint. The current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_cninfo.py)
define a symbol-scoped response with the exact 26 profile fields, including
company/display names, A/B/H codes, market/industry, registration/contact
context, dates and business descriptions. The adapter accepts only the explicit
`view=cninfo_profile` selector, passes the six-digit A-share code, validates
the single row, exact field set, A-share identity, scalar/null values and
valid date-or-null values, and records the symbol-scoped current company-profile
snapshot for replay. The normalizer emits
`AKSHARE_CNINFO_PROFILE_RAW_ONLY`; descriptive, registration, contact and
provider-specific date fields do not become canonical company or listing facts.
The response remains outside calculations, gates, pipeline, CLI and input-loader
contracts.

The A-share `stock_zyjs_ths` view passes the unprefixed six-digit listing code
to the documented Tonghuashun main-business-introduction endpoint. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_zyjs_ths.py)
define a symbol-scoped response with the exact five fields `股票代码`, `主营业务`,
`产品类型`, `产品名称` and `经营范围`. The adapter accepts only the explicit
`view=business_intro` selector, passes the six-digit A-share code, validates the
single row, exact field set, A-share identity and string/null values, and records
the symbol-scoped current business-introduction snapshot for replay. The
normalizer emits `AKSHARE_BUSINESS_INTRO_RAW_ONLY`; descriptive business,
product and operating-scope text does not become canonical revenue,
core-business or Business Quality facts. The response remains outside
calculations, gates, pipeline, CLI and input-loader contracts.

The A/H `stock_zh_ah_spot_em` view passes no upstream arguments to the
documented Eastmoney A+H comparison endpoint. Its delayed 15-minute response
contains the exact `序号`, `名称`, five-digit `H股代码`, H-share price/change,
six-digit `A股代码`, A-share price/change, `比价` and `溢价` fields. The adapter
validates the full universe, unique ascending sequence, code widths and finite
numeric/null values before filtering by the requested A- or H-share side. It
records `HKD_per_share` and `RMB_per_share` price units, percent/ratio/premium
units, the delayed current-day snapshot and retrieval-only date binding. The
normalizer emits `AKSHARE_AH_COMPARISON_RAW_ONLY`; because the response has no
stable row-level observation timestamp, its cross-market prices and comparison
fields do not replace canonical current price or become FX, comparison,
valuation or calculation inputs.

The A-share `stock_zh_ab_comparison_em` view passes no upstream arguments to
the documented Eastmoney A+B comparison endpoint. The current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
define the exact ten fields `序号`, `B股代码`, `B股名称`, `最新价B`,
`涨跌幅B`, `A股代码`, `A股名称`, `最新价A`, `涨跌幅A` and `比价`. The
official implementation divides the published quote, change and ratio values
by 100 before returning the table. The adapter accepts only
`MARKET_QUOTE` with explicit `view=ab_comparison`, validates the complete
universe and official field order before filtering by the requested A-share
code, and records the current-trading-day retrieval-only snapshot, field
order, provider-reported per-share values, percent/ratio units and row counts.
The endpoint does not document the B-share currency, so the provider does not
invent one. The normalizer emits `AKSHARE_AB_COMPARISON_RAW_ONLY`; its
cross-share-class prices, changes and ratio do not replace canonical current
price or become currency, comparison, valuation or calculation inputs.

The A-share `stock_fhps_detail_em` view passes the unprefixed six-digit listing
code to the documented Eastmoney dividend-distribution detail endpoint. The
adapter requires the explicit `view=event_detail`, validates the exact 19-field
symbol-scoped table, strictly ascending `报告期` values, valid optional event
dates, finite numeric/null fields, non-negative integer `总股本` and string/null
status fields, and binds the upstream symbol, row counts and historical-detail
scope into replay metadata. The normalizer emits
`AKSHARE_A_DIVIDEND_DETAIL_RAW_ONLY`; its distribution ratios, event plans,
per-share indicators and share-count context remain raw evidence and do not
establish settled ordinary dividend cash or a canonical payout denominator.
The A-share `stock_ipo_summary_cninfo` view passes the unprefixed six-digit
listing code to the documented CNINFO IPO-summary endpoint. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ipo_summary_cninfo.py)
define the exact 15 fields `股票代码`, `招股公告日期`, `中签率公告日`,
`每股面值`, `总发行数量`, `发行前每股净资产`, `摊薄发行市盈率`,
`募集资金净额`, `上网发行日期`, `上市日期`, `发行价格`, `发行费用总额`,
`发行后每股净资产`, `上网发行中签率` and `主承销商`. The adapter requires
`view=ipo_summary`, validates exactly one symbol-matching row, optional valid
dates, finite numeric/null fields and string/null underwriter text, and binds
the request view, symbol, row counts, historical scope and row-date binding
into replay metadata. The normalizer emits
`AKSHARE_IPO_SUMMARY_RAW_ONLY`; offering dates, proceeds, fees, quantities and
underwriter context do not establish canonical issuance cash, dilution or a
share fact.
The A-share `stock_dxsyl_em` view passes no upstream arguments to the
documented Eastmoney IPO-yield universe at
`https://data.eastmoney.com/xg/xg/dxsyl.html`. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_dxsyl_em.py)
define the exact 17-field source order `序号`, `股票代码`, `股票简称`, `发行价`,
`最新价`, `网上-发行中签率`, `网上-有效申购股数`, `网上-有效申购户数`,
`网上-超额认购倍数`, `网下-配售中签率`, `网下-有效申购股数`, `网下-有效申购户数`,
`网下-配售认购倍数`, `总发行数量`, `开盘溢价`, `首日涨幅` and `上市日期`.
The provider validates the complete universe, including exact field order,
six-digit identities, unique ascending sequence numbers, valid listing dates
and finite numeric/null values, before filtering to the requested A-share.
It records the full/selected row counts, documented percent/household units,
source field order, row-date boundary and `view=ipo_yield` for replay. The
normalizer emits `AKSHARE_IPO_YIELD_RAW_ONLY`; provider-reported IPO yields,
prices, returns, issue quantities and listing dates do not establish a settled
issuance-cash period, unit or diluted-share fact.
The A-share `stock_dzjy_mrmx` view passes `symbol="A股"` and the requested
`start_date`/`end_date` to the documented Eastmoney block-trade detail
universe. The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_dzjy_em.py)
define the exact 13-field source order `序号`, `交易日期`, `证券代码`, `证券简称`,
`涨跌幅`, `收盘价`, `成交价`, `折溢率`, `成交量`, `成交额`, `成交额/流通市值`,
`买方营业部` and `卖方营业部`. The provider validates the full inclusive
date-range response before filtering to the requested A-share, records the
source order, documented units, unresolved price/discount units, request
dates and full/selected row counts, and the normalizer emits
`AKSHARE_BLOCK_TRADE_RAW_ONLY`; no trade-price, shareholder-return, issuer
cash-flow, governance, valuation or canonical market fact is created.
The A-share `stock_zh_a_new_em` view passes no upstream arguments to the
documented Eastmoney new-stock-board universe. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_special.py)
define the exact 17 fields `序号`, `代码`, `名称`, quote/change fields,
`成交量`, `成交额`, `振幅`, OHLC, `量比`, `换手率`, `市盈率-动态` and `市净率`.
The adapter validates six-digit A-share codes, unique positive sequence numbers,
finite numeric/null values and non-empty names before filtering the current-day
universe to the requested listing. The normalizer emits
`AKSHARE_NEW_STOCKS_RAW_ONLY`; this quote snapshot has retrieval-only date
binding and does not establish a dated listing, return, valuation, governance
or canonical market fact.
The A-share `stock_individual_notice_report` view passes the unprefixed
six-digit listing code as `security`, the selected provider-neutral category as
`symbol` and optional date bounds as `begin_date`/`end_date` to the documented
Eastmoney individual-notice endpoint. The current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py)
define the exact `代码`, `名称`, `公告标题`, `公告类型`, `公告日期` and `网址`
fields. The adapter validates the exact field set, six-digit requested-listing
identity, non-empty text, valid optional dates/URLs and inclusive request-date
range, then records `row_filtering=upstream`, the category, optional bounds and
the symbol-scoped history/range scope. The normalizer emits
`AKSHARE_INDIVIDUAL_NOTICES_RAW_ONLY`; announcement titles, types, dates and
links remain raw discovery evidence and do not establish filing contents,
accounting opinion or governance risk.
The A-share `stock_notice_report` view passes the selected documented notice
category as `symbol` and a required `date=YYYYMMDD` to the Eastmoney market-wide
notice endpoint. The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py)
define the exact six fields `代码`, `名称`, `公告标题`, `公告类型`, `公告日期`
and `网址`. The adapter selects this callable only with
`view=market_notice`, validates the complete A-share universe and requires each
announcement date to equal the requested date before filtering to the requested
listing. It records the category, request/row date binding, provider filtering,
market scope and selected counts for replay. The normalizer emits
`AKSHARE_MARKET_NOTICES_RAW_ONLY`; announcement metadata remains raw evidence
and does not establish filing contents, an accounting opinion or a governance
risk fact.
The A-share `stock_gddh_em` view calls the documented no-argument Eastmoney
shareholder-meeting endpoint. The current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gddh_em.py)
define its exact twelve-field response: `代码`, `简称`, `股东大会名称`, seven
nullable event/publication dates, `序列号` and `提案`. The adapter validates the
complete A-share response before retaining every row for the requested listing,
records field order, event-date fields, selected/upstream counts and
`row_filtering=provider` for replay, and keeps an unmatched listing as an empty
raw snapshot. The normalizer emits
`AKSHARE_SHAREHOLDER_MEETINGS_RAW_ONLY`; meeting dates and proposals do not
establish a filing-backed governance-risk judgment or canonical corporate-action
fact, so `governance_risk_level` remains critically missing.
The A-share `stock_comment_detail_scrd_focus_em` view passes the unprefixed
six-digit listing code to the documented Eastmoney market-focus endpoint. The
current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py)
define the exact `交易日` and `用户关注指数` fields, with a 30-row page limit.
The adapter validates the exact two-field response, strict ascending ISO dates,
finite numeric/null focus values and the symbol-scoped latest-30-trading-day
boundary, then records the symbol, row limit and observed date bounds for
replay. The normalizer emits `AKSHARE_MARKET_FOCUS_RAW_ONLY`; provider-defined
user-attention scores remain raw evidence and do not establish a canonical
market metric, issuer cash flow, shareholder return, governance or valuation
fact.
The A-share `stock_comment_detail_zlkp_jgcyd_em` view passes the unprefixed
six-digit listing code to the documented Eastmoney institution-participation
endpoint. The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py)
define the exact `交易日` and `机构参与度` fields; the implementation publishes
the participation value in percent and returns the symbol's historical series.
The adapter validates the exact two-field response, strict ascending ISO dates,
finite numeric/null percentage values and the symbol-scoped request, then records
the value unit and observed date bounds for replay. The normalizer emits
`AKSHARE_MARKET_INSTITUTION_PARTICIPATION_RAW_ONLY`; provider-defined
institution-participation percentages remain raw evidence and do not establish
a canonical market metric, issuer cash flow, shareholder return, governance or
valuation fact.
The A-share `stock_zt_pool_em` view passes the explicit `date` to the documented
Eastmoney limit-up-pool endpoint. The current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
define the exact 16 fields `序号`, `代码`, `名称`, `涨跌幅`, `最新价`, `成交额`,
`流通市值`, `总市值`, `换手率`, `封板资金`, `首次封板时间`, `最后封板时间`,
`炸板次数`, `涨停统计`, `连板数` and `所属行业`. The adapter requires
`view=limit_up_pool`, validates the date, full-universe field shape, six-digit
codes, strictly ascending ranks, valid `HHMMSS` lock times, `days/ct` summary
strings, finite numeric/null values and non-empty text before filtering to the
requested A-share listing. It records the request date, observation date,
selection counts and replay scope; the normalizer emits
`AKSHARE_LIMIT_UP_POOL_RAW_ONLY`. Quote, limit-up activity, ranking and
market-cap fields remain raw evidence and do not become issuer cash flow,
shareholder return, governance, valuation or a canonical market fact.
The A-share `stock_zt_pool_dtgc_em` view passes the explicit `date` to the
documented Eastmoney limit-down-pool endpoint. The current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
define the exact 16 fields `序号`, `代码`, `名称`, `涨跌幅`, `最新价`, `成交额`,
`流通市值`, `总市值`, `动态市盈率`, `换手率`, `封单资金`, `最后封板时间`,
`板上成交额`, `连续跌停`, `开板次数` and `所属行业`. The adapter requires
`view=limit_down_pool`, validates the recent-data date, full-universe field
shape, six-digit codes, strictly ascending ranks, valid `HHMMSS` lock times,
finite numeric/null values and integer-like counters before filtering to the
requested A-share listing. It records the request date, observation date,
selection counts and replay scope; the fixture is a frozen real response
snapshot for 20260910. The normalizer emits
`AKSHARE_LIMIT_DOWN_POOL_RAW_ONLY`. Quote, limit-down activity, ranking and
market-cap fields remain raw evidence and do not become issuer cash flow,
shareholder return, governance, valuation or a canonical market fact.
The A-share `stock_intraday_em` view passes the unprefixed six-digit listing
code to the documented Eastmoney intraday-trade endpoint. Its latest-trading-day
response contains the exact time-only fields `时间`, `成交价`, `手数` and
`买卖盘性质`, including pre-market observations. The adapter validates the
field set, finite numeric/null prices, integer/null lot counts, recognized trade
sides and non-decreasing `时间` values, and records the explicit
`view=intraday_trades`, symbol, listing scope, latest-day snapshot, time-only
date binding and observed time bounds for replay. The normalizer emits
`AKSHARE_INTRADAY_TRADES_RAW_ONLY`; because no trading date is returned, these
trades do not establish canonical daily history, liquidity or valuation input.
The A-share `stock_intraday_sina` view passes the lower-case market-prefixed
symbol and explicit `YYYYMMDD` date to the documented [Sina large-order
endpoint](https://akshare.akfamily.xyz/data/stock/stock.html), whose [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_sina.py)
returns the exact fields `symbol`, `name`, `ticktime`, `price`,
`volume`, `prev_price` and `kind`; the adapter validates symbol identity,
non-empty names, finite numeric/null price and volume values, integer volume,
recognized `U`/`D`/`E` kinds and non-decreasing `ticktime` values. The response
records the requested trading date as request-only scope because rows carry
only time-of-day observations. The normalizer emits
`AKSHARE_SINA_INTRADAY_RAW_ONLY`; no canonical daily-history, liquidity,
order-flow or valuation fact is created.
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
goodwill-impairment forecast/detail/goodwill-detail/market-profile, ESG-rating, margin-trading, corporate-action/IPO-summary,
external-guarantee, company-litigation, share-capital, ownership-pledge,
main-shareholder, shareholder-count, top-ten-shareholder,
top-ten-tradable-shareholder, top-ten-tradable-shareholder-detail,
insider-share-change, management-holding,
individual-info, individual-fund-flow, market-participation-desire, hot-rank,
H-share historical-hot-rank,
A+B/A+H quote-comparison, chip-distribution, Eastmoney/Sina intraday-trade, Tencent latest-trading-day tick, Sina minute-history, A-share/H-share intraday-history, pre-market-history and
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
The market-participation-desire slice remains raw evidence because its
provider-defined scores/change fields describe a recent latest-30-trading-day
window rather than a canonical market metric. Its explicit view, unprefixed
listing symbol, exact field set, row limit and observed date bounds remain part
of the replay scope; no issuer cash-flow, shareholder-return, governance or
valuation fact is admitted.
The stock hot-rank slice remains raw evidence because current popularity
ordering and quote context do not establish a canonical market metric. Its
explicit view, no-argument endpoint, exact field set, top-100 limit and
filtered-listing replay scope remain part of the replay boundary.
The H-share historical-hot-rank slice remains raw evidence because a dated
provider popularity rank is not an issuer financial, shareholder-return,
governance or canonical market observation. Its explicit view, unprefixed
symbol, `marketType=000003`, exact three-field order, strict date ordering,
symbol-scoped request and observed date bounds remain part of the replay
boundary.
The A-share historical-hot-rank slice remains raw evidence because its
date-bound popularity rank and follower ratios do not establish issuer cash
flow, shareholder return, governance or a canonical market observation. Its
explicit `view=hot_rank_detail`, market-prefixed `SZ000665` symbol,
`marketType=""`, exact five-field order, strict date ordering, matching code,
positive rank, fraction units, percent-to-fraction scaling, symbol-scoped
request, documented Eastmoney source URI, row counts and observed date bounds
remain part of the replay boundary.
The A+H quote-comparison slice remains raw evidence because its delayed
cross-market prices, changes, ratio and premium do not establish a canonical
current-price, FX, comparison or valuation fact. Its explicit view,
no-argument endpoint, exact ten-field set, five-/six-digit code identities,
side-specific filtered-listing scope, units and retrieval-only snapshot remain
part of the replay boundary.
The A+B quote-comparison slice remains raw evidence because its current-day
cross-share-class prices, changes and ratio do not establish a canonical
current-price, currency, comparison or valuation fact. Its explicit view,
no-argument endpoint, exact ten-field order, six-digit A/B identities,
A-side filtered-listing scope, provider-reported per-share values,
percent/ratio units and retrieval-only snapshot remain part of the replay
boundary; the B-share currency is not documented by the endpoint.
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
The IPO-yield view additionally leaves the numeric price, issue-quantity and
multiple units, rate scaling beyond the documented percent labels, and the
relationship between listing-day returns and a settled issuance-cash period
unresolved. Its listing dates are retained as row-level IPO context rather than
promoted to canonical listing or accounting facts.
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

For the A-share Eastmoney shareholder-count-detail slice, the current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdhs.py)
define `stock_zh_a_gdhs_detail_em` with the six-digit A-share `symbol` and the
provider-neutral selector `view=holder_count_detail`. The implementation calls
the Eastmoney `RPT_HOLDERNUM_DET` report, paginates the published response,
renames and selects exactly `股东户数统计截止日`, `区间涨跌幅`,
`股东户数-本次`, `股东户数-上次`, `股东户数-增减`, `股东户数-增减比例`,
`户均持股市值`, `户均持股数量`, `总市值`, `总股本`, `股本变动`,
`股本变动原因`, `股东户数公告日期`, `代码` and `名称`, converts numeric
columns and date columns, and sorts by `股东户数统计截止日` ascending. The
upstream request fixes `reportName=RPT_HOLDERNUM_DET`, `sortColumns=END_DATE`,
`sortTypes=-1`, `pageSize=500`, one-based `pageNumber` pagination,
`quoteColumns=f2,f3`, `source=WEB`, `client=WEB` and
`filter=(SECURITY_CODE="{symbol}")`; the adapter exposes only the six-digit
symbol and neutral view selector at its provider boundary. The documented
`区间涨跌幅` and `股东户数-增减比例` are percent fields, holder counts are
integer counts, `总股本`/`股本变动` are integer share-base fields, and the
provider's market-value/average-holding fields retain their documented raw
scale without an inferred currency conversion. The
provider requires the exact field order, upstream symbol identity, non-decreasing
observation dates, nullable announcement dates, finite numeric values and
non-negative count/market/share-base fields, then records the row-derived date
range and upstream listing scope. The normalizer emits
`AKSHARE_SHAREHOLDER_COUNT_DETAIL_RAW_ONLY`, leaves `governance_risk_level`
critically missing and does not calculate concentration, control, governance,
valuation or diluted-share facts.

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

For the distinct A-share CNINFO management-holding-detail slice, the current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
define `stock_hold_management_detail_cninfo(symbol="增持")` with the choices
`增持` and `减持`. The implementation maps those choices to `B`/`S`, posts to
CNINFO `p_sysapi1030`, and requests the prior-year-through-current-date rolling
window. Its output is reordered to the exact fields `证券代码`, `证券简称`,
`截止日期`, `公告日期`, `高管姓名`, `董监高姓名`, `董监高职务`,
`变动人与董监高关系`, `期初持股数量`, `期末持股数量`, `变动数量`,
`变动比例`, `成交均价`, `期末市值`, `持股变动原因` and `数据来源`.
The provider-neutral boundary requires `view=cninfo_management_detail` and an
explicit `direction`, validates the full universe's exact field order, six-digit
codes, dates, finite numeric/null values and non-negative holdings/price/value
ranges, then filters it to the requested A-share listing. Direction, rolling
window scope, units, source field order, row counts and observed cutoff-date
bounds are retained as replay metadata. The normalizer emits
`AKSHARE_CNINFO_MANAGEMENT_HOLDINGS_RAW_ONLY`, leaves `governance_risk_level`
critically missing and creates no ownership, share-count, dilution, settled-cash,
return, valuation or governance fact.

For the distinct A-share Eastmoney executive/shareholder-change slice, the
current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdzjc_em.py)
define `stock_ggcg_em(symbol="全部")` with the choices `全部`, `股东增持` and
`股东减持`. The implementation requests a direction-filtered full universe
and returns the exact 16 fields `代码`, `名称`, `最新价`, `涨跌幅`, `股东名称`,
`持股变动信息-增减`, `持股变动信息-变动数量`, `持股变动信息-占总股本比例`,
`持股变动信息-占流通股比例`, `变动后持股情况-持股总数`,
`变动后持股情况-占总股本比例`, `变动后持股情况-持流通股数`,
`变动后持股情况-占流通股比例`, `变动开始日`, `变动截止日` and `公告日`.
The provider-neutral boundary requires `view=executive_share_changes` and an
explicit direction, validates the full response's field order, six-digit
codes, direction scope, finite numeric/null values and nullable event dates,
then filters it to the requested A-share listing. Direction, source field
order, documented quantity/ratio units, the undocumented latest-price unit,
event-date bounds and upstream/selected row counts are retained for replay.
The normalizer emits `AKSHARE_EXECUTIVE_SHARE_CHANGES_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
dilution, settled-cash, return, valuation or governance fact.

For the distinct A-share Eastmoney management-person slice, the current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
define `stock_hold_management_person_em(symbol, name)` as a symbol-and-person
scoped response with the exact 16 fields `日期`, `代码`, `名称`, `变动人`,
`变动股数`, `成交均价`, `变动金额`, `变动原因`, `变动比例`, `变动后持股数`,
`持股种类`, `董监高人员姓名`, `职务`, `变动人与董监高的关系`, `开始时持有`
and `结束后持有`. The provider selects it only with the explicit
`view=management_person` request, passes the six-digit listing code and
non-empty executive name, validates listing/person identity, field order,
ISO change dates, finite numeric/null values and non-negative price/holding
fields, and records the scope, source order, page size, date bounds and
`not_documented` numeric units for replay. The normalizer emits
`AKSHARE_MANAGEMENT_PERSON_RAW_ONLY`, leaves `governance_risk_level` critically
missing and creates no canonical share, dilution, transaction-cash, governance
or shareholder-return fact.

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

For the A-share goodwill market-profile slice, the documented
`stock_sy_profile_em` response is retained as raw evidence only. Its
market-wide `商誉`, `商誉减值`, `净资产` and `净利润规模` amounts are in CNY,
while its three ratios remain provider-reported values; neither group has a
canonical denominator, issuer scope or filing-backed period. `报告期` is
validated as a strictly ascending provider history, but annual and interim
rows are not silently collapsed into a listing-level accounting series. The
normalizer therefore emits `AKSHARE_GOODWILL_PROFILE_RAW_ONLY`, leaves
`goodwill` and `impairment` critically missing and creates no canonical
accounting, profit, ratio or Business Quality fact. H-share coverage and
primary-filing reconciliation remain unresolved.

For the A-share goodwill-impairment forecast slice, the documented
`stock_sy_yq_em` response is retained as raw evidence only. The request binds
the upstream `REPORT_DATE` filter through `date=YYYYMMDD`; the returned
`最新商誉报告期` is a separate provider field and is not silently treated as
the requested accounting period. Expected-profit bounds, change-rate bounds,
prior-year profit, goodwill context and `公告日期` remain provider evidence
without an admitted filing entity, period basis or canonical forecast/profit
fact. The adapter validates the complete 14-field universe before listing
selection, and the normalizer emits `AKSHARE_GOODWILL_FORECAST_RAW_ONLY` with
`goodwill` and `impairment` critically missing. H-share coverage and
primary-filing reconciliation remain unresolved.

For the A-share goodwill-detail slice, the documented `stock_sy_em` response is
retained as raw evidence only. Its `商誉`, `净利润` and `上年商誉` amounts are
aggregator values in CNY, while `商誉占净资产比例` and `净利润同比` are
provider-reported ratios; neither group establishes a canonical entity,
statement scope, denominator or filing-backed period. `公告日期` is publication
metadata, and `序号` is response ordering rather than a report-period key. The
adapter validates the complete ten-field universe before listing selection, and
the normalizer emits `AKSHARE_GOODWILL_DETAIL_RAW_ONLY` with `goodwill` and
`impairment` critically missing. H-share coverage and primary-filing
reconciliation remain unresolved.

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

For the A-share Eastmoney market-profile slice, the current [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define `stock_gpzy_profile_em` as a no-argument historical market-wide response.
The provider selects it only with `OWNERSHIP_PLEDGE` plus explicit
`view=market_profile`, validates the exact eight-field row shape and strictly
ascending `交易日期` values, and retains the full A-share history. The requested
listing code remains request provenance only: these rows have no issuer code,
so the provider records `listing_scoped_request=false`, `row_filtering=none`,
`entity_rows_selected=false` and `entity_row_count=0` rather than pretending
that market observations are issuer observations.

The source implementation divides its documented percent input for
`A股质押总比例` by 100 before returning the table. The adapter therefore records
`pledge_ratio_unit=fraction_of_total_a_shares` and
`pledge_ratio_source_scale=percent_divided_by_100` without rescaling the raw
payload a second time. `交易日期`, the aggregate pledge counts/shares/value,
`沪深300指数` and `涨跌幅` remain provider fields. The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_PROFILE_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical pledge,
governance, cash, debt-equivalent or share fact. H-share coverage and
filing-backed pledge interpretation remain unresolved.

For the A-share Eastmoney important-shareholder pledge-detail slice, the
current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define `stock_gpzy_pledge_ratio_detail_em` as a no-argument full-universe
response backed by the `RPTA_APP_ACCUMDETAILS` report. The upstream
implementation fetches every 500-row page ordered by descending `NOTICE_DATE`,
then returns the exact 15-field source order `序号`, `股票代码`, `股票简称`,
`股东名称`, `质押股份数量`, `占所持股份比例`, `占总股本比例`, `质押机构`,
`最新价`, `质押日收盘价`, `预估平仓线`, `质押开始日期`, `质押结束日期`,
`状态`, `公告日期`. The adapter exposes it only with
`OWNERSHIP_PLEDGE` plus explicit `view=market_pledge_detail`, validates the
complete response before provider filtering, preserves the source order,
sequence and announcement-date boundaries, rejects duplicate pledge identity,
and records field types, nullability, identity fields, shares/percent/CNY per
share units, date bounds, pagination and row counts for replay.

AKShare's documented coercion can return JSON null for `质押机构` and
`质押开始日期`; populated institution values must be non-empty text, while
populated start dates must be ISO dates. `公告日期` remains required, and
pledge-start/end boundary comparisons are applied only when a start date is
present. Null institution/start values remain part of the explicit row
identity and duplicate detection rather than being replaced or discarded.

The requested A-share code is used only for provider-boundary filtering; the
normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_MARKET_DETAIL_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. Holder, counterparty, quantity,
ratio, price, status and event-date context remain raw evidence pending the
filing/evidence workflow.

For the A-share Eastmoney pledge-institution company-distribution slice, the
current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define `stock_gpzy_distribute_statistics_company_em` as a no-argument,
market-wide response backed by `RPT_GDZY_ZYJG_SUM`. The implementation filters
the report to securities with `(PFORG_TYPE="证券")`, requests one 500-row page
ordered by descending `ORG_NUM`, generates one-based `序号` values and returns
the exact eight-field source order `序号`, `质押机构`, `质押公司数量`, `质押笔数`,
`质押数量`, `未达预警线比例`, `达到预警线未达平仓线比例`, `达到平仓线比例`.

The provider exposes this endpoint only with `OWNERSHIP_PLEDGE` plus explicit
`view=company_distribution`. It validates the complete response before
retention: source field order and types, non-nullability, one-based sequence,
unique non-empty institution identity, non-increasing company-count order,
finite non-negative numeric values and documented 0–100 percentage bounds. The
documented `质押数量` unit is shares and the three risk-state values are
percent; the official implementation does not rescale those values, so the
adapter preserves their returned numeric scale and records that choice. This
endpoint has no date parameter or row date, so `date_binding=retrieval_only`
and `date_boundary=not_applicable` are explicit replay metadata. The requested
listing code remains provenance only: the full institution response is kept,
with no listing filtering and zero selected entity rows.

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_COMPANY_DISTRIBUTION_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. Institution ranking, pledge counts,
shares, risk-state percentages and report context remain raw evidence pending
the filing/evidence workflow.

For the A-share Eastmoney pledge-institution bank-distribution slice, the
current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define `stock_gpzy_distribute_statistics_bank_em` as the no-argument,
market-wide bank response backed by `RPT_GDZY_ZYJG_SUM`. It requests one
500-row page ordered by descending `ORG_NUM`, applies the documented
`(PFORG_TYPE="银行")` filter and returns the exact eight-field source order
`序号`, `质押机构`, `质押公司数量`, `质押笔数`, `质押数量`, `未达预警线比例`,
`达到预警线未达平仓线比例`, `达到平仓线比例`. The adapter exposes it only
with `OWNERSHIP_PLEDGE` plus explicit `view=bank_distribution` and validates
the complete response before retention.

The bank view shares the company-distribution schema contract: one-based
sequence, unique non-empty institution identity, non-increasing company-count
ordering, finite non-negative numeric values, integer count fields, documented
shares and percent units, unchanged provider numeric scale, exact field
order/types/nullability and full row count. It records the fixed report,
filter, page, sort and non-listing replay scope. A live probe on 2026-09-11
observed current Eastmoney report labels `银行Ⅱ`/`证券Ⅱ`; the exact
documented `银行` filter returned no rows, so the adapter records the current
AKShare wrapper contract and does not silently reinterpret or merge the
suffixed labels. That upstream drift requires a separately reviewed fix.

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_BANK_DISTRIBUTION_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. Bank institution ranking, pledge
counts, shares, risk-state percentages and report context remain raw evidence
pending the filing/evidence workflow.

For the A-share Eastmoney ownership-pledge industry-data slice, the current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define `stock_gpzy_industry_data_em` as a no-argument, market-wide response
backed by `RPT_CSDC_INDUSTRY_STATISTICS`. It requests one 500-row page ordered
by descending `AVERAGE_PLEDGE_RATIO`, drops the upstream `INDUSTRY_CODE` and
returns the exact eight-field source order `序号`, `行业`, `平均质押比例`,
`公司家数`, `质押总笔数`, `质押总股本`, `最新质押市值`, `统计时间`. The
adapter exposes it only with `OWNERSHIP_PLEDGE` plus explicit
`view=industry_data`, validates the complete response before retention and
keeps the requested listing code as provenance rather than filtering the
market-wide rows.

The provider validates one-based sequence, unique non-empty industry identity,
non-increasing average-pledge-ratio ordering, finite non-negative numeric
values, integer count fields, the 0–100 provider-reported percent bound and
required ISO row dates.
It records row-date min/max bounds, exact field order/types, documented
percent/shares/CNY units, undocumented count units, fixed report/page/sort
metadata and full row counts for replay. A live probe on 2026-09-11 observed
provider industry labels with the `Ⅱ` suffix; the adapter preserves provider
text and does not normalize or merge those labels.

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_INDUSTRY_DATA_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. Industry rows, ratios, counts,
shares, market values and row dates remain raw evidence pending the
filing/evidence workflow.

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

The SZSE area-summary slice is also acquisition-only. The current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_szse_area_summary` as a monthly region-ranked report accepting
`date=YYYYMM`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
returns the seven-column base shape and the 2025-added preferred-stock and
options turnover columns. The adapter keeps either exact source order, passes
only the normalized month, validates positive ascending ranks, unique regions,
finite values and documented CNY/percentage units, and records the request
month plus non-listing counts for cache replay. It emits
`AKSHARE_SZSE_AREA_SUMMARY_RAW_ONLY`; regional exchange aggregates do not
become listing-level quote, cash-flow, return, governance, valuation or market
facts.

The Eastmoney industry-board slice is also acquisition-only. The current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_board_industry_name_em` as a current 12-field industry-board
snapshot. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_industry_em.py)
uses a no-argument full-universe request and returns ranked board identity,
market-value, turnover and leader fields. The adapter validates the exact
source order, positive ascending ranks, unique board names/codes, finite
numeric/null values and documented percentage units, and records board ordering
plus replay counts. It emits `AKSHARE_INDUSTRY_BOARD_RAW_ONLY`; current
industry-board aggregates do not become listing-level quote, cash-flow, return,
governance, valuation or market facts.

The SZSE sector-summary slice is also acquisition-only. The current [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_szse_sector_summary` as a monthly industry-trading report
accepting `symbol=当月` or `当年` and `date=YYYYMM`. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
selects the published month or year-to-date table and returns nine source
fields. The adapter passes only the normalized selector and month, validates
the source field order, leading `合计` row, unique industry order and finite
non-negative values, and records explicit CNY/share/transaction/percentage
units plus replay counts. It emits
`AKSHARE_SZSE_SECTOR_SUMMARY_RAW_ONLY`; industry exchange aggregates do not
become listing-level quote, cash-flow, return, governance, valuation or market
facts.

The A-share Eastmoney institution-daily Dragon-Tiger slice is also acquisition-
only. The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
define `stock_lhb_jgmmtj_em(start_date, end_date)` as an inclusive date-bounded
all-history response with 16 source fields. The adapter selects it only with
`MARKET_ACTIVITY` plus explicit `view=institution_daily`, passes only the two
documented date strings, validates every full-universe row's exact field order,
six-digit code, ISO date, sequence, finite numeric/null values and
listing/date uniqueness, then filters by the requested A-share code. It records
the request range, observed date bounds, source order, CNY/亿元 units,
`listing_scoped_request=false`, provider filtering and both row counts in raw
response metadata for deterministic cache replay. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_DAILY_RAW_ONLY`; institution counts,
listing-day quote context and transaction aggregates remain raw evidence and
do not enter cash flow, shareholder return, governance, valuation or canonical
market calculations.

The A-share Eastmoney institutional-research statistics slice is also
acquisition-only. The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
define `stock_jgdy_tj_em(date)` as a full A-share response whose `date` input
is the start of the announcement-date query. The upstream filter is strictly
`公告日期 > date`, and the output has 11 source fields covering listing,
research-visit, announcement, institution-count and quote context. The adapter
selects it only with `MARKET_ACTIVITY` plus explicit
`view=institution_research`, passes only the documented date string, validates
the full response's exact field order, six-digit code, two ISO dates, source
sequence, finite numeric/null values, integer institution counts and unique
listing/research-date/announcement-date identities, then filters by requested
A-share code. It records the requested cutoff, both date-field bounds, source
order, documented percentage units, `listing_scoped_request=false`, provider
filtering and both row counts for deterministic cache replay. The normalizer
emits `AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_RAW_ONLY`; research visits,
institution counts and quote context remain raw evidence and do not enter cash
flow, shareholder return, governance, valuation or canonical market
calculations.

The A-share Eastmoney institutional-research detail slice is also
acquisition-only. The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
define `stock_jgdy_detail_em(date)` as a full A-share response whose `date`
input is the start of the research-date query. The upstream filter is strictly
`调研日期 > date`, and the output has 13 source fields for listing, research
institution/person, reception context, research date, announcement date and
quote context. The adapter selects it only with `MARKET_ACTIVITY` plus
explicit `view=institution_research_detail`, passes only the documented date
string, validates the full response's exact field order, six-digit code, two
ISO dates, source sequence, finite numeric/null values and detail identity
including institution/reception context, then filters by requested A-share
code. It records the requested cutoff, both date-field bounds, source order,
documented percentage units, `listing_scoped_request=false`, provider filtering
and both row counts for deterministic cache replay. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_DETAIL_RAW_ONLY`; research
participants, visit dates and quote context remain raw evidence and do not
enter cash flow, shareholder return, governance, valuation or canonical market
calculations.

The A-share Eastmoney stock-account-statistics slice is also acquisition-only.
The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_account_em.py)
define `stock_account_statistics_em()` as a no-argument market-wide 101-row
monthly history backed by `RPT_STOCK_OPEN_DATA`. The wrapper returns the exact 11
fields `数据日期`, investor-account counts and changes, market-cap aggregates
and Shanghai Composite context; the upstream report exposes
`STATISTICS_DATE_NY` as an additional display field that the wrapper drops.
The provider selects it only with `MARKET_ACTIVITY` plus explicit
`view=account_statistics`, retains the complete A-share history, validates
strict contiguous 101-month `YYYY-MM` row range, nullable change fields, finite
numeric values and non-negative account/market-cap/index-close values, and records the
500-row single-page report/column/sort/drop/unit contract for replay. The
documented investor-count `万户` and average-market-value `万` units remain
explicit; other numeric units remain `not_documented`.

The normalizer emits `AKSHARE_ACCOUNT_STATISTICS_RAW_ONLY`; market-wide
investor-account, market-cap and index history has no listing/entity accounting
scope and therefore creates no canonical accounting, shareholder-return,
governance, market or valuation fact. H-share requests and any calculation,
gate, pipeline, CLI or input-loader use remain outside this slice.

The A-share Legu market-activity slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_market_legu.py)
define `stock_market_activity_legu()` as a no-argument HTML-backed snapshot of
the Shanghai/Shenzhen A-share market. The wrapper returns exactly 12 ordered
`item`/`value` rows for rise/fall, limit-up/down, flat/suspended, activity and
statistic-date metrics. The provider selects it only with `MARKET_ACTIVITY` plus
explicit `view=market_activity_legu`, validates the complete row count, official
item order, finite non-negative numeric counts, non-empty activity text and the
strict provider timestamp, and records the mixed value types, no-unit boundary,
source URI and market-wide row counts for deterministic cache replay.

The normalizer emits `AKSHARE_MARKET_ACTIVITY_LEGU_RAW_ONLY`; the market-wide
snapshot has no listing/entity accounting scope and therefore creates no
canonical market, return, governance, valuation or accounting fact. H-share
requests and any calculation, gate, pipeline, CLI or input-loader use remain
outside this slice.

The A-share Legu congestion slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_congestion_lg.py)
define `stock_a_congestion_lg()` as a no-argument token-backed JSON history
covering the latest four years, with exact `date`, `close` and `congestion`
fields. The provider selects it only with `MARKET_ACTIVITY` plus explicit
`view=congestion`, validates the non-empty strictly ascending ISO-date rows,
finite non-negative numeric values and exact source order, and records the
rolling-history, token/cookie-CSRF transport, source/API URIs and market-wide
row counts for deterministic cache replay.

The normalizer emits `AKSHARE_MARKET_CONGESTION_RAW_ONLY`; provider-defined
congestion and index-close history has no listing/entity accounting scope and
therefore creates no canonical market, return, governance, valuation or
accounting fact. H-share requests and any calculation, gate, pipeline, CLI or
input-loader use remain outside this slice.

The A-share Legu equity-bond-spread slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ebs_lg.py)
define `stock_ebs_lg()` as a no-argument token-backed JSON history for the CSI
300 index and the market-wide equity-bond-spread series, with exact `日期`,
`沪深300指数`, `股债利差` and `股债利差均线` fields. The provider selects it
only with `MARKET_ACTIVITY` plus explicit `view=equity_bond_spread`, validates
the non-empty strictly ascending ISO-date rows, finite numeric values and
non-negative index values, and records the all-history, fixed CSI-300 code,
token/cookie-CSRF transport, source/API URIs and market-wide row counts for
deterministic cache replay. Signed provider-defined spread values remain
accepted because the upstream documentation does not declare a non-negative
domain for those fields.

The normalizer emits `AKSHARE_EQUITY_BOND_SPREAD_RAW_ONLY`; the market-wide
history has no listing/entity accounting scope and therefore creates no
canonical market, return, governance, valuation or accounting fact. H-share
requests and any calculation, gate, pipeline, CLI or input-loader use remain
outside this slice.

The A-share Legu Buffett-index slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_buffett_index_lg.py)
define `stock_buffett_index_lg()` as a no-argument token-backed JSON history
with the documented `日期`, `收盘价`, `总市值` and `GDP` fields. The provider
selects it only with `MARKET_ACTIVITY` plus explicit `view=buffett_index`,
validates the non-empty strictly ascending ISO-date rows and finite
non-negative base values, and records the all-history, token/cookie-CSRF
transport, source/API URIs and market-wide row counts for deterministic cache
replay. The two named percentile extensions emitted by the current wrapper are
accepted only in their official optional order and remain raw without inferred
units.

The normalizer emits `AKSHARE_BUFFETT_INDEX_RAW_ONLY`; the market-wide
index/market-capitalization/GDP history has no listing/entity accounting scope
and therefore creates no canonical market, return, governance, valuation or
accounting fact. H-share requests and any calculation, gate, pipeline, CLI or
input-loader use remain outside this slice.

The A-share Legu TTM/LYR PE slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ttm_lyr.py)
define `stock_a_ttm_lyr()` as a no-argument token-backed JSON history from the
Legu `market-ttm-lyr` API, with the fixed upstream `marketId=5` and exact
`date`, TTM/LYR median and average PE, eight percentile-context, and `close`
fields. The provider selects it only with `MARKET_ACTIVITY` plus explicit
`view=ttm_lyr`, validates a non-empty strictly ascending ISO-date response,
finite required numeric values and non-negative `close`, and records the
all-history scope, exact field order, token/cookie-CSRF transport, source/API
URIs and row counts for deterministic cache replay. Signed PE and percentile
values remain raw because the official contract does not establish a
non-negative domain or numeric units.

The normalizer emits `AKSHARE_A_TTM_LYR_RAW_ONLY`; the market-wide PE and
index-close history has no listing/entity accounting scope and therefore
creates no canonical market, return, governance, valuation or accounting fact.
H-share requests and any calculation, gate, pipeline, CLI or input-loader use
remain outside this slice.

The A-share Legu all-PB slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_all_pb.py)
define `stock_a_all_pb()` as a no-argument token-backed JSON history from the
Legu `market-index-pb` API, with the fixed upstream `marketId=ALL`. The wrapper
drops the upstream `weightingAveragePB` field and returns the exact `date`,
median PB, equal-weight-average PB, `close` and four percentile-context fields.
The provider selects it only with `MARKET_ACTIVITY` plus explicit
`view=all_pb`, validates a non-empty strictly ascending ISO-date response,
finite required numeric values and non-negative `close`, and records the
all-history scope, dropped wrapper field, exact output order, token/cookie-CSRF
transport, source/API URIs and row counts for deterministic cache replay.
Signed PB and percentile values remain raw because the official contract does
not establish a non-negative domain or numeric units.

The normalizer emits `AKSHARE_A_ALL_PB_RAW_ONLY`; the market-wide PB and
index-close history has no listing/entity accounting scope and therefore
creates no canonical market, return, governance, valuation or accounting fact.
H-share requests and any calculation, gate, pipeline, CLI or input-loader use
remain outside this slice.

The A-share Legu market-PE slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_market_pe_lg` with four explicit symbols: `上证`, `深证`,
`创业板` and `科创版`. The first three symbols use the shared
`market-pe` JSON API with fixed `marketId` values 1, 2 and 4 and return the
exact `日期`, `指数`, `平均市盈率` fields; `科创版` uses the dedicated
`get-ke-chuang-ban-pe` JSON API and returns `日期`, `总市值`, `市盈率`.
The provider exposes the endpoint only with `MARKET_ACTIVITY` plus explicit
`view=market_pe` and a required symbol, preserves each symbol's source page,
API and transport metadata, and validates the variant-specific field order,
complete non-empty history, strict ascending ISO dates, finite numeric values
and non-negative index/market-capitalization values. No PE unit or universal
non-negative PE domain is inferred, so signed PE values remain raw.

The normalizer emits `AKSHARE_MARKET_PE_RAW_ONLY`; this market-wide board/index
context has no listing/entity accounting scope and therefore creates no
canonical market, return, governance, valuation or accounting fact. H-share
requests and any calculation, gate, pipeline, CLI or input-loader use remain
outside this slice.

The A-share Legu index-PE slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_index_pe_lg` with 12 explicit index symbols: `上证50`,
`沪深300`, `上证380`, `创业板50`, `中证500`, `上证180`, `深证红利`,
`深证100`, `中证1000`, `上证红利`, `中证100` and `中证800`. All symbols
use the `index-basic-pe` JSON API with their documented fixed `indexCode` and
return the exact `日期`, `指数`, `等权静态市盈率`, `静态市盈率`,
`静态市盈率中位数`, `等权滚动市盈率`, `滚动市盈率`,
`滚动市盈率中位数` fields. The provider exposes the endpoint only with
`MARKET_ACTIVITY` plus explicit `view=index_pe` and a required symbol,
preserves the fixed code and source/API/transport metadata, and validates a
complete non-empty history, strict ascending ISO dates, exact field order,
finite numeric values and non-negative index values. No PE unit or universal
non-negative PE domain is inferred, so signed PE values remain raw.

The normalizer emits `AKSHARE_INDEX_PE_RAW_ONLY`; this index-wide PE context
has no listing/entity accounting scope and therefore creates no canonical
market, return, governance, valuation or accounting fact. H-share requests
and any calculation, gate, pipeline, CLI or input-loader use remain outside
this slice.

The A-share Legu index-PB slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_index_pb_lg` with the same 12 explicit index symbols as the
index-PE view. All symbols use the `index-basic-pb` JSON API with their
documented fixed `indexCode` and return the exact `日期`, `指数`, `市净率`,
`等权市净率`, `市净率中位数` fields. The documented wrapper page is
`https://legulegu.com/stockdata/sz50-pb`, while the current official
implementation supplies CSRF cookies from
`https://legulegu.com/stockdata/zz500-ttm-lyr`; the adapter records the
documented source page as `source_uri` and the actual CSRF page as
`wrapper_source_page_uri`. It validates a complete non-empty history, strict
ascending ISO dates, exact field order, finite numeric values and non-negative
index values. No PB unit or universal non-negative PB domain is inferred, so
signed PB values remain raw.

The normalizer emits `AKSHARE_INDEX_PB_RAW_ONLY`; this index-wide PB context
has no listing/entity accounting scope and therefore creates no canonical
market, return, governance, valuation or accounting fact. H-share requests
and any calculation, gate, pipeline, CLI or input-loader use remain outside
this slice.

The A-share Baidu valuation-history slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_zh_valuation_baidu.py)
document `stock_zh_valuation_baidu` as a listing-scoped historical series with
`symbol`, an `indicator` in `总市值`, `市盈率(TTM)`, `市盈率(静)`, `市净率` or
`市现率`, and a `period` in `近一年`, `近三年`, `近五年`, `近十年` or `全部`.
The wrapper calls Baidu's JSON `https://gushitong.baidu.com/opendata` resource
with the fixed `openapi=1`, `dspName=iphone`, `tn=tangram`, `client=app`,
`word=''`, `resource_id=51171`, `market=ab`, `industry_select=''`,
`skip_industry=1` and `finClientType=pc` parameters, while deriving `query`,
`code`, `tag` and `chart_select` from the request. The adapter preserves the
exact wrapper output fields `date` and `value`, validates a non-empty strictly
ascending ISO-date history and finite numeric values, and does not infer units
or reject signed valuation values.

The normalizer emits `AKSHARE_BAIDU_VALUATION_RAW_ONLY`; the provider-defined
indicator/period series is retained as raw evidence only. Even though the
request is listing-scoped, the wrapper's valuation semantics are not reconciled
to filing-backed accounting periods, units or the canonical valuation contract,
so no canonical valuation, market, return, governance or accounting fact is
created. H-share requests and any calculation, gate, pipeline, CLI or
input-loader use remain outside this slice.

The A-share Eastmoney valuation-comparison slice is also acquisition-only. The
current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
document `stock_zh_valuation_comparison_em` as a single-symbol industry
comparison table. The adapter exposes it only under `MARKET_ACTIVITY` with
explicit `view=valuation_comparison`; the requested A-share listing supplies
the exchange-prefixed six-digit upstream `symbol` and Eastmoney filter. The
current wrapper emits 20 fields in its selected output order: `排名`, `代码`,
`简称`, `PEG`, the documented TTM/estimate PE fields, PS fields, PB fields,
cash-flow multiple fields and `EV/EBITDA-24A`; the separately listed
`市盈率-24A` input field is not selected by the current implementation. The
provider freezes the JSON report, `columns=ALL`, filter, sort and client
parameters, preserves target/industry-summary/peer row roles, and validates
the exact output schema, target identity, summary labels, ranked peer codes and
nullable finite numeric values.

The normalizer emits `AKSHARE_VALUATION_COMPARISON_RAW_ONLY`; the provider-defined
peer ranking and valuation multiples remain raw evidence only and create no
canonical valuation, market, return, governance or accounting fact. H-share
requests and any calculation, gate, pipeline, CLI or input-loader use remain
outside this slice.

The H-share Baidu valuation-history slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hk_valuation_baidu.py)
document `stock_hk_valuation_baidu` as a listing-scoped historical series with
`symbol`, the same five documented indicators and a `period` in `近一年`, `近三年`
or `全部`. The adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=valuation_baidu_hk`; the requested H-share listing supplies the five-digit
upstream `symbol`. The wrapper calls Baidu's JSON
`https://finance.baidu.com/opendata` resource with the fixed
`openapi=1`, `dspName=iphone`, `tn=tangram`, `client=app`, `word=''`,
`resource_id=51171`, `market=hk`, `industry_select=''`, `skip_industry=1` and
`finClientType=pc` parameters, while deriving `query`, `code`, `tag` and
`chart_select` from the request. The adapter preserves the exact wrapper output
fields `date` and `value`, validates a non-empty strictly ascending ISO-date
history and finite numeric values, and does not infer units or reject signed
valuation values.

The normalizer emits `AKSHARE_HK_BAIDU_VALUATION_RAW_ONLY`; the provider-defined
indicator/period series is retained as raw evidence only. Its valuation
semantics are not reconciled to filing-backed accounting periods, units or the
canonical valuation contract, so no canonical valuation, market, return,
governance or accounting fact is created. A-share requests and any calculation,
gate, pipeline, CLI or input-loader use remain outside this slice.

The A-share Legu market-PB slice is also acquisition-only. The current
[AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_market_pb_lg` with four explicit symbols: `上证`, `深证`,
`创业板` and `科创版`. All symbols use the
`index-basic-pb` JSON API with fixed `indexCode` values 1, 2, 4 and 7 and
return the exact `日期`, `指数`, `市净率`, `等权市净率`, `市净率中位数`
fields. The provider exposes the endpoint only with `MARKET_ACTIVITY` plus
explicit `view=market_pb` and a required symbol, preserves each symbol's source
page, API and transport metadata, and validates the complete non-empty history,
strict ascending ISO dates, exact field order, finite numeric values and the
non-negative index boundary. No PB unit or universal non-negative PB domain is
inferred, so signed PB values remain raw.

The normalizer emits `AKSHARE_MARKET_PB_RAW_ONLY`; this market-wide board/index
context has no listing/entity accounting scope and therefore creates no
canonical market, return, governance, valuation or accounting fact. H-share
requests and any calculation, gate, pipeline, CLI or input-loader use remain
outside this slice.

## 13. Deliberate non-goals

This foundation plus the Phase 2.2–3.21 structured slices does not include:

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
