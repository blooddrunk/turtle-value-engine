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
