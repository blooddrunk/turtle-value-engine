# turtle-value-engine

Evidence-based value investing engine for A/H shares, inspired by the “龟龟投资法” framework and adapted into deterministic, auditable screening and analysis rules.

## Core idea

The engine does **not** try to predict short-term stock prices. It asks five separate questions:

1. **Balance-sheet safety** — can the company survive without relying on refinancing?
2. **Real cash generation** — how much owner-distributable cash does the business actually create?
3. **Shareholder return** — how much of that economic value really reaches shareholders through dividends and net share reduction?
4. **Business quality** — how durable, understandable and capital-efficient is the business model?
5. **Valuation** — is the current market value low enough to provide a sufficient margin of safety?

The four quality/safety gates must pass independently before valuation can turn a company into a candidate. A high score in one dimension must not compensate for a hard failure in another.

## Current specification

The initial specification is being migrated from the design discussion into modular documents under `docs/spec/`.

Planned modules:

- `00-overview.md` — philosophy, decision flow, hard-gate model
- `01-cdc.md` — Core CDC / All-in CDC and cash-flow normalization
- `02-net-cash.md` — strict cash, debt equivalents and owner-realizable net cash
- `03-through-return.md` — conservative payout and net share-reduction return
- `04-business-quality.md` — evidence-based business quality model
- `05-valuation.md` — valuation engine and target-entry-price model
- `06-data-contract.md` — data provenance, confidence and pipeline boundaries

The current normalized input baseline is the standalone
`schemas/normalized-input.schema.json` contract. It is exercised by the
offline synthetic inputs under `fixtures/`.

## Implementation status

The current milestone provides isolated deterministic CDC, net-cash,
Through Return, valuation and hard-gate primitives, plus an offline
`tve analyze` command that assembles a schema-valid `CompanyAnalysis`.
Business Quality scoring accepts explicit dimension judgments, validates their
evidence lineage and applies the strict-v1 score caps; the analyze command does
not infer qualitative scores from sparse facts. Without an explicit structured
Business Quality assessment, its gate remains `NOT_EVALUATED`, valuation stays
indicative, and the final decision cannot authorize an automatic investment
recommendation.

Phase 2.2 now includes a read-only, optional-dependency `AKShareProvider` for
A/H listing metadata, company metadata, quotes and daily market history. Its
raw responses can be replayed through the provider cache and its focused
normalizer emits only canonical facts and evidence. Phase 2.3 adds cash-flow
statement acquisition for A/H listings and maps only explicit reported
operating cash flow and acquisition cash. Phase 2.4 adds a narrow income
statement slice that maps only explicit parent-attributable and consolidated
net profit. Phase 2.5–2.6 add a narrow balance-sheet slice that maps only
explicit book cash, parent/total equity and an explicitly reported
interest-bearing-debt total. Phase 2.7 adds read-only A/H dividend-event
acquisition as raw structured evidence only; it does not turn per-share plans
or plan strings into `ordinary_dividend_cash` or a payout ratio. The current
documented A-share aggregate
endpoint is date-based and only supplies the cash and total-equity subset;
the provider preserves that missing coverage rather than substituting total
liabilities. It does not rename total liabilities, sum loan sub-items, or
infer restricted cash, lease debt or upstreamability. The
adapter does not derive CDC, classify interest or restricted cash, accept
provider metrics, or infer filing-derived adjustments. Phase 2.8 adds the
documented A-share `stock_zh_a_gbjg_em` share-capital endpoint as a raw-only
history slice; its share-count and dilution semantics remain unresolved and
are not mapped into canonical facts. Phase 2.9 adds the documented A-share
`stock_repurchase_em` endpoint as a listing-filtered raw-only corporate-action
slice and Phase 2.10 adds the documented `stock_allotment_cninfo` rights-issue
endpoint as a listing-scoped raw-only slice. Planned/completed repurchase
amounts and announcement dates, plus rights-issue outcome, date, unit and
dilution semantics, are not mapped into canonical buyback, issuance or
dilution facts without a settled period and economic-scope review. Phase 2.11
adds the documented A-share `stock_share_change_cninfo` endpoint as an
explicit-date-range raw-only share-capital slice; its date, unit, class and
dilution semantics remain unresolved and are not mapped into canonical facts.
The same phase adds the documented A-share `stock_gpzy_pledge_ratio_em`
ownership-pledge snapshot as a date-bound raw-only slice; its ratio and
observation date do not identify a controlling holder or establish a
governance-risk, pledged-cash or debt-equivalent fact.
Phase 2.12 adds the documented A-share `stock_fhps_em` distribution snapshot
with an explicit June-30 or December-31 report date; its distribution ratios,
status and multiple event dates remain raw-only and do not establish settled
ordinary dividend cash or a canonical payout ratio.
Phase 2.13 adds the documented A-share `stock_yjyg_em` earnings-forecast
snapshot under a distinct `EARNINGS_FORECAST` category; its forecast ranges,
forecast type and announcement dates remain raw-only and do not establish
reported parent or consolidated net profit for the requested period.
Phase 2.14 adds the documented A-share `stock_yjbb_em` performance-report
snapshot under a distinct `PERFORMANCE_REPORT` category; its headline net
profit has no admitted parent/consolidated basis and its operating cash flow
is per share, so the response remains raw-only without canonical profit or CFO
facts. Phase 2.15 adds the documented A-share `stock_yjkb_em` earnings-quick-
report snapshot under a distinct `EARNINGS_QUICK_REPORT` category; its
headline profit/revenue comparisons, per-share indicators and announcement
date do not establish canonical entity, unit, diluted-share or filing-period
semantics, so the response remains raw-only without canonical profit or
revenue facts.
Phase 2.16 adds the documented A-share `stock_zygc_em` main-business
composition history under a distinct `BUSINESS_COMPOSITION` category. Its
overlapping product, industry and geographic rows remain raw-only because
their aggregation, unit, entity and core-business semantics are unresolved;
the normalizer emits no canonical revenue, margin or business-quality fact.
Phase 2.17 adds the documented A-share Sina `stock_financial_abstract`
historical key-indicator matrix under a distinct `FINANCIAL_ABSTRACT` category.
Its amount, per-share and ratio rows remain raw-only because the wide response
does not establish the canonical entity, unit, period or diluted-share basis;
the normalizer emits no canonical revenue, profit or CFO fact.
Phase 2.18 adds the documented A-share Eastmoney
`stock_financial_analysis_indicator_em` endpoint under a distinct
`FINANCIAL_INDICATORS` category. Its reported amounts, per-share values and
provider ratios remain raw-only because the response does not establish the
canonical entity, unit, point-in-time basis or calculation methodology; the
normalizer emits no canonical revenue, profit or CFO fact.
Phase 2.19 adds the documented SSE `stock_share_hold_change_sse` endpoint for
Shanghai A-share listings under `INSIDER_SHARE_CHANGES`. Its holder roles,
holdings, prices and event dates remain raw-only: they do not establish a
company-level diluted-share series or a governance-risk judgment, and the
normalizer emits `AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY` without creating
share-count, dilution, governance, buyback or issuance facts.
Phase 2.20 extends the same raw-only category to the documented Shenzhen
`stock_share_hold_change_szse` endpoint for Shenzhen A-share listings. Its
documented holding quantities, prices, units and event dates remain evidence
only; the normalizer preserves the same no-fabrication boundary. Phase 2.21
extends the category to the documented Beijing `stock_share_hold_change_bse`
endpoint for Beijing A-share listings. Its holding quantities are documented
in 万股 and prices in 元, but the rows remain raw evidence because they do not
establish a company-level diluted-share series or governance-risk judgment.
Phase 2.22 adds the documented H-share
`stock_financial_hk_analysis_indicator_em` historical indicator endpoint under
the same `FINANCIAL_INDICATORS` category. Its `年度`/`报告期` rows retain
reported amounts, per-share values and provider ratios as raw evidence only;
the normalizer emits the existing `AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY`
boundary without canonical revenue, profit or CFO facts. H-share
insider-share coverage remains unresolved because the current AKShare stock
documentation does not define an equivalent H-share insider endpoint.
Phase 2.23 adds the documented H-share `stock_hk_financial_indicator_em`
latest-indicator endpoint under a separate `LATEST_INDICATORS` category. Its
symbol-scoped mixed per-share, share-capital, dividend, headline financial and
valuation row remains raw evidence only; the normalizer emits
`AKSHARE_LATEST_INDICATORS_RAW_ONLY` without canonical financial, share,
dividend, market-cap, metric or valuation facts. The published output omits a
canonical statement period and row-level listing identity, so the request
scope is preserved without inventing either. H-share insider-share coverage
remains unresolved.
Phase 2.25 reviews the remaining H-share disclosure gap against the current
AKShare stock documentation: it documents no general H-share disclosure-notice
counterpart to the A-share CNINFO endpoint. The one adjacent documented slice
added here is the H-share `stock_hk_fhpx_detail_ths` dividend-event detail
endpoint, selected explicitly with `view=event_detail`. Its announcement,
ex-date, payment-date, plan, type, progress and scrip fields remain raw
structured evidence; the normalizer emits
`AKSHARE_HK_DIVIDEND_DETAIL_RAW_ONLY` without canonical dividend cash, payout,
filing or governance facts. General H-share disclosure retrieval remains a
Phase 3 concern.
Phase 2.26 adds the documented A-share `stock_zh_a_st_em` risk-warning-board
universe under `RISK_WARNING_STATUS`. The provider validates explicit listing
codes and retains the requested listing's current-trading-day row as raw
structured evidence only; the normalizer emits
`AKSHARE_RISK_WARNING_STATUS_RAW_ONLY`, leaves `special_treatment` critically
missing and does not infer `special_treatment=False` when no row matches.
H-share risk-warning coverage remains outside this slice.
Phase 2.27 adds the documented A-share Sina `stock_main_stock_holder`
endpoint under `SHAREHOLDER_HOLDINGS`. Its historical holder names, holding
quantities/ratios, share-class labels and dates remain raw structured evidence;
the normalizer emits `AKSHARE_MAIN_SHAREHOLDERS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no ownership,
share-count, dilution or valuation facts. Beneficial-control interpretation
and H-share coverage remain outside this slice.
Phase 2.28 adds the documented A-share Eastmoney `stock_tfp_em` endpoint under
`TRADING_SUSPENSIONS`. Its requested-date suspension rows, event dates,
reasons and expected resume dates remain raw structured evidence; the
normalizer emits `AKSHARE_TRADING_SUSPENSIONS_RAW_ONLY`, leaves
`special_treatment` and `governance_risk_level` critically missing and creates
no canonical status, governance or accounting fact. A complete status history
and filing-backed suspension interpretation remain outside this slice.
Phase 2.29 adds the documented A-share Eastmoney
`stock_restricted_release_queue_em` endpoint as an explicit
`view=restricted_release_queue` under `SHARE_CAPITAL`. Its symbol-scoped
restricted-share release batches remain raw structured evidence; the
normalizer emits `AKSHARE_RESTRICTED_SHARE_RELEASES_RAW_ONLY`, leaves
`normalized_diluted_economic_shares` critically missing and creates no
canonical share, dilution or valuation fact. H-share coverage and
filing-backed release interpretation remain outside this slice.
Phase 2.30 adds the documented A-share Eastmoney `stock_sy_jz_em` goodwill-
impairment report-date snapshot under `GOODWILL_IMPAIRMENT`. Its goodwill,
impairment, ratios, profit and announcement-date fields remain raw structured
evidence; the normalizer emits `AKSHARE_GOODWILL_IMPAIRMENT_RAW_ONLY`, leaves
`goodwill` and `impairment` critically missing and creates no canonical facts
until primary-filing scope and reconciliation are available. H-share coverage
and filing-backed impairment interpretation remain outside this slice.
Phase 2.31 adds the documented Sina `stock_esg_rate_sina` no-argument mixed
A/H ESG-rating universe under `ESG_RATINGS`. Its explicit code/market, agency,
rating, quarter and marker rows remain raw structured evidence; different
agency scales and provider quarter labels do not establish a comparable score,
governance-risk level or Business Quality assessment, so the normalizer emits
`AKSHARE_ESG_RATINGS_RAW_ONLY` with no canonical facts.
Phase 2.32 adds the documented SSE `stock_margin_detail_sse` endpoint under
`MARGIN_TRADING` for Shanghai A-share listings with an exact `YYYYMMDD` date.
The provider filters the full SSE security universe to the requested code and
retains financing balances, quantities and transaction flows as raw evidence.
Those are investor/security-level margin observations rather than issuer
accounting debt or cash, so the normalizer emits
`AKSHARE_MARGIN_TRADING_RAW_ONLY`, leaves `financial_debt` critically missing
and creates no canonical leverage, cash or valuation fact.
Phase 2.33 adds the documented A-share CNINFO `stock_cg_guarantee_cninfo`
external-guarantee universe under `EXTERNAL_GUARANTEES`. The provider calls
the documented `symbol="全部"` universe, filters by explicit listing code and
preserves the requested date range, guarantee count/amount, parent-company
equity and published ratio as raw evidence. Because the aggregate does not
settle quasi-debt, legal guarantee status, canonical period/entity scope or a
governance judgment, the normalizer emits
`AKSHARE_EXTERNAL_GUARANTEES_RAW_ONLY`, leaves
`material_quasi_debt`, `major_illegal_guarantee` and
`governance_risk_level` critically missing and creates no canonical fact.
H-share coverage and filing-backed interpretation remain unresolved.
Phase 2.34 adds the documented A-share
`stock_gpzy_individual_pledge_ratio_detail_em` symbol-scoped detail endpoint
as an explicit `view=individual_pledge_detail` under the existing
`OWNERSHIP_PLEDGE` category. Its holder, institution, quantity, ratio, price,
status and event-date fields remain raw structured evidence; the normalizer
emits `AKSHARE_INDIVIDUAL_PLEDGE_DETAIL_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. H-share coverage and filing-backed
pledge interpretation remain unresolved.
Phase 2.35 adds the documented A-share CNINFO `stock_cg_lawsuit_cninfo`
company-litigation universe under `LITIGATION`. The provider calls the
documented `symbol="全部"` universe, filters by explicit listing code and
preserves the requested date range, announcement interval, lawsuit count and
amount as raw evidence. Because the date-range aggregate does not settle a
canonical period, legal/accounting scope, material quasi-debt amount or
governance judgment, the normalizer emits
`AKSHARE_LITIGATION_RAW_ONLY`, leaves `material_quasi_debt` and
`governance_risk_level` critically missing and creates no canonical fact.
H-share coverage and filing-backed litigation review remain unresolved.
Phase 2.36 adds the documented A-share CNINFO
`stock_cg_equity_mortgage_cninfo` endpoint as an explicit
`view=equity_mortgage` under the existing `OWNERSHIP_PLEDGE` category. Its
query date, announcement date, pledgor/pledgee, quantities, ratios and event
description remain raw structured evidence; they do not establish a canonical
pledge period, fully diluted share count, settled pledged cash/debt-equivalent
amount or governance judgment. The normalizer emits
`AKSHARE_EQUITY_MORTGAGE_RAW_ONLY`, leaves `governance_risk_level` critically
missing and creates no canonical fact. H-share coverage and filing-backed
pledge interpretation remain unresolved.
Phase 2.37 extends the documented `stock_margin_detail_szse` endpoint under
`MARGIN_TRADING` to Shenzhen A-share listings. The provider passes an exact
`YYYYMMDD` request date, filters the full Shenzhen security universe by
explicit code and retains financing balances, financing/short-sale quantities
and security names as raw evidence. The endpoint does not return a row-level
date, so the request date is preserved as provenance rather than invented in
the payload. The normalizer emits `AKSHARE_MARGIN_TRADING_RAW_ONLY`, leaves
`financial_debt` critically missing and creates no issuer debt, cash, leverage
or valuation fact. Market-level margin summaries remain unresolved.
Phase 2.38 adds the documented A-share CNINFO `stock_hold_num_cninfo` endpoint
under the existing `SHAREHOLDER_HOLDINGS` category. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_num_cninfo.py)
define an exact quarter-end `date` from `20170331` and return shareholder
counts, average holdings and their change percentages. The provider validates
the request and each row's `变动日期`, filters the full universe to the
requested A-share listing and preserves the fields as raw evidence. The
normalizer emits `AKSHARE_SHAREHOLDER_COUNTS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no concentration,
governance or diluted-share fact.
Phase 2.39 extends the documented BSE
[`stock_margin_detail_bse`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under `MARGIN_TRADING` to Beijing A-share listings. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_bse.py)
passes an exact `YYYYMMDD` date to the full BSE security universe, validates
explicit codes and retains the requested listing as raw evidence. Because the
documented rows have no row-level observation date, the request date is
preserved only in request/response metadata. Security-level investor financing
is not issuer debt, cash or leverage, so the normalizer emits the existing
`AKSHARE_MARGIN_TRADING_RAW_ONLY` boundary without canonical facts. Market-level
margin summaries remain unresolved.
Phase 2.40 adds the documented A/H `stock_hsgt_individual_em` endpoint under
the existing `SHAREHOLDER_HOLDINGS` category, selected only with the explicit
`view=hsgt_individual` request. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
define symbol-scoped historical north-/southbound investor-holding rows for
A/H listings. The provider preserves the dated quantities, market values,
ratios and market-specific change fields as raw evidence; because the official
response drops row-level security identity, the request scope is retained
without inventing a code. The normalizer emits
`AKSHARE_HSGT_INDIVIDUAL_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no ownership,
concentration, share-count, dilution, buyback, issuance, return or valuation
fact.
Phase 2.41 adds the documented A-share CNINFO `stock_hold_control_cninfo`
endpoint under the existing `SHAREHOLDER_HOLDINGS` category, selected only
with `view=control_changes`. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
define a full A-share universe with the optional control-scope selector
`单独控制`, `实际控制人`, `一致行动人`, `家族控制` or `全部`, and publish
security identity, change date, controller names, holding quantity/ratio and
control type. The provider calls the documented universe, filters it to the
requested listing and retains the rows as raw evidence. The normalizer emits
`AKSHARE_CONTROL_HOLDINGS_RAW_ONLY`, leaves `governance_risk_level` critically
missing and creates no canonical ownership, control, share-count, dilution or
valuation fact because filing-backed legal and point-in-time semantics remain
unresolved.
Phase 2.42 adds the documented Eastmoney `stock_hold_management_detail_em`
endpoint under the existing `INSIDER_SHARE_CHANGES` category, selected only
with `view=management_detail`. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
define a no-argument full management/related-person holding-change universe
with `日期`, `代码`, `名称`, transaction, role, relationship and beginning/
ending holding fields. The provider validates every returned code and change
date, filters the universe to the requested A-share listing and retains the
documented raw fields plus endpoint/view and row-count provenance. The
normalizer emits `AKSHARE_MANAGEMENT_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
dilution, buyback, issuance, ownership, return or valuation fact.
Phase 2.43 adds the documented Eastmoney
[`stock_individual_info_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under an explicit `SHARE_CAPITAL` request with `view=individual_info`;
the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_info_em.py)
confirms the `item/value` response shape. The
listing-scoped `item/value` snapshot is validated for its returned A-share code
and optional `上市时间`, then retained as raw evidence. Its total/float shares,
market values, latest price, industry and listing date do not establish a
canonical reporting period, unit or fully diluted economic-share scope, so the
normalizer emits `AKSHARE_INDIVIDUAL_INFO_RAW_ONLY` and no canonical share or
valuation fact.
Phase 2.44 adds the documented Eastmoney
[`stock_individual_fund_flow`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under a distinct `CAPITAL_FLOW` category. Its recent daily investor
net-flow amounts/percentages and close-price context remain raw-only: they do
not establish issuer cash flow, an accounting period, a canonical liquidity
metric or a valuation fact. The provider derives the documented `sh`/`sz`/`bj`
market argument from the requested A-share identity and validates observation
dates; the normalizer emits `AKSHARE_INDIVIDUAL_FUND_FLOW_RAW_ONLY`.
Phase 2.45 adds the documented Eastmoney
[`stock_gdfx_top_10_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
under `SHAREHOLDER_HOLDINGS` with the explicit `view=top_10` selector and an
exact quarter-end report `date`. Rank, holder, share type, quantity, ratio and
change fields remain raw evidence only: they do not establish beneficial
control, a canonical concentration metric or a company-level diluted-share
series. The provider preserves the requested report period and listing scope,
and the normalizer emits `AKSHARE_TOP_10_SHAREHOLDERS_RAW_ONLY`.
Phase 2.46 adds the distinct Eastmoney
[`stock_gdfx_free_top_10_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
under `SHAREHOLDER_HOLDINGS` with the explicit `view=free_top_10` selector and
the same exact quarter-end report `date`. Its tradable-shareholder rank,
holder, share type, quantity, float-share ratio and change fields remain raw
evidence only: they do not establish beneficial control, a canonical
concentration metric or a company-level diluted-share series. The provider
preserves the requested report period and listing scope, and the normalizer
emits `AKSHARE_FREE_TOP_10_SHAREHOLDERS_RAW_ONLY`.
Phase 2.47 adds the distinct Eastmoney
[`stock_gdfx_free_holding_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint and its [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
under `SHAREHOLDER_HOLDINGS` with the explicit `view=free_holding_detail`
selector and an exact quarter-end report `date`. The provider validates the
full universe's listing code, holder, report period and optional announcement
date, then filters it to the requested A-share listing. Its holding detail,
quantity/change, float-market-value and announcement fields remain raw evidence
only: they do not establish beneficial control, a canonical concentration metric,
a company-level diluted-share series or a filing-backed governance conclusion.
The normalizer emits `AKSHARE_FREE_HOLDING_DETAIL_RAW_ONLY`.
Phase 2.48 adds the documented Eastmoney
[`stock_lhb_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under a new provider-neutral `MARKET_ACTIVITY` category. Its
inclusive date-range universe is validated and filtered to the requested
A-share listing, then retained as raw evidence; Dragon-Tiger amounts, activity
labels and forward-looking post-listing returns do not become issuer
cash-flow, shareholder-return, governance, market or valuation facts.
Phase 2.49 adds the distinct documented Eastmoney
[`stock_lhb_stock_statistic_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under the same category with explicit `view=stock_statistic` and a
`period` selected from the documented one-, three-, six- or twelve-month
windows. Its full-universe per-listing activity counts, amount aggregates and
trailing returns are validated and filtered to the requested A-share listing,
then retained as raw evidence only; they do not become issuer cash-flow,
shareholder-return, governance, market or valuation facts.
Phase 2.50 adds the distinct documented Eastmoney
[`stock_lhb_jgstatistic_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
institution-seat tracking endpoint under the same category with explicit
`view=institution_statistic` and the same documented period choices. Its
full-universe per-listing institution buy/sell counts, amount aggregates and
trailing returns are validated and filtered to the requested A-share listing,
then retained as raw evidence only; they do not become issuer cash-flow,
shareholder-return, governance, market or valuation facts.
Phase 2.51 adds the distinct documented Eastmoney
[`stock_bid_ask_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under the existing provider-neutral `MARKET_QUOTE` category with
explicit `view=bid_ask` for Shanghai and Shenzhen A-share listings. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ask_bid_em.py)
returns a fixed 36-row `item`/`value` order-book and quote-context snapshot;
the adapter validates and preserves it as raw evidence only because the
intraday response has no stable observation timestamp. It does not create a
canonical current-price, liquidity or valuation fact.
Phase 2.52 adds the distinct documented Eastmoney
[`stock_zh_a_hist_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under the existing provider-neutral `MARKET_HISTORY` category with
explicit `view=intraday`, datetime range, interval and adjustment parameters.
The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
returns period-specific minute-bar rows; the adapter validates their field
shape, finite numeric values, ascending timestamps and requested replay scope.
The normalizer emits `AKSHARE_INTRADAY_HISTORY_RAW_ONLY`: minute bars do not
replace canonical daily history or become valuation inputs.
Phase 2.53 adds the distinct documented Eastmoney
[`stock_zh_a_hist_pre_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under `MARKET_HISTORY` with explicit `view=pre_market` and
time-of-day bounds. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
returns the latest trading day's minute rows including pre-market observations;
the adapter validates the exact shape, one trading date, finite numeric values,
ascending timestamps and time-window replay scope. The normalizer emits
`AKSHARE_PRE_MARKET_HISTORY_RAW_ONLY`: this latest-day snapshot does not replace
canonical daily history or become a valuation input.
Phase 2.54 adds the distinct documented Sina
[`stock_zh_a_minute`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under `MARKET_HISTORY` with explicit `view=sina_minute`, minute
interval and adjustment parameters. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py)
returns a recent timestamped minute-bar window; the adapter validates the exact
field set, finite numeric/null values and strictly ascending timestamps. The
normalizer emits `AKSHARE_SINA_MINUTE_HISTORY_RAW_ONLY`: the provider-window
minute bars do not replace canonical daily history or become valuation inputs.
Phase 2.55 adds the distinct documented Tencent
[`stock_zh_a_hist_tx`](https://akshare.akfamily.xyz/data/stock/stock.html)
endpoint under `MARKET_HISTORY` with explicit `view=tencent_daily`, date-range
and adjustment parameters. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_tx.py)
returns market-prefixed A-share daily rows with date, OHLC, volume, turnover
and amount; the adapter validates the exact field set, finite numeric/null
values, ascending dates and inclusive range binding, and preserves the
symbol/date/adjustment replay scope. Because this is a dated daily series, the
normalizer maps the existing daily-history extension facts; volume is preserved
as `shares` and amount as `CNY`, while the provider turnover ratio remains raw
context and does not introduce a new metric or valuation fact.
Phase 2.56 adds the distinct documented Tencent historical-tick endpoint
[`stock_zh_a_tick_tx`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official callable is
[`stock_zh_a_tick_tx_js`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_tick_tx.py),
under `MARKET_HISTORY` with explicit `view=tencent_tick`. It returns the latest
trading day's time-only A-share trade rows; the adapter validates their exact
base shape, one known amount-column spelling (`成交金额` or documented `成交额`),
finite numeric/null values, integer volume/amount values, recognized trade sides
and non-decreasing times. The normalizer emits
`AKSHARE_TENCENT_TICK_RAW_ONLY`: without a trading date, these rows do not
become canonical daily-history, liquidity or valuation facts.
Phase 2.57 adds the distinct documented Eastmoney H-share minute-history
endpoint [`stock_hk_hist_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official callable is defined in the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py),
under `MARKET_HISTORY` with explicit `view=hk_intraday`. It passes the
six-digit H-share code plus datetime range, interval and adjustment mode;
the adapter validates the period-specific response fields, finite numeric/null
values, strictly ascending timestamps and inclusive range binding, and records
the listing, symbol, range, interval, adjustment and `shares`/`HKD` unit scope
for replay. The normalizer emits `AKSHARE_HK_INTRADAY_HISTORY_RAW_ONLY`: the
recent H-share minute bars remain raw evidence and do not become canonical
daily-history or valuation facts.
Phase 2.58 adds the distinct documented Eastmoney A-share chip-distribution
endpoint [`stock_cyq_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official callable is defined in the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_cyq_em.py),
under `MARKET_HISTORY` with explicit `view=chip_distribution`. It passes the
unprefixed six-digit listing code and empty-string/`qfq`/`hfq` adjustment mode;
the adapter validates the exact nine-field response, finite numeric/null values,
strictly ascending ISO dates and the maximum 90-row latest-trading-day window,
then records the listing, symbol, adjustment and observed date scope for replay.
The normalizer emits `AKSHARE_CHIP_DISTRIBUTION_RAW_ONLY`: provider-defined
benefit, cost and concentration observations remain raw evidence and do not
become canonical daily-history, liquidity, concentration or valuation facts.
Phase 2.59 adds the distinct documented Eastmoney A-share
market-participation-desire endpoint
[`stock_comment_detail_scrd_desire_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current callable is defined in the
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py),
under `MARKET_ACTIVITY` with explicit `view=participation_desire`. It passes the
unprefixed six-digit A-share listing code; the adapter validates the exact six
fields, finite numeric/null values, strictly ascending ISO dates and the
implementation's maximum 30-row window, and records the listing, symbol and
observed-date scope for replay. The normalizer emits
`AKSHARE_MARKET_PARTICIPATION_DESIRE_RAW_ONLY`: provider-defined participation
scores and changes remain raw evidence and do not become issuer cash flow,
shareholder return, governance, market or valuation facts.
Phase 2.60 adds the distinct documented Eastmoney A-share intraday-trade
endpoint [`stock_intraday_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_intraday_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_em.py),
under `MARKET_HISTORY` with explicit `view=intraday_trades`. It passes the
unprefixed six-digit A-share listing code and returns the latest trading day's
time-only `时间`, `成交价`, `手数` and `买卖盘性质` rows, including pre-market
observations. The adapter validates the exact shape, finite numeric values,
integer lot counts, recognized trade sides and non-decreasing times, while the
normalizer emits `AKSHARE_INTRADAY_TRADES_RAW_ONLY`: without a trading date,
these rows do not become canonical daily-history, liquidity or valuation facts.
Phase 2.61 adds the distinct documented Eastmoney A-share stock-popularity
endpoint [`stock_hot_rank_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_hot_rank_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py),
under `MARKET_ACTIVITY` with explicit `view=hot_rank`. It calls the documented
no-argument top-100 universe, validates the market-prefixed listing codes,
strictly ascending ranks, finite numeric/null quote fields and exact six-field
shape, then filters the response to the requested A-share listing. The
normalizer emits `AKSHARE_HOT_RANK_RAW_ONLY`: current popularity ordering and
quote context remain raw evidence and do not become a canonical market,
issuer-cash-flow, shareholder-return, governance or valuation fact.
Phase 2.62 adds the distinct documented Eastmoney A+H comparison endpoint
[`stock_zh_ah_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_hsgt_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hsgt_em.py),
under `MARKET_QUOTE` with explicit `view=ah_comparison`. It calls the
documented no-argument full A+H universe, validates the exact ten-field
response, five-/six-digit H/A identities, unique ascending sequence and finite
numeric/null comparison fields, then filters by the requested A- or H-share
side. The normalizer emits `AKSHARE_AH_COMPARISON_RAW_ONLY`: the documented
15-minute-delayed cross-market prices, changes, ratio and premium have no
stable observation timestamp and do not replace canonical current price or
become FX, comparison, valuation or calculation inputs.
Phase 2.63 adds the distinct documented Eastmoney A-share dividend-distribution
detail endpoint [`stock_fhps_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_fhps_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_fhps_em.py),
under `DIVIDENDS` with explicit `view=event_detail`. It passes the unprefixed
six-digit A-share code, validates the exact 19-field response, report-date
ordering, finite numeric/null values, optional event dates and text fields, and
records the symbol-scoped historical-detail replay boundary. The normalizer
emits `AKSHARE_A_DIVIDEND_DETAIL_RAW_ONLY`: report-period distribution rows,
event dates, ratios, per-share indicators and share-count context do not establish
settled ordinary dividend cash or a canonical payout denominator.
Phase 2.64 adds the distinct documented CNINFO A-share IPO-summary endpoint
[`stock_ipo_summary_cninfo`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_ipo_summary_cninfo.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ipo_summary_cninfo.py),
under `CORPORATE_ACTIONS` with explicit `view=ipo_summary`. It passes the
unprefixed six-digit A-share code, validates one exact 15-field row with
optional dates/numeric values and string/null underwriter context, and records
the historical IPO-summary replay scope. The normalizer emits
`AKSHARE_IPO_SUMMARY_RAW_ONLY`: offering dates, proceeds, fees and share
quantities do not establish settled issuance cash, dilution or a canonical
share fact.
Phase 2.65 adds the distinct documented Eastmoney A-share new-stock-board
endpoint [`stock_zh_a_new_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_zh_a_special.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_special.py),
under `MARKET_ACTIVITY` with explicit `view=new_stock`. It calls the documented
no-argument universe, validates the exact 17-field response, six-digit A-share
codes, unique positive sequence numbers, finite numeric/null quote fields and
non-empty names, then filters to the requested listing. The normalizer emits
`AKSHARE_NEW_STOCKS_RAW_ONLY`: the current-trading-day quote universe remains
raw evidence and does not establish a dated listing, return, valuation,
governance or canonical market fact.
Phase 2.66 adds the distinct documented Eastmoney A-share individual-notice
endpoint [`stock_individual_notice_report`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_notice.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py),
under `DISCLOSURE_NOTICES` with explicit `view=individual_notice`. It passes the
six-digit listing as `security`, maps the provider-neutral category and optional
`YYYYMMDD` bounds to the documented `symbol`, `begin_date` and `end_date`, and
validates the exact six-field code/name/title/type/date/URL response. The
normalizer emits `AKSHARE_INDIVIDUAL_NOTICES_RAW_ONLY`: announcement metadata
remains raw evidence and does not establish filing contents, an accounting
opinion or a governance-risk judgment.
Phase 2.67 adds the distinct documented Eastmoney A-share market-focus endpoint
[`stock_comment_detail_scrd_focus_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_comment_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py),
under `MARKET_ACTIVITY` with explicit `view=focus`. It passes the unprefixed
six-digit listing code, validates the exact `交易日`/`用户关注指数` rows, strict
date ordering, finite numeric/null values and the official 30-row limit, then
binds the symbol, listing, latest-window and observed-date range into replay
metadata. The normalizer emits `AKSHARE_MARKET_FOCUS_RAW_ONLY`: provider-defined
user-attention scores remain raw evidence and do not establish a canonical
market, issuer-cash-flow, shareholder-return, governance or valuation fact.
Phase 2.68 adds the distinct documented Eastmoney A-share institution-participation
endpoint [`stock_comment_detail_zlkp_jgcyd_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in the same
[`stock_comment_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py),
under `MARKET_ACTIVITY` with explicit `view=institution_participation`. It passes
the unprefixed six-digit listing code, validates the exact `交易日`/`机构参与度`
rows, strict date ordering and finite numeric/null percentage values, then binds
the symbol, historical-series scope and observed date range into replay metadata.
The normalizer emits `AKSHARE_MARKET_INSTITUTION_PARTICIPATION_RAW_ONLY`:
provider-defined institution-participation percentages remain raw evidence and
do not establish a canonical market, issuer-cash-flow, shareholder-return,
governance or valuation fact.
Phase 2.69 adds the distinct documented Eastmoney A-share limit-up-pool
endpoint [`stock_zt_pool_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_ztb_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py),
under `MARKET_ACTIVITY` with explicit `view=limit_up_pool` and a required
`YYYYMMDD` `date`. It validates the exact 16-field response, six-digit codes,
strictly ascending ranks, valid `HHMMSS` lock times, `days/ct` limit-up
statistics, finite numeric/null fields and non-empty text, then filters the
full recent-date universe to the requested listing. The normalizer emits
`AKSHARE_LIMIT_UP_POOL_RAW_ONLY`: requested-date quote, limit-up activity,
provider ranking and market-cap fields remain raw evidence and do not establish
issuer cash flow, shareholder return, governance, valuation or a canonical
market fact.
Phase 2.70 adds the distinct documented Eastmoney A-share latest stock-popularity
endpoint [`stock_hot_rank_latest_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_hot_rank_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py),
under `MARKET_ACTIVITY` with explicit `view=hot_rank_latest`. It passes the
market-prefixed A-share symbol, validates the exact ten-row `item`/`value`
response and documented item set, checks the symbol identity, `calcTime`
timestamp and integer rank fields, and records the symbol-scoped latest-rank
snapshot for replay. The normalizer emits
`AKSHARE_HOT_RANK_LATEST_RAW_ONLY`: provider popularity rank and timing remain
raw evidence and do not become issuer cash-flow, shareholder-return,
governance, valuation or canonical market facts.
Phase 2.71 adds the distinct documented Xueqiu A-share individual-spot endpoint
[`stock_individual_spot_xq`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_xq.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_xq.py),
under `MARKET_QUOTE` with explicit `view=xueqiu_spot`. It passes the derived
market-prefixed symbol, accepts no credential or timeout fields in the
provider request, validates the exact `item`/`value` row shape, documented item
allowlist, A-share identity, numeric values and `时间` timestamp, and records
the symbol-scoped snapshot for replay. The existing canonical quote contract
maps only `现价` to `current_price` and `时间` to `market_quote_timestamp`; all
other Xueqiu fields remain inside raw evidence. No calculation, gate, pipeline,
CLI or input-loader contract is changed.
Phase 2.72 adds the distinct documented Xueqiu A-share company-profile endpoint
[`stock_individual_basic_info_xq`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_basic_info_xq.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_basic_info_xq.py),
under `COMPANY_METADATA` with explicit `view=xueqiu_basic_info`. It passes the
derived market-prefixed symbol, accepts no credential or timeout fields in the
provider request, validates the exact `item`/`value` row shape, documented item
allowlist, required profile identifiers, scalar values, the documented
`affiliate_industry` object and numeric date/asset/personnel/issuance fields,
and records the symbol-scoped company-profile snapshot for replay. The
normalizer emits `AKSHARE_XUEQIU_BASIC_INFO_RAW_ONLY`: descriptive,
registration, personnel and provider-specific date fields remain raw evidence
and do not become canonical company/listing facts. No calculation, gate,
pipeline, CLI or input-loader contract is changed.

Phase 2.73 adds the distinct documented CNINFO A-share company-profile endpoint
[`stock_profile_cninfo`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_profile_cninfo.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_cninfo.py),
under `COMPANY_METADATA` with explicit `view=cninfo_profile`. It passes the
unprefixed six-digit A-share code, validates the exact 26-field single-row
profile, A-share code identity, scalar/null values and valid date-or-null
values, and
records the symbol-scoped company-profile snapshot for replay. The normalizer
emits `AKSHARE_CNINFO_PROFILE_RAW_ONLY`: descriptive, registration, contact
and provider-specific date fields do not become canonical company or listing
facts. No calculation, gate, pipeline, CLI or input-loader contract is
changed.

Phase 2.74 adds the distinct documented Tonghuashun A-share main-business-
introduction endpoint [`stock_zyjs_ths`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current official implementation is in
[`stock_zyjs_ths.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_zyjs_ths.py),
under `COMPANY_METADATA` with explicit `view=business_intro`. It passes the
unprefixed six-digit A-share code, validates the exact five-field single-row
response (`股票代码`, `主营业务`, `产品类型`, `产品名称`, `经营范围`) and code
identity, and records the symbol-scoped current business-introduction snapshot
for replay. The normalizer emits `AKSHARE_BUSINESS_INTRO_RAW_ONLY`:
descriptive business, product and operating-scope text remains raw evidence and
does not become canonical revenue, core-business or Business Quality facts. No
calculation, gate, pipeline, CLI or input-loader contract is changed.

Phase 2.75 adds the next documented A-share Eastmoney ownership-pledge view,
[`stock_gpzy_profile_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
under the existing `OWNERSHIP_PLEDGE` category with explicit
`view=market_profile`. The current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
accepts no upstream arguments and returns the historical market-wide fields
`交易日期`, `A股质押总比例`, `质押公司数量`, `质押笔数`, `质押总股数`,
`质押总市值`, `沪深300指数` and `涨跌幅`. The adapter validates the exact
shape and ascending row dates, records the A-share market scope and preserves
the source-returned ratio fraction; the source divides its documented percent
input by 100, so that scaling is explicit replay metadata. Because these rows
have no issuer identity, the normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_PROFILE_RAW_ONLY` with no canonical pledge,
governance, cash, debt-equivalent or share fact. No H-share counterpart or
calculation, gate, pipeline, CLI or input-loader contract is added.

Phase 2.76 adds the next documented A-share Eastmoney goodwill market-profile
view, [`stock_sy_profile_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
under the existing `GOODWILL_IMPAIRMENT` category with explicit
`view=market_profile`. The current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
accepts no upstream arguments and returns the historical eight-field A-share
market overview keyed by `报告期`: goodwill, goodwill impairment, net assets,
net-profit scale and three provider ratios. The adapter validates the exact
shape, finite numeric/null values and strictly ascending report periods,
records the market-wide scope and CNY/provider-ratio context, and retains all
rows without claiming issuer-level selection. The normalizer emits
`AKSHARE_GOODWILL_PROFILE_RAW_ONLY`, leaves `goodwill` and `impairment`
critically missing and creates no canonical accounting, profit, ratio or
business-quality fact because the aggregate response mixes annual/interim
periods and still requires primary-filing entity/scope reconciliation. No
H-share counterpart or calculation, gate, pipeline, CLI or input-loader
contract is changed.

Phase 2.77 adds the next documented A-share Eastmoney goodwill-impairment
forecast view, [`stock_sy_yq_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
under the same category with explicit `view=impairment_forecast` and a required
`date=YYYYMMDD`. The current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
returns a date-filtered universe with the exact 14 fields for sequence, listing
identity, change reason, latest/prior goodwill, expected-profit ranges and
change ranges, prior-year profit, announcement date and market; its documented
amount fields are primarily yuan and its change ranges are percent values. The adapter
validates the full universe's exact shape, positive ascending sequence, nullable
dates/numbers and text fields before filtering to the requested A-share code,
then records the request-period and provider-filter scope for replay. The
normalizer emits `AKSHARE_GOODWILL_FORECAST_RAW_ONLY`, leaves `goodwill` and
`impairment` critically missing and creates no canonical accounting, forecast,
profit, ratio or Business Quality fact because expected values and goodwill
context still require primary-filing entity, period and reconciliation review.
No H-share counterpart or calculation, gate, pipeline, CLI or input-loader
contract is changed.

Phase 2.78 adds the distinct documented A-share Sina large-order endpoint
[`stock_intraday_sina`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_sina.py)
takes a market-prefixed `symbol` and required `date=YYYYMMDD` under
`MARKET_HISTORY` with explicit `view=intraday_sina`. The adapter validates the
exact `symbol`, `name`, `ticktime`, `price`, `volume`, `prev_price`, `kind`
schema, `U`/`D`/`E` kind values, finite numeric fields, integer volumes and
non-decreasing time order. The normalizer emits
`AKSHARE_SINA_INTRADAY_RAW_ONLY`: because the response rows are time-only even
when the request date is explicit, they remain raw evidence and do not become
canonical daily-history, liquidity, order-flow or valuation facts. The date,
derived symbol, units and observed time bounds remain replay scope; no
calculation, gate, pipeline, CLI or input-loader contract is changed.

Phase 2.79 adds the distinct documented A-share Eastmoney goodwill-detail
endpoint [`stock_sy_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
takes a required `date=YYYYMMDD` under `GOODWILL_IMPAIRMENT`. The adapter
selects it only with explicit `view=goodwill_detail`, validates the exact ten
fields, positive ascending sequence, nullable announcement date, numeric/null
amount and ratio fields, and text fields before filtering the full A-share
universe to the requested listing. The normalizer emits
`AKSHARE_GOODWILL_DETAIL_RAW_ONLY`: aggregator goodwill, profit, ratio and
announcement values remain raw evidence and do not become canonical accounting,
profit, ratio or Business Quality facts. No H-share counterpart or calculation,
gate, pipeline, CLI or input-loader contract is changed.

Phase 2.80 adds the distinct documented A-share Eastmoney market-wide notice
endpoint [`stock_notice_report`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py)
takes a category `symbol` and required `date=YYYYMMDD` under
`DISCLOSURE_NOTICES` with explicit `view=market_notice`. The adapter validates
the exact six fields `代码`, `名称`, `公告标题`, `公告类型`, `公告日期` and `网址`,
requires every row date to match the requested date, then filters the complete
A-share notice universe to the requested listing. The normalizer emits
`AKSHARE_MARKET_NOTICES_RAW_ONLY`: date-bound announcement metadata remains raw
evidence and does not establish filing contents, an accounting opinion or a
governance-risk judgment. No H-share counterpart or calculation, gate, pipeline,
CLI or input-loader contract is changed.

Phase 2.81 adds the distinct documented A-share Eastmoney shareholder-meeting
endpoint [`stock_gddh_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gddh_em.py)
is a no-argument current-published-data call under `DISCLOSURE_NOTICES` with
explicit `view=shareholder_meeting`. The adapter validates the exact twelve-field
response, validates nullable event/publication dates and integer-like sequence
values across the full A-share response, then retains every row for the requested
listing with provider-filter metadata. The normalizer emits
`AKSHARE_SHAREHOLDER_MEETINGS_RAW_ONLY`: meeting dates and proposals remain raw
evidence, no canonical fact is emitted, and `governance_risk_level` remains
critically missing. No H-share counterpart or calculation, gate, pipeline, CLI,
or input-loader contract is changed.

Phase 2.82 adds the distinct documented Eastmoney H-share latest stock-hot-rank
endpoint [`stock_hk_hot_rank_latest_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_hot_rank_em.py)
uses the `getCurrentHkUsLatest` source and returns the exact ten-row `item`/
`value` response. Under `MARKET_ACTIVITY` with explicit
`view=hot_rank_latest`, the adapter passes the unprefixed five-digit H-share
code, requires `marketType=000003`, validates `innerCode` and `HK|` response
identity, and records the H-share endpoint, symbol format, latest-rank snapshot,
row counts and `calcTime` for replay. The normalizer emits
`AKSHARE_HK_HOT_RANK_LATEST_RAW_ONLY`, creates no canonical fact and leaves the
provider popularity rank outside calculations, gates, pipeline, CLI and
input-loader contracts. Live calls remain opt-in; tests use the official-doc
fixture with cache replay, market-specific request/response validation,
raw-only normalization and replay-scope coverage.

Phase 2.83 adds the distinct documented Eastmoney A-share limit-down-pool
endpoint [`stock_zt_pool_dtgc_em`](https://akshare.akfamily.xyz/data/stock/stock.html),
whose current [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
uses a recent-data `date` and returns the exact 16 fields for the requested
trading-day pool. Under `MARKET_ACTIVITY` with explicit
`view=limit_down_pool`, the adapter validates the full response, including
codes, ascending ranks, `HHMMSS` lock times, finite numeric/null values and
integer-like counters, before filtering to the requested A-share listing. The
fixture is a frozen real response snapshot for 20260910; cache replay and
scope-metadata checks are covered. The normalizer emits
`AKSHARE_LIMIT_DOWN_POOL_RAW_ONLY`: quote, limit-down activity, ranking and
market-cap fields remain raw evidence and do not establish issuer cash flow,
shareholder return, governance, valuation or a canonical market fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 2.84 adds the distinct documented A-share Eastmoney shareholder-count-detail
endpoint [`stock_zh_a_gdhs_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
with the symbol-scoped `view=holder_count_detail` selector. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdhs.py)
returns the exact 15-field historical response, which the adapter validates for
field order, six-digit listing identity, non-decreasing cut-off dates, nullable
announcement dates, numeric types and finite/non-negative ranges. A real
Eastmoney response fixture covers 61 rows from 2013-03-07 through 2026-06-30;
cache replay and replay-scope failures are tested. The normalizer emits
`AKSHARE_SHAREHOLDER_COUNT_DETAIL_RAW_ONLY`: holder counts, capital-change
context and market-value fields remain raw evidence and do not establish a
canonical concentration metric, governance judgment or diluted-share series.
No calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 2.85 adds the distinct documented A-share CNINFO management-holding-detail
endpoint [`stock_hold_management_detail_cninfo`](https://akshare.akfamily.xyz/data/stock/stock.html)
with the explicit provider-neutral selector `view=cninfo_management_detail` and
`direction` mapped to the official `symbol` choice `增持` or `减持`. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
returns a rolling near-one-year full universe; the adapter validates its exact
16-field schema, dates, numeric/null types and non-negative ranges before
filtering to the requested A-share code. An official response sample is checked
in with selected and non-selected codes; direction, window, units and row counts
are retained in replay metadata. The normalizer emits
`AKSHARE_CNINFO_MANAGEMENT_HOLDINGS_RAW_ONLY`: management transactions remain
raw evidence and do not establish a diluted-share series, settled cash amount or
governance judgment. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 2.86 adds the distinct documented Eastmoney H-share historical-hot-rank
endpoint [`stock_hk_hot_rank_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
with explicit `view=hk_hot_rank_detail`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_hot_rank_em.py)
posts the unprefixed five-digit H-share symbol with `marketType=000003` and
returns the exact three fields `时间`, `排名` and `证券代码` for recent historical
dates. The adapter validates the complete symbol-scoped payload, including exact
field order, ISO dates in strict ascending order, exact five-digit identity and
positive integer rank, then records the upstream symbol, H-share market type,
row counts, source field order and observed date bounds. The checked-in official
response fixture for `00700` contains 120 rows from `2026-05-15` through
`2026-09-11`; because the endpoint is already symbol-scoped, no universe row
filter is applied. The normalizer emits
`AKSHARE_HK_HOT_RANK_DETAIL_RAW_ONLY` and creates no canonical fact: dated
provider popularity rank remains raw evidence only. No calculation, gate,
pipeline, CLI or input-loader contract changes.

Phase 2.87 adds the distinct documented Eastmoney A-share A+B comparison
endpoint [`stock_zh_ab_comparison_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
with explicit `view=ab_comparison`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
returns the exact ten fields `序号`, `B股代码`, `B股名称`, `最新价B`,
`涨跌幅B`, `A股代码`, `A股名称`, `最新价A`, `涨跌幅A` and `比价`, scaling
the published quote/change/ratio values by 100 before returning them. The
adapter validates the complete no-argument A/B universe, including exact
field order, six-digit A/B identities, unique strictly ascending ranks,
finite numeric/null values and non-empty names, before filtering to the
requested A-share listing. The checked-in fixture preserves the official
documentation sample rows with both selected and non-selected A-share codes;
the B-share currency is not documented by the endpoint and is left
unresolved. The adapter records the field order, units, retrieval-only
current-trading-day scope and row counts for cache replay. The normalizer
emits `AKSHARE_AB_COMPARISON_RAW_ONLY` and creates no canonical quote,
currency, comparison or valuation fact. No calculation, gate, pipeline, CLI
or input-loader contract changes.

Phase 2.88 adds the distinct documented Eastmoney A-share historical-hot-rank
endpoint [`stock_hot_rank_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
with explicit `view=hot_rank_detail`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py)
uses the market-prefixed symbol `SZ000665`, `marketType=""` and its historical
rank/follower sources, returning the exact fields `时间`, `排名`, `证券代码`,
`新晋粉丝` and `铁杆粉丝` in that order. The adapter validates the complete
symbol-scoped payload before retaining it, including strict dates, matching
market-prefixed identity, positive integer rank and finite follower ratios;
the documented percent rates are divided by 100 into fractions. The checked-in
official snapshot uses the documented Eastmoney source URI
`https://guba.eastmoney.com/rank/stock?code=000665`, contains 366 rows from
`2025-09-11` through `2026-09-11`, and has no selected/non-selected universe
filter because the request is already listing-scoped. Row counts, field order,
units, request symbol, source URI and date bounds are retained for cache replay.
The normalizer emits `AKSHARE_HOT_RANK_DETAIL_RAW_ONLY` and creates no
canonical fact: date-bound popularity rank and follower ratios do not establish
issuer cash flow, shareholder return, governance, valuation or a canonical
market metric. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 2.89 adds the distinct documented Eastmoney A-share IPO-yield endpoint
[`stock_dxsyl_em`](https://akshare.akfamily.xyz/data/stock/stock.html), whose
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_dxsyl_em.py)
returns the no-argument full universe at
`https://data.eastmoney.com/xg/xg/dxsyl.html`. Under `CORPORATE_ACTIONS` with
explicit `view=ipo_yield`, the adapter preserves the exact 17-field source
order, provider-reported numeric values (including the documented percent and
household fields), listing dates and nulls; it validates every upstream row,
including six-digit codes, unique ascending sequence numbers, dates and finite
numeric values, before filtering to the requested A-share listing. The checked-in
fixture contains three official response rows with one selected and two
non-selected codes, and records the 3-to-1 upstream/selected counts and date
bounds for replay. The normalizer emits `AKSHARE_IPO_YIELD_RAW_ONLY`: IPO
yield, issue quantities, prices, returns and listing dates do not establish a
settled issuance-cash period, unit or diluted-share fact. No calculation, gate,
pipeline, CLI or input-loader contract changes.

Phase 2.90 adds the distinct documented Eastmoney A-share block-trade detail
endpoint [`stock_dzjy_mrmx`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_ACTIVITY` with explicit `view=block_trade_detail`,
`symbol="A股"`, `start_date` and `end_date`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_dzjy_em.py)
returns the exact 13 fields `序号`, `交易日期`, `证券代码`, `证券简称`, `涨跌幅`,
`收盘价`, `成交价`, `折溢率`, `成交量`, `成交额`, `成交额/流通市值`, `买方营业部`
and `卖方营业部`. The provider validates the complete requested date-range
universe, field order, six-digit identities, sequence numbers, dates, finite
numeric values and non-empty text before filtering to the requested A-share.
The normalizer emits `AKSHARE_BLOCK_TRADE_RAW_ONLY`: trade prices, quantities,
amounts, discount/premium and brokerage context do not establish issuer cash
flow, shareholder return, governance, valuation or a canonical market metric.
No calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 2.91 adds the distinct documented Eastmoney H-share main-board quote
endpoint [`stock_hk_main_board_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=hk_main_board`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
is a no-argument full-universe request at
`https://quote.eastmoney.com/center/gridlist.html#hk_mainboard` and returns the
exact 12 fields `序号`, `代码`, `名称`, `最新价`, `涨跌额`, `涨跌幅`, `今开`, `最高`,
`最低`, `昨收`, `成交量` and `成交额`. The provider validates the complete
main-board response, including five-digit identities, strictly ascending
sequence numbers, exact field order and finite numeric/null values, before
filtering to the requested H-share. The checked-in fixture freezes three
source-shaped rows with one selected listing; scope, units and full/selected
row counts are retained for replay. Because the official documentation marks
the quote as 15-minute delayed and supplies no stable observation timestamp,
the normalizer emits `AKSHARE_HK_MAIN_BOARD_QUOTE_RAW_ONLY`, marks
`current_price` critically missing and creates no canonical quote fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 2.92 adds the distinct official SSE daily-deal overview endpoint
[`stock_sse_deal_daily`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_ACTIVITY` with explicit `view=sse_deal_daily` and a required
`date=YYYYMMDD`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
returns the exact six fields `单日情况`, `股票`, `主板A`, `主板B`, `科创板` and
`股票回购` in eight fixed metric rows, supports dates from `20211227`, and
passes only the date to the SSE market-level call. The provider validates the
complete response and exact field/metric order, records the requested date,
SSE scope, absence of documented numeric units and non-listing row counts for
replay, and the normalizer emits `AKSHARE_SSE_DEAL_DAILY_RAW_ONLY` without
creating a canonical fact. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 2.93 adds the distinct official SSE market-summary endpoint
[`stock_sse_summary`](https://akshare.akfamily.xyz/data/stock/stock.html) under
`MARKET_ACTIVITY` with explicit `view=sse_summary`. The no-argument endpoint's
eight market/board metrics and embedded report date are validated in the
source-shaped order returned by the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py),
then retained as a market-level raw snapshot with source scope, undocumented
numeric units and replay counts. The normalizer emits
`AKSHARE_SSE_SUMMARY_RAW_ONLY` without creating a listing-level or canonical
market fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 2.94 adds the distinct official SZSE market-summary endpoint
[`stock_szse_summary`](https://akshare.akfamily.xyz/data/stock/stock.html) under
`MARKET_ACTIVITY` with explicit `view=szse_summary` and required
`date=YYYYMMDD`. Its exact five-field response—`证券类别`, `数量`, `成交金额`,
`总市值`, `流通市值`—is validated row by row in the source-shaped order
returned by the [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py),
including category uniqueness, the required `股票` category, numeric types and
null handling. The adapter records Shenzhen scope, requested/observation date,
documented quantity/transaction-amount units, undocumented market-value units
and replay metadata. The normalizer emits
`AKSHARE_SZSE_SUMMARY_RAW_ONLY` without creating a listing-level or canonical
market fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 2.95 adds the distinct official SZSE `stock_szse_area_summary` endpoint
under `MARKET_ACTIVITY` with explicit `view=szse_area_summary` and required
monthly `date=YYYYMM`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define a region-ranked base response with seven fields and a 2025 extended
response adding preferred-stock and options turnover. The provider validates
the exact source order, positive ascending ranks, unique regions, finite
numeric values and documented CNY/percentage units, and preserves the request
month and non-listing row counts for replay. The normalizer emits
`AKSHARE_SZSE_AREA_SUMMARY_RAW_ONLY` without creating a listing-level or
canonical market fact. No calculation, gate, pipeline, CLI or input-loader
contract changes.

Phase 2.96 adds the distinct official A-share SZSE
`stock_szse_sector_summary` endpoint under `MARKET_ACTIVITY` with explicit
`view=szse_sector_summary`, `symbol` selector (`当月` or `当年`) and monthly
`date=YYYYMM`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
define the nine-field industry-trading response and the source's separate
month/year-to-date tables. The provider validates the complete source order,
non-empty unique industry order, numeric/null values and documented
CNY/share/transaction/percentage units, and preserves the selector, month and
non-listing row counts for replay. The normalizer emits
`AKSHARE_SZSE_SECTOR_SUMMARY_RAW_ONLY` without creating a listing-level or
canonical market fact. No calculation, gate, pipeline, CLI or input-loader
contract changes.

Phase 2.97 adds the distinct official A-share Eastmoney
`stock_board_industry_name_em` endpoint under `MARKET_ACTIVITY` with explicit
`view=industry_board`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_industry_em.py)
define the current 12-field industry-board snapshot. The provider validates
the complete source order, ranked board/code identity, numeric/null values and
documented percentage units, and preserves the board ordering and
non-listing row counts for replay. The normalizer emits
`AKSHARE_INDUSTRY_BOARD_RAW_ONLY` without creating a listing-level or canonical
market fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 2.98 adds the distinct official A-share Eastmoney
`stock_ggcg_em` endpoint under `INSIDER_SHARE_CHANGES` with explicit
`view=executive_share_changes` and `direction` (`全部`, `股东增持` or
`股东减持`). The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdzjc_em.py)
define a direction-filtered full-universe response with 16 source-shaped
identity, holder, quote, quantity/ratio and event-date fields. The provider
validates the complete response before filtering it to the requested listing,
and preserves direction, field order, documented 万股/% units, the
undocumented latest-price unit, event-date bounds and replay row counts. The
normalizer emits `AKSHARE_EXECUTIVE_SHARE_CHANGES_RAW_ONLY` without creating a
canonical share, dilution, cash, governance or shareholder-return fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 2.99 adds the distinct official A-share Eastmoney
`stock_hold_management_person_em` endpoint under `INSIDER_SHARE_CHANGES` with
explicit `view=management_person`, a six-digit listing `symbol` and executive
`name`. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
define the symbol/person-scoped 16-field change response. The provider
validates field order, listing/person identity, dates, numeric ranges and
replay scope while leaving all numeric units `not_documented`; the normalizer
emits `AKSHARE_MANAGEMENT_PERSON_RAW_ONLY` without creating canonical share,
dilution, cash, governance or shareholder-return facts. No calculation, gate,
pipeline, CLI or input-loader contract changes.

Phase 3.00 adds the distinct official A-share Eastmoney
`stock_lhb_jgmmtj_em` institution-daily Dragon-Tiger view under
`MARKET_ACTIVITY` with explicit `view=institution_daily` and an inclusive
`start_date`/`end_date` range. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
define the exact 16-field full-universe response. The provider validates source
order, six-digit listing identity, date range, sequence, finite numeric/null
values and non-negative fields before filtering to the requested listing; it
records the documented CNY/亿元 units and leaves all other numeric units
`not_documented`. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_DAILY_RAW_ONLY` without creating a
canonical cash-flow, return, governance, valuation or market fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.01 adds the distinct official A-share Eastmoney
`stock_jgdy_tj_em` institutional-research statistics view under
`MARKET_ACTIVITY` with explicit `view=institution_research` and a
`date=YYYYMMDD` notice-date cutoff. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
define the exact 11-field full-universe response. The provider validates source
order, six-digit listing identity, reception/announcement dates, the strict
announcement-date boundary, finite numeric/null values and non-negative fields
before filtering to the requested listing; only the documented percentage unit
is recorded and other numeric units remain `not_documented`. The normalizer
emits `AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_RAW_ONLY` without creating
a canonical cash-flow, return, governance, valuation or market fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.02 adds the distinct official A-share Eastmoney
`stock_jgdy_detail_em` institutional-research detail view under
`MARKET_ACTIVITY` with explicit `view=institution_research_detail` and a
`date=YYYYMMDD` research-date cutoff. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
define the exact 13-field full-universe response. The provider validates source
order, six-digit listing identity, strict research-date boundary, finite
numeric/null values and detail identity including institution/reception
context before filtering to the requested listing; only the documented
percentage unit is recorded and price units remain `not_documented`. The
normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_DETAIL_RAW_ONLY` without
creating a canonical cash-flow, return, governance, valuation or market fact.
No calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.03 adds the next distinct official A-share Eastmoney pledge endpoint,
`stock_gpzy_pledge_ratio_detail_em`, under `OWNERSHIP_PLEDGE` with explicit
`view=market_pledge_detail` and no upstream arguments. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define a full-universe important-shareholder pledge-detail response with 15
source-shaped fields, 500-row pagination and descending announcement-date
ordering. The provider validates exact field order, six-digit identity,
required text/announcement fields, source-coerced nullable `质押机构` and
`质押开始日期`, sequence/date boundaries, duplicate pledge identity, finite
non-negative numeric values and explicit shares/percent/CNY-per-share units
before filtering to the requested A-share listing, and records source order,
required/nullable fields, nullable identity fields, date bounds and pagination
for replay. The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_MARKET_DETAIL_RAW_ONLY`; holder, counterparty,
quantity, ratio, price, status and event-date context remain raw evidence and
do not become canonical share, cash, debt-equivalent or governance facts. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.04 adds the next distinct official A-share Eastmoney pledge endpoint,
`stock_gpzy_distribute_statistics_company_em`, under `OWNERSHIP_PLEDGE` with
explicit `view=company_distribution` and no upstream arguments. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define the current securities-only `RPT_GDZY_ZYJG_SUM` institution-distribution
snapshot with eight source-shaped fields, a 500-row page, descending
`ORG_NUM` ordering and documented shares/percent units. The provider validates
the full response before retention, preserves source-returned numeric scale,
and records exact field order/types/nullability, institution identity/order,
sort/filter/pagination and non-listing replay scope. The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_COMPANY_DISTRIBUTION_RAW_ONLY`; institution rows and
provider percentages remain raw evidence and do not become canonical share,
cash, debt-equivalent or governance facts. No calculation, gate, pipeline, CLI
or input-loader contract changes.

Phase 3.05 adds the next distinct official A-share Eastmoney pledge endpoint,
`stock_gpzy_distribute_statistics_bank_em`, under `OWNERSHIP_PLEDGE` with
explicit `view=bank_distribution` and no upstream arguments. The [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define the same eight source-shaped fields as the company-distribution view,
backed by `RPT_GDZY_ZYJG_SUM`, one 500-row page, descending `ORG_NUM` order and
the documented `(PFORG_TYPE="银行")` filter. The provider validates the full
market-wide response before retention and records exact field order/types,
nullability, institution identity/order, units, sort/filter/pagination and
non-listing replay scope. The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_BANK_DISTRIBUTION_RAW_ONLY`; bank institution rows,
pledged-share counts and provider percentages remain raw evidence and do not
become canonical share, cash, debt-equivalent or governance facts.

A live probe on 2026-09-11 observed current Eastmoney report labels
`银行Ⅱ`/`证券Ⅱ`, while the documented `银行` filter used by the current
AKShare wrapper returned no rows. The adapter records the official wrapper
filter contract and does not silently reinterpret or merge the suffixed report
labels; that upstream drift requires a separately reviewed adapter/upstream
fix. No calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.06 adds the next distinct official A-share Eastmoney pledge endpoint,
`stock_gpzy_industry_data_em`, under `OWNERSHIP_PLEDGE` with explicit
`view=industry_data` and no upstream arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
define the current `RPT_CSDC_INDUSTRY_STATISTICS` industry snapshot with eight
source-shaped fields, one 500-row page and descending
`AVERAGE_PLEDGE_RATIO` ordering. The provider validates the complete
market-wide response, preserves row-specific `统计时间`, documented
percent/shares/CNY units and provider industry text, and records the fixed
report/page/sort contract for replay. A live probe observed labels with the
`Ⅱ` suffix; the adapter does not merge or relabel them. The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_INDUSTRY_DATA_RAW_ONLY`; industry rows and metrics
remain raw evidence and do not become canonical share, cash, debt-equivalent
or governance facts. No calculation, gate, pipeline, CLI or input-loader
contract changes.

Phase 3.07 adds the next distinct official A-share Eastmoney goodwill endpoint,
`stock_sy_hy_em`, under `GOODWILL_IMPAIRMENT` with explicit
`view=industry_data` and a required `date=YYYYMMDD`. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
define the `RPT_GOODWILL_INDUSTATISTICS` market-wide industry response with
the six fields `行业名称`, `公司家数`, `商誉规模`, `净资产`,
`商誉规模占净资产规模比例` and `净利润规模`. The provider validates the
complete all-page response, preserves the provider ratio scale, binds the
request date to the report filter and records source columns, dropped fields,
ordering and units for replay. The normalizer emits
`AKSHARE_GOODWILL_INDUSTRY_DATA_RAW_ONLY`; industry aggregates remain raw
evidence and do not become canonical goodwill or impairment facts. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.08 adds the documented A-share Eastmoney
`stock_account_statistics_em` endpoint under `MARKET_ACTIVITY` with explicit
`view=account_statistics` and no upstream arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_account_em.py)
define the complete 101-row monthly history from `2015-04` through the
documented `2023-08` endpoint range, returning 11 fields for data date, investor-account
counts, market-cap aggregates and Shanghai Composite context. The provider
validates exact field order, the contiguous 101-month `YYYY-MM` date range,
finite numeric values, nullable change fields, non-negative stock/account aggregates and
records the upstream report, columns, sort and wrapper-drop contract for
replay. The normalizer emits
`AKSHARE_ACCOUNT_STATISTICS_RAW_ONLY`; market-wide account, market-cap and
index history remains raw evidence and does not become canonical accounting,
shareholder-return, governance or valuation facts. No calculation, gate,
pipeline, CLI or input-loader contract changes.

Phase 3.09 adds the documented A-share Legu
`stock_market_activity_legu` endpoint under `MARKET_ACTIVITY` with explicit
`view=market_activity_legu` and no upstream arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_market_legu.py)
define the HTML-backed current Shanghai/Shenzhen A-share market snapshot with
12 exact `item`/`value` rows: rise/fall and limit-up/down counts, flat/suspended
counts, activity text and the provider timestamp. The provider validates the
official metric order, finite non-negative numeric values, non-empty activity
text, strict timestamp format and complete market-wide row counts, while
retaining the absence of documented units. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_LEGU_RAW_ONLY`; the market-wide snapshot creates no
canonical market, return, governance, valuation or accounting fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.10 adds the documented A-share Legu
`stock_a_congestion_lg` endpoint under `MARKET_ACTIVITY` with explicit
`view=congestion` and no user-supplied upstream arguments. The [AKShare
stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_congestion_lg.py)
define a token-backed JSON history of the latest four years with exact
`date`, `close` and `congestion` fields. The provider validates non-empty
strictly ascending ISO dates, finite non-negative numeric values, source/API
metadata and market-wide row counts while preserving undocumented units. The
normalizer emits `AKSHARE_MARKET_CONGESTION_RAW_ONLY`; provider-defined
congestion and index-close history does not become a canonical market, return,
governance, valuation or accounting fact. No calculation, gate, pipeline, CLI
or input-loader contract changes.

Phase 3.11 adds the documented A-share Legu
`stock_ebs_lg` endpoint under `MARKET_ACTIVITY` with explicit
`view=equity_bond_spread` and no user-supplied arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ebs_lg.py)
define a token-backed JSON history with exact `日期`, `沪深300指数`, `股债利差`
and `股债利差均线` fields in ascending date order. The provider validates the
non-empty complete history, strict ISO dates, finite numeric values and the
non-negative index series while preserving signed spread values and
undocumented units. The normalizer emits
`AKSHARE_EQUITY_BOND_SPREAD_RAW_ONLY`; this market-wide provider context does
not become a canonical market, return, valuation, governance or accounting
fact. No calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.12 adds the documented A-share Legu
`stock_buffett_index_lg` endpoint under `MARKET_ACTIVITY` with explicit
`view=buffett_index` and no user-supplied arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_buffett_index_lg.py)
define a token-backed JSON history with four documented fields: `日期`, `收盘价`,
`总市值` and `GDP`. The provider validates a non-empty strictly ascending
history, strict ISO dates and finite non-negative base values; the two named
percentile extensions emitted by the wrapper, when present, remain optional
raw fields with no inferred units. The normalizer emits
`AKSHARE_BUFFETT_INDEX_RAW_ONLY`; this market-wide index/market-capitalization/
GDP context does not become a canonical market, return, valuation, governance
or accounting fact. No calculation, gate, pipeline, CLI or input-loader
contract changes.

Phase 3.13 adds the documented A-share Legu
`stock_a_ttm_lyr` endpoint under `MARKET_ACTIVITY` with explicit
`view=ttm_lyr` and no user-supplied arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ttm_lyr.py)
define a token-backed JSON history with the documented date, equal-weight and
median TTM/LYR PE fields, their percentile context and CSI 300 close. The
provider validates the complete 14-field schema, strict ascending ISO dates,
finite numeric values and a non-negative index-close field without inferring
units or PE semantics. The normalizer emits
`AKSHARE_A_TTM_LYR_RAW_ONLY`; this market-wide valuation context does not become
a canonical market, return, valuation, governance or accounting fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.14 adds the documented A-share Legu
`stock_a_all_pb` endpoint under `MARKET_ACTIVITY` with explicit
`view=all_pb` and no user-supplied arguments. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_all_pb.py)
define a token-backed JSON history with the documented median and equal-weight
average PB fields, percentile context and Shanghai index close. The wrapper
drops the upstream `weightingAveragePB` field; the provider validates the
remaining complete eight-field schema, strict ascending ISO dates, finite
numeric values and a non-negative index-close field without inferring units or
PB semantics. The normalizer emits `AKSHARE_A_ALL_PB_RAW_ONLY`; this
market-wide valuation context does not become a canonical market, return,
valuation, governance or accounting fact. No calculation, gate, pipeline, CLI
or input-loader contract changes.

Phase 3.15 adds the documented A-share Legu `stock_market_pe_lg` endpoint under
`MARKET_ACTIVITY` with explicit `view=market_pe` and a required `symbol` in
`{"上证", "深证", "创业板", "科创版"}`. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
define standard-board output as `日期`, `指数`, `平均市盈率`, and the 科创版
variant as `日期`, `总市值`, `市盈率`. The provider preserves the
symbol-specific source page/API, fixed `marketId` for 上证/深证/创业板, exact
variant schema and strict all-history ordering; index/market-capitalization
values must be non-negative while PE values remain signed raw context because
the official contract documents no unit or PE domain. The normalizer emits
`AKSHARE_MARKET_PE_RAW_ONLY`; this market-wide context does not become a
canonical market, return, valuation, governance or accounting fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.16 adds the documented A-share Legu `stock_market_pb_lg` endpoint under
`MARKET_ACTIVITY` with explicit `view=market_pb` and a required `symbol` in the
same four-board set. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
define the exact five-field output `日期`, `指数`, `市净率`, `等权市净率`,
`市净率中位数`. The provider preserves symbol-specific source pages and the
fixed upstream `indexCode` values 1/2/4/7, validates the complete strictly
ascending all-history response, and retains signed PB values as raw context
because the official contract documents no unit or PB domain. The normalizer
emits `AKSHARE_MARKET_PB_RAW_ONLY`; this market-wide context does not become a
canonical market, return, valuation, governance or accounting fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.17 adds the documented A-share Legu `stock_index_pe_lg` endpoint under
`MARKET_ACTIVITY` with explicit `view=index_pe` and a required `symbol` in the
12 documented index choices (`上证50`, `沪深300`, `上证380`, `创业板50`,
`中证500`, `上证180`, `深证红利`, `深证100`, `中证1000`, `上证红利`,
`中证100`, `中证800`). The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
define the exact eight-field date/index/static-PE/rolling-PE history. The
provider preserves the fixed Legu `indexCode` mapping and source/API metadata,
validates complete strictly ascending all-history rows, and retains signed PE
values as raw context because the official contract documents no unit or PE
domain. The normalizer emits `AKSHARE_INDEX_PE_RAW_ONLY`; this index-wide
context does not become a canonical market, return, valuation, governance or
accounting fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 3.18 adds the documented A-share Legu `stock_index_pb_lg` endpoint under
`MARKET_ACTIVITY` with explicit `view=index_pb` and a required `symbol` in the
same 12 documented index choices. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
define the exact five-field `日期`, `指数`, `市净率`, `等权市净率` and
`市净率中位数` history. The provider preserves the fixed Legu `indexCode`
mapping and `index-basic-pb` API metadata, validates complete strictly ascending
all-history rows, and retains signed PB values as raw context because the
official contract documents no unit or PB domain. The documented source page is
`sz50-pb`; the official wrapper's CSRF transport currently uses
`zz500-ttm-lyr`, and both are retained distinctly in metadata. The normalizer
emits `AKSHARE_INDEX_PB_RAW_ONLY`; this index-wide context does not become a
canonical market, return, valuation, governance or accounting fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.19 adds the documented A-share Baidu `stock_zh_valuation_baidu`
valuation-history endpoint under `MARKET_ACTIVITY` with explicit
`view=valuation_baidu`, a derived six-digit listing code, one of the five
documented indicators (`总市值`, `市盈率(TTM)`, `市盈率(静)`, `市净率`,
`市现率`) and one of the five documented periods (`近一年`, `近三年`, `近五年`,
`近十年`, `全部`). The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_zh_valuation_baidu.py)
define the exact `date`/`value` history and the Baidu JSON request parameters.
The provider freezes the documented fixed parameters, preserves the selected
indicator/period and listing-scoped row counts, validates non-empty strictly
ascending dates and finite numeric values, and allows signed valuation values
because the upstream contract documents no unit or universal domain. The
normalizer emits `AKSHARE_BAIDU_VALUATION_RAW_ONLY`; this provider-defined
series is retained as raw evidence and does not become a canonical valuation,
market, return, governance or accounting fact. No calculation, gate, pipeline,
CLI or input-loader contract changes.

Phase 3.20 adds the documented H-share Baidu `stock_hk_valuation_baidu`
valuation-history endpoint under `MARKET_ACTIVITY` with explicit
`view=valuation_baidu_hk`, a derived five-digit H-share listing code, one of the
five documented indicators (`总市值`, `市盈率(TTM)`, `市盈率(静)`, `市净率`,
`市现率`) and one of the three documented periods (`近一年`, `近三年`, `全部`).
The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hk_valuation_baidu.py)
define the exact `date`/`value` history and the Baidu JSON request parameters.
The provider freezes the documented fixed parameters including `market=hk`,
preserves the selected indicator/period and listing-scoped row counts, validates
non-empty strictly ascending dates and finite numeric values, and allows signed
valuation values because the upstream contract documents no unit or universal
domain. The normalizer emits `AKSHARE_HK_BAIDU_VALUATION_RAW_ONLY`; this
provider-defined series remains raw evidence and does not become a canonical
valuation, market, return, governance or accounting fact. No calculation, gate,
pipeline, CLI or input-loader contract changes.

Phase 3.21 adds the documented A-share Eastmoney
`stock_zh_valuation_comparison_em` valuation-comparison endpoint under
`MARKET_ACTIVITY` with explicit `view=valuation_comparison` and a derived
exchange-prefixed six-digit listing symbol. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
define the wrapper's 20-field target/industry-summary/peer table; the current
implementation does not emit the separately listed `市盈率-24A` field. The
provider freezes the Eastmoney JSON report/filter/sort parameters, preserves
the target and peer-row roles, accepts nullable and signed provider multiples,
and validates the target, summary rows, peer codes/ranks and exact output
schema. The normalizer emits `AKSHARE_VALUATION_COMPARISON_RAW_ONLY`; this
provider-defined peer comparison remains raw evidence and does not become a
canonical valuation, market, return, governance or accounting fact. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.22 adds the documented H-share Eastmoney
`stock_hk_valuation_comparison_em` valuation-comparison endpoint under
`MARKET_ACTIVITY` with explicit `view=valuation_comparison_hk` and a derived
five-digit H-share listing symbol. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_comparison_em.py)
define the exact 18-field single-listing output: two text identity fields,
eight nullable/signed valuation multiples and eight positive integer rank
fields. The provider freezes the Eastmoney JSON report, explicit columns,
listing filter and client parameters, records the wrapper's one-row scope and
validates the exact output schema. The normalizer emits
`AKSHARE_HK_VALUATION_COMPARISON_RAW_ONLY`; this provider-defined comparison
remains raw evidence and does not become a canonical valuation, market, return,
governance or accounting fact. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 3.23 adds the documented A-share Eastmoney
`stock_zh_growth_comparison_em` growth-comparison endpoint under
`MARKET_ACTIVITY` with explicit `view=growth_comparison` and a derived
exchange-prefixed six-digit listing symbol. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
define the exact 21-field industry-average/industry-median/peer/target table.
The provider freezes the Eastmoney JSON report, filter, sort, client and
version parameters, preserves the wrapper row roles and ranks, accepts
nullable and signed growth values, and validates the exact output schema. The
normalizer emits `AKSHARE_GROWTH_COMPARISON_RAW_ONLY`; this provider-defined
growth comparison remains raw evidence and does not become a canonical growth,
valuation, market, return, governance or accounting fact. No calculation,
gate, pipeline, CLI or input-loader contract changes.

Phase 3.24 adds the documented H-share Eastmoney
`stock_hk_growth_comparison_em` growth-comparison endpoint under
`MARKET_ACTIVITY` with explicit `view=growth_comparison_hk` and a derived
unprefixed five-digit H-share listing symbol. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_comparison_em.py)
define the exact 10-field single-listing output, including the source's mapped
`基本每股收总资产同比增长率益同比增长率` label. The provider freezes the
explicit Eastmoney report/columns, dual listing filter, page/client/version
parameters and dropped fields, accepts nullable/signed growth metrics and
positive integer ranks, and validates the one-row listing identity. The
normalizer emits `AKSHARE_HK_GROWTH_COMPARISON_RAW_ONLY`; this provider-defined
comparison remains raw evidence and does not become a canonical growth,
valuation, market, return, governance or accounting fact. No calculation,
gate, pipeline, CLI or input-loader contract changes.

Phase 3.25 adds the documented A-share Eastmoney
`stock_zh_dupont_comparison_em` DuPont-comparison endpoint under
`MARKET_ACTIVITY` with explicit `view=dupont_comparison` and a derived
exchange-prefixed six-digit listing symbol. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
define the exact 19-field industry-summary/ranked-comparison output: two text
identity fields, 16 nullable/signed DuPont metrics and a nullable positive
integer `ROE-3年平均排名` field. The provider freezes the Eastmoney JSON report,
filter, sort, client and version parameters, preserves the current wrapper row
roles and validates the exact output schema. The normalizer emits
`AKSHARE_DUPONT_COMPARISON_RAW_ONLY`; this provider-defined comparison remains
raw evidence and does not become a canonical profitability, growth, valuation,
market, return, governance or accounting fact. No calculation, gate, pipeline,
CLI or input-loader contract changes.

Phase 3.26 adds the documented A-share Eastmoney
`stock_zh_scale_comparison_em` company-scale comparison endpoint under
`MARKET_ACTIVITY` with explicit `view=scale_comparison` and a derived
exchange-prefixed six-digit listing symbol. The [AKShare stock-data
documentation](https://akshare.akfamily.xyz/data/stock/stock.html) and [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
define the exact 10-field single-listing output: two text identity fields,
four nullable numeric scale metrics and four positive integer rank fields. The
provider freezes the Eastmoney report/columns, dual listing filter, single-page
sort, source/client/version parameters and dropped fields, validates the
listing identity and preserves the official row as raw structured evidence.
The normalizer emits `AKSHARE_SCALE_COMPARISON_RAW_ONLY`; this
provider-defined company-scale snapshot does not become a canonical market,
valuation or accounting fact. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 3.27 adds the documented A-share CDR daily-history endpoint
`stock_zh_a_cdr_daily` under `MARKET_HISTORY` with explicit
`view=cdr_daily`, an exchange-prefixed Sina symbol and inclusive date-range
parameters. The [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py)
define the exact six-field `date`/OHLC/`volume` output. The provider freezes
the CDR source page, encrypted-JavaScript upstream, decoder and date-slice
metadata, records the documented lot-volume unit, validates strict date order
and finite numeric rows, and preserves the response as raw evidence.
The normalizer emits `AKSHARE_CDR_DAILY_HISTORY_RAW_ONLY`; this CDR-specific
series does not become a canonical daily market-history fact. No calculation,
gate, pipeline, CLI or input-loader contract changes.

Phase 3.28 adds the documented H-share Eastmoney famous-stock quote endpoint
[`stock_hk_famous_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=hk_famous`. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_famous.py)
issues a no-argument request for the `b:DLMK0106` famous-stock universe through
Eastmoney's JSON quote API and returns the exact 12 fields `序号`, `代码`, `名称`,
`最新价`, `涨跌额`, `涨跌幅`, `今开`, `最高`, `最低`, `昨收`, `成交量` and `成交额`.
The provider freezes the official query parameters and source page, validates
the complete five-digit H-share universe, then filters to the requested
listing while retaining HKD/share, percent, share-count and HKD-turnover units
and full/selected row counts in replay metadata.

Because the official quote is a 15-minute-delayed current-day snapshot without
a stable observation timestamp, the normalizer emits
`AKSHARE_HK_FAMOUS_QUOTE_RAW_ONLY`, marks `current_price` critically missing and
creates no canonical quote fact. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 3.29 adds the documented H-share Stock Connect constituent quote endpoint
[`stock_hk_ggt_components_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=hk_ggt_components`. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
issues a no-argument paginated request for the `b:DLMK0146,b:DLMK0144` universe
through `https://33.push2.eastmoney.com/api/qt/clist/get` and returns the exact
12 fields `序号`, `代码`, `名称`, `最新价`, `涨跌额`, `涨跌幅`, `今开`, `最高`, `最低`,
`昨收`, `成交量` and `成交额`. The provider freezes the official `pz=100`
pagination and query parameters, validates the complete five-digit H-share
universe, then filters to the requested listing while retaining HKD/share,
percent, share-count and HKD-turnover units and full/selected row counts in
replay metadata.

The official quote is a 15-minute-delayed current-day snapshot without a stable
observation timestamp, so the normalizer emits
`AKSHARE_HK_GGT_COMPONENTS_QUOTE_RAW_ONLY`, marks `current_price` critically
missing and creates no canonical quote fact. No calculation, gate, pipeline,
CLI or input-loader contract changes.

Phase 3.30 adds the documented Eastmoney HSGT minute-fund-flow endpoint
[`stock_hsgt_fund_min_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `CAPITAL_FLOW` with explicit `view=hsgt_fund_min` and a required
`symbol` of `北向资金` or `南向资金`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_min_em.py)
calls the `kamtbs.rtmin/get` JSON endpoint and returns the exact five-field
northbound (`日期`, `时间`, `沪股通`, `深股通`, `北向资金`) or southbound
(`日期`, `时间`, `港股通(沪)`, `港股通(深)`, `南向资金`) minute-flow shape.
The provider preserves the documented `万元` units, direction, one-market-day
row order and fixed upstream parameters. The official documentation states
that the source stopped providing data from 2024-05-13; the normalizer therefore
emits `AKSHARE_HSGT_FUND_MIN_RAW_ONLY` and creates no issuer cash-flow,
liquidity, return or valuation fact. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 3.31 adds the documented Eastmoney HSGT board-rank endpoint
[`stock_hsgt_board_rank_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_ACTIVITY` with explicit `view=hsgt_board_rank`, one of the three
documented board selectors (`北向资金增持行业板块排行`, `北向资金增持概念板块排行`
or `北向资金增持地域板块排行`) and one of the seven documented periods
(`今日`, `3日`, `5日`, `10日`, `1月`, `1季` or `1年`). The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
derives the current report date from the wrapper page and calls the Eastmoney
JSON report `RPT_MUTUAL_BOARD_HOLDRANK_WEB` with the exact board-type and
interval filters. The provider validates the complete 17-field source order,
strict ascending rank, unique board names, constant report date, numeric/null
fields and text-valued largest-increase/decrease fields, while preserving the
market-wide northbound board ranking and upstream filter in replay metadata.
The normalizer emits `AKSHARE_HSGT_BOARD_RANK_RAW_ONLY`: this aggregate does
not establish issuer cash flow, shareholder return, governance, valuation or a
canonical market fact. No calculation, gate, pipeline, CLI or input-loader
contract changes.

Phase 3.32 adds the documented Eastmoney HSGT individual-ranking endpoint
[`stock_hsgt_hold_stock_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `SHAREHOLDER_HOLDINGS` with explicit `view=hsgt_hold_stock`, a required
`market` of `北向`, `沪股通` or `深股通`, and a required `indicator` of `今日排行`,
`3日排行`, `5日排行`, `10日排行`, `月排行`, `季排行` or `年排行`. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
derives the report date from the list page and calls the Eastmoney JSON report
`RPT_MUTUAL_STOCK_NORTHSTA`, using `MUTUAL_TYPE=001`/`003` for the two
directional markets and indicator codes `1`/`3`/`5`/`10`/`M`/`Q`/`Y`. The
provider validates the complete 16-field dynamic source order, six-digit code,
rank sequence, unique listing identity, constant date and finite numeric/null
values before filtering the full A-share universe to the requested listing.
The normalizer emits `AKSHARE_HSGT_HOLD_STOCK_RAW_ONLY`; investor-position
rankings and provider-estimated changes do not establish beneficial control,
issuer cash flow or a canonical diluted-share series. No calculation, gate,
pipeline, CLI or input-loader contract changes.

Phase 3.33 adds the documented Eastmoney HSGT daily stock-statistics endpoint
[`stock_hsgt_stock_statistics_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `SHAREHOLDER_HOLDINGS` with explicit `view=hsgt_stock_statistics`, a
required `symbol` of `北向持股`, `沪股通持股`, `深股通持股` or `南向持股`, and
inclusive `start_date`/`end_date` values in `YYYYMMDD` form. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
uses the `RPT_MUTUAL_STOCK_NORTHSTA` report for northbound symbols and
`RPT_MUTUAL_STOCK_HOLDRANKS` for southbound holdings, with
`INTERVAL_TYPE=1`, the documented mutual-type or `RN=1` scope, descending
`TRADE_DATE` order, page size `1000` and all-page pagination. The provider
validates the exact 11-field date/code/name/price/holding-value/change schema,
fixed-width A/H codes, date range, source order and finite numeric/null values
before filtering the full universe to the requested listing. CNY/share and
HKD/share prices, ten-thousand-share quantities, ten-thousand-currency market
values, percentages and currency-denominated market-value changes remain
explicitly scoped in replay metadata.

The normalizer emits `AKSHARE_HSGT_STOCK_STATISTICS_RAW_ONLY`; investor
holding quantities, market values, ratios and changes do not establish
beneficial control, issuer cash flow or a canonical diluted-share series. No
calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.34 adds the documented Eastmoney HSGT institution-statistics endpoint
[`stock_hsgt_institution_statistics_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `SHAREHOLDER_HOLDINGS` with explicit `view=hsgt_institution_statistics`,
required `market` of `北向持股`, `沪股通持股`, `深股通持股` or `南向持股`, and
inclusive `start_date`/`end_date` values in `YYYYMMDD` form. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
calls `PRT_MUTUAL_ORG_STA` with `HOLD_DATE` descending, page size `500` and
market-type filters `N`, `001`, `003` or `S`, returning the exact seven fields
for date, institution, count, value and 1/5/10-day changes. The provider
preserves the official 19-column raw mapping, validates the complete
market-wide response before storage, and keeps A/H listing identity as request
context only because the rows have no listing code. The normalizer emits
`AKSHARE_HSGT_INSTITUTION_STATISTICS_RAW_ONLY`; institution counts, market
values and changes do not establish ownership, concentration, issuer cash flow
or a canonical diluted-share series. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 3.35 adds the documented Eastmoney HSGT Shanghai-to-Hong Kong real-time
quote endpoint
[`stock_hsgt_sh_hk_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=hk_sh_spot` and H-share listing
context. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hsgt_em.py)
uses the no-argument `b:DLMK0144` quote universe and returns the exact 12
fields for sequence, code, name, price, change, open/high/low/previous close,
volume and turnover. The provider freezes the Eastmoney JSON field mapping and
unit transforms, validates the complete five-digit-code universe in ascending
code order before filtering to the requested H-share listing, and records the
full and selected identity order in replay metadata. The snapshot is a
current-trading-day delayed quote with no stable observation timestamp, so the
normalizer emits `AKSHARE_HK_SH_SPOT_QUOTE_RAW_ONLY` and does not establish
`current_price`. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 3.36 adds the documented Eastmoney HSGT historical-flow endpoint
[`stock_hsgt_hist_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `CAPITAL_FLOW` with explicit `view=hsgt_hist` and the six documented
symbols `北向资金`, `沪股通`, `深股通`, `南向资金`, `港股通沪` and `港股通深`.
The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
calls the paginated `RPT_MUTUAL_DEAL_HISTORY` JSON report with exact
`MUTUAL_TYPE` filters, then returns the symbol-specific 13-field date, flow,
holding-value, leading-stock and index context. The provider freezes the
official report, descending upstream order, page size `1000`, all-page
pagination, symbol-to-market mapping, field order and documented unit/transform
metadata, validating the complete ascending-date response before storage.
Because this is market-wide northbound/southbound history rather than
listing-scoped issuer data, the normalizer emits
`AKSHARE_HSGT_HIST_RAW_ONLY` and creates no issuer cash-flow, liquidity, return
or valuation fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 3.37 adds the documented A-share Eastmoney HSGT individual-detail
endpoint
[`stock_hsgt_individual_detail_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `SHAREHOLDER_HOLDINGS` with explicit `view=hsgt_individual_detail` and
inclusive `start_date`/`end_date` bounds. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
uses the requested six-digit symbol, tries `MARKET_CODE=003` and falls back to
`MARKET_CODE=001`, then returns exact institution-level holding-detail fields.
The provider validates the descending date-grouped response, preserves the
upstream filters, 17-column source mapping and CNY/share, CNY, shares and
percentage units, and records the requested listing/date scope for replay.
The normalizer emits `AKSHARE_HSGT_INDIVIDUAL_DETAIL_RAW_ONLY`; institution
holdings do not establish beneficial control, governance severity or a
company-level diluted-share series. No calculation, gate, pipeline, CLI or
input-loader contract changes.

Phase 3.38 adds the documented Eastmoney HSGT market-wide fund-flow-summary
endpoint
[`stock_hsgt_fund_flow_summary_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `CAPITAL_FLOW` with explicit `view=hsgt_fund_flow_summary` and A/H
listing context. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hsgt_em.py)
calls the `RPT_MUTUAL_QUOTA` JSON report with fixed 2000-row single-page
parameters, sorts by `MUTUAL_TYPE`, and returns the exact 13-field trading-day,
direction, status, amount, count and index-context summary. The provider
preserves the official 17-column wrapper mapping, documented 亿元/percent/count
units and complete market-wide response metadata; no listing filtering is
performed. The normalizer emits `AKSHARE_HSGT_FUND_FLOW_SUMMARY_RAW_ONLY` and
creates no issuer cash-flow, listing-specific liquidity, return or valuation
fact. No calculation, gate, pipeline, CLI or input-loader contract changes.

Phase 3.39 adds the documented Eastmoney Shanghai A-share real-time quote
endpoint [`stock_sh_a_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=sh_a_spot` and a Shanghai A-share
listing context. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
calls the `push2.eastmoney.com/api/qt/clist/get` JSON endpoint with the fixed
Shanghai filters `m:1 t:2,m:1 t:23`, provider-driven pagination, `f3` descending
sort and the exact 23-field wrapper output. The provider preserves the official
field order, wrapper source mapping, documented price/volume/turnover/percentage
units and complete-universe response metadata before selecting the requested
code. The normalizer emits `AKSHARE_SH_A_SPOT_QUOTE_RAW_ONLY`: the current-day
snapshot has no stable observation timestamp and therefore creates no canonical
current-price fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 3.40 adds the documented Eastmoney Shenzhen A-share real-time quote
endpoint [`stock_sz_a_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=sz_a_spot` and a Shenzhen A-share
listing context. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
calls the `push2.eastmoney.com/api/qt/clist/get` JSON endpoint with the fixed
Shenzhen filters `m:0 t:6,m:0 t:80`, provider-driven pagination, `f3` descending
sort and the exact 23-field wrapper output. The provider preserves the official
field order, wrapper source mapping, documented price/volume/turnover/percentage
units and complete-universe response metadata before selecting the requested
code. The normalizer emits `AKSHARE_SZ_A_SPOT_QUOTE_RAW_ONLY`: the current-day
snapshot has no stable observation timestamp and therefore creates no canonical
current-price fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Phase 3.41 adds the documented Eastmoney Beijing A-share real-time quote
endpoint [`stock_bj_a_spot_em`](https://akshare.akfamily.xyz/data/stock/stock.html)
under `MARKET_QUOTE` with explicit `view=bj_a_spot` and a Beijing A-share
listing context. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
calls the `push2.eastmoney.com/api/qt/clist/get` JSON endpoint with the fixed
Beijing filter `m:0 t:81 s:2048`, provider-driven pagination, `f3` descending
sort and the exact 23-field wrapper output. The provider preserves the official
field order, wrapper source mapping, documented price/volume/turnover/percentage
units and complete-universe response metadata before selecting the requested
code. The normalizer emits `AKSHARE_BJ_A_SPOT_QUOTE_RAW_ONLY`: the current-day
snapshot has no stable observation timestamp and therefore creates no canonical
current-price fact. No calculation, gate, pipeline, CLI or input-loader contract
changes.

Filing retrieval and LLM-assisted evidence analysis remain unimplemented. The
deterministic `tve analyze` command is still offline-only and does not call a
provider or an LLM.

Install the live-provider extra only when an explicitly network-enabled
workflow is intended:

```text
python -m pip install ".[akshare]"
```

Phase 2 now includes a provider-neutral raw-record/cache foundation, a
normalized-field capability matrix and the focused AKShare adapter. All
provider output must feed the existing normalized input contract rather than
introduce a second analysis model.

Implementation-oriented assets will later live under:

- `rules/` — deterministic thresholds and parameter sets
- `schemas/` — machine-readable JSON Schemas
- `agents/` — LLM roles, prompts and evidence contracts
- `src/` — calculation and orchestration code
- `tests/` — formula, rule and regression tests

The adapter entry points are under `src/turtle_value_engine/providers/akshare.py`.
Ordinary tests use injected clients and frozen JSON fixtures; live integration
is opt-in with `TVE_RUN_AKSHARE_LIVE=1` and must not be used as a substitute
for cached replay.

## Design principles

- **Hard gates before scores**: a critical failure cannot be rescued by a weighted average.
- **Deterministic math**: financial calculations and thresholds belong in code, not LLM reasoning.
- **LLMs only where judgment is unavoidable**: annual-report reading, business-model analysis, anomaly classification and evidence synthesis.
- **Evidence before conclusion**: every material qualitative judgment must carry supporting evidence, counter-evidence and confidence.
- **Conservative normalization**: prefer normalized multi-year cash generation to a single unusually strong year.
- **Economic substance over accounting labels**: cash, debt, buybacks and capital allocation are classified by economic meaning, not merely by line-item name.

## Status

Early implementation stage. The framework is intentionally conservative and
should be treated as a research and decision-support system rather than
investment advice.
