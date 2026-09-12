# Structured Provider Field Matrix

> Status: Phase 2 normalization guardrail

This matrix classifies normalized fields used by the current strict-v1 input
and gate pipeline. It is an allowlist for what a structured-data adapter may
automatically normalize. It does not change the frozen JSON Schema or imply
that every provider has the required coverage.

## Status meanings

| Status | Meaning for a Phase 2 adapter |
| --- | --- |
| `STRUCTURED_AUTO` | The provider may emit the field when it reports the same economic value, entity, period and unit unambiguously. |
| `DERIVED_DETERMINISTIC` | A normalizer or engine-owned projection may derive it from accepted canonical facts using a versioned deterministic rule. A provider must not provide a conflicting calculated value as authoritative. |
| `REQUIRES_PRIMARY_FILING` | A structured value may be a discovery hint, but the strict normalized fact requires an annual/interim report, exchange filing, formal announcement or equivalent primary disclosure. |
| `REQUIRES_JUDGMENT` | The field requires economic interpretation or an analyst judgment. It is not an automatic provider fact. |
| `UNAVAILABLE` | The value is intentionally not produced by the Phase 2 adapter boundary; it remains null or output-only until a later layer exists. |

`STRUCTURED_AUTO` means “reported and unambiguous,” not “authoritative for
every investment conclusion.” Primary-filing verification can still be
required by a later policy. A field marked `REQUIRES_PRIMARY_FILING` or
`REQUIRES_JUDGMENT` must not be fabricated from a similarly named aggregate.

## Phase 2.2 market and metadata extension facts

The current normalized schema intentionally permits future scalar fact names.
The first AKShare adapter uses the following provider-neutral extension facts
for observations that are not yet consumed by strict-v1 calculations:

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `company_name`, `company_english_name`, `company_registration_region` | `STRUCTURED_AUTO` | Preserve the explicit metadata value as evidence; required `Company` identity remains caller-supplied. |
| `company_incorporation_date`, `company_industry`, `fiscal_year_end` | `STRUCTURED_AUTO` | Enrich nullable company context only; do not infer a missing sector or reporting currency. |
| `listing_code`, `listing_name`, `listing_date`, `listing_exchange`, `listing_board` | `STRUCTURED_AUTO` | Retain the listing's explicit code and metadata; do not infer listing age from history rows. |
| `listing_security_type`, `listing_isin`, `listing_hk_connect` | `STRUCTURED_AUTO` | Preserve explicit security metadata; connect status is not a governance or eligibility conclusion. |
| `market_quote_timestamp` | `STRUCTURED_AUTO` | Retain the provider's observation timestamp separately from the analysis `as_of` date. |
| `historical_open`, `historical_high`, `historical_low`, `historical_close` | `STRUCTURED_AUTO` | Dated price observations retain the listing currency and are not financial statement facts. |
| `historical_volume`, `historical_turnover`, `historical_change_percent` | `STRUCTURED_AUTO` | Preserve the upstream unit convention in `Fact.unit`; no liquidity or return metric is calculated here. |

Only `current_price` from a quote for the selected primary listing is a
strict-v1 input candidate. The extension facts above are evidence-backed
observations for later market-data consumers, not engine outputs. The adapter
does not map AKShare's headline `总市值`/market-cap fields because market cap
must remain an engine-owned deterministic projection.

## Phase 2.3 cash-flow statement slice

The first financial-statement mapping slice is intentionally narrower than the
full cash-flow contract:

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `reported_cfo` | `STRUCTURED_AUTO` | Map only an explicit operating-cash-flow line for an exact report period and preserve the reported sign/currency. |
| `acquisition_cash` | `STRUCTURED_AUTO` | Map only an explicit cash-paid-for-acquisition line; do not infer acquisitions from total investing cash flow. |
| `ppe_purchase_cash`, `intangible_purchase_cash` | `STRUCTURED_AUTO` | Not mapped when the provider combines PPE, intangible and other long-term assets in one line. |
| `equity_financing`, `debt_financing`, `other_financing` | `STRUCTURED_AUTO` | Deferred until a provider line has the same canonical category semantics; gross borrowings or repayments are not silently renamed. |
| `core_cdc` and all CDC/interest classifications | `DERIVED_DETERMINISTIC` / `REQUIRES_PRIMARY_FILING` | Not emitted by the provider normalizer. |

The current AKShare slice supports A-share wide statement rows and H-share
long-form statement items. It rejects missing or year-only report periods and
ambiguous duplicate periods/items. Explicit nulls stay null and are never
converted to zero.

## Phase 2.4 income-statement slice

The income-statement slice is limited to the two numeric statement facts that
already exist in the normalized contract. It does not turn an income-table
headline or ratio into a provider metric.

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `parent_net_profit` | `STRUCTURED_AUTO` | Map only an explicit parent-attributable net-profit line for an exact report period, entity and currency; preserve sign and nulls. |
| `consolidated_net_profit` | `STRUCTURED_AUTO` | Map only an explicit consolidated/net-profit line for an exact report period, entity and currency; preserve sign and nulls. |
| `revenue`, `operating_profit`, `gross_margin`, `net_margin` | `STRUCTURED_AUTO` / `DERIVED_DETERMINISTIC` | Not mapped in this slice; any future use must define entity, period, unit and derivation semantics separately. |
| income-statement ratios and filing-derived classifications | `DERIVED_DETERMINISTIC` / `REQUIRES_PRIMARY_FILING` | Not emitted by the provider normalizer. |

The A-share income endpoint is expected to provide wide report-period rows and
the H-share endpoint long-form items. Missing or year-only periods and
ambiguous duplicate periods/items are rejected. Explicit nulls remain null and
are not treated as zero. The Phase 2 mapping review owns unresolved field-name
coverage, parent/consolidated entity basis, currency/unit scaling and
point-in-time publication semantics.

## Phase 2.5 balance-sheet statement slice

The balance-sheet slice is limited to directly reported point-in-time totals.
It does not manufacture an interest-bearing-debt total from neighboring
liability or borrowing rows.

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `book_cash` | `STRUCTURED_AUTO` | Map only an explicit reported cash/cash-equivalents line for an exact statement period, entity and currency. |
| `parent_equity` | `STRUCTURED_AUTO` | Map only an explicit equity-attributable-to-parent line for the matching period and entity. |
| `total_equity` | `STRUCTURED_AUTO` | Map only an explicit total owners'/shareholders' equity line for the matching period. |
| `reported_interest_bearing_debt` | `STRUCTURED_AUTO` | Map only an explicit aggregate interest-bearing-debt line; do not sum short-/long-term borrowing sub-items or rename total liabilities. |
| `financial_debt` | `STRUCTURED_AUTO` | Not emitted by this slice; a later mapping must establish whether an upstream debt total has the canonical post-classification scope. |
| `minority_equity` | `STRUCTURED_AUTO` | Deferred from this slice; minority attribution and consolidated/standalone basis require a separate mapping review. |
| `restricted_cash`, `pledged_deposits`, `lease_debt`, `subsidiary_cash`, `subsidiary_debt` | `REQUIRES_PRIMARY_FILING` | Do not infer accessibility, debt-equivalent treatment or upstreamability from aggregate balance-sheet rows. |

The A-share detailed balance endpoint provides wide report-period rows and
the H-share endpoint provides long-form statement items. The current
documented A-share aggregate fallback (`stock_zcfz_em` or
`stock_zcfz_bj_em`) is requested by exact quarter-end date, returns a universe
row set and exposes only cash and total-equity fields from this allowlist; the
normalizer selects the requested listing and uses the requested date as the
statement period. Missing or year-only periods and ambiguous periods/items
are rejected. Explicit nulls remain null and are not treated as zero. The
Phase 2 mapping review owns unresolved balance-sheet field-name coverage,
consolidated-versus-standalone entity basis, currency/unit scaling, the
missing parent-equity/debt aggregates in the documented A-share shape and
point-in-time publication semantics.

For all statement amounts, an explicit valid three-letter currency code is
required before a currency is attached to a fact. The mapper does not use the
listing market as a currency default: omitted currency remains `null`, and
conflicting explicit currencies within one report period are rejected. Unit
scaling and conversion remain outside this slice.

For all three statement slices, an explicit row-level security code must match
the requested listing; a mismatch is a normalization error. If an upstream
statement response has no row-level code, the mapper relies only on the
listing-scoped request and does not infer a code from another row.

## Phase 2.8 share-capital raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes `stock_zh_a_gbjg_em` as an A-share endpoint with a `symbol` input and
all historical records. Its documented output includes `变更日期`, `总股本`,
circulation fields and `变动原因`; `总股本` is typed as `int64`, but the
documentation does not state an explicit unit or a diluted-economic-share
definition. The endpoint's legal share-capital history also does not establish
the treatment of options, convertibles, multiple share classes or the economic
meaning of each change reason.

The provider passes only the requested six-digit A-share code and preserves the
entire response as a `RawProviderRecord`. The normalizer retains the evidence,
sets `normalized_diluted_economic_shares` in the critical-missing inventory and
emits `AKSHARE_SHARE_CAPITAL_RAW_ONLY`; it emits no canonical fact and does not
use `变更日期` as a financial-statement period. H-share share capital and
dividend, buyback, issuance and split classifications remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `变更日期` | Raw-only; effective-date versus observation-period semantics are unresolved. |
| `总股本` | Raw-only; no unit or fully diluted economic scope is admitted. |
| `流通受限股份`, `已流通股份`, `已上市流通A股` | Raw-only; legal circulation categories are not normalized into economic share counts. |
| `变动原因` | Raw-only; text is not classified as buyback, issuance, split or other action. |

## Phase 2.43 A-share individual-info raw share snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_individual_info_em` as an Eastmoney A-share endpoint with a
six-digit `symbol` input and an `item/value` response. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_info_em.py)
maps the published snapshot to `最新`, `股票代码`, `股票简称`, `总股本`, `流通股`,
`总市值`, `流通市值`, `行业` and `上市时间`.

The provider selects this endpoint only for the explicit `SHARE_CAPITAL` view
`individual_info`, validates the returned code against the requested A-share
listing and validates `上市时间` when it is populated. It retains every
`item/value` row and its listing/view/snapshot provenance. The snapshot is not
silently treated as a reporting-period fact: its share-count unit, current
observation basis and fully diluted economic scope are not settled by this
endpoint. The normalizer emits `AKSHARE_INDIVIDUAL_INFO_RAW_ONLY`, marks
`normalized_diluted_economic_shares` as critically missing and creates no
canonical share, market-cap or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码`, `股票简称` | Listing identity/context; the code is required to match the requested A-share listing. |
| `总股本`, `流通股` | Raw share-count context; no unit, class, point-in-time or fully diluted economic scope is admitted. |
| `总市值`, `流通市值`, `最新` | Raw current-snapshot market context; no provider market cap, price or valuation metric replaces the deterministic engine. |
| `行业` | Raw provider classification; it does not overwrite the caller's sector or establish a special model. |
| `上市时间` | Validated raw listing-date context; it is not used as a statement period or automatic diluted-share fact. |

## Phase 2.44 A-share individual-fund-flow raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_individual_fund_flow` as an Eastmoney A-share endpoint with
`stock` and `market` inputs. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_fund_em.py)
accepts the six-digit stock code and `sh`, `sz` or `bj` market selector, and
returns recent daily rows (approximately 100 trading days) with the fields
listed below.

The provider derives the documented market selector from the explicit A-share
listing identity, passes the six-digit code and market, validates the optional
row code when present, rejects missing/invalid/duplicate observation dates and
records the observed date range and request-bound listing provenance. The
normalizer retains the response as evidence under
`AKSHARE_INDIVIDUAL_FUND_FLOW_RAW_ONLY`; no normalized field or canonical fact
is admitted by this slice. These values describe daily investor-flow aggregates
and market-price context, not issuer cash flow, an accounting period, a
canonical liquidity metric or a valuation input.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `日期` | Validated observation date for a recent trading-day row; it is not an accounting or statement period. |
| `收盘价`, `涨跌幅` | Raw market context only; these values do not replace the quote or market-history contracts. |
| `主力净流入-净额`, `超大单净流入-净额`, `大单净流入-净额`, `中单净流入-净额`, `小单净流入-净额` | Raw investor-flow amounts only; they are not issuer CFO, financing cash flow, shareholder return or liquidity facts. |
| `主力净流入-净占比`, `超大单净流入-净占比`, `大单净流入-净占比`, `中单净流入-净占比`, `小单净流入-净占比` | Raw provider percentages only; denominator and investor-flow scope are not normalized into a canonical metric or valuation input. |
| request `stock`, derived `market` | Explicit A-share endpoint selection and replayable listing provenance; no provider-specific identity leaks into the calculation layer. |

## Phase 2.45 A-share top-ten-shareholder raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gdfx_top_10_em` as an Eastmoney endpoint with a
market-prefixed A-share `symbol` and an exact quarter-end `date`. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
publishes rank, holder, share type, holding quantity, total-share ratio and
change fields for the requested report period.

The provider selects this endpoint only for the explicit
`SHAREHOLDER_HOLDINGS` request `view=top_10`, validates the quarter-end date,
rank and holder identity, and retains the symbol-scoped response without
inventing a row-level listing code or filing date. The normalizer emits
`AKSHARE_TOP_10_SHAREHOLDERS_RAW_ONLY`; no canonical ownership, concentration,
share, dilution, governance or valuation fact is admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `名次` | Raw report-period ordering; no deterministic beneficial-owner or concentration ranking is inferred. |
| `股东名称` | Raw holder identity; no beneficial control or legal ownership fact is admitted. |
| `股份类型` | Raw provider share-class label; no A/H equivalence or dilution treatment is inferred. |
| `持股数` | Raw holding quantity; unit and fully diluted economic-share scope remain unresolved. |
| `占总股本持股比例` | Raw provider ratio; it is not normalized into a canonical concentration metric. |
| `增减`, `变动比率` | Raw change context; it is not classified as issuance, buyback, transfer or dilution. |
| request `symbol`, `view=top_10`, exact quarter-end `date` | Explicit endpoint and replay scope; the report-period date is not treated as filing availability or an accounting fact. |

## Phase 2.46 A-share top-ten-tradable-shareholder raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gdfx_free_top_10_em` as an Eastmoney endpoint with a
market-prefixed A-share `symbol` and an exact quarter-end `date`. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
publishes rank, holder, holder type, share type, holding quantity, float-share
ratio and change fields for the requested report period.

The provider selects this endpoint only for the explicit
`SHAREHOLDER_HOLDINGS` request `view=free_top_10`, validates the quarter-end
date, rank and holder identity, and retains the symbol-scoped response without
inventing a row-level listing code or filing date. The normalizer emits
`AKSHARE_FREE_TOP_10_SHAREHOLDERS_RAW_ONLY`; no canonical ownership,
concentration, share, dilution, governance or valuation fact is admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `名次` | Raw report-period ordering; no deterministic beneficial-owner or concentration ranking is inferred. |
| `股东名称`, `股东性质` | Raw holder identity/type; no beneficial control or legal ownership fact is admitted. |
| `股份类型` | Raw provider share-class label; no A/H equivalence or dilution treatment is inferred. |
| `持股数` | Raw tradable-holding quantity; unit and fully diluted economic-share scope remain unresolved. |
| `占总流通股本持股比例` | Raw provider float-share ratio; it is not normalized into a canonical concentration metric. |
| `增减`, `变动比率` | Raw change context; it is not classified as issuance, buyback, transfer or dilution. |
| request `symbol`, `view=free_top_10`, exact quarter-end `date` | Explicit endpoint and replay scope; the report-period date is not treated as filing availability or an accounting fact. |

## Phase 2.47 A-share top-ten-tradable-shareholder detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gdfx_free_holding_detail_em` as an Eastmoney full-universe
endpoint accepting an exact quarter-end `date`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)
returns listing code/name, holder identity/type, report period, holding
quantity and change, float-market value and announcement date fields for all
matching report-period rows.

The provider selects this endpoint only for the explicit
`SHAREHOLDER_HOLDINGS` request `view=free_holding_detail`, passes only the
documented `date`, validates every listing code, holder and exact report
period plus any announcement date, and filters the full universe to the
requested A-share listing. The normalizer emits
`AKSHARE_FREE_HOLDING_DETAIL_RAW_ONLY`; no canonical ownership, concentration,
share, dilution, governance or valuation fact is admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码`, `股票简称` | Validated listing identity/name used to select the requested listing; no cross-listing or issuer-level ownership fact is inferred. |
| `股东名称`, `股东类型` | Raw holder identity/type; no beneficial control or legal ownership fact is admitted. |
| `报告期` | Exact report-period binding for the requested quarter; it is not treated as filing availability. |
| `期末持股-数量`, `期末持股-数量变化`, `期末持股-数量变化比例` | Raw tradable-holding quantity/change fields; unit and fully diluted economic-share scope remain unresolved. |
| `期末持股-持股变动` | Raw provider change label; it is not classified as issuance, buyback, transfer or dilution. |
| `期末持股-流通市值` | Raw provider float-market value; it is not normalized into a valuation or concentration metric. |
| `公告日` | Validated announcement-date context; it is not treated as a filing's contents or an accounting period. |
| request `view=free_holding_detail`, exact quarter-end `date` | Explicit endpoint and replay scope; the full-universe response is filtered by listing before storage. |

## Phase 2.48 A-share Dragon-Tiger market-activity raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_lhb_detail_em` as an Eastmoney full-universe endpoint with
explicit inclusive `start_date` and `end_date` parameters in `YYYYMMDD` form.
The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
returns listing-day activity, provider amount/ratio fields, listing reasons and
post-listing return columns.

The provider selects this endpoint only for the provider-neutral
`MARKET_ACTIVITY` category and an A-share listing, validates every returned
listing code and `上榜日` against the requested date range, then filters the
full universe to the requested listing. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_RAW_ONLY`; no canonical market, issuer cash-flow,
shareholder-return, governance or valuation fact is admitted. Post-listing
returns remain forward-looking raw context and are never used as as-of facts.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称` | Validated listing identity/name used to select the requested listing; no additional issuer fact is inferred. |
| `上榜日` | Validated listing-day event date inside the inclusive request range; it is not an accounting or fund-flow period. |
| `解读`, `上榜原因` | Raw provider activity labels; no governance, causality or investment conclusion is inferred. |
| `收盘价`, `涨跌幅`, `换手率`, `流通市值` | Raw market context; it is not promoted to canonical quote, history or valuation input. |
| `龙虎榜净买额`, `龙虎榜买入额`, `龙虎榜卖出额`, `龙虎榜成交额`, `市场总成交额`, percentage fields | Raw provider market-activity amounts/ratios; they are not issuer cash flow, shareholder return or a canonical liquidity metric. |
| `上榜后1日`, `上榜后2日`, `上榜后5日`, `上榜后10日` | Forward-looking post-listing context; never normalized into as-of facts or used by calculations/gates. |
| request `start_date`, `end_date` | Explicit inclusive date-range and replay scope; the full-universe response is filtered by listing before storage. |

## Phase 2.49 A-share Dragon-Tiger stock-statistic raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_lhb_stock_statistic_em` as an Eastmoney full-universe endpoint
with an explicit `symbol` window choice: `近一月`, `近三月`, `近六月` or `近一年`.
The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
maps those choices to the upstream statistic-cycle filter and returns one
aggregate row per listing.

The provider selects this endpoint only for the provider-neutral
`MARKET_ACTIVITY` request with `view=stock_statistic`, maps the explicit
`period` to the upstream `symbol`, validates every returned listing code and
`最近上榜日`, then filters the full universe to the requested A-share listing.
The normalizer emits `AKSHARE_MARKET_ACTIVITY_STATISTICS_RAW_ONLY`; no issuer
cash-flow, shareholder-return, governance, canonical market or valuation fact
is admitted. The selected window is replay scope, while trailing returns remain
provider context rather than as-of facts.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称` | Validated listing identity/name used to select the requested listing; no additional issuer fact is inferred. |
| `最近上榜日` | Validated recent Dragon-Tiger listing-day context; it is not an accounting, fund-flow or filing period. |
| `收盘价`, `涨跌幅` | Raw market context; it is not promoted to canonical quote, history or valuation input. |
| `上榜次数` | Raw activity count for the selected provider window; it is not a shareholder or governance conclusion. |
| `龙虎榜净买额`, `龙虎榜买入额`, `龙虎榜卖出额`, `龙虎榜总成交额` | Raw Dragon-Tiger amount aggregates; they are not issuer cash flow, shareholder return or a canonical liquidity metric. |
| `买方机构次数`, `卖方机构次数`, `机构买入净额`, `机构买入总额`, `机构卖出总额` | Raw institution-activity aggregates; institution labels and amounts do not establish beneficial ownership, governance or issuer-level flows. |
| `近1个月涨跌幅`, `近3个月涨跌幅`, `近6个月涨跌幅`, `近1年涨跌幅` | Trailing provider return context; it is not used as an as-of return, valuation input or calculation/gate fact. |
| request `view=stock_statistic`, `period` | Explicit endpoint-selection and statistic-window replay scope; the full-universe response is filtered by listing before storage. |

## Phase 2.50 A-share Dragon-Tiger institution-statistic raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_lhb_jgstatistic_em` as an Eastmoney full-universe endpoint
with an explicit `symbol` window choice: `近一月`, `近三月`, `近六月` or `近一年`.
The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
maps those choices to the upstream statistic-cycle filter and returns one
institution-seat tracking row per listing.

The provider selects this endpoint only for the provider-neutral
`MARKET_ACTIVITY` request with `view=institution_statistic`, maps the explicit
`period` to the upstream `symbol`, validates every returned listing code and
filters the full universe to the requested A-share listing. The normalizer
emits `AKSHARE_MARKET_ACTIVITY_INSTITUTION_STATISTICS_RAW_ONLY`; no issuer
cash-flow, shareholder-return, governance, canonical market or valuation fact
is admitted. The selected window and trailing returns remain provider context,
not as-of calculation inputs.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称` | Validated listing identity/name used to select the requested listing; no additional issuer fact is inferred. |
| `收盘价`, `涨跌幅` | Raw market context; it is not promoted to canonical quote, history or valuation input. |
| `龙虎榜成交金额`, `上榜次数` | Raw Dragon-Tiger institution-activity amount/count for the selected provider window; they are not issuer cash flow or a governance conclusion. |
| `机构买入额`, `机构买入次数`, `机构卖出额`, `机构卖出次数`, `机构净买额` | Raw institution-seat amount/count fields; they do not establish beneficial ownership, shareholder return or issuer-level flow. |
| `近1个月涨跌幅`, `近3个月涨跌幅`, `近6个月涨跌幅`, `近1年涨跌幅` | Trailing provider return context; it is not used as an as-of return, valuation input or calculation/gate fact. |
| request `view=institution_statistic`, `period` | Explicit endpoint-selection and institution-statistic-window replay scope; the full-universe response is filtered by listing before storage. |

## Phase 2.51 A-share five-level bid-ask raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_bid_ask_em` as an Eastmoney A-share endpoint with one
six-digit `symbol` input. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ask_bid_em.py)
returns a fixed `item`/`value` table with five ask levels, five bid levels and
intraday quote-context values.

The provider selects this endpoint only under the provider-neutral
`MARKET_QUOTE` category with explicit `view=bid_ask` for Shanghai and Shenzhen
A-share listings, passes the normalized six-digit code and validates exactly
the documented 36 item names. It records the listing, view, symbol and current
snapshot scope for replay. The normalizer emits
`AKSHARE_BID_ASK_RAW_ONLY`; because the endpoint does not provide a stable
observation timestamp, no canonical current-price, liquidity or valuation fact
is admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `sell_5`, `sell_4`, `sell_3`, `sell_2`, `sell_1` and matching `_vol` items | Validated five-level ask prices and volumes; retained as raw order-book evidence only. |
| `buy_1`, `buy_2`, `buy_3`, `buy_4`, `buy_5` and matching `_vol` items | Validated five-level bid prices and volumes; retained as raw order-book evidence only. |
| `最新`, `均价`, `涨幅`, `涨跌`, `总手`, `金额`, `换手`, `量比`, `最高`, `最低`, `今开`, `昨收`, `涨停`, `跌停`, `外盘`, `内盘` | Validated intraday quote context; values are not promoted to canonical current price, history, liquidity or valuation inputs. |
| request `view=bid_ask`, derived `symbol` | Explicit endpoint-selection and listing/snapshot replay scope; only Shanghai/Shenzhen A-share listings are accepted. |

## Phase 2.52 A-share intraday-history raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_hist_min_em` as an Eastmoney A-share intraday-history
endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
accepts a six-digit `symbol`, `start_date` and `end_date` datetimes, an
interval in `1`, `5`, `15`, `30` or `60` minutes and an adjustment choice of
empty string, `qfq` or `hfq`. The one-minute response exposes `均价`; other
intervals expose `涨跌幅`, `涨跌额`, `振幅` and `换手率` instead.

The provider selects this endpoint only under `MARKET_HISTORY` with explicit
`view=intraday`, validates the period-specific field set, finite numeric or
null values, strictly ascending `时间` values and the requested datetime
range, and records the effective symbol/range/interval/adjustment and
observation bounds. The normalizer emits
`AKSHARE_INTRADAY_HISTORY_RAW_ONLY`, marks `market_history` as critically
missing when no canonical daily history is present, and creates no facts:
minute-bar interval, adjustment mode and recent-data limits do not establish
the canonical daily history or a valuation input.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `时间` | Validated intraday observation timestamp inside the requested range; it is not silently converted into a daily history period. |
| `开盘`, `收盘`, `最高`, `最低` | Raw minute-bar prices retained as structured evidence only; they do not replace canonical daily OHLC history. |
| `成交量` | Raw provider volume, documented in lots; no cross-frequency liquidity or valuation fact is inferred. |
| `成交额` | Raw intraday turnover amount; it is not issuer cash flow or a canonical valuation input. |
| `均价` for `period=1`; `涨跌幅`, `涨跌额`, `振幅`, `换手率` for other periods | Validated interval-specific quote context; provider calculations and intraday scope remain raw-only. |
| request `view=intraday`, derived `symbol`, `start_date`, `end_date`, `period`, `adjust` | Explicit endpoint-selection and intraday replay scope; the response is listing-scoped and cannot be replayed under a different range, interval or adjustment mode. |

## Phase 2.53 A-share pre-market-history raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_hist_pre_min_em` as an Eastmoney A-share endpoint.
The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
accepts a six-digit `symbol`, `start_time` and `end_time` time-of-day bounds,
and returns the most recent trading day's minute rows including pre-market
observations. Its output contains `时间`, OHLC, `成交量`, `成交额` and `最新价`.

The provider selects this endpoint only under `MARKET_HISTORY` with explicit
`view=pre_market`, passes the normalized A-share code and effective time
window, validates the exact field set, finite numeric/null values, one trading
date, strictly ascending timestamps and the requested time range, and records
the listing-scoped response plus its time/date replay scope. The normalizer
emits `AKSHARE_PRE_MARKET_HISTORY_RAW_ONLY`; the latest-day minute snapshot is
not a canonical daily-history or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `时间` | Validated timestamp within the requested time-of-day window and one latest trading date; it is not converted into a daily-history period. |
| `开盘`, `收盘`, `最高`, `最低` | Raw minute prices retained as structured evidence only; they do not replace canonical daily OHLC history. |
| `成交量` | Raw provider volume, documented in lots; no cross-frequency liquidity or valuation fact is inferred. |
| `成交额` | Raw intraday turnover amount; it is not issuer cash flow or a canonical valuation input. |
| `最新价` | Raw latest-price context within the snapshot; without an independent stable quote timestamp it does not replace `current_price`. |
| request `view=pre_market`, derived `symbol`, `start_time`, `end_time` | Explicit endpoint-selection and latest-trading-day time-window replay scope; the response cannot be replayed under a different listing or time range. |

## Phase 2.54 A-share Sina minute-history raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_minute` as a Sina A-share stock/index minute-history
endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py)
accepts a market-prefixed `symbol`, a `period` of `1`, `5`, `15`, `30` or `60`,
and an adjustment mode of empty string, `qfq` or `hfq`. It returns a recent
timestamped minute-bar response with `day`, OHLC, `volume` and `amount`.

The provider selects this endpoint only under `MARKET_HISTORY` with explicit
`view=sina_minute`, derives the market-prefixed symbol from the requested
A-share listing, validates the exact field set, finite numeric/null values and
strictly ascending timestamps, and records the effective listing, interval,
adjustment and recent-window replay scope. The normalizer emits
`AKSHARE_SINA_MINUTE_HISTORY_RAW_ONLY`; the provider-window minute bars are not
a canonical daily-history or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `day` | Validated minute timestamp in ascending order; it is retained as raw observation context and is not converted into a daily-history period. |
| `open`, `high`, `low`, `close` | Raw minute prices retained as structured evidence only; they do not replace canonical daily OHLC history. |
| `volume` | Raw provider minute volume; unit and recent-window scope remain provider context, with no cross-frequency liquidity fact inferred. |
| `amount` | Raw minute turnover amount; it is not issuer cash flow or a canonical valuation input. |
| request `view=sina_minute`, derived market-prefixed `symbol`, `period`, `adjust` | Explicit endpoint-selection and recent-window replay scope; the response cannot be replayed under a different listing, interval or adjustment mode. |

## Phase 2.55 A-share Tencent daily-history slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_hist_tx` as Tencent Securities daily historical data for
A-share stocks. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_tx.py)
accepts a market-prefixed or six-digit `symbol`, `start_date` defaulting to
`19000101`, `end_date` defaulting to `20500101`, and an adjustment mode of empty
string, `qfq` or `hfq`. The response contains `date`, OHLC, `volume` in shares,
decimal `turnover` and `amount` in yuan.

The provider selects this endpoint only under `MARKET_HISTORY` with explicit
`view=tencent_daily`, derives the market-prefixed symbol from the requested
A-share listing, applies the documented date defaults, validates the exact
field set, finite numeric/null values, strictly ascending dates and inclusive
requested range, and records the effective symbol/date/adjustment replay scope.
The normalizer applies the existing dated daily-history extension mapping. It
maps OHLC, volume and amount into the already-defined historical facts; volume
uses `shares` and amount uses `CNY`. The provider's decimal `turnover` ratio is
retained in raw evidence but is not mapped to `historical_turnover`, whose
existing contract represents turnover amount.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `date` | Validated ascending observation date inside the requested inclusive range; used as the historical fact period. |
| `open`, `high`, `low`, `close` | Mapped to the existing dated daily-history price facts with `price_per_share` units. |
| `volume` | Mapped to `historical_volume`; the documented and replayed unit is `shares`. |
| `amount` | Mapped to the existing `historical_turnover` amount fact with `CNY` units; it is not issuer cash flow. |
| `turnover` | Validated decimal provider ratio retained in raw evidence; it does not create a new canonical turnover-ratio or valuation fact. |
| request `view=tencent_daily`, derived market-prefixed `symbol`, `start_date`, `end_date`, `adjust` | Explicit endpoint-selection, listing, date-range and adjustment replay scope; rows cannot be replayed under a different request scope. |

## Phase 2.56 A-share Tencent latest-trading-day tick raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents the Tencent historical-tick endpoint as `stock_zh_a_tick_tx`; its
example calls the current source's `stock_zh_a_tick_tx_js` callable. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_tick_tx.py)
accepts a market-prefixed `symbol` and returns the latest available trading
day's time-only trade rows. The documented output labels amount `成交额`, while
the current implementation emits `成交金额`; these are the two known upstream
shapes and are not mixed.

The provider selects this callable only under `MARKET_HISTORY` with explicit
`view=tencent_tick`, derives the market-prefixed symbol from the requested
A-share listing, validates the exact base fields plus one known amount variant,
finite numeric/null values, integer volume/amount values, recognized buy/sell
markers and non-decreasing times, and records the listing, amount-column and
time-only replay scope. The normalizer emits
`AKSHARE_TENCENT_TICK_RAW_ONLY`; no canonical fact is created because the
response has no trading date and does not establish daily-history, liquidity or
valuation semantics.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `成交时间` | Validated `HH:MM:SS` trade time in non-decreasing order; it is not a dated historical period. |
| `成交价格`, `价格变动` | Raw per-share price/change with `CNY_per_share`; they do not replace quote or daily history. |
| `成交量` | Raw trade volume documented in lots/`手`; no cross-frequency liquidity or valuation fact is inferred. |
| `成交金额` or documented `成交额` | Raw trade amount in yuan/`CNY`; the exact spelling is retained and it is not issuer cash flow. |
| `性质` | Validated marker `买盘`, `卖盘` or `中性盘`; no order-flow or governance conclusion is inferred. |
| request `view=tencent_tick`, derived market-prefixed `symbol` | Explicit endpoint-selection, listing and latest-trading-day time-only replay scope; rows cannot be replayed under a different listing or amount shape. |

## Phase 2.57 H-share intraday-history raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hk_hist_min_em` as an Eastmoney H-share minute-history
endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
accepts a six-digit H-share `symbol`, `period` `1`, `5`, `15`, `30` or `60`,
adjustment mode ``, `qfq` or `hfq`, and explicit `start_date`/`end_date`
datetimes. The provider selects it only under `MARKET_HISTORY` with explicit
`view=hk_intraday`, passes the unprefixed H-share code, validates the exact
period-specific field set, finite numeric/null values, strictly ascending
timestamps and inclusive requested range, and records the effective replay
scope and market units.

For period `1`, the documented response fields are `时间`, `开盘`, `收盘`,
`最高`, `最低`, `成交量`, `成交额` and `最新价`. For periods `5`, `15`, `30`
and `60`, the documented fields are `时间`, `开盘`, `收盘`, `最高`, `最低`,
`涨跌幅`, `涨跌额`, `成交量`, `成交额`, `振幅` and `换手率`. The response is
retained as raw evidence only; minute-bar OHLC, volume, amount and provider
ratios do not become canonical daily-history, liquidity or valuation facts.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `时间` | Required timestamp; it must be parseable, strictly ascending and inside the inclusive requested datetime range. |
| `开盘`, `收盘`, `最高`, `最低` | Required raw H-share price fields; the documented market currency is retained as `HKD_per_share`, but no daily-history fact is emitted. |
| `成交量` | Required raw volume in shares; no cross-frequency liquidity metric is inferred. |
| `成交额` | Required raw turnover amount in HKD; it is not issuer cash flow or a canonical daily turnover fact. |
| `最新价` (period `1`) | Required raw latest-price field for the one-minute schema; it does not replace the canonical quote. |
| `涨跌幅`, `涨跌额`, `振幅`, `换手率` (periods other than `1`) | Required raw provider change/ratio context; no return, liquidity or valuation metric is calculated. |
| request `view=hk_intraday`, H-share `symbol`, `start_date`, `end_date`, `period`, `adjust` | Explicit endpoint-selection, listing, datetime-range, interval and adjustment replay scope; rows cannot be replayed under a different H-share request. |

The normalizer emits `AKSHARE_HK_INTRADAY_HISTORY_RAW_ONLY` and leaves
`market_history` critically missing for this raw-only slice. `shares`,
`HKD_per_share`, `HKD`, the period-specific schema and the observed row range
remain replayable provider-boundary metadata; they are not imported into the
calculation, gate, pipeline, CLI or input-loader contract.

## Phase 2.58 A-share chip-distribution raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_cyq_em` as an Eastmoney concept-board chip-distribution
endpoint. It accepts an A-share six-digit `symbol` and an adjustment mode of
empty string, `qfq` or `hfq`, and returns approximately the latest 90 trading
days. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_cyq_em.py)
normalizes the response to the exact nine fields below and keeps the final 90
rows.

The provider selects this endpoint only under the existing `MARKET_HISTORY`
category with explicit `view=chip_distribution`, passes the unprefixed listing
code and adjustment mode, validates the exact field set, ISO dates in strict
ascending order, finite numeric/null values and the maximum 90-row window, and
records the listing, symbol, adjustment, row limit and observed date bounds for
replay. No price, ratio or concentration unit is inferred from the published
field names. The normalizer emits
`AKSHARE_CHIP_DISTRIBUTION_RAW_ONLY`, leaves `market_history` critically
missing and creates no canonical history, liquidity, concentration or valuation
fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `日期` | Required ISO observation date in strict ascending order; retained as raw row context and not silently converted into a canonical daily-history period. |
| `获利比例` | Provider-defined benefit-ratio field retained as raw evidence; no unit, denominator or valuation meaning is inferred. |
| `平均成本` | Provider-defined average-cost field retained as raw evidence; no currency, per-share or valuation meaning is inferred. |
| `90成本-低`, `90成本-高`, `90集中度` | Provider-defined 90-window cost/concentration fields retained as raw evidence; no canonical range or concentration metric is calculated. |
| `70成本-低`, `70成本-高`, `70集中度` | Provider-defined 70-window cost/concentration fields retained as raw evidence; no canonical range or concentration metric is calculated. |
| request `view=chip_distribution`, unprefixed A-share `symbol`, `adjust` | Explicit endpoint-selection, listing, adjustment, latest-90-trading-day window, exact-field and observed-date replay scope; rows cannot be replayed under a different request. |

The provider-specific benefit/cost/concentration response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts. Its raw evidence
is available for later review without being treated as canonical daily history,
liquidity, shareholder concentration or valuation input.

## Phase 2.59 A-share market-participation desire raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_comment_detail_scrd_desire_em` as an Eastmoney symbol-scoped
A-share endpoint with a six-digit `symbol`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py)
requests the participation report with a 30-row page size, maps the response
to exactly the six fields below and sorts by `交易日期`.

The provider selects this endpoint only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=participation_desire`, passes the
unprefixed listing code, validates the exact field set, listing identity,
finite numeric/null values, strictly ascending ISO dates and the maximum
30-row window, and records the listing, symbol and observed-date scope for
replay. The normalizer emits
`AKSHARE_MARKET_PARTICIPATION_DESIRE_RAW_ONLY`; no canonical market,
issuer-cash-flow, shareholder-return, governance, valuation or other fact is
admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `交易日期` | Validated ISO observation date in strict ascending order; raw market-activity context, not an accounting, fund-flow or filing period. |
| `股票代码` | Required to match the requested A-share listing; no additional issuer fact is inferred. |
| `参与意愿`, `5日平均参与意愿` | Provider-defined participation scores; no scale, denominator, canonical sentiment or market metric is inferred. |
| `参与意愿变化`, `5日平均变化` | Provider-defined change fields; no return, flow, governance or valuation meaning is inferred. |
| request `view=participation_desire`, unprefixed six-digit `symbol` | Explicit endpoint/listing and latest-30-trading-day replay scope; observed date bounds are retained as metadata. |

## Phase 2.60 A-share Eastmoney intraday-trade raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_intraday_em` as an Eastmoney A-share endpoint with a six-digit
`symbol`; the latest trading day's response includes pre-market observations
and exactly `时间`, `成交价`, `手数` and `买卖盘性质`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_em.py)
confirms the same symbol-only callable and maps the upstream side codes to the
documented buy/sell/neutral labels.

The provider selects this endpoint only under `MARKET_HISTORY` with explicit
`view=intraday_trades`, passes the unprefixed A-share code, validates the exact
field set, finite numeric/null prices, integer/null lot counts, recognized trade
sides and non-decreasing time-of-day values, and records the listing, symbol,
latest-trading-day snapshot, time-only date binding and observed time bounds for
replay. The normalizer emits `AKSHARE_INTRADAY_TRADES_RAW_ONLY`; no canonical
daily-history, liquidity, order-flow or valuation fact is admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `时间` | Validated `HH:MM:SS` observation time in non-decreasing order; it has no row-level trading date and is not converted into a daily-history period. |
| `成交价` | Provider trade-price field retained as raw evidence; no quote or daily-history replacement is inferred. |
| `手数` | Provider lot-count field must be an integer or null; no cross-frequency liquidity metric is calculated. |
| `买卖盘性质` | Validated `买盘`, `卖盘` or `中性盘` marker; no order-flow, sentiment or governance conclusion is inferred. |
| request `view=intraday_trades`, unprefixed A-share `symbol` | Explicit endpoint/listing/latest-day/time-only replay scope; observed time bounds are retained as metadata and cannot be replayed under a different request. |

The provider-specific intraday trade response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts. Its raw evidence is available
for later review without being treated as canonical daily history, liquidity,
order flow or valuation input.

## Phase 2.61 A-share Eastmoney stock hot-rank raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hot_rank_em` as an Eastmoney no-argument A-share endpoint
returning the current-trading-day top 100 popularity rows. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py)
confirms the six output fields `当前排名`, `代码`, `股票名称`, `最新价`, `涨跌额`
and `涨跌幅`; its market-prefixed security code is preserved as raw identity
context.

The provider selects this endpoint only under the existing provider-neutral
`MARKET_ACTIVITY` category with explicit `view=hot_rank`, validates the exact
field set, market-prefixed A-share identity, unique strictly ascending ranks,
finite numeric/null quote fields and the documented 100-row maximum, then
filters the universe to the requested listing. The current-day snapshot is
bound only to retrieval provenance because the response has no row-level date.
The normalizer emits `AKSHARE_HOT_RANK_RAW_ONLY`; no canonical market,
issuer-cash-flow, shareholder-return, governance or valuation fact is admitted.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `当前排名` | Validated positive rank in strict ascending order; no canonical popularity, sentiment or market metric is inferred. |
| `代码`, `股票名称` | Required market-prefixed A-share identity and display context; no issuer or governance fact is inferred. |
| `最新价`, `涨跌额`, `涨跌幅` | Raw current-day quote context; it is not used to replace the canonical quote or derive return, liquidity or valuation. |
| request `view=hot_rank` | Explicit endpoint-selection and filtered-listing replay scope; the no-argument current-day snapshot is not replayed as a dated observation. |

The provider-specific stock hot-rank response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts. Its raw evidence is available
for later review without being treated as a canonical market metric,
shareholder-return, governance or valuation input.

## Phase 2.62 A+H Eastmoney quote-comparison raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_ah_spot_em` as an Eastmoney no-argument A+H comparison
endpoint, delayed by 15 minutes. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hsgt_em.py)
confirms the exact ten output fields `序号`, `名称`, `H股代码`, `最新价-HKD`,
`H股-涨跌幅`, `A股代码`, `最新价-RMB`, `A股-涨跌幅`, `比价` and `溢价`.

The provider selects this endpoint only under `MARKET_QUOTE` with explicit
`view=ah_comparison`, validates the full response before filtering it to the
requested A- or H-share code, and records the side-specific code field,
`HKD_per_share`/`RMB_per_share` price units, percent change/premium units,
ratio units and filtered row counts for replay. The normalizer emits
`AKSHARE_AH_COMPARISON_RAW_ONLY`; no canonical current-price, FX, comparison,
valuation or calculation fact is admitted because the cross-market snapshot is
delayed and has no stable row-level observation timestamp.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `序号` | Required positive integer in a strictly ascending full-universe sequence; no canonical rank or market metric is inferred. |
| `名称` | Required non-empty display name; it is retained as raw entity context only. |
| `H股代码`, `A股代码` | Required five-/six-digit string identities; the requested side is used only for provider-boundary filtering and replay scope. |
| `最新价-HKD`, `最新价-RMB` | Raw H-share/HKD and A-share/RMB quote context; neither replaces canonical current price or establishes FX/share equivalence. |
| `H股-涨跌幅`, `A股-涨跌幅` | Raw percentage changes; no return or valuation fact is inferred. |
| `比价`, `溢价` | Raw provider comparison/premium fields; no canonical ratio, FX or valuation fact is inferred. |
| request `view=ah_comparison` | Explicit no-argument endpoint-selection, side-filtered-listing and delayed-snapshot replay scope. |

The provider-specific A+H comparison response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts. Its raw evidence is available
for later review without being treated as a canonical quote, FX, comparison,
market or valuation input.

## Phase 2.87 A-share Eastmoney A+B quote-comparison raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_ab_comparison_em` as a no-argument Eastmoney universe
endpoint for all A/B share pairs. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
returns the exact ten fields `序号`, `B股代码`, `B股名称`, `最新价B`,
`涨跌幅B`, `A股代码`, `A股名称`, `最新价A`, `涨跌幅A` and `比价`, dividing
the upstream quote/change/ratio values by 100 before returning the table.

The provider selects this endpoint only under `MARKET_QUOTE` with explicit
`view=ab_comparison`, validates the complete response and official field order
before filtering to the requested six-digit A-share code, and records the
retrieval-only current-trading-day scope, field order, row counts and units.
The endpoint does not document the B-share currency; the adapter retains the
returned per-share values without inventing a currency. The normalizer emits
`AKSHARE_AB_COMPARISON_RAW_ONLY`, leaves `current_price` critically missing
and creates no canonical quote, currency, comparison or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `序号` | Required positive integer in the strictly ascending full-universe sequence; no canonical rank or market metric is inferred. |
| `B股代码`, `A股代码` | Required six-digit B/A identities; the A-share code is used only for provider-boundary filtering and replay scope. |
| `B股名称`, `A股名称` | Required non-empty display names; retained as raw entity context only. |
| `最新价B`, `最新价A` | Provider-returned per-share quote values; the B-share currency is undocumented and neither side replaces canonical `current_price`. |
| `涨跌幅B`, `涨跌幅A` | Raw percentage-change values; no return or valuation fact is inferred. |
| `比价` | Raw provider comparison ratio; no canonical ratio, currency conversion or valuation fact is inferred. |
| request `view=ab_comparison` | Explicit no-argument endpoint selection, A-share-only filtered-listing scope and retrieval-only snapshot boundary. |

The provider-specific A+B comparison response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts. Its raw evidence is available
for later review without being treated as a canonical quote, currency,
comparison, market or valuation input.

## Phase 2.88 A-share Eastmoney historical stock-hot-rank raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hot_rank_detail_em` as a symbol-scoped Eastmoney A-share
historical-hot-rank endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py)
uses the market-prefixed `SZ000665` symbol with `marketType=""` and combines
the historical rank and follower-rate sources. Its exact returned fields are
`时间`, `排名`, `证券代码`, `新晋粉丝` and `铁杆粉丝`, in that order; the source
percent rates are divided by 100 into fractions by the official adapter.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=hot_rank_detail`, validates the complete symbol-scoped response before
retaining it, and preserves the documented Eastmoney source URI
`https://guba.eastmoney.com/rank/stock?code=000665`. Dates must be valid ISO
dates in strict ascending order, the code must match the requested
market-prefixed A-share identity, ranks must be positive integers and follower
ratios must be finite fractions in `[0, 1]`. The checked-in official snapshot
contains 366 rows from `2025-09-11` through `2026-09-11`; no selected/
non-selected universe rows or adapter-side listing filter apply because the
upstream request is already symbol-scoped. Request symbol, field order, rate
units/scaling, source URI, row counts and observed date bounds remain replay
metadata.

| Raw upstream item | Phase 2.88 treatment |
| --- | --- |
| `时间` | Required `YYYY-MM-DD` row observation date; strict ordering is validated and the date is not promoted to a report or accounting period. |
| `排名` | Required positive integer provider popularity rank; retained as raw rank evidence and not converted into a return, liquidity, valuation or canonical market metric. |
| `证券代码` | Required market-prefixed A-share identity (`SH`/`SZ`/`BJ` plus six digits) matching the requested listing; used for response identity validation only. |
| `新晋粉丝`, `铁杆粉丝` | Optional finite follower rates represented as fractions after the documented percent-to-fraction scaling; they remain raw popularity context and do not establish issuer cash flow, shareholder return or governance. |
| request `view=hot_rank_detail`, `symbol=SZ000665` | Explicit A-share endpoint selector and listing-scoped request; `marketType=""`, source URI, field order, row counts, units/scaling and observed date bounds remain part of the cache replay boundary. |

The provider-specific A-share historical-hot-rank response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts. The normalizer
emits `AKSHARE_HOT_RANK_DETAIL_RAW_ONLY` and creates no canonical facts.

## Phase 2.89 A-share Eastmoney IPO-yield raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_dxsyl_em.py)
document `stock_dxsyl_em` as a no-argument Eastmoney A-share IPO-yield
universe at `https://data.eastmoney.com/xg/xg/dxsyl.html`. The official output
order is exactly `序号`, `股票代码`, `股票简称`, `发行价`, `最新价`,
`网上-发行中签率`, `网上-有效申购股数`, `网上-有效申购户数`, `网上-超额认购倍数`,
`网下-配售中签率`, `网下-有效申购股数`, `网下-有效申购户数`, `网下-配售认购倍数`,
`总发行数量`, `开盘溢价`, `首日涨幅` and `上市日期`.

The provider exposes this callable only under `CORPORATE_ACTIONS` with
explicit `view=ipo_yield`, passes no upstream arguments, validates the full
universe and exact field order before filtering to the requested six-digit
A-share code, and records the source URI, field order, documented units, row
counts and listing-date bounds for replay. The checked-in official fixture
contains three rows (`688801`, `301689` and `301699`), with one selected row
and two non-selected rows. Rates and all other numeric values remain exactly
as returned; no percentage rescaling or missing unit is invented.

| Raw upstream item | Phase 2.89 treatment |
| --- | --- |
| `序号` | Required positive integer in the strictly ascending full-universe sequence; retained for raw ordering only. |
| `股票代码` | Required exact six-digit A-share identity; used for conservative provider-boundary filtering and replay validation only. |
| `股票简称` | Required non-empty display name; retained as raw entity context only. |
| `发行价`, `最新价` | Finite numeric-or-null provider values; numeric units and whether `最新价` is a stable observation are not documented, so no canonical price fact is created. |
| `网上-发行中签率`, `网下-配售中签率` | Finite provider-reported values documented as percent fields; raw values are preserved without converting to fractions or a canonical subscription metric. |
| `网上-有效申购股数`, `网下-有效申购股数`, `总发行数量` | Finite provider-reported issue/subscription quantities; the endpoint does not establish a canonical share unit, settlement period or diluted-share scope. |
| `网上-有效申购户数`, `网下-有效申购户数` | Finite provider-reported household counts; retained as raw participation context only. |
| `网上-超额认购倍数`, `网下-配售认购倍数` | Finite provider-reported multiples; no canonical demand, return or valuation metric is derived. |
| `开盘溢价`, `首日涨幅` | Finite provider-reported listing-day return context; no shareholder-return, price or valuation fact is inferred. |
| `上市日期` | Valid date-or-null row-level IPO context; it is not promoted to canonical listing or accounting period. |
| request `view=ipo_yield` | Explicit no-argument full-universe endpoint selector; `listing_scoped_request=false`, provider filtering, source URI, field order, documented units and full/selected row counts remain part of the cache replay boundary. |

The normalizer emits `AKSHARE_IPO_YIELD_RAW_ONLY`, marks
`share_issuance_cash` as critically missing and creates no canonical issuance,
dilution, price, return or listing-date fact. The provider-specific response
remains outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.90 A-share Eastmoney block-trade detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_dzjy_em.py)
document `stock_dzjy_mrmx` as an Eastmoney A-share block-trade detail
universe at `https://data.eastmoney.com/dzjy/dzjy_mrmx.html`. The adapter
exposes it under `MARKET_ACTIVITY` only with explicit
`view=block_trade_detail`, passes `symbol="A股"` with the requested
`start_date`/`end_date`, validates the full date-range response and filters it
to the requested six-digit A-share code.

The official A-share output order is exactly `序号`, `交易日期`, `证券代码`,
`证券简称`, `涨跌幅`, `收盘价`, `成交价`, `折溢率`, `成交量`, `成交额`,
`成交额/流通市值`, `买方营业部` and `卖方营业部`.

| Raw upstream item | Phase 2.90 treatment |
| --- | --- |
| `序号` | Required positive integer in the strictly ascending provider sequence; retained for source ordering only. |
| `交易日期` | Required `YYYY-MM-DD` observation date and must fall within the requested inclusive date range. It is retained as raw trade context, not an accounting period. |
| `证券代码` | Required exact six-digit A-share identity; used for conservative provider-boundary filtering and replay validation only. |
| `证券简称`, `买方营业部`, `卖方营业部` | Required non-empty source text; retained as entity and brokerage context only. |
| `涨跌幅`, `成交额/流通市值` | Finite provider values documented as percent fields; no canonical return, liquidity or valuation metric is derived. |
| `成交量` | Finite provider value documented in shares; its block-trade context does not establish a canonical volume or shareholder-return fact. |
| `成交额` | Finite provider value documented in CNY; it is trade activity, not issuer cash flow or shareholder cash. |
| `收盘价`, `成交价`, `折溢率` | Finite provider numeric values; the current documentation does not establish their units/scaling for a canonical price or discount metric. |
| request `view=block_trade_detail`, `symbol="A股"`, `start_date`, `end_date` | Explicit A-share full-universe selector; `listing_scoped_request=false`, provider filtering, source URI, field order, units, request-date binding and full/selected row counts remain part of the cache replay boundary. |

The normalizer emits `AKSHARE_BLOCK_TRADE_RAW_ONLY` and creates no canonical
fact. Date-bound trade prices, quantities, amounts, discount/premium and
brokerage context remain raw evidence and do not establish issuer cash flow,
shareholder return, governance, valuation or a canonical market metric. The
provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.91 H-share Eastmoney main-board quote raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)
document `stock_hk_main_board_spot_em` as a no-argument Eastmoney H-share
main-board quote universe at
`https://quote.eastmoney.com/center/gridlist.html#hk_mainboard`. The adapter
exposes it under `MARKET_QUOTE` only with explicit `view=hk_main_board`,
validates the full response and filters it to the requested five-digit H-share
code.

The official output order is exactly `序号`, `代码`, `名称`, `最新价`, `涨跌额`,
`涨跌幅`, `今开`, `最高`, `最低`, `昨收`, `成交量` and `成交额`.

| Raw upstream item | Phase 2.91 treatment |
| --- | --- |
| `序号` | Required positive integer in the strictly ascending full-universe sequence; retained for source ordering only. |
| `代码` | Required exact five-digit H-share identity; used for conservative provider-boundary filtering and replay validation only. |
| `名称` | Required non-empty display name; retained as raw entity context only. |
| `最新价`, `涨跌额` | Finite numeric-or-null values documented in HKD per share; the delayed snapshot has no stable observation timestamp, so no canonical current-price or change fact is created. |
| `涨跌幅` | Finite numeric-or-null provider value documented as percent; retained as raw quote context only. |
| `今开`, `最高`, `最低`, `昨收` | Finite numeric-or-null values documented in HKD per share; retained as raw session context only. |
| `成交量` | Finite numeric-or-null value documented in shares; it does not establish a canonical dated volume or liquidity input. |
| `成交额` | Finite numeric-or-null value documented in HKD; it is market activity, not issuer cash flow or shareholder cash. |
| request `view=hk_main_board` | Explicit no-argument full-universe endpoint selector; `listing_scoped_request=false`, provider filtering, source URI, field order, units, delayed current-day scope and full/selected row counts remain part of the cache replay boundary. |

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes the endpoint as 15-minute delayed and does not provide a stable
observation timestamp. The normalizer emits
`AKSHARE_HK_MAIN_BOARD_QUOTE_RAW_ONLY`, marks `current_price` as critically
missing and creates no canonical quote fact. The checked-in fixture freezes
three source-shaped rows with one selected listing. The provider-specific
response remains outside the calculation, gate, pipeline, CLI and input-loader
contracts.

## Phase 2.93 SSE market-summary raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sse_summary` as the Shanghai Stock Exchange stock-market
summary. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
accepts no upstream arguments and returns the eight metrics `流通股本`, `总市值`,
`平均市盈率`, `上市公司`, `上市股票`, `流通市值`, `报告时间` and `总股本`.
The implementation's final DataFrame column order is `项目`, `股票`, `主板` and
`科创板`; the adapter pins that source-shaped order for replay.

The provider exposes this endpoint under `MARKET_ACTIVITY` only with explicit
`view=sse_summary`, validates the complete market-level response, requires the
three `报告时间` values to be the same valid `YYYYMMDD` date, and records that
embedded report date, source field/metric order, the absence of documented
numeric units and non-listing row counts for replay. The normalizer emits
`AKSHARE_SSE_SUMMARY_RAW_ONLY`; no canonical quote, accounting, return,
governance, valuation or market fact is admitted from the exchange-wide
aggregate.

| Raw upstream item | Phase 2.93 treatment |
| --- | --- |
| `项目` | Required metric label in the official eight-row order; `报告时间` is the only row used to bind the snapshot date, not a listing identity. |
| `股票`, `主板`, `科创板` | Finite numeric-or-null exchange/board aggregates; numeric units are not documented by the endpoint and no listing-level metric is inferred. |
| `报告时间` | Required finite integer-like `YYYYMMDD` value repeated consistently across all three value columns; retained as response scope, not as an accounting period. |
| request `view=sse_summary` | Explicit no-argument SSE market-summary scope; `listing_scoped_request=false`, no provider filtering, source URI, field/metric order and row counts remain part of the cache replay boundary. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.94 SZSE market-summary raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_szse_summary` as a Shenzhen Stock Exchange requested-date
market summary. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
accepts `date=YYYYMMDD` and returns the exact source-shaped fields
`证券类别`, `数量`, `成交金额`, `总市值` and `流通市值`, in that order. The
documentation sample returns the categories `股票`, `主板A股`, `主板B股`,
`中小板`, `创业板A股`, `基金`, `ETF`, `LOF`, `封闭式基金`, `分级基金`,
`债券`, `债券现券`, `债券回购`, `ABS` and `期权` in that order.

The provider exposes the endpoint under `MARKET_ACTIVITY` only with explicit
`view=szse_summary`, passes only the normalized date to the upstream callable,
and validates every returned category row before retention. It records the
requested/observation date, Shenzhen market scope, returned category order,
source field order, documented units, undocumented market-value units and
non-listing row counts for cache replay. The normalizer emits
`AKSHARE_SZSE_SUMMARY_RAW_ONLY`; no canonical quote, accounting, return,
governance, valuation or market fact is admitted from this exchange-wide
aggregate.

| Raw upstream item | Phase 2.94 treatment |
| --- | --- |
| `证券类别` | Required non-empty unique category label; the returned category order is preserved as response metadata and `股票` must be present. It is a security-category scope, not a listing identity. |
| `数量` | Non-negative integer or null security count; the documented unit is `只` (represented as `securities` in metadata). |
| `成交金额` | Finite non-negative numeric or null transaction amount; the documented unit is `元` (represented as `CNY` in metadata). |
| `总市值`, `流通市值` | Finite non-negative numeric or null market-value aggregates; the endpoint does not document their numeric units, so nulls are retained and no listing-level valuation is inferred. |
| request `view=szse_summary`, `date` | Explicit requested-day SZSE market-summary scope; `listing_scoped_request=false`, no provider filtering, source URI, field/category order and row counts remain part of the cache replay boundary. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.95 SZSE area-summary raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_szse_area_summary` as a Shenzhen Stock Exchange monthly
region-ranked trading summary. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
accepts `date=YYYYMM` and returns the base source-shaped fields `序号`, `地区`,
`总交易额`, `占市场`, `股票交易额`, `基金交易额` and `债券交易额`, in that
order. The documentation adds `优先股交易额` and `期权交易额` from 2025
onward; the adapter accepts either exact documented variant and does not
silently fill a missing variant.

The provider exposes the endpoint under `MARKET_ACTIVITY` only with explicit
`view=szse_area_summary`, passes only the normalized month to the upstream
callable, and validates the complete region-ranked response before retention.
It records the requested/observation month, Shenzhen market scope, strict rank
and source order, documented units and non-listing row counts for cache replay.
The normalizer emits `AKSHARE_SZSE_AREA_SUMMARY_RAW_ONLY`; no canonical quote,
accounting, return, governance, valuation or market fact is admitted from this
exchange-wide regional aggregate.

| Raw upstream item | Phase 2.95 treatment |
| --- | --- |
| `序号` | Required positive integer rank with strict ascending order; it orders the source response and is not a listing identifier. |
| `地区` | Required non-empty unique region label; it is geographic scope only and does not establish an issuer identity. |
| `总交易额`, `股票交易额`, `基金交易额`, `债券交易额` | Finite non-negative numeric or null transaction aggregates; the documented unit is `元` (represented as `CNY` in metadata). |
| `优先股交易额`, `期权交易额` | Optional only as the documented 2025 extended variant; finite non-negative numeric or null transaction aggregates with documented `元`/`CNY` units. |
| `占市场` | Finite non-negative numeric or null market-share value; the documented unit is `%` (represented as `percent` in metadata), not a canonical liquidity or valuation metric. |
| request `view=szse_area_summary`, `date` | Explicit requested-month SZSE region-ranking scope; `listing_scoped_request=false`, no provider filtering, source URI, field order and row counts remain part of the cache replay boundary. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.96 SZSE sector-summary raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_szse_sector_summary` as a Shenzhen Stock Exchange monthly
industry-trading report. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
accepts `symbol` as `当月` or `当年` and a `date=YYYYMM`; it selects the
published month or year-to-date table and returns the nine source-shaped fields
`项目名称`, `项目名称-英文`, `交易天数`, `成交金额-人民币元`,
`成交金额-占总计`, `成交股数-股数`, `成交股数-占总计`, `成交笔数-笔` and
`成交笔数-占总计`, in that order.

The provider exposes the endpoint under `MARKET_ACTIVITY` only with explicit
`view=szse_sector_summary`, passes the selector and normalized month to the
upstream callable, and validates the complete industry response before
retention. It records the requested/observation month, selector scope,
Shenzhen market scope, source industry order, documented units and
non-listing row counts for cache replay. The normalizer emits
`AKSHARE_SZSE_SECTOR_SUMMARY_RAW_ONLY`; no canonical quote, accounting,
return, governance, valuation or market fact is admitted from this
exchange-wide industry aggregate.

| Raw upstream item | Phase 2.96 treatment |
| --- | --- |
| `项目名称` | Required non-empty unique industry label; the source order is preserved and `合计` must lead the report, but no industry row is a listing identity. |
| `项目名称-英文` | Optional source text retained as raw context; it is not used to classify the requested company. |
| `交易天数` | Non-negative integer report context; its `trading_days` unit is explicit metadata and it is not a listing observation period. |
| `成交金额-人民币元` | Non-negative integer transaction aggregate with documented `人民币元`/`CNY` unit. |
| `成交金额-占总计` | Finite non-negative transaction-share value with documented `%`/`percent` unit. |
| `成交股数-股数` | Non-negative integer transaction aggregate with documented `股数`/`shares` unit. |
| `成交股数-占总计` | Finite non-negative share-volume proportion with documented `%`/`percent` unit. |
| `成交笔数-笔` | Non-negative integer transaction aggregate with documented `笔`/`transactions` unit. |
| `成交笔数-占总计` | Finite non-negative transaction-count proportion with documented `%`/`percent` unit. |
| request `view=szse_sector_summary`, `symbol`, `date` | Explicit requested-month SZSE industry-report scope; `listing_scoped_request=false`, no provider filtering, source URI, selector, source field/industry order and row counts remain part of the cache replay boundary. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.97 A-share Eastmoney industry-board raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_board_industry_name_em` as an Eastmoney current snapshot of
all industry boards. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_industry_em.py)
uses a no-argument request and returns the 12 source-shaped fields `排名`,
`板块名称`, `板块代码`, `最新价`, `涨跌额`, `涨跌幅`, `总市值`, `换手率`,
`上涨家数`, `下跌家数`, `领涨股票` and `领涨股票-涨跌幅`, in that order.

The provider exposes this endpoint under `MARKET_ACTIVITY` only with explicit
`view=industry_board`, passes no upstream arguments, and validates the complete
board universe before retention. It records the ranked board/name/code order,
documented percentage units, undocumented price/market-value units and
non-listing row counts for cache replay. The normalizer emits
`AKSHARE_INDUSTRY_BOARD_RAW_ONLY`; no canonical quote, accounting, return,
governance, valuation or market fact is admitted from this current
industry-board snapshot.

| Raw upstream item | Phase 2.97 treatment |
| --- | --- |
| `排名` | Required positive integer with strict ascending source order; it ranks the response and is not a listing identifier. |
| `板块名称`, `板块代码` | Required unique board identity; the `BK...` code and name are retained as raw context and do not establish a requested issuer's industry classification. |
| `最新价`, `涨跌额`, `总市值` | Finite numeric-or-null current board context; the endpoint does not settle canonical quote or market-value units. |
| `涨跌幅`, `换手率`, `领涨股票-涨跌幅` | Finite numeric-or-null provider percentages with documented `%`/`percent` units; no canonical return or liquidity metric is inferred. |
| `上涨家数`, `下跌家数` | Non-negative integer board breadth counts; they remain aggregate market context only. |
| `领涨股票` | Optional source leader name retained as raw context; it does not establish issuer quality, governance or shareholder-return evidence. |
| request `view=industry_board` | Explicit no-argument current board-universe scope; `listing_scoped_request=false`, no provider filtering, source URI, board order and row counts remain part of the cache replay boundary. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.98 A-share Eastmoney executive/shareholder-change raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_ggcg_em` as an Eastmoney full A-share universe for executive
and shareholder holding changes. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdzjc_em.py)
accepts `symbol="全部"`, `symbol="股东增持"` or `symbol="股东减持"`, applies the
corresponding direction filter upstream and returns the exact 16 fields
`代码`, `名称`, `最新价`, `涨跌幅`, `股东名称`, `持股变动信息-增减`,
`持股变动信息-变动数量`, `持股变动信息-占总股本比例`,
`持股变动信息-占流通股比例`, `变动后持股情况-持股总数`,
`变动后持股情况-占总股本比例`, `变动后持股情况-持流通股数`,
`变动后持股情况-占流通股比例`, `变动开始日`, `变动截止日` and `公告日`,
in that order.

The provider exposes this endpoint under `INSIDER_SHARE_CHANGES` only with
explicit `view=executive_share_changes` and a direction, validates the full
direction-filtered response before listing selection, and records direction,
source field order, documented units, undocumented price units, event-date
bounds and upstream/selected row counts for replay. The normalizer emits
`AKSHARE_EXECUTIVE_SHARE_CHANGES_RAW_ONLY`; no canonical share, dilution,
transaction-cash, governance, shareholder-return or valuation fact is admitted
from holder-change evidence.

| Raw upstream item | Phase 2.98 treatment |
| --- | --- |
| `代码`, `名称` | Required six-digit A-share code and source security name; the provider filters by code, but no security-master or canonical issuer fact is inferred. |
| `最新价` | Finite numeric-or-null quote context; the documentation does not specify a unit, so it remains `not_documented` metadata and is not promoted to a quote fact. |
| `涨跌幅` | Finite quote-change value retained with the documented `%` unit; it is not a dated canonical return. |
| `股东名称`, `持股变动信息-增减` | Holder identity and source direction text retained as raw evidence; the latter is validated as `增持` or `减持` even though the documentation table labels its type inconsistently. |
| `持股变动信息-变动数量`, `变动后持股情况-持股总数`, `变动后持股情况-持流通股数` | Finite non-negative quantities retained with the documented `万股` unit; they do not establish a fully diluted share series or settled transaction cash. |
| `持股变动信息-占总股本比例`, `持股变动信息-占流通股比例`, `变动后持股情况-占总股本比例`, `变动后持股情况-占流通股比例` | Finite non-negative provider ratios retained with the documented `%` unit; no ownership, dilution or governance conclusion is inferred. |
| `变动开始日`, `变动截止日`, `公告日` | Nullable parsed event/publication dates retained as row-date evidence; `变动截止日` supplies replay bounds and does not create a reporting period. |
| request `view=executive_share_changes`, `direction` / upstream `symbol` | Explicit direction scope retained in request/evidence metadata; the provider sends the direction to the full A-share universe, filters the requested listing locally, and records `listing_scoped_request=false`, source order, page size and both row counts for replay. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.99 A-share Eastmoney management-person raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
document `stock_hold_management_person_em` as a symbol-and-person-scoped
Eastmoney response. Its `symbol` is a six-digit A-share code and its `name` is
the requested executive name. The source returns the exact 16 fields
`日期`, `代码`, `名称`, `变动人`, `变动股数`, `成交均价`, `变动金额`,
`变动原因`, `变动比例`, `变动后持股数`, `持股种类`, `董监高人员姓名`,
`职务`, `变动人与董监高的关系`, `开始时持有` and `结束后持有`, in that
order.

The provider exposes this endpoint under `INSIDER_SHARE_CHANGES` only with
explicit `view=management_person`, passes `symbol` and `name` upstream and
retains the already listing/person-scoped response. It validates exact field
order, listing/person identity, ISO change dates, finite numeric/null values
and non-negative price/holding fields. Numeric units are recorded as
`not_documented`; no conversion or economic interpretation is applied.

| Raw upstream item | Phase 2.99 treatment |
| --- | --- |
| `日期` | Required ISO change/event date retained as row evidence and used only for observed replay bounds; it is not a report period. |
| `代码`, `名称` | Required listing identity and source security name; the code must match the requested six-digit A-share listing, but no security-master fact is inferred. |
| `变动人`, `董监高人员姓名`, `职务`, `变动人与董监高的关系` | Requested person, management identity, role and relationship text retained as raw evidence; person identity is validated against the upstream `name` scope. |
| `变动股数`, `成交均价`, `变动金额`, `变动比例`, `变动后持股数`, `开始时持有`, `结束后持有` | Finite numeric/null transaction, price, ratio and holding values retained without a documented unit, dilution treatment or settled-cash interpretation. |
| `变动原因`, `持股种类` | Source reason and holding-type labels retained as raw context; no governance or ownership conclusion is inferred. |
| request `view=management_person`, `symbol`, `name` | Explicit symbol/person scope, upstream page size and source field order are retained in request/response metadata for cache replay; no local universe filtering occurs. |

The normalizer emits `AKSHARE_MANAGEMENT_PERSON_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
dilution, transaction-cash or shareholder-return fact. The provider-specific
response remains outside the calculation, gate, pipeline, CLI and input-loader
contracts.

## Phase 3.00 A-share Eastmoney Dragon-Tiger institution-daily raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_lhb_jgmmtj_em` as the Eastmoney Dragon-Tiger institution
buy/sell daily-statistics endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_lhb_em.py)
accepts `start_date` and `end_date` as `YYYYMMDD` strings, applies the inclusive
date filter to the all-history response and returns the exact 16 fields
`序号`, `代码`, `名称`, `收盘价`, `涨跌幅`, `买方机构数`, `卖方机构数`,
`机构买入总额`, `机构卖出总额`, `机构买入净额`, `市场总成交额`,
`机构净买额占总成交额比`, `换手率`, `流通市值`, `上榜原因` and `上榜日期`,
in that order.

The provider exposes this endpoint under `MARKET_ACTIVITY` only with explicit
`view=institution_daily`, validates the complete full-universe response before
filtering it to the requested A-share listing, and preserves the requested
range, source sequence, exact field order, date bounds and both row counts for
cache replay. The documented monetary units are CNY for the four institution/
market totals and 亿元 for `流通市值`; every other numeric unit remains
`not_documented`. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_DAILY_RAW_ONLY`; no canonical issuer cash
flow, shareholder return, governance, valuation or market fact is admitted.

| Raw upstream item | Phase 3.00 treatment |
| --- | --- |
| `序号` | Required positive integer source ordering, validated as strictly ascending; it is not a report-period or listing metric. |
| `代码`, `名称` | Required six-digit listing identity and source security name; the provider validates every full-universe row and filters by code without inferring a security-master or issuer fact. |
| `收盘价`, `涨跌幅` | Finite numeric-or-null quote context retained with `not_documented` units; no dated canonical quote or return is inferred. |
| `买方机构数`, `卖方机构数` | Finite non-negative institution-count context retained with `not_documented` units; counts do not establish ownership or issuer cash flow. |
| `机构买入总额`, `机构卖出总额`, `机构买入净额`, `市场总成交额` | Finite trading aggregates retained in documented CNY units; they are market activity evidence, not issuer cash-flow facts. |
| `机构净买额占总成交额比`, `换手率` | Finite numeric-or-null provider ratios retained with `not_documented` units; no canonical liquidity, return or valuation metric is inferred. |
| `流通市值` | Finite non-negative market-value context retained in documented 亿元 units; it is not promoted to a canonical market-cap or valuation input. |
| `上榜原因`, `上榜日期` | Required reason text and ISO row date retained as raw evidence; the date must fall inside the requested inclusive range and is not a filing or accounting period. |
| request `view=institution_daily`, `start_date`, `end_date` | Explicit all-A-share date-range scope; `listing_scoped_request=false`, provider filtering, source order, date bounds and upstream/selected row counts remain part of the replay contract. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 3.01 A-share Eastmoney institutional-research statistics raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_jgdy_tj_em` as the Eastmoney institutional-research statistics
endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
accepts `date=YYYYMMDD` as the start of the announcement-date query, applies a
strict `公告日期 > date` filter and returns the exact 11 fields `序号`, `代码`,
`名称`, `最新价`, `涨跌幅`, `接待机构数量`, `接待方式`, `接待人员`, `接待地点`,
`接待日期` and `公告日期`, in that order.

The provider exposes this endpoint under `MARKET_ACTIVITY` only with explicit
`view=institution_research`, validates the complete full-universe response
before filtering it to the requested A-share listing, and preserves the
requested cutoff, both date-field bounds, source sequence, exact field order
and both row counts for cache replay. The official contract documents `%` for
`涨跌幅`; price and institution-count units remain `not_documented`. The
normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_RAW_ONLY`; research visits,
institution counts and quote context do not become canonical issuer cash flow,
shareholder return, governance, valuation or market facts.

| Raw upstream item | Phase 3.01 treatment |
| --- | --- |
| `序号` | Required positive integer source ordering, validated as strictly ascending; it is not a report period or listing metric. |
| `代码`, `名称` | Required six-digit listing identity and source security name; the provider validates every full-universe row and filters by code without inferring a security-master or issuer fact. |
| `最新价` | Finite non-negative numeric-or-null quote context retained with a `not_documented` unit; no canonical dated quote or valuation input is inferred. |
| `涨跌幅` | Finite numeric-or-null quote-change context retained in the documented percent unit; no canonical return is inferred. |
| `接待机构数量` | Finite non-negative integer institution-count context retained with a `not_documented` unit; it does not establish ownership, governance or issuer cash flow. |
| `接待方式`, `接待人员`, `接待地点` | Research-visit context retained as non-empty raw text when published, with documented nullable values preserved; no qualitative governance judgment is inferred. |
| `接待日期`, `公告日期` | Required ISO dates retained as event/announcement evidence; `公告日期` must be strictly after the requested cutoff, and neither date is treated as a filing or accounting period. |
| request `view=institution_research`, `date` | Explicit all-A-share start-cutoff scope; `listing_scoped_request=false`, provider filtering, source order, both date bounds and upstream/selected row counts remain part of the replay contract. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 3.02 A-share Eastmoney institutional-research detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_jgdy_detail_em` as the Eastmoney institutional-research detail
endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_jgdy_em.py)
accepts `date=YYYYMMDD` as the start of the research-date query, applies a
strict `调研日期 > date` filter and returns the exact 13 fields `序号`, `代码`,
`名称`, `最新价`, `涨跌幅`, `调研机构`, `机构类型`, `调研人员`, `接待方式`,
`接待人员`, `接待地点`, `调研日期` and `公告日期`, in that order.

The provider exposes this endpoint under `MARKET_ACTIVITY` only with explicit
`view=institution_research_detail`, validates the complete full-universe
response before filtering it to the requested A-share listing, and preserves
the requested cutoff, both date-field bounds, source sequence, exact field
order and both row counts for cache replay. Because multiple institutions can
share one listing, research date and announcement date, detail identity also
includes the published institution, institution type, researchers and
reception context. The official contract documents `%` for `涨跌幅`; price
units remain `not_documented`. The normalizer emits
`AKSHARE_MARKET_ACTIVITY_INSTITUTION_RESEARCH_DETAIL_RAW_ONLY`; research
participants, visit dates and quote context do not become canonical issuer
cash flow, shareholder return, governance, valuation or market facts.

| Raw upstream item | Phase 3.02 treatment |
| --- | --- |
| `序号` | Required positive integer source ordering, validated as strictly ascending; it is not a report period or listing metric. |
| `代码`, `名称` | Required six-digit listing identity and source security name; the provider validates every full-universe row and filters by code without inferring a security-master or issuer fact. |
| `最新价` | Finite non-negative numeric-or-null quote context retained with a `not_documented` unit; no canonical dated quote or valuation input is inferred. |
| `涨跌幅` | Finite numeric-or-null quote-change context retained in the documented percent unit; no canonical return is inferred. |
| `调研机构`, `机构类型`, `调研人员`, `接待方式`, `接待人员`, `接待地点` | Published institution, participant and reception context retained as nullable raw text; it distinguishes detail identities but does not establish ownership, governance or issuer cash flow. |
| `调研日期`, `公告日期` | Required ISO dates retained as research/announcement evidence; `调研日期` must be strictly after the requested cutoff, and neither date is treated as a filing or accounting period. |
| request `view=institution_research_detail`, `date` | Explicit all-A-share research-date start-cutoff scope; `listing_scoped_request=false`, provider filtering, source order, both date bounds and upstream/selected row counts remain part of the replay contract. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 3.03 A-share Eastmoney important-shareholder pledge-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gpzy_pledge_ratio_detail_em` as the important-shareholder
pledge-detail endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
uses the no-argument Eastmoney `RPTA_APP_ACCUMDETAILS` report, fetches all
500-row pages ordered by descending `NOTICE_DATE`, generates one-based `序号`
values, and returns the following final DataFrame/record order:
`序号`, `股票代码`, `股票简称`, `股东名称`, `质押股份数量`, `占所持股份比例`,
`占总股本比例`, `质押机构`, `最新价`, `质押日收盘价`, `预估平仓线`,
`质押开始日期`, `质押结束日期`, `状态`, `公告日期`. The adapter exposes it
only under `OWNERSHIP_PLEDGE` with explicit `view=market_pledge_detail`,
validates the complete response before filtering to the requested A-share
code, and retains source order, nullability, date bounds, pagination and full/
selected row counts for deterministic replay.

| Raw upstream item | Phase 3.03 treatment |
| --- | --- |
| `序号` | Required positive integer; the full response must use one-based source positions and the selected response must remain strictly ascending. It is not a report period or listing metric. |
| `股票代码` | Required six-digit string identity validated across the full response and used only for provider filtering; it does not replace caller-supplied company identity. |
| `股票简称`, `股东名称`, `状态` | Required non-empty source text retained as raw evidence; holder names are not interpreted as beneficial control, governance severity or debt ownership. |
| `质押机构` | Nullable source text; when populated it must be non-empty. A null counterparty is preserved in the raw row and its explicit identity tuple rather than inferred or zero-filled. |
| `质押股份数量` | Finite non-negative numeric-or-null value in shares; no canonical diluted-share or pledged-cash fact is inferred. |
| `占所持股份比例`, `占总股本比例` | Finite numeric-or-null values in percent, bounded to 0–100; provider ratios do not become canonical ownership or governance metrics. |
| `最新价`, `质押日收盘价`, `预估平仓线` | Finite non-negative numeric-or-null values in CNY per share; no canonical quote, valuation, cash or liquidation conclusion is inferred. |
| `质押开始日期` | Nullable ISO `YYYY-MM-DD` date; when populated it must not follow the announcement date or a populated pledge-end date. Null is preserved when the provider's date coercion has no source value. |
| `公告日期` | Required ISO `YYYY-MM-DD` date; announcement dates must be non-increasing in source order. It is not treated as an accounting or filing period. |
| `质押结束日期` | Nullable ISO `YYYY-MM-DD` date; when both end and pledge-start dates are present, end must not precede start. Null is preserved as an active/undetermined end date, not zero-filled. |
| row identity | Duplicate `(股票代码, 股东名称, 质押机构, 质押股份数量, 质押开始日期, 质押结束日期, 公告日期, 状态)` identities are rejected before filtering; nullable institution/start/quantity/end values remain identity components. |
| request `view=market_pledge_detail` | No upstream arguments; full A-share current-published important-shareholder detail, `listing_scoped_request=false`, `row_filtering=provider`, page size 500, all pages and `NOTICE_DATE` descending remain replay metadata. |

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_MARKET_DETAIL_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. Holder, counterparty, quantity,
ratio, price, status and event-date context remain structured evidence pending
the official filing/evidence workflow. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.04 A-share Eastmoney pledge-institution company-distribution raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gpzy_distribute_statistics_company_em` as the current
pledge-institution distribution endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
uses the no-argument Eastmoney `RPT_GDZY_ZYJG_SUM` report with
`filter=(PFORG_TYPE="证券")`, `pageSize=500`, `pageNumber=1`, and descending
`ORG_NUM` order. It generates one-based `序号` values and returns the exact
source order `序号`, `质押机构`, `质押公司数量`, `质押笔数`, `质押数量`,
`未达预警线比例`, `达到预警线未达平仓线比例`, `达到平仓线比例`. The adapter
exposes it only under `OWNERSHIP_PLEDGE` with explicit
`view=company_distribution`, validates the complete institution response
before retention, and keeps the requested listing code as provenance rather
than filtering the market-wide rows.

| Raw upstream item | Phase 3.04 treatment |
| --- | --- |
| `序号` | Required positive integer generated as the one-based source row position and validated as strictly ascending; it is rank/order context, not a listing metric. |
| `质押机构` | Required non-empty text identity; duplicate institutions are rejected in the full response, and institution order is preserved as source order. It does not establish a lender, beneficial owner or governance conclusion. |
| `质押公司数量` | Required integer, finite and non-negative; source order must be non-increasing because the official request sorts by `ORG_NUM`. Its count unit is not separately documented. |
| `质押笔数` | Required integer, finite and non-negative; its count unit is not separately documented and it does not become a canonical pledge-event count. |
| `质押数量` | Required finite non-negative numeric value in shares (`股`); source values remain raw and do not become a canonical diluted-share, pledged-cash or debt-equivalent fact. |
| `未达预警线比例`, `达到预警线未达平仓线比例`, `达到平仓线比例` | Required finite numeric values in the documented percent unit, bounded to 0–100. The upstream implementation returns them without an additional scale conversion, so the adapter preserves the provider-returned numeric values unchanged. They do not become canonical governance or liquidation metrics. |
| row identity and ordering | Duplicate `质押机构` identities are rejected; exact field order, field types, non-nullability, one-based sequence, institution order, company-count ordering and full row count are retained for replay. |
| request `view=company_distribution` | No upstream arguments beyond the implementation's fixed report/filter/page/sort request; current market-wide securities-only snapshot, `listing_scoped_request=false`, `row_filtering=none`, `date_binding=retrieval_only` and `date_boundary=not_applicable` remain explicit metadata. |

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_COMPANY_DISTRIBUTION_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.05 A-share Eastmoney pledge-institution bank-distribution raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
document `stock_gpzy_distribute_statistics_bank_em` as the next distinct
pledge-institution distribution endpoint. It is a no-argument, market-wide
`RPT_GDZY_ZYJG_SUM` response filtered with `(PFORG_TYPE="银行")`, requested as
one 500-row page ordered by descending `ORG_NUM`. The wrapper returns the same
exact eight-field source order as the company view; the adapter exposes it
only under `OWNERSHIP_PLEDGE` with explicit `view=bank_distribution`, validates
the full response before retention and keeps the requested listing code as
provenance rather than filtering the market-wide rows.

| Raw upstream item | Phase 3.05 treatment |
| --- | --- |
| `序号` | Required positive integer generated as the one-based source row position and validated as strictly ascending; it is rank/order context, not a listing metric. |
| `质押机构` | Required non-empty bank-institution identity; duplicate institutions are rejected in the full response and source order is preserved. It does not establish a lender, beneficial owner or governance conclusion. |
| `质押公司数量` | Required integer, finite and non-negative; source order must be non-increasing because the official request sorts by `ORG_NUM`. Its count unit is not separately documented. |
| `质押笔数` | Required integer, finite and non-negative; its count unit is not separately documented and it does not become a canonical pledge-event count. |
| `质押数量` | Required finite non-negative numeric value in shares (`股`); it remains raw and does not become a canonical diluted-share, pledged-cash or debt-equivalent fact. |
| `未达预警线比例`, `达到预警线未达平仓线比例`, `达到平仓线比例` | Required finite numeric values in the documented percent unit, bounded to 0–100. The upstream implementation returns them without an additional scale conversion, so the adapter preserves the provider-returned values unchanged. They do not become canonical governance or liquidation metrics. |
| row identity and ordering | Duplicate `质押机构` identities are rejected; exact field order, field types, non-nullability, one-based sequence, institution order, company-count ordering and full row count are retained for replay. |
| request `view=bank_distribution` | No upstream arguments beyond the implementation's fixed report/filter/page/sort request; current market-wide bank-only snapshot, `listing_scoped_request=false`, `row_filtering=none`, `date_binding=retrieval_only` and `date_boundary=not_applicable` remain explicit metadata. |

A live probe on 2026-09-11 observed current Eastmoney report labels
`银行Ⅱ`/`证券Ⅱ`, while the exact documented `银行` filter used by the current
AKShare wrapper returned no rows. The adapter records the official wrapper
filter contract and does not silently reinterpret or merge the suffixed report
labels; the drift requires a separately reviewed upstream/adapter fix rather
than a fixture-specific fallback.

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_BANK_DISTRIBUTION_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.06 A-share Eastmoney ownership-pledge industry-data raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
document `stock_gpzy_industry_data_em` as a no-argument, market-wide industry
pledge snapshot backed by `RPT_CSDC_INDUSTRY_STATISTICS`. The implementation
requests one 500-row page ordered by descending `AVERAGE_PLEDGE_RATIO` and
uses upstream columns `INDUSTRY_CODE`, `INDUSTRY`, `TRADE_DATE`,
`AVERAGE_PLEDGE_RATIO`, `ORG_NUM`, `PLEDGE_TOTAL_NUM`, `TOTAL_PLEDGE_SHARES`
and `PLEDGE_TOTAL_MARKETCAP`. It drops `INDUSTRY_CODE`, generates one-based
`序号` values and returns the exact eight-field source order `序号`, `行业`,
`平均质押比例`, `公司家数`, `质押总笔数`, `质押总股本`, `最新质押市值`,
`统计时间`. The adapter exposes it only under `OWNERSHIP_PLEDGE` with
explicit `view=industry_data`, validates the complete response before
retention and keeps the requested listing code as provenance rather than
filtering the market-wide rows.

| Raw upstream item | Phase 3.06 treatment |
| --- | --- |
| `序号` | Required positive integer generated as the one-based source row position and validated as strictly ascending; it is rank/order context, not a listing metric. |
| `行业` | Required non-empty industry identity; duplicate labels are rejected in the full response and source order is preserved. Provider labels, including a live-observed `Ⅱ` suffix, are retained as text without merging or relabeling. |
| `平均质押比例` | Required finite non-negative value in the provider-reported percent unit, bounded to 0–100 and non-increasing in the official source order; it does not become a canonical ownership or governance metric. |
| `公司家数`, `质押总笔数` | Required finite non-negative integer counts; their units are not separately documented and they do not become canonical listing or pledge-event counts. |
| `质押总股本` | Required finite non-negative numeric value in shares (`股`); it remains raw and does not become a canonical diluted-share, pledged-cash or debt-equivalent fact. |
| `最新质押市值` | Required finite non-negative numeric value in CNY (`元`); it remains provider market-value context and does not become a valuation or cash fact. |
| `统计时间` | Required ISO `YYYY-MM-DD` row date sourced from `TRADE_DATE`; row-specific dates are retained with their min/max range and are not treated as an accounting or filing period. |
| row identity and ordering | Duplicate `行业` identities are rejected; exact field order/types, non-nullability, one-based sequence, industry order, ratio ordering and full row count are retained for replay. |
| request `view=industry_data` | No upstream arguments beyond the implementation's fixed report/page/sort request; current market-wide industry snapshot, `listing_scoped_request=false`, `row_filtering=none`, `date_binding=row_dates`, `date_boundary=row_min_max` and upstream column/drop metadata remain explicit. |

The normalizer emits
`AKSHARE_OWNERSHIP_PLEDGE_INDUSTRY_DATA_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical share,
cash, debt-equivalent or governance fact. Industry rows, ratios, counts,
shares, market values and row dates remain structured evidence pending the
filing/evidence workflow. The response remains outside the calculation, gate,
pipeline, CLI and input-loader contracts.

## Phase 3.07 A-share Eastmoney goodwill-industry raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
document `stock_sy_hy_em` as a date-filtered, market-wide A-share goodwill
industry response. The explicit adapter request is
`GOODWILL_IMPAIRMENT` plus `view=industry_data` and a required `date=YYYYMMDD`;
the upstream wrapper binds that date to `REPORT_DATE`, requests all columns,
retrieves every 5000-row page and sorts by descending `SUMSHEQUITY_RATIO`. The
wrapper returns six fields and does not expose the report date as a row field,
so the request-period binding remains response metadata.

| Raw upstream item | Phase 3.07 treatment |
| --- | --- |
| `行业名称` | Required non-empty industry identity; duplicate identities are rejected and provider text is preserved in source order. |
| `公司家数` | Required finite non-negative integer company count; its unit is not documented and it does not become a listing count in the canonical model. |
| `商誉规模`, `净资产`, `净利润规模` | Required finite numeric aggregate amounts recorded with `CNY` context; `净利润规模` may be signed, and none becomes a listing-level accounting or profit fact. |
| `商誉规模占净资产规模比例` | Required finite provider ratio with undocumented unit and unchanged source scale; source order must be non-increasing by this ratio, without inferring a canonical denominator or percentage conversion. |
| request `view=industry_data`, `date=YYYYMMDD` | Explicit A-share routing and request-period scope; the complete market-wide response is retained with `listing_scoped_request=false`, `row_filtering=none`, `entity_rows_selected=false` and `date_binding=request_period`. |
| upstream mapping | `RPT_GOODWILL_INDUSTATISTICS`, `REPORT_DATE`, `INDUSTRY_NAME`, `INDUSTRY_CODE`, `ORG_NUM`, `GOODWILL`, `GOODWILL_CHANGE`, `SUMSHEQUITY`, `SUMSHEQUITY_RATIO`, `SE_CHANGE_RATIO`, `PARENTNETPROFIT` and `PNP_CHANGE_RATIO` remain explicit replay metadata; the wrapper drops `REPORT_DATE`, `INDUSTRY_CODE`, `GOODWILL_CHANGE`, `SE_CHANGE_RATIO` and `PNP_CHANGE_RATIO`. |

The provider rejects empty responses, missing/unexpected/reordered fields,
duplicate or blank industry identities, null/non-finite/non-numeric values,
fractional or negative company counts and increasing source ratio order. The
normalizer emits `AKSHARE_GOODWILL_INDUSTRY_DATA_RAW_ONLY`, marks `goodwill`
and `impairment` as critically missing and creates no canonical accounting,
profit, ratio or Business Quality fact. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.08 A-share Eastmoney stock-account-statistics raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_account_em.py)
document `stock_account_statistics_em()` as a no-argument A-share market
history backed by `RPT_STOCK_OPEN_DATA`. The documented response covers the
complete 101-row monthly range from `2015-04` through `2023-08`, and the
wrapper returns the exact 11 fields below in ascending `数据日期` order. The adapter exposes it
only with `MARKET_ACTIVITY` plus explicit `view=account_statistics`; the
requested listing is provenance context, not a row filter.

| Raw upstream item | Phase 3.08 treatment |
| --- | --- |
| `数据日期` | Required strict contiguous `YYYY-MM` monthly observation date; the documented 101-row `2015-04`–`2023-08` range is enforced, and duplicate, descending or invalid dates are rejected. |
| `新增投资者-数量`, `期末投资者-总量`, `期末投资者-A股账户`, `期末投资者-B股账户` | Required finite non-negative investor-account counts; the documented unit is `万户`, and the market-wide counts do not become listing-level shareholders or canonical accounting facts. |
| `新增投资者-环比`, `新增投资者-同比` | Finite numeric-or-null change fields; the documentation does not establish a canonical ratio unit or period interpretation. |
| `沪深总市值` | Required finite non-negative market-wide aggregate; its numeric unit is not documented and it does not become a canonical valuation or cash fact. |
| `沪深户均市值` | Required finite non-negative average market value; the documented unit is `万`, retained as `CNY_10k` context without promoting it to a listing valuation input. |
| `上证指数-收盘`, `上证指数-涨跌幅` | Required finite non-negative index close and finite signed change; numeric units are not documented and neither becomes a listing quote or return fact. |
| upstream mapping | `RPT_STOCK_OPEN_DATA` requests `ALL`, page size 500, descending `STATISTICS_DATE` and no filter; the wrapper source columns are recorded and `STATISTICS_DATE_NY` is the only dropped display field. |
| request `view=account_statistics` | A-share-only market-wide monthly scope with no upstream arguments, `listing_scoped_request=false`, `row_filtering=none`, `entity_rows_selected=false`, exact source order/types/nullability and full row counts for cache replay. |

The provider rejects empty responses, missing/unexpected/reordered fields,
invalid or non-ascending months, non-numeric/boolean/non-finite values, null
required values and negative account/market-cap/index-close aggregates. The
normalizer emits `AKSHARE_ACCOUNT_STATISTICS_RAW_ONLY` and creates no
canonical accounting, shareholder-return, governance, market or valuation
fact: the market-wide history has no listing/entity accounting scope. The
response remains outside the calculation, gate, pipeline, CLI and input-loader
contracts.

## Phase 3.09 A-share Legu market-activity raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_market_legu.py)
document `stock_market_activity_legu()` as a no-argument HTML-backed current
market snapshot. The adapter exposes it only under `MARKET_ACTIVITY` with
explicit `view=market_activity_legu` and an A-share provenance listing. The
wrapper returns exactly 12 ordered rows with the fields `item` and `value`.

| Raw upstream item | Phase 3.09 treatment |
| --- | --- |
| `上涨`, `下跌`, `平盘`, `停牌` | Required finite non-negative market-wide counts; the endpoint does not document their numeric units and they do not become listing-level quote, return or liquidity facts. |
| `涨停`, `真实涨停`, `st st*涨停`, `跌停`, `真实跌停`, `st st*跌停` | Required finite non-negative limit-up/down counts; provider category labels remain raw activity evidence and do not establish a canonical market metric or governance conclusion. |
| `活跃度` | Required non-empty provider text, including the documented percent-style sample; no canonical activity or return ratio is inferred. |
| `统计日期` | Required strict `YYYY-MM-DD HH:MM:SS` provider timestamp binding the current snapshot; it is not an accounting or filing period. |
| request `view=market_activity_legu` | Explicit A-share-only, no-upstream-argument routing; the market-wide response is retained with no row filtering, exact item order, mixed value types and complete row counts for cache replay. |

The provider rejects empty/short/long responses, missing or unexpected fields,
reordered rows, wrong metric labels, non-numeric/boolean/non-finite/negative
numeric values, blank activity text and invalid timestamps. The normalizer
emits `AKSHARE_MARKET_ACTIVITY_LEGU_RAW_ONLY` and creates no canonical market,
return, governance, valuation or accounting fact. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.10 A-share Legu congestion raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_congestion_lg.py)
document `stock_a_congestion_lg()` as a no-argument token-backed JSON history
covering the latest four years. The adapter exposes it only under
`MARKET_ACTIVITY` with explicit `view=congestion` and an A-share provenance
listing. The wrapper returns exact `date`, `close` and `congestion` fields in
ascending date order.

| Raw upstream item | Phase 3.10 treatment |
| --- | --- |
| `date` | Required strict `YYYY-MM-DD` observation date; dates must be strictly ascending and represent the provider's rolling latest-four-year history, not an accounting or filing period. |
| `close` | Required finite non-negative index-close context; the endpoint does not document a canonical unit and the value is not promoted to a listing quote, return or valuation input. |
| `congestion` | Required finite non-negative provider-defined congestion value; its unit and economic interpretation remain undocumented, and it is not promoted to a canonical market or return metric. |
| request `view=congestion` | Explicit A-share-only, no-user-parameter routing; token/cookie-CSRF transport, source/API URIs, exact field order, no filtering and complete market-wide row counts remain part of cache replay. |

The provider rejects empty responses, missing/unexpected/reordered fields,
invalid or non-ascending dates, null/non-numeric/boolean/non-finite values and
negative numeric values. The normalizer emits
`AKSHARE_MARKET_CONGESTION_RAW_ONLY` and creates no canonical market, return,
governance, valuation or accounting fact. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.11 A-share Legu equity-bond-spread raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ebs_lg.py)
document `stock_ebs_lg()` as a no-argument token-backed JSON history with all
available observations. The adapter exposes it only under `MARKET_ACTIVITY`
with explicit `view=equity_bond_spread` and an A-share provenance listing. The
wrapper returns four exact fields in ascending date order.

| Raw upstream item | Phase 3.11 treatment |
| --- | --- |
| `日期` | Required strict `YYYY-MM-DD` observation date in the provider's all-history response; it is not an accounting, filing or listing period. |
| `沪深300指数` | Required finite non-negative CSI 300 index-close context; no unit is documented and it is not promoted to a listing quote, return or valuation input. |
| `股债利差`, `股债利差均线` | Required finite signed provider-defined spread and moving-average values; no unit or canonical equity/bond interpretation is inferred. |
| request `view=equity_bond_spread` | Explicit A-share-only, no-user-parameter routing with fixed upstream `code=000300.SH`; token/cookie-CSRF transport, source/API URIs, exact field order, no filtering and complete market-wide row counts remain part of cache replay. |

The provider rejects empty responses, missing/unexpected/reordered fields,
invalid or non-ascending dates, null/non-numeric/boolean/non-finite values and
negative CSI 300 index values. The normalizer emits
`AKSHARE_EQUITY_BOND_SPREAD_RAW_ONLY` and creates no canonical market, return,
valuation, governance or accounting fact. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.12 A-share Legu Buffett-index raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_buffett_index_lg.py)
document `stock_buffett_index_lg()` as a no-argument token-backed JSON history
with four documented output fields. The adapter exposes it only under
`MARKET_ACTIVITY` with explicit `view=buffett_index` and an A-share provenance
listing. The wrapper's two named percentile extensions are accepted in their
documented optional order when the upstream API supplies them; they remain raw
and no percentile unit or interpretation is inferred.

| Raw upstream item | Phase 3.12 treatment |
| --- | --- |
| `日期` | Required strict `YYYY-MM-DD` observation date in the all-history response; it is not an accounting, filing or listing period. |
| `收盘价` | Required finite non-negative index-close context; the endpoint does not document a canonical unit and it is not promoted to a listing quote, return or valuation input. |
| `总市值` | Required finite non-negative market-capitalization context. The documentation describes the A-share close times issued A+B+H share capital but does not provide a numeric unit; no issuer market-cap or valuation fact is inferred. |
| `GDP` | Required finite non-negative prior-year domestic-GDP context; no numeric unit or issuer accounting fact is inferred. |
| `近十年分位数`, `总历史分位数` | Optional finite numeric wrapper extensions, accepted only together in the official extended field order when present; no percentile scale or valuation interpretation is inferred. |
| request `view=buffett_index` | Explicit A-share-only, no-user-parameter routing; token/cookie-CSRF transport, source/API URIs, observed field variant/order, no filtering and complete market-wide row counts remain part of cache replay. |

The provider rejects empty responses, missing/unexpected/reordered fields,
invalid or non-ascending dates, null required values, non-numeric/boolean/
non-finite values and negative base values. Optional percentile fields may be
null because the official wrapper coerces optional output columns. The
normalizer emits `AKSHARE_BUFFETT_INDEX_RAW_ONLY` and creates no canonical
market, return, valuation, governance or accounting fact. The response remains
outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.13 A-share Legu TTM/LYR PE raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ttm_lyr.py)
document `stock_a_ttm_lyr()` as a no-argument token-backed JSON history for
the all-A-share TTM/LYR price-earnings context. The adapter exposes it only
under `MARKET_ACTIVITY` with explicit `view=ttm_lyr` and an A-share provenance
listing. The wrapper returns the exact 14 fields below in this order; no
numeric units or percentile scale are documented, so none is inferred.

| Raw upstream item | Phase 3.13 treatment |
| --- | --- |
| `date` | Required strict `YYYY-MM-DD` observation date for the market-wide history; it is not an accounting, filing or listing period. |
| `middlePETTM`, `averagePETTM`, `middlePELYR`, `averagePELYR` | Required finite signed TTM/LYR PE aggregates; signed values are retained as raw evidence and are not promoted to a listing valuation fact. |
| `quantileInAllHistoryMiddlePeTtm`, `quantileInRecent10YearsMiddlePeTtm`, `quantileInAllHistoryAveragePeTtm`, `quantileInRecent10YearsAveragePeTtm`, `quantileInAllHistoryMiddlePeLyr`, `quantileInRecent10YearsMiddlePeLyr`, `quantileInAllHistoryAveragePeLyr`, `quantileInRecent10YearsAveragePeLyr` | Required finite percentile-context values; the endpoint does not document a numeric unit or scale, and no percentile interpretation is inferred. |
| `close` | Required finite non-negative CSI 300/index-close context; the endpoint does not document a canonical unit and it is not promoted to a listing quote, return or valuation input. |
| request `view=ttm_lyr` | Explicit A-share-only, no-user-parameter routing; token/cookie-CSRF transport, fixed upstream `marketId=5`, source/API URIs, exact field order, no filtering and complete row counts remain part of cache replay. |

The provider rejects empty responses, missing/unexpected/reordered fields,
invalid or non-ascending dates, null required values, non-numeric/boolean/
non-finite values and negative `close` values. Signed PE and percentile fields
are deliberately accepted because the upstream contract does not establish a
non-negative domain for them. The normalizer emits
`AKSHARE_A_TTM_LYR_RAW_ONLY` and creates no canonical market, return,
valuation, governance or accounting fact. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.14 A-share Legu all-PB raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_all_pb.py)
document `stock_a_all_pb()` as a no-argument token-backed JSON history for the
all-A-share median and equal-weight-average price-to-book context. The adapter
exposes it only under `MARKET_ACTIVITY` with explicit `view=all_pb` and an
A-share provenance listing. The wrapper drops the upstream
`weightingAveragePB` field and returns the exact eight fields below in this
order; no numeric units or percentile scale are documented, so none is
inferred.

| Raw upstream item | Phase 3.14 treatment |
| --- | --- |
| `date` | Required strict `YYYY-MM-DD` observation date for the market-wide history; it is not an accounting, filing or listing period. |
| `middlePB`, `equalWeightAveragePB` | Required finite signed PB aggregates; signed values are retained as raw evidence and are not promoted to a listing valuation fact. |
| `close` | Required finite non-negative Shanghai-index close context; the endpoint does not document a canonical unit and it is not promoted to a listing quote, return or valuation input. |
| `quantileInAllHistoryMiddlePB`, `quantileInRecent10YearsMiddlePB`, `quantileInAllHistoryEqualWeightAveragePB`, `quantileInRecent10YearsEqualWeightAveragePB` | Required finite percentile-context values; the endpoint does not document a numeric unit or scale, and no percentile interpretation is inferred. |
| request `view=all_pb` | Explicit A-share-only, no-user-parameter routing; token/cookie-CSRF transport, fixed upstream `marketId=ALL`, wrapper-dropped `weightingAveragePB`, source/API URIs, exact output field order, no filtering and complete row counts remain part of cache replay. |

The provider rejects empty responses, missing/unexpected/reordered fields,
invalid or non-ascending dates, null required values, non-numeric/boolean/
non-finite values and negative `close` values. Signed PB and percentile fields
are deliberately accepted because the upstream contract does not establish a
non-negative domain for them. The normalizer emits
`AKSHARE_A_ALL_PB_RAW_ONLY` and creates no canonical market, return, valuation,
governance or accounting fact. The response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 3.15 A-share Legu market PE raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_market_pe_lg` as a symbol-selected Legu market history. The
adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=market_pe`, a required A-share provenance listing and one of the four
documented symbols. The three standard-board symbols share the
`market-pe` JSON API and return `日期`, `指数`, `平均市盈率`; `科创版` uses
the dedicated `get-ke-chuang-ban-pe` JSON API and returns `日期`, `总市值`,
`市盈率`. No numeric unit or PE domain is documented, so none is inferred.

| Raw upstream item | Phase 3.15 treatment |
| --- | --- |
| `日期` | Required strict `YYYY-MM-DD` observation date for the complete market history; it is not an accounting, filing or listing period. |
| `指数`, `平均市盈率` | Required finite numeric values for `上证`, `深证` and `创业板`; the index value must be non-negative, while signed PE values remain raw context. |
| `总市值`, `市盈率` | Required finite numeric values for `科创版`; market capitalization must be non-negative, while signed PE values remain raw context. |
| request `view=market_pe`, `symbol` | Explicit A-share-only routing. `上证`/`深证`/`创业板` use `https://legulegu.com/api/stock-data/market-pe` with fixed `marketId=1`/`2`/`4`; `科创版` uses `https://legulegu.com/api/stockdata/get-ke-chuang-ban-pe` without a fixed market ID. Symbol-specific source pages, exact variant field order, token/cookie-CSRF transport, no filtering and complete row counts remain part of cache replay. |

The provider rejects unsupported symbols, empty responses,
missing/unexpected/reordered fields, invalid or non-ascending dates,
null/non-numeric/boolean/non-finite values and negative index or market-capitalization
values. The normalizer emits `AKSHARE_MARKET_PE_RAW_ONLY` and creates no
canonical market, return, valuation, governance or accounting fact. The
response remains outside the calculation, gate, pipeline, CLI and input-loader
contracts.

## Phase 3.16 A-share Legu market PB raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_market_pb_lg` as a symbol-selected Legu market history. The
adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=market_pb`, a required A-share provenance listing and one of `上证`,
`深证`, `创业板` or `科创版`. All variants return the exact five fields below;
no numeric unit or PB domain is documented, so none is inferred.

| Raw upstream item | Phase 3.16 treatment |
| --- | --- |
| `日期` | Required strict `YYYY-MM-DD` observation date for the complete market history; it is not an accounting, filing or listing period. |
| `指数` | Required finite non-negative index value; it is context for the selected market and is not promoted to a listing quote or return fact. |
| `市净率`, `等权市净率`, `市净率中位数` | Required finite numeric PB aggregates; signed values remain raw context because the upstream contract does not document a non-negative domain or unit. |
| request `view=market_pb`, `symbol` | Explicit A-share-only routing. All four symbols use `https://legulegu.com/api/stockdata/index-basic-pb` with fixed `indexCode=1`/`2`/`4`/`7` for 上证/深证/创业板/科创版. Symbol-specific source pages, exact field order, token/cookie-CSRF transport, no filtering and complete row counts remain part of cache replay. |

The provider rejects unsupported symbols, empty responses,
missing/unexpected/reordered fields, invalid or non-ascending dates,
null/non-numeric/boolean/non-finite values and negative index values. The
normalizer emits `AKSHARE_MARKET_PB_RAW_ONLY` and creates no canonical market,
return, valuation, governance or accounting fact. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.17 A-share Legu index PE raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_index_pe_lg` as a symbol-selected Legu index history. The
adapter exposes it only under `MARKET_ACTIVITY` with explicit `view=index_pe`,
a required A-share provenance listing and one of the 12 documented index
symbols. All variants use the `index-basic-pe` JSON API and return the exact
eight fields below; no numeric unit or PE domain is documented, so none is
inferred.

| Raw upstream item | Phase 3.17 treatment |
| --- | --- |
| `日期` | Required strict `YYYY-MM-DD` observation date for the complete index history; it is not an accounting, filing or listing period. |
| `指数` | Required finite non-negative index value; it is context for the selected index and is not promoted to a listing quote or return fact. |
| `等权静态市盈率`, `静态市盈率`, `静态市盈率中位数`, `等权滚动市盈率`, `滚动市盈率`, `滚动市盈率中位数` | Required finite PE aggregates; signed values remain raw context because the upstream contract does not document a non-negative domain or unit. |
| request `view=index_pe`, `symbol` | Explicit A-share-only routing. All 12 symbols use `https://legulegu.com/api/stockdata/index-basic-pe` with fixed `indexCode` values from the official mapping (`000016.SH`, `000300.SH`, `000009.SH`, `399673.SZ`, `000905.SH`, `000010.SH`, `399324.SZ`, `399330.SZ`, `000852.SH`, `000015.SH`, `000903.SH`, `000906.SH`). The source page, exact field order, token/cookie-CSRF transport, no filtering and complete row counts remain part of cache replay. |

The provider rejects unsupported symbols, empty responses,
missing/unexpected/reordered fields, invalid or non-ascending dates,
null/non-numeric/boolean/non-finite values and negative index values. The
normalizer emits `AKSHARE_INDEX_PE_RAW_ONLY` and creates no canonical market,
return, valuation, governance or accounting fact. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.18 A-share Legu index PB raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_a_pe_and_pb.py)
document `stock_index_pb_lg` as a symbol-selected Legu index history. The
adapter exposes it only under `MARKET_ACTIVITY` with explicit `view=index_pb`,
a required A-share provenance listing and one of the same 12 documented index
symbols as the index-PE view. All variants use the `index-basic-pb` JSON API
and return the exact five fields below; no numeric unit or PB domain is
documented, so none is inferred.

| Raw upstream item | Phase 3.18 treatment |
| --- | --- |
| `日期` | Required strict `YYYY-MM-DD` observation date for the complete index history; it is not an accounting, filing or listing period. |
| `指数` | Required finite non-negative index value; it is context for the selected index and is not promoted to a listing quote or return fact. |
| `市净率`, `等权市净率`, `市净率中位数` | Required finite numeric PB aggregates; signed values remain raw context because the upstream contract does not document a non-negative domain or unit. |
| request `view=index_pb`, `symbol` | Explicit A-share-only routing. All 12 symbols use `https://legulegu.com/api/stockdata/index-basic-pb` with fixed `indexCode` values from the official mapping (`000016.SH`, `000300.SH`, `000009.SH`, `399673.SZ`, `000905.SH`, `000010.SH`, `399324.SZ`, `399330.SZ`, `000852.SH`, `000015.SH`, `000903.SH`, `000906.SH`). The documented source page is `https://legulegu.com/stockdata/sz50-pb`; the current wrapper CSRF transport page is `https://legulegu.com/stockdata/zz500-ttm-lyr`. Exact field order, token/cookie-CSRF transport, no filtering and complete row counts remain part of cache replay. |

The provider rejects unsupported symbols, empty responses,
missing/unexpected/reordered fields, invalid or non-ascending dates,
null/non-numeric/boolean/non-finite values and negative index values. The
normalizer emits `AKSHARE_INDEX_PB_RAW_ONLY` and creates no canonical market,
return, valuation, governance or accounting fact. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.19 A-share Baidu valuation raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_zh_valuation_baidu.py)
document `stock_zh_valuation_baidu` as a listing-scoped historical valuation
series. The adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=valuation_baidu`; the requested A-share listing supplies the six-digit
upstream `symbol`, while `indicator` and `period` must use the documented
choices. The wrapper returns exactly `date` and `value`; the upstream contract
does not document a numeric unit or a universal non-negative domain.

| Raw upstream item | Phase 3.19 treatment |
| --- | --- |
| `date` | Required strict `YYYY-MM-DD` observation date for the requested indicator/period history; it is not treated as a filing or accounting period. |
| `value` | Required finite numeric value retained as provider-defined valuation context; signed values are accepted because no universal domain is documented and no unit is inferred. |
| request `view=valuation_baidu`, `indicator`, `period` | Explicit A-share-only listing-scoped routing. `indicator` is one of `总市值`, `市盈率(TTM)`, `市盈率(静)`, `市净率` or `市现率`; `period` is one of `近一年`, `近三年`, `近五年`, `近十年` or `全部`. The Baidu `https://gushitong.baidu.com/opendata` JSON request freezes the official fixed parameters and derives `query`, `code`, `tag` and `chart_select` from the request. Exact field order, upstream row counts, selected indicator/period and observed date bounds remain part of cache replay. |

The provider rejects unsupported choices, empty responses,
missing/unexpected/reordered fields, invalid or non-ascending dates and
null/non-numeric/boolean/non-finite values. The normalizer emits
`AKSHARE_BAIDU_VALUATION_RAW_ONLY` and creates no canonical valuation, market,
return, governance or accounting fact: the provider-defined series is raw
evidence only until its period, units and accounting scope are reconciled.
The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts.

## Phase 3.20 H-share Baidu valuation raw history

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hk_valuation_baidu.py)
document `stock_hk_valuation_baidu` as a listing-scoped historical valuation
series. The adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=valuation_baidu_hk`; the requested H-share listing supplies the five-digit
upstream `symbol`, while `indicator` and `period` must use the documented
choices. The wrapper returns exactly `date` and `value`; the upstream contract
does not document a numeric unit or a universal non-negative domain.

| Raw upstream item | Phase 3.20 treatment |
| --- | --- |
| `date` | Required strict `YYYY-MM-DD` observation date for the requested indicator/period history; it is not treated as a filing or accounting period. |
| `value` | Required finite numeric value retained as provider-defined H-share valuation context; signed values are accepted because no universal domain is documented and no unit is inferred. |
| request `view=valuation_baidu_hk`, `indicator`, `period` | Explicit H-share-only listing-scoped routing. `indicator` is one of `总市值`, `市盈率(TTM)`, `市盈率(静)`, `市净率` or `市现率`; `period` is one of `近一年`, `近三年` or `全部`. The Baidu `https://finance.baidu.com/opendata` JSON request freezes the official fixed parameters including `market=hk` and derives `query`, `code`, `tag` and `chart_select` from the request. Exact field order, upstream row counts, selected indicator/period and observed date bounds remain part of cache replay. |

The provider rejects unsupported choices, empty responses,
missing/unexpected/reordered fields, invalid or non-ascending dates and
null/non-numeric/boolean/non-finite values. The normalizer emits
`AKSHARE_HK_BAIDU_VALUATION_RAW_ONLY` and creates no canonical valuation,
market, return, governance or accounting fact: the provider-defined series is
raw evidence only until its period, units and accounting scope are reconciled.
The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts.

## Phase 3.21 A-share Eastmoney valuation-comparison raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
document `stock_zh_valuation_comparison_em` as a single-symbol industry
valuation-comparison table. The adapter exposes it only under
`MARKET_ACTIVITY` with explicit `view=valuation_comparison`; an A-share listing
is converted to the exchange-prefixed six-digit upstream `symbol` expected by
the wrapper. The current implementation selects 20 output fields and does not
select the separately listed `市盈率-24A` field.

| Raw upstream item | Phase 3.21 treatment |
| --- | --- |
| `排名`, `代码`, `简称` | Required wrapper text fields; the first row is the requested listing, the next two are `行业平均`/`行业中值` summary rows, and remaining rows are ranked peers. |
| `PEG`, PE/PS/PB/cash-flow multiple fields, `EV/EBITDA-24A` | Nullable finite numeric provider-defined comparison values; signed values are preserved and no unit or universal non-negative domain is inferred. |
| request `view=valuation_comparison` | Explicit A-share-only listing-scoped routing. The Eastmoney JSON request freezes `RPT_PCF10_INDUSTRY_CVALUE`, `columns=ALL`, `sortColumns=PAIMING`, `source=HSF10` and `client=PC`, while deriving `filter=(SECUCODE="<code>.<exchange>")` from the requested listing. Exact wrapper field order, row roles, peer ranks, upstream fields and replay metadata remain part of the raw contract. |

The provider rejects unsupported views/parameters, non-A listings, missing or
unexpected/reordered fields, malformed target/summary/peer rows, duplicate or
non-ascending peer ranks and non-finite/non-numeric values. The normalizer
emits `AKSHARE_VALUATION_COMPARISON_RAW_ONLY` and creates no canonical
valuation, market, return, governance or accounting fact: the peer table is
raw evidence only until its provider-defined scope, periods and units are
reconciled. The response remains outside the calculation, gate, pipeline, CLI
and input-loader contracts.

## Phase 3.22 H-share Eastmoney valuation-comparison raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_comparison_em.py)
document `stock_hk_valuation_comparison_em` as a single-symbol industry
valuation-comparison row. The adapter exposes it only under
`MARKET_ACTIVITY` with explicit `view=valuation_comparison_hk`; an H-share
listing is converted to the unprefixed five-digit upstream `symbol` expected
by the wrapper.

| Raw upstream item | Phase 3.22 treatment |
| --- | --- |
| `代码`, `简称` | Required wrapper text fields; `代码` must match the requested H-share listing and the wrapper returns one row. |
| Eight valuation multiples | Nullable finite numeric provider-defined values; signed values are preserved and no unit or universal non-negative domain is inferred. |
| Eight `*排名` fields | Required positive integer provider ranks; they remain raw comparison metadata and are not converted into a canonical score. |
| request `view=valuation_comparison_hk` | Explicit H-share-only listing-scoped routing. The Eastmoney JSON request freezes `RPT_PCF10_INDUSTRY_HKCVALUE`, the explicit official column list, `pageNumber=1`, `source=F10`, `client=PC` and the dual listing filter `(SECUCODE="<code>.HK")(CORRE_SECUCODE="<code>.HK")`. Exact field order, one-row scope, upstream fields and replay metadata remain part of the raw contract. |

The provider rejects unsupported views/parameters, non-H listings,
missing/unexpected/reordered fields, wrong listing identity, null/non-integer
ranks and non-finite/non-numeric multiples. The normalizer emits
`AKSHARE_HK_VALUATION_COMPARISON_RAW_ONLY` and creates no canonical valuation,
market, return, governance or accounting fact: the row is raw evidence only
until its provider-defined periods, units and accounting scope are reconciled.
The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts.

## Phase 3.23 A-share Eastmoney growth-comparison raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
document `stock_zh_growth_comparison_em` as a single-symbol industry growth
table. The adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=growth_comparison`; an A-share listing is converted to the
exchange-prefixed six-digit upstream `symbol` expected by the wrapper.

| Raw upstream item | Phase 3.23 treatment |
| --- | --- |
| `代码`, `简称` | Required wrapper text fields; the first two rows are `行业平均` and `行业中值`, and the final row must match the requested A-share listing. |
| 18 growth-rate fields | Nullable finite numeric provider-defined growth values; signed values are preserved and no unit or universal non-negative domain is inferred. |
| `基本每股收益增长率-3年复合排名` | Nullable for the two industry summaries and a positive integer-valued provider rank for peers and the target; it remains raw comparison metadata. |
| request `view=growth_comparison` | Explicit A-share-only listing-scoped routing. The Eastmoney JSON request freezes `RPT_PCF10_INDUSTRY_GROWTH`, `columns=ALL`, `sortTypes=1`, `sortColumns=PAIMING`, `source=HSF10`, `client=PC` and the wrapper's version parameter, while deriving `filter=(SECUCODE="<code>.<exchange>")` from the requested listing. Exact field order, row roles, rank order, upstream fields and replay metadata remain part of the raw contract. |

The provider rejects unsupported views/parameters, non-A listings,
missing/unexpected/reordered fields, malformed summary/peer/target rows,
duplicate or non-ascending peer ranks and non-finite/non-numeric values. The
normalizer emits `AKSHARE_GROWTH_COMPARISON_RAW_ONLY` and creates no canonical
growth, valuation, market, return, governance or accounting fact: the table is
raw evidence only until its provider-defined periods, units and accounting
scope are reconciled. The response remains outside the calculation, gate,
pipeline, CLI and input-loader contracts.

## Phase 3.24 H-share Eastmoney growth-comparison raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_comparison_em.py)
document `stock_hk_growth_comparison_em` as a single-symbol industry growth
row. The adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=growth_comparison_hk`; an H-share listing is converted to the unprefixed
five-digit upstream `symbol` expected by the wrapper.

| Raw upstream item | Phase 3.24 treatment |
| --- | --- |
| `代码`, `简称` | Required wrapper text fields; `代码` must match the requested H-share listing and the wrapper returns exactly one row. |
| Four growth-rate fields | Nullable finite numeric provider-defined growth values; signed values are preserved and no unit or universal non-negative domain is inferred. The mapped total-asset label is retained exactly as `基本每股收总资产同比增长率益同比增长率`. |
| Four `*排名` fields | Required positive integer provider ranks; each rank is retained as raw comparison metadata and is not converted into a canonical score. |
| request `view=growth_comparison_hk` | Explicit H-share-only listing-scoped routing. The Eastmoney JSON request freezes `RPT_PCF10_INDUSTRY_HKGROWTH`, the explicit current-wrapper column list, `pageNumber=1`, `source=F10`, `client=PC`, the current wrapper `v` parameter and the dual listing filter `(SECUCODE="<code>.HK")(CORRE_SECUCODE="<code>.HK")`. Exact field order, one-row scope, upstream fields, dropped fields and replay metadata remain part of the raw contract. |

The provider rejects unsupported views/parameters, non-H listings,
missing/unexpected/reordered fields, wrong listing identity, null/non-integer
ranks and non-finite/non-numeric growth values. The normalizer emits
`AKSHARE_HK_GROWTH_COMPARISON_RAW_ONLY` and creates no canonical growth,
valuation, market, return, governance or accounting fact: the row is raw
evidence only until its provider-defined periods, units and accounting scope
are reconciled. The response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 3.25 A-share Eastmoney DuPont-comparison raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
document `stock_zh_dupont_comparison_em` as a full listing-scoped DuPont
comparison table. The adapter exposes it only under `MARKET_ACTIVITY` with
explicit `view=dupont_comparison`; an A-share listing is converted to the
exchange-prefixed six-digit upstream `symbol` expected by the wrapper.

| Raw upstream item | Phase 3.25 treatment |
| --- | --- |
| `代码`, `简称` | Required wrapper text fields. The first two rows are the current source order `行业中值` and `行业平均`; ranked rows use six-digit comparison codes and exactly one row must match the requested A-share listing. |
| 16 DuPont metric fields | Nullable finite numeric provider-defined values covering `ROE`, `净利率`, `总资产周转率` and `权益乘数` for the documented three-year average and 22A/23A/24A labels. Values are preserved as signed where supplied; no unit or accounting-scope inference is made. |
| `ROE-3年平均排名` | Nullable on the two industry summaries and a positive integer-valued provider rank on ranked comparison rows; it remains raw comparison metadata. |
| request `view=dupont_comparison` | Explicit A-share-only listing-scoped routing. The Eastmoney JSON request freezes `RPT_PCF10_INDUSTRY_DBFX`, `columns=ALL`, `sortTypes=1`, `sortColumns=PAIMING`, `source=HSF10`, `client=PC`, the current wrapper `v` parameter and `filter=(SECUCODE="<code>.<exchange>")`. Exact field order, row roles, rank order, upstream fields, dropped fields and replay metadata remain part of the raw contract. |

The provider rejects unsupported views/parameters, non-A listings,
missing/unexpected/reordered fields, malformed summary/target/peer rows,
duplicate or non-ascending ranks and non-finite/non-numeric values. The
normalizer emits `AKSHARE_DUPONT_COMPARISON_RAW_ONLY` and creates no canonical
profitability, growth, valuation, market, return, governance or accounting fact:
the table is raw evidence only until its provider-defined periods, units and
accounting scope are reconciled. The response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 3.26 A-share Eastmoney company-scale comparison raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_comparison_em.py)
document `stock_zh_scale_comparison_em` as a listing-scoped company-scale
comparison row. The adapter exposes it only under `MARKET_ACTIVITY` with
explicit `view=scale_comparison`; an A-share listing is converted to the
exchange-prefixed six-digit upstream `symbol` expected by the wrapper.

| Raw upstream item | Phase 3.26 treatment |
| --- | --- |
| `代码`, `简称` | Required wrapper text fields; the returned six-digit `代码` must match the requested A-share listing and exactly one row is retained. |
| `总市值`, `流通市值`, `营业收入`, `净利润` | Nullable finite numeric company-scale values; the provider-defined units and periods are not documented sufficiently for canonical market, valuation or accounting facts, and signed values are preserved. |
| `总市值排名`, `流通市值排名`, `营业收入排名`, `净利润排名` | Required positive integer provider ranks; each remains raw comparison metadata and is not converted into a canonical score. |
| request `view=scale_comparison` | Explicit A-share-only listing-scoped routing. The Eastmoney JSON request freezes `RPT_PCF10_INDUSTRY_MARKET`, the official 17-column list, the dual listing filter (SECUCODE="<code>.<exchange>")(CORRE_SECUCODE="<code>.<exchange>"), `pageNumber=1`, `pageSize=5`, `sortTypes=-1`, `sortColumns=TOTAL_CAP`, `source=HSF10`, `client=PC` and the wrapper version parameter. Exact field order, one-row scope, upstream fields, dropped fields and replay metadata remain part of the raw contract. |

The provider rejects unsupported views/parameters, non-A listings,
missing/unexpected/reordered fields, wrong listing identity, non-finite or
non-numeric metrics and non-positive/non-integer ranks. The normalizer emits
`AKSHARE_SCALE_COMPARISON_RAW_ONLY` and creates no canonical market, valuation
or accounting fact: the row is raw evidence only until its provider-defined
units, periods and economic scope are reconciled. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.27 A-share CDR daily-history raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py)
document `stock_zh_a_cdr_daily` as a Sina CDR daily-history endpoint. The
adapter exposes it under `MARKET_HISTORY` with explicit `view=cdr_daily`,
derives the exchange-prefixed upstream symbol and applies the requested
inclusive date range after the full encrypted-JavaScript history response.

| Raw upstream item | Phase 3.27 treatment |
| --- | --- |
| `date` | Required ISO trading date; rows must be within the requested inclusive range and strictly ascending. |
| `open`, `high`, `low`, `close` | Required finite numeric daily prices; the upstream documentation does not establish a canonical unit or adjustment basis. |
| `volume` | Required finite numeric volume retained with the documented unit `lots` (手); it is not converted into the canonical daily-history share unit. |
| request `view=cdr_daily`, `start_date`, `end_date` | Explicit A-share CDR listing-scoped routing. The adapter freezes the Sina source page, symbol-derived encrypted-JavaScript URL, `hk_js_decode` decoder, inclusive wrapper date slicing, field order, row counts and replay metadata. |

The provider rejects unsupported views/parameters, non-A listings,
missing/unexpected/reordered fields, invalid or out-of-range dates,
non-ascending or duplicate dates, non-finite/non-numeric values and reversed
date ranges. The normalizer emits
`AKSHARE_CDR_DAILY_HISTORY_RAW_ONLY` and creates no canonical daily
market-history, return, valuation or accounting fact: the response remains raw
evidence until its CDR-specific adjustment, calendar and economic scope are
reconciled. The response remains outside the calculation, gate, pipeline, CLI
and input-loader contracts.

## Phase 3.28 H-share famous-stock quote raw snapshot

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_famous.py)
document `stock_hk_famous_spot_em` as a no-argument Eastmoney famous-stock
universe quote. The adapter exposes it under `MARKET_QUOTE` with explicit
`view=hk_famous`, validates the complete upstream universe before filtering by
the requested five-digit H-share code, and retains the official fixed query
metadata.

| Raw upstream item | Phase 3.28 treatment |
| --- | --- |
| `序号` | Required positive integer assigned by the wrapper; values must be strictly ascending in the returned universe. |
| `代码`, `名称` | Required five-digit H-share code and non-empty name; every upstream row is validated before provider-side selection. |
| `最新价`, `涨跌额`, `今开`, `最高`, `最低`, `昨收` | Nullable finite numeric quote fields retained in HKD per share; no canonical current-price fact is inferred. |
| `涨跌幅` | Nullable finite numeric change percentage retained in percent units. |
| `成交量`, `成交额` | Nullable finite numeric volume and turnover retained in shares and HKD, respectively. |
| request `view=hk_famous` | Explicit H-share-only no-argument routing. The provider freezes `https://69.push2.eastmoney.com/api/qt/clist/get`, `b:DLMK0106`, the documented field selector, page size `50000`, ordering parameters, full/selected row counts and the `hk_wellknown` source page in replay metadata. |

The provider rejects unsupported views/parameters, non-H listings,
missing/unexpected/reordered fields, invalid codes, duplicate or non-ascending
sequence numbers, empty names and non-finite/non-numeric values. The normalizer
emits `AKSHARE_HK_FAMOUS_QUOTE_RAW_ONLY` and creates no canonical current-price,
return, valuation or accounting fact: the official 15-minute-delayed current-day
snapshot has no stable observation timestamp. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.92 SSE daily-deal overview raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sse_deal_daily` as an SSE requested-trading-day market
overview. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_summary.py)
accepts `date=YYYYMMDD` (supported from `20211227`) and returns the final six
fields `单日情况`, `股票`, `主板A`, `主板B`, `科创板` and `股票回购`. Its eight
metric rows are explicitly ordered as `挂牌数`, `市价总值`, `流通市值`,
`成交金额`, `成交量`, `平均市盈率`, `换手率` and `流通换手率`.

The provider exposes this endpoint under `MARKET_ACTIVITY` only with explicit
`view=sse_deal_daily`, passes only the date to the no-symbol upstream call and
validates the complete market-level response before retention. It records the
requested date, SSE market scope, exact field/metric order, the absence of
documented numeric units and non-listing row counts for cache replay. The
normalizer emits `AKSHARE_SSE_DEAL_DAILY_RAW_ONLY`; no canonical quote,
accounting, return, governance, valuation or market fact is admitted from an
exchange-wide aggregate.

| Raw upstream item | Phase 2.92 treatment |
| --- | --- |
| `单日情况` | Required metric label in the official eight-row order; it is not a report period or listing identity. |
| `股票`, `主板A`, `主板B`, `科创板`, `股票回购` | Finite numeric-or-null market/board aggregates; the endpoint does not document numeric units, and no listing-level quote, turnover, valuation or issuer cash-flow fact is inferred. |
| request `view=sse_deal_daily`, `date` | Explicit requested-day SSE market-overview scope; `listing_scoped_request=false`, no provider filtering, source URI, field/metric order and row counts remain part of the cache replay boundary. |

The provider-specific response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 2.63 A-share Eastmoney dividend-distribution detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_fhps_detail_em` as a symbol-scoped Eastmoney A-share
dividend-distribution detail endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_fhps_em.py)
accepts a six-digit `symbol` and returns the exact 19 fields `报告期`,
`业绩披露日期`, the distribution and cash-ratio fields, per-share indicators,
`总股本`, and the announcement/record/ex-rights/progress dates.

The provider selects this endpoint only under `DIVIDENDS` with explicit
`view=event_detail`, passes the unprefixed A-share code, validates the exact
field set, strictly ascending report periods, valid optional dates, finite
numeric/null values, non-negative integer share counts and string/null text
fields, and records the symbol-scoped historical-detail request for replay.
The normalizer emits `AKSHARE_A_DIVIDEND_DETAIL_RAW_ONLY`; no canonical dividend
cash or payout denominator is admitted because provider ratios, event plans,
per-share indicators and total-share context do not establish settled ordinary
cash with the accepted entity, unit and period semantics.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `报告期`, `业绩披露日期` | Required/validated report and disclosure dates; retained as raw historical context, not treated as a settled cash period. |
| `送转股份-*`, `现金分红-*` | Raw distribution ratios, description and yield context; no canonical ordinary-dividend cash or payout ratio is inferred. |
| `每股收益`, `每股净资产`, `每股公积金`, `每股未分配利润`, `净利润同比增长` | Raw per-share/ratio indicators; they do not replace the canonical income or equity facts. |
| `总股本` | Validated non-negative integer raw share-count context; its economic/diluted scope is not admitted as a canonical share fact. |
| `预案公告日`, `股权登记日`, `除权除息日`, `最新公告日期`, `方案进度` | Raw event/progress context; dates and status do not prove settlement or filing-backed classification. |
| request `view=event_detail`, unprefixed A-share `symbol` | Explicit endpoint, listing and historical-detail replay scope; the complete symbol-scoped response remains opaque. |

The provider-specific dividend-distribution detail response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts. Its raw evidence is
available for later review without being treated as a canonical dividend-cash,
payout, share-count, income or valuation input.

## Phase 2.64 A-share CNINFO IPO-summary raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_ipo_summary_cninfo` as a symbol-scoped CNINFO A-share
listing/IPO-summary endpoint. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_ipo_summary_cninfo.py)
accepts a six-digit `symbol`, reads the first returned record and exposes the
15 documented fields below.

The provider selects this callable only under the existing
`CORPORATE_ACTIONS` category with explicit `view=ipo_summary`, passes the
unprefixed requested A-share code, requires exactly one response row and
validates its exact field set, listing identity, optional dates, finite numeric
values and string/null underwriter field before storing raw evidence. It records
the view, symbol, row counts, historical IPO-summary scope and row-date binding
for replay. The normalizer emits `AKSHARE_IPO_SUMMARY_RAW_ONLY`, marks
`share_issuance_cash` as critically missing and creates no canonical issuance,
dilution or share fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码` | Required six-digit A-share identity; it must match the requested listing and is not a new canonical entity fact. |
| `招股公告日期`, `中签率公告日`, `上网发行日期`, `上市日期` | Validated date-or-null fields; historical offering/listing context only, not a settled issuance-cash period or canonical listing-date fact. |
| `每股面值`, `总发行数量`, `发行前每股净资产`, `摊薄发行市盈率`, `募集资金净额`, `发行价格`, `发行费用总额`, `发行后每股净资产`, `上网发行中签率` | Validated finite numeric-or-null fields; provider scale and economic basis remain raw because the response does not establish the accepted unit, settlement period or diluted-share scope. |
| `主承销商` | Validated string-or-null issuer/underwriter context; no governance, issuance or valuation fact is inferred. |
| request `view=ipo_summary`, unprefixed A-share `symbol` | Explicit endpoint, A-share listing and historical row-date replay scope. |

The provider-specific IPO-summary response remains outside the calculation, gate,
pipeline, CLI and input-loader contracts. Its raw evidence is available for
later review without being treated as canonical issuance cash, dilution,
share-count, listing-date, income or valuation input.

## Phase 2.65 A-share Eastmoney new-stock-board raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_new_em` as a no-argument Eastmoney A-share new-stock
universe. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_special.py)
confirms the exact 17 fields `序号`, `代码`, `名称`, quote/change fields,
`成交量`, `成交额`, `振幅`, OHLC, `量比`, `换手率`, `市盈率-动态` and `市净率`.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=new_stock`, validates the exact response shape, six-digit A-share codes,
unique positive sequence numbers, finite numeric/null values and non-empty names,
then filters the current-trading-day universe to the requested listing. The
normalizer emits `AKSHARE_NEW_STOCKS_RAW_ONLY`; no canonical listing date,
return, valuation, governance or market fact is admitted because the response
is a current quote universe without a stable row-level observation date.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `序号` | Validated positive integer with no duplicate; raw display order only, not a canonical rank or market metric. |
| `代码`, `名称` | Required six-digit A-share identity and non-empty display name; used only for provider-boundary filtering and evidence context. |
| `最新价`, `涨跌幅`, `涨跌额`, `成交量`, `成交额`, `振幅`, `最高`, `最低`, `今开`, `昨收`, `量比`, `换手率`, `市盈率-动态`, `市净率` | Finite numeric/null current-trading-day quote, activity and provider-metric context; no return, liquidity, valuation or calculation fact is inferred. |
| request `view=new_stock` | Explicit no-argument endpoint, A-share listing filter and retrieval-only current-day snapshot scope; no synthetic observation date is added. |

The provider-specific new-stock-board response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts. Its raw evidence is available
for later review without being treated as a canonical listing, return,
valuation, governance or market input.

## Phase 2.66 A-share Eastmoney individual-notice raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py)
document `stock_individual_notice_report` as a symbol-scoped Eastmoney A-share
individual-notice endpoint. Its documented request uses `security`, category
`symbol` (default `全部`) and optional `begin_date`/`end_date` bounds; its exact
response fields are `代码`, `名称`, `公告标题`, `公告类型`, `公告日期` and `网址`.

The provider selects this endpoint only under `DISCLOSURE_NOTICES` with explicit
`view=individual_notice`, passes the requested six-digit code as `security`,
maps the provider-neutral category and optional `YYYYMMDD` bounds to the
documented upstream names, validates every exact six-field row and inclusive
date bound, and retains the complete listing-scoped response as raw evidence.
The normalizer emits `AKSHARE_INDIVIDUAL_NOTICES_RAW_ONLY` and marks
`accounting_opinion` and `governance_risk_level` as critically missing; it does
not fetch or classify the linked notice and creates no filing-derived financial
or governance fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称` | Required six-digit listing identity and non-empty display name; used only for request-boundary validation and evidence context. |
| `公告标题`, `公告类型` | Required non-empty discovery metadata; announcement text/type is not classified as an accounting, filing or governance conclusion. |
| `公告日期` | Required date-or-null output field; validated against optional request bounds, but not promoted to a financial-statement period or point-in-time governance fact. |
| `网址` | Required HTTP(S) retrieval locator; the linked notice remains outside this structured-data slice and requires the Phase 3 filing/evidence workflow. |
| request `view=individual_notice`, `category`, `start_date`, `end_date` | Explicit endpoint selector, category and optional inclusive listing-notice history/range replay scope; upstream names are not exposed to calculations, gates, pipeline, CLI or input-loader code. |

The slice deliberately leaves `accounting_opinion` and
`governance_risk_level` unresolved: announcement metadata and links alone do
not establish filing contents, audit language, materiality or governance
severity.

## Phase 2.67 A-share Eastmoney market-focus raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py)
document `stock_comment_detail_scrd_focus_em` as a symbol-scoped Eastmoney
A-share market-focus endpoint. Its documented request accepts a six-digit
`symbol`, requests the `RPT_STOCK_MARKETFOCUS` report with a 30-row page size,
and maps the response to exactly `交易日` and `用户关注指数`.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=focus`, passes the unprefixed requested listing code, validates the exact
two-field response, strict ascending ISO dates, finite numeric/null focus values
and the official 30-row maximum, and retains the symbol-scoped response with
observed date bounds as raw evidence. The normalizer emits
`AKSHARE_MARKET_FOCUS_RAW_ONLY`; it does not promote provider-defined user
attention into a canonical market, issuer-cash-flow, shareholder-return,
governance or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `交易日` | Required ISO observation date in strict ascending order; retained as raw market-activity context, not an accounting, fund-flow or filing period. |
| `用户关注指数` | Provider-defined user-attention score; finite numeric/null values are retained without inferring a scale, denominator, sentiment judgment or canonical market metric. |
| request `view=focus`, unprefixed six-digit `symbol` | Explicit endpoint, A-share listing and latest-30-trading-day replay scope; observed date bounds remain provider-boundary metadata. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. User-attention history alone does not establish issuer
cash flow, shareholder return, governance severity or valuation.

## Phase 2.68 A-share Eastmoney institution-participation raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_comment_em.py)
document `stock_comment_detail_zlkp_jgcyd_em` as a symbol-scoped Eastmoney
A-share institution-participation endpoint. Its documented request accepts a
six-digit `symbol` and returns the exact `交易日` and `机构参与度` fields; the
implementation publishes the participation value in percent and returns the
symbol's historical series.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=institution_participation`, passes the unprefixed requested listing code,
validates the exact two-field response, strict ascending ISO dates and finite
numeric/null percentage values, and retains observed date bounds as raw
evidence. The normalizer emits
`AKSHARE_MARKET_INSTITUTION_PARTICIPATION_RAW_ONLY`; it does not promote
provider-defined institution participation into a canonical market,
issuer-cash-flow, shareholder-return, governance or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `交易日` | Required ISO observation date in strict ascending order; retained as raw market-activity context, not an accounting, fund-flow or filing period. |
| `机构参与度` | Provider-defined participation percentage; finite numeric/null values are retained with `value_unit=percent` without inferring a scale, denominator, sentiment judgment or canonical market metric. |
| request `view=institution_participation`, unprefixed six-digit `symbol` | Explicit endpoint, A-share listing and symbol-scoped historical-series replay scope; observed date bounds remain provider-boundary metadata. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. Institution-participation history alone does not
establish issuer cash flow, shareholder return, governance severity or
valuation.

## Phase 2.69 A-share Eastmoney limit-up-pool raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
document `stock_zt_pool_em` as an Eastmoney A-share limit-up-pool endpoint.
The request requires a recent-data `date` in `YYYYMMDD` form and the documented
response contains exactly `序号`, `代码`, `名称`, `涨跌幅`, `最新价`, `成交额`,
`流通市值`, `总市值`, `换手率`, `封板资金`, `首次封板时间`, `最后封板时间`,
`炸板次数`, `涨停统计`, `连板数` and `所属行业`.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=limit_up_pool`, passes the request date unchanged, validates the full
recent-date universe before filtering to the requested A-share listing, and
records the requested/observed date binding, row counts, exact field scope,
rank ordering and provider source URI. The normalizer emits
`AKSHARE_LIMIT_UP_POOL_RAW_ONLY`; it creates no canonical fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `序号` | Required positive integer with strictly ascending full-universe ordering; retained as provider ranking context only. |
| `代码` | Required six-digit A-share identity; used only for provider-boundary filtering and replay scope. |
| `名称`, `所属行业` | Required non-empty text context; no issuer classification or business-quality fact is inferred. |
| `涨跌幅`, `最新价`, `成交额`, `流通市值`, `总市值`, `换手率`, `封板资金`, `炸板次数`, `连板数` | Finite numeric-or-null quote, activity, market-cap and provider-statistic fields; they do not become return, liquidity, valuation, cash-flow or canonical market facts. |
| `首次封板时间`, `最后封板时间` | Required valid `HHMMSS` time-only fields; request `date` supplies provenance only and no synthetic timestamp is created. |
| `涨停统计` | Required `days/ct` provider summary string; it remains raw limit-up activity context and is not normalized into a canonical activity or return metric. |
| request `view=limit_up_pool`, `date` | Explicit endpoint, A-share listing filter and requested-trading-date replay scope; the upstream date is retained as request-bound provenance. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. Quote, limit-up activity, provider ranking and
market-cap fields remain raw evidence only and do not establish issuer cash
flow, shareholder return, governance, valuation or a canonical market metric.

## Phase 2.70 A-share Eastmoney latest stock-hot-rank raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hot_rank_em.py)
document `stock_hot_rank_latest_em` as a symbol-scoped Eastmoney A-share
latest-rank endpoint. Its request accepts a market-prefixed `symbol` such as
`SZ000665`; the returned table has the exact `item` and `value` columns and the
ten documented items `marketType`, `marketAllCount`, `calcTime`, `innerCode`,
`srcSecurityCode`, `rank`, `rankChange`, `hisRankChange`, `hisRankChange_rank`
and `flag`.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=hot_rank_latest`, passes the market-prefixed A-share symbol, validates
the exact item/value schema, item uniqueness, requested-symbol identity,
`calcTime` timestamp and integer/null value rules, and records the
symbol-scoped latest-rank replay boundary. The normalizer emits
`AKSHARE_HOT_RANK_LATEST_RAW_ONLY`; it creates no canonical fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `marketType`, `innerCode` | Required non-empty text identifiers; retained as raw provider context, not normalized into an exchange or issuer identity. |
| `srcSecurityCode` | Required market-prefixed A-share code matching the requested listing; used for request/response identity validation only. |
| `calcTime` | Required `YYYY-MM-DD HH:MM:SS` row timestamp; binds the latest-rank observation only and is not an accounting or market-history period. |
| `marketAllCount`, `rank`, `rankChange`, `hisRankChange`, `hisRankChange_rank`, `flag` | Integer or null provider values, with positive `marketAllCount` and `rank`; retained as popularity-rank evidence only and not as a canonical return, liquidity, valuation or market metric. |
| request `view=hot_rank_latest`, market-prefixed `symbol` | Explicit endpoint, A-share listing, symbol-scoped current-day latest-rank snapshot and row-count replay scope. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. Popularity rank and provider timing alone do not
establish issuer cash flow, shareholder return, governance severity or
valuation.

## Phase 2.71 A-share Xueqiu individual-spot quote slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_xq.py)
document `stock_individual_spot_xq` as a symbol-scoped Xueqiu A-share quote
endpoint. Its documented call accepts a market-prefixed `symbol` plus optional
Xueqiu `token` and request `timeout`, and returns a two-column `item`/`value`
table. The adapter derives the symbol from the canonical listing, accepts only
`view=xueqiu_spot` in the provider request, and leaves credentials and timeout
controls out of the persisted request/cache identity.

The provider validates the exact two-field row shape, unique items, the
documented item allowlist, requested A-share code, required name/current-price/
timestamp items, finite numeric values and the `YYYY-MM-DD HH:MM:SS` quote time.
The existing canonical quote contract applies narrowly: `现价` becomes
`current_price` (or the existing secondary-listing quote field) and `时间`
becomes `market_quote_timestamp`. No other Xueqiu item is normalized.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称`, `时间` | Required symbol identity, display context and quote observation timestamp; identity and timestamp are validated at the provider boundary, while the timestamp is mapped only to the existing quote-timestamp fact. |
| `现价` | Required numeric-or-null quote item; mapped to the existing `current_price` contract with the A-share currency and `price_per_share` unit. |
| all other documented Xueqiu items | Retained in the opaque raw response after type/allowlist validation; they do not become market-cap, return, liquidity, valuation, dividend or financial facts. |
| request `view=xueqiu_spot`, derived market-prefixed `symbol` | Explicit endpoint selection, A-share listing scope and current-quote replay boundary; optional Xueqiu credentials/timeouts are intentionally not accepted as provider request fields. |

The slice does not change calculations, gates, pipeline, CLI or input-loader
contracts. Only the existing quote fields are normalized; provider-specific
Xueqiu names remain at the adapter/raw-evidence boundary.

## Phase 2.72 A-share Xueqiu company-profile raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_basic_info_xq.py)
document `stock_individual_basic_info_xq` as a symbol-scoped Xueqiu A-share
company-profile endpoint. Its documented call accepts a market-prefixed
`symbol`, optional Xueqiu `token` and request `timeout`, and returns the
`item`/`value` profile table. The adapter derives the symbol from the canonical
listing, accepts only `view=xueqiu_basic_info`, and leaves credentials and
timeout controls out of the provider request/cache identity.

The provider validates the exact two-field row shape, unique items, the
documented 39-item allowlist, required `org_id`/`org_name_cn`/
`org_short_name_cn` profile identifiers, scalar values, the documented
`affiliate_industry` object, and finite numeric date, asset, personnel and
issuance fields. The normalizer
emits `AKSHARE_XUEQIU_BASIC_INFO_RAW_ONLY`; no profile field becomes a
canonical company or listing fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `org_id`, `org_name_cn`, `org_short_name_cn` | Required profile identity/display values; validated and retained as raw evidence only, with no canonical company or listing identity replacement. |
| descriptive, registration, personnel and control items | Raw-only provider evidence; no canonical sector, jurisdiction, control, employee, asset or governance fact is admitted. |
| `established_date`, `listed_date` | Finite numeric provider timestamp values; raw-only because epoch/unit semantics are not verified as canonical incorporation or listing dates. |
| `reg_asset`, `staff_num`, `executives_nums`, `actual_issue_vol`, `issue_price`, `actual_rc_net_amt`, `pe_after_issuing`, `online_success_rate_of_issue` | Finite numeric provider values; raw-only, with no balance-sheet asset, normalized employee, issuance or valuation fact. |
| `affiliate_industry` | Documented object value retained as raw provider context; no canonical industry classification is inferred. |
| request `view=xueqiu_basic_info`, derived market-prefixed `symbol` | Explicit endpoint selection, A-share listing scope, symbol-scoped company-profile snapshot and replay boundary; optional Xueqiu credentials/timeouts are not request/cache identity. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. Provider-specific Xueqiu names and profile semantics
remain at the adapter/raw-evidence boundary.

## Phase 2.73 A-share CNINFO company-profile raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_cninfo.py)
document `stock_profile_cninfo` as a symbol-scoped CNINFO A-share company
profile. The implementation passes the six-digit `symbol` as the upstream
`scode` and returns the documented 26-column profile table. The provider
selects it only with `COMPANY_METADATA` plus explicit `view=cninfo_profile`,
validates one exact row, the A-share code identity, scalar/null values and
valid date-or-null `成立日期`/`上市日期` values, and records the symbol-scoped snapshot for
replay.

The normalizer emits `AKSHARE_CNINFO_PROFILE_RAW_ONLY`; no profile field
becomes a canonical company or listing fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `公司名称`, `英文名称`, `曾用简称`, `A股代码`, `A股简称`, `B股代码`, `B股简称`, `H股代码`, `H股简称` | Profile identity and display context; the requested A-share code is validated, but cross-listing and name fields do not replace caller-supplied company identity. |
| `入选指数`, `所属市场`, `所属行业`, `法人代表` | Raw classification and representative context; no canonical exchange, sector, control or governance fact is inferred. |
| `注册资金`, `成立日期`, `上市日期` | Raw registration/date context; the provider validates scalar values and date-or-null values, but no unit, accounting basis or canonical incorporation/listing fact is admitted. |
| `官方网站`, `电子邮箱`, `联系电话`, `传真`, `注册地址`, `办公地址`, `邮政编码` | Raw contact and location evidence; no jurisdiction, operating status or governance conclusion is inferred. |
| `主营业务`, `经营范围`, `机构简介` | Raw descriptive evidence; overlapping descriptions do not establish canonical revenue, core business or Business Quality facts. |
| request `view=cninfo_profile`, unprefixed six-digit `symbol` | Explicit endpoint, A-share listing scope, symbol-scoped current company-profile snapshot and replay boundary. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. CNINFO profile names, descriptions, contact fields and
provider-specific semantics remain at the adapter/raw-evidence boundary.

## Phase 2.74 A-share Tonghuashun main-business-introduction raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_zyjs_ths.py)
document `stock_zyjs_ths` as a symbol-scoped Tonghuashun A-share main-business-
introduction response with the exact five fields `股票代码`, `主营业务`, `产品类型`,
`产品名称` and `经营范围`. The provider selects it only with
`COMPANY_METADATA` plus explicit `view=business_intro`, passes the unprefixed
six-digit A-share code, validates one exact row, code identity and string/null
values, and records the current business-introduction snapshot for replay.

The normalizer emits `AKSHARE_BUSINESS_INTRO_RAW_ONLY`; no business,
product or operating-scope field becomes a canonical company, revenue,
core-business or Business Quality fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码` | Required A-share identity check against the requested listing; retained in raw evidence only and does not replace caller-supplied company/listing identity. |
| `主营业务`, `产品类型`, `产品名称`, `经营范围` | String/null descriptive evidence; no canonical revenue, margin, core-business or Business Quality fact is inferred. |
| request `view=business_intro`, unprefixed six-digit `symbol` | Explicit A-share endpoint selection, symbol-scoped current snapshot and replay boundary. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. Tonghuashun business-introduction names and
descriptions remain at the adapter/raw-evidence boundary.

## Phase 2.75 A-share Eastmoney ownership-pledge market-profile raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
document `stock_gpzy_profile_em` as a no-argument, historical A-share
market-wide ownership-pledge profile. The provider selects it only with
`OWNERSHIP_PLEDGE` plus explicit `view=market_profile`, validates each row's
exact field set and strictly ascending `交易日期`, and retains the complete
response. The requested A-share code is provenance context only because the
market-profile rows have no issuer/listing identity; no rows are filtered or
marked as entity-selected.

The official implementation divides the documented percent input for
`A股质押总比例` by 100 before returning it. The adapter preserves those
source-returned fractions and records the source scale explicitly, so raw
replay does not rescale the ratio twice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `交易日期` | Required market observation date; rows must be strictly ascending and are retained as raw evidence, not a listing-specific statement period. |
| `A股质押总比例` | Source-returned fraction of total A-share shares; the source percent-to-fraction conversion is recorded as replay metadata, with no canonical pledge ratio fact. |
| `质押公司数量`, `质押笔数` | Non-negative aggregate market counts; raw evidence only, with no issuer-level count or governance inference. |
| `质押总股数`, `质押总市值` | Non-negative aggregate market shares/value; raw evidence only, without a settled issuer cash, debt-equivalent or diluted-share basis. |
| `沪深300指数`, `涨跌幅` | Market-index and change context; raw evidence only, not a canonical price, return or valuation input. |
| request `view=market_profile` | Explicit A-share endpoint selection, no-argument upstream call, market-wide historical scope and replay boundary; `listing_scoped_request=false`, `row_filtering=none`, `entity_rows_selected=false`. |

The normalizer emits `AKSHARE_OWNERSHIP_PLEDGE_PROFILE_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical pledge,
governance, cash, debt-equivalent or share fact. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts. No H-share
counterpart or filing-backed pledge interpretation is added.

## Phase 2.76 A-share Eastmoney goodwill market-profile raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
document `stock_sy_profile_em` as a no-argument A-share Eastmoney market
overview with historical rows. The explicit adapter request is
`GOODWILL_IMPAIRMENT` plus `view=market_profile`; upstream arguments are empty
and the requested listing is provenance context only. The response has no
issuer/listing identity, so all rows are retained with
`listing_scoped_request=false`, `row_filtering=none` and
`entity_rows_selected=false`.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `报告期` | Required report-period label; rows must be strictly ascending and remain provider history rather than a listing-specific statement period. |
| `商誉`, `商誉减值`, `净资产`, `净利润规模` | Amount fields documented in yuan; recorded with `amount_unit=CNY` as market-wide raw evidence, without canonical accounting or profit scope. |
| `商誉占净资产比例`, `商誉减值占净资产比例`, `商誉减值占净利润比例` | Provider-reported ratios retained with `ratio_unit=provider_reported_ratio`; no canonical ratio or denominator is inferred. |
| request `view=market_profile` | Explicit A-share endpoint selection, no-argument upstream call, exact eight-field schema and replay scope. |
| market-wide response and report-period bounds | Complete response retained; aggregate annual/interim periods require primary-filing entity, scope and reconciliation review. |

The adapter rejects missing or unexpected fields, invalid periods, non-finite
or non-numeric values and duplicate/non-ascending `报告期` rows. The normalizer
emits `AKSHARE_GOODWILL_PROFILE_RAW_ONLY`, marks `goodwill` and `impairment`
as critically missing and creates no canonical accounting, profit, ratio or
Business Quality fact. H-share goodwill coverage and filing-backed
reconciliation remain unresolved. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.77 A-share Eastmoney goodwill-impairment forecast raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
document `stock_sy_yq_em` as a date-filtered A-share Eastmoney goodwill-
impairment forecast universe. The explicit adapter request is
`GOODWILL_IMPAIRMENT` plus `view=impairment_forecast` and a required
`date=YYYYMMDD`; the provider passes that date to the callable, validates the
complete response, then retains only rows matching the requested A-share code.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `序号` | Required positive sequence; rows must be strictly ascending before listing selection. |
| `股票代码`, `股票简称`, `业绩变动原因`, `交易市场` | Required listing/context fields; code identity is required for universe filtering, while text remains opaque raw evidence and may be null where the provider returns null. |
| `最新商誉报告期`, `公告日期` | Nullable provider dates; validated when populated. `最新商誉报告期` is not silently substituted for the request's `REPORT_DATE` filter. |
| `最新一期商誉`, `上年商誉` | Nullable goodwill context amounts documented primarily in yuan; raw evidence only, without filing-backed entity, accounting scope or canonical goodwill. |
| `预计净利润-下限`, `预计净利润-上限`, `业绩变动幅度-下限`, `业绩变动幅度-上限`, `上年度同期净利润` | Nullable numeric forecast/prior-period context; documented amount fields are primarily yuan (`amount_unit=CNY`) and change-range fields are percent values (`ratio_unit=provider_reported_percent`), but remain raw evidence without canonical forecast, profit or ratio interpretation. |
| request `view=impairment_forecast`, `date=YYYYMMDD` | Explicit endpoint routing and request-period binding to the upstream report-date filter; `listing_scoped_request=false`, `row_filtering=provider`, `entity_rows_selected=true`. |
| date-filtered universe | Full 14-field schema is checked before matching rows are selected; upstream and selected row counts remain replay metadata. |

The adapter rejects missing or unexpected fields, non-positive/non-ascending
sequence values, invalid populated dates, non-finite or non-numeric numeric
values and non-text context values. The normalizer emits
`AKSHARE_GOODWILL_FORECAST_RAW_ONLY`, marks `goodwill` and `impairment` as
critically missing and creates no canonical accounting, forecast, profit, ratio
or Business Quality fact. H-share goodwill coverage and primary-filing
reconciliation remain unresolved. The response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 2.78 A-share Sina intraday-trade raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_intraday_sina.py)
document `stock_intraday_sina` as a date-bound A-share large-order response.
The adapter selects it only under `MARKET_HISTORY` with explicit
`view=intraday_sina`, derives a lower-case market-prefixed `symbol`, and passes
the required `date=YYYYMMDD` unchanged. The exact seven-field response is
validated before the raw record is returned.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `symbol` | Must equal the requested lower-case market-prefixed A-share symbol; it is retained as raw identity context. |
| `name` | Required non-empty provider security name; retained as raw evidence and not used to overwrite company identity. |
| `ticktime` | Required `HH:MM:SS` time-of-day value in non-decreasing order; the request date is not silently attached as a row-level date. |
| `price`, `prev_price` | Finite numeric or null CNY-per-share fields; raw large-order context only. |
| `volume` | Finite integer or null share count; raw large-order context only. |
| `kind` | Required documented trade-kind code `U`, `D` or `E`; no order-flow classification is inferred. |
| request `view=intraday_sina`, `date=YYYYMMDD` | Explicit endpoint routing and requested-trading-day replay scope; `listing_scoped_request=true`, `date_binding=request_only`, `range_filtering=none`. |

The normalizer emits `AKSHARE_SINA_INTRADAY_RAW_ONLY`, marks `market_history`
as critically missing and creates no canonical daily-history, liquidity,
order-flow or valuation fact. The requested date, derived symbol, units and
observed time bounds are checked during replay. The response remains outside
the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.79 A-share Eastmoney goodwill-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
document `stock_sy_em` as a date-filtered A-share Eastmoney goodwill-detail
universe. The adapter selects it only under `GOODWILL_IMPAIRMENT` with explicit
`view=goodwill_detail` and required `date=YYYYMMDD`, passes the date unchanged,
validates the complete market-wide response and then retains only the requested
A-share code.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `序号` | Required positive sequence; the complete response must be strictly ascending before listing selection. |
| `股票代码`, `股票简称`, `交易市场` | Required listing identity/context fields; the code must be an explicit A-share code matching the requested listing, while text remains opaque raw evidence. |
| `商誉`, `净利润`, `上年商誉` | Nullable numeric amounts documented primarily in yuan; retained as aggregator evidence without filing-backed entity, accounting scope or canonical goodwill/profit interpretation. |
| `商誉占净资产比例`, `净利润同比` | Nullable finite provider-reported ratios; no canonical denominator, growth metric or Business Quality fact is inferred. |
| `公告日期` | Nullable `YYYY-MM-DD` provider publication date; it is not silently admitted as a report or recognition date. |
| request `view=goodwill_detail`, `date=YYYYMMDD` | Explicit endpoint routing and request-period binding to the upstream `REPORT_DATE` filter; `listing_scoped_request=false`, `row_filtering=provider`, `entity_rows_selected=true`. |
| date-filtered universe | Exact ten-field schema is checked before matching rows are selected; upstream and selected counts, sequence ordering, units and scope remain replay metadata. |

The adapter rejects missing or unexpected fields, non-positive/non-ascending
sequence values, invalid populated dates, non-finite or non-numeric numeric
values and invalid text values. The normalizer emits
`AKSHARE_GOODWILL_DETAIL_RAW_ONLY`, marks `goodwill` and `impairment` as
critically missing and creates no canonical accounting, profit, ratio or
Business Quality fact. H-share goodwill coverage and primary-filing
reconciliation remain unresolved. The response remains outside the
calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.80 A-share Eastmoney market-wide notice raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_notice.py)
document `stock_notice_report` as a market-wide Eastmoney A-share notice
endpoint. Its request accepts a documented category `symbol` and required
`date=YYYYMMDD`; the adapter exposes those through explicit
`view=market_notice` routing. The exact response fields are `代码`, `名称`,
`公告标题`, `公告类型`, `公告日期` and `网址`.

The provider validates the complete response before filtering it to the
requested A-share code. Every row must have a six-digit code, non-empty text,
valid HTTP(S) URL and an `公告日期` equal to the requested date. The raw record
retains the selected row(s), upstream/selected counts, category, request/row
date binding, market-wide scope and provider-filter metadata; no matching row
is an error. The normalizer emits `AKSHARE_MARKET_NOTICES_RAW_ONLY` and leaves
`accounting_opinion` and `governance_risk_level` critically missing.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码` | Required six-digit A-share listing identity; validated across the full market response and used only for provider-boundary filtering/evidence context. |
| `名称` | Required non-empty provider display name; retained as raw evidence and not used to overwrite company identity. |
| `公告标题`, `公告类型` | Required non-empty announcement discovery metadata; not interpreted as filing contents, accounting language or governance severity. |
| `公告日期` | Required valid date matching the explicit request date; retained as notice-date evidence, not promoted to a financial-statement period or governance fact. |
| `网址` | Required HTTP(S) notice locator; linked filing contents remain outside this structured-data slice and require the Phase 3 evidence workflow. |
| request `view=market_notice`, `category`, `date=YYYYMMDD` | Explicit endpoint selector, documented category mapping and date-bound A-share universe; upstream names are not exposed to calculations, gates, pipeline, CLI or input-loader code. |

The slice deliberately remains raw-only: date-bound announcement metadata
identifies candidates for review but does not establish filing contents, an
accounting opinion, materiality or a governance-risk judgment. The response
remains outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.81 A-share Eastmoney shareholder-meeting raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gddh_em.py)
document `stock_gddh_em` as a no-argument Eastmoney A-share shareholder-meeting
endpoint. The implementation requests the current published dataset and exposes
the exact twelve fields `代码`, `简称`, `股东大会名称`, `召开开始日`, `股权登记日`,
`现场登记日`, `网络投票时间-开始日`, `网络投票时间-结束日`, `决议公告日`,
`公告日`, `序列号` and `提案`. The adapter exposes this callable only through
explicit `view=shareholder_meeting` routing.

The provider validates the complete response before filtering it to the
requested six-digit A-share code. All matching rows are retained, including
multiple meeting/proposal rows for one listing; no matching row is an error. The
raw record records the exact field order, seven event/publication date fields,
upstream/selected counts, current-published snapshot scope and
`row_filtering=provider` for cache replay. Nullable dates and proposal text are
preserved as null; no date is treated as a financial reporting period.

| Raw upstream item | Phase 2.81 treatment |
| --- | --- |
| `代码` | Required six-digit A-share identity; validated across the complete response and used only for provider-boundary filtering/evidence context. |
| `简称` | Required non-empty provider display name; retained as raw evidence and not used to overwrite canonical company identity. |
| `股东大会名称` | Required non-empty meeting title; retained as event metadata, not interpreted as a governance conclusion. |
| `召开开始日`, `股权登记日`, `现场登记日` | Nullable valid event/registration dates; retained as row-level dates and not promoted to a report period or corporate-action fact. |
| `网络投票时间-开始日`, `网络投票时间-结束日` | Nullable valid online-voting window dates; retained as raw meeting logistics. |
| `决议公告日`, `公告日` | Nullable valid resolution/publication dates; retained as disclosure context, not as filing contents or an accounting date. |
| `序列号` | Required positive integer-like source sequence; retained for source identity/order only. |
| `提案` | Nullable non-empty proposal text; retained as raw evidence and not classified into a governance risk level. |
| request `view=shareholder_meeting` | Explicit A-share endpoint selector with no upstream arguments; source scope, field schema and provider filtering remain replay metadata and do not leak into calculations, gates, pipeline, CLI or input-loader code. |

The normalizer emits `AKSHARE_SHAREHOLDER_MEETINGS_RAW_ONLY`, creates no
canonical facts and leaves `governance_risk_level` critically missing. Meeting
dates, proposals and announcement context require filing-backed review before
they can support a governance judgment or corporate-action interpretation. The
slice remains outside the calculation, gate, pipeline, CLI and input-loader
contracts.

## Phase 2.82 H-share Eastmoney latest stock-hot-rank raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_hot_rank_em.py)
document `stock_hk_hot_rank_latest_em` as a symbol-scoped Eastmoney H-share
latest-rank endpoint. Its request accepts an unprefixed five-digit `symbol`
such as `00700`; the implementation calls `getCurrentHkUsLatest` with
`marketType=000003` and returns the exact `item`/`value` table for
`marketType`, `marketAllCount`, `calcTime`, `innerCode`, `srcSecurityCode`,
`rank`, `rankChange`, `hisRankChange`, `hisRankChange_rank` and `flag`.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=hot_rank_latest`, validates the exact ten-row response, item uniqueness,
H-share `innerCode`/`HK|` identity, the `calcTime` timestamp and integer/null
value rules, and records the H-share symbol format, `000003` market type,
current-day latest-rank scope and row-derived observation time for replay.
The normalizer emits `AKSHARE_HK_HOT_RANK_LATEST_RAW_ONLY`; it creates no
canonical fact.

| Raw upstream item | Phase 2.82 treatment |
| --- | --- |
| `marketType` | Required non-empty text exactly equal to `000003` for the documented H-share endpoint; retained as raw provider scope, not normalized into an exchange or issuer identity. |
| `innerCode` | Required five-digit H-share provider code, optionally followed by the documented underscore suffix such as `_2`, matching the requested listing code; used for response identity validation only. |
| `srcSecurityCode` | Required `HK|`-prefixed five-digit H-share code matching the requested listing; used for request/response identity validation only. |
| `calcTime` | Required `YYYY-MM-DD HH:MM:SS` row timestamp; binds the latest-rank observation only and is not an accounting or market-history period. |
| `marketAllCount`, `rank`, `rankChange`, `hisRankChange`, `hisRankChange_rank`, `flag` | Integer or null provider values, with positive `marketAllCount` and `rank`; retained as popularity-rank evidence only and not as a canonical return, liquidity, valuation or market metric. |
| request `view=hot_rank_latest`, H-share `symbol` | Explicit H-share endpoint selector, unprefixed five-digit upstream symbol, symbol-scoped current-day latest-rank snapshot and row-count replay scope. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. H-share popularity rank and provider timing alone do
not establish issuer cash flow, shareholder return, governance severity or
valuation.

## Phase 2.83 A-share Eastmoney limit-down-pool raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_ztb_em.py)
document `stock_zt_pool_dtgc_em` as the recent-data Eastmoney A-share
limit-down-pool endpoint. The request accepts a required `date` in `YYYYMMDD`
form and the response schema is exactly `序号`, `代码`, `名称`, `涨跌幅`,
`最新价`, `成交额`, `流通市值`, `总市值`, `动态市盈率`, `换手率`, `封单资金`,
`最后封板时间`, `板上成交额`, `连续跌停`, `开板次数` and `所属行业`.

The provider selects this endpoint only under `MARKET_ACTIVITY` with explicit
`view=limit_down_pool`, passes the date unchanged, validates the complete
recent-date universe before filtering to the requested A-share listing, and
records the requested/observed date binding, row counts, exact field scope,
rank ordering and provider source URI. The fixture is a frozen real response
snapshot for 20260910. The normalizer emits
`AKSHARE_LIMIT_DOWN_POOL_RAW_ONLY`; it creates no canonical fact.

| Raw upstream item | Phase 2.83 treatment |
| --- | --- |
| `序号` | Required positive integer with strictly ascending full-universe ordering; retained as provider ranking context only. |
| `代码` | Required six-digit A-share identity; used only for provider-boundary filtering and replay scope. |
| `名称`, `所属行业` | Required non-empty text context; no issuer classification or business-quality fact is inferred. |
| `涨跌幅`, `最新价`, `流通市值`, `总市值`, `动态市盈率`, `换手率` | Finite numeric-or-null quote, market-cap and provider-statistic fields; they do not become return, liquidity, valuation, cash-flow or canonical market facts. |
| `成交额`, `封单资金`, `板上成交额`, `连续跌停`, `开板次数` | Finite integer-like-or-null activity and provider-counter fields; they remain raw evidence only. |
| `最后封板时间` | Required valid `HHMMSS` time-only field; request `date` supplies provenance and no synthetic timestamp is created. |
| request `view=limit_down_pool`, `date` | Explicit endpoint, A-share listing filter and requested-trading-date replay scope; the upstream date is retained as request-bound provenance. |

The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts. Quote, limit-down activity, provider ranking and
market-cap fields remain raw evidence only and do not establish issuer cash
flow, shareholder return, governance, valuation or a canonical market metric.

## Phase 2.84 A-share Eastmoney shareholder-count-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdhs.py)
document `stock_zh_a_gdhs_detail_em` as a symbol-scoped Eastmoney A-share
history endpoint. The request uses a six-digit `symbol`; this adapter exposes
it only under `SHAREHOLDER_HOLDINGS` with explicit `view=holder_count_detail`.
The implementation requests the `RPT_HOLDERNUM_DET` report, paginates its
published data, converts numeric/date values and returns exactly the following
15 fields in this order: `股东户数统计截止日`, `区间涨跌幅`, `股东户数-本次`,
`股东户数-上次`, `股东户数-增减`, `股东户数-增减比例`, `户均持股市值`,
`户均持股数量`, `总市值`, `总股本`, `股本变动`, `股本变动原因`,
`股东户数公告日期`, `代码`, `名称`.
The upstream request fixes `reportName=RPT_HOLDERNUM_DET`,
`sortColumns=END_DATE`, `sortTypes=-1`, `pageSize=500`, one-based
`pageNumber` pagination, `quoteColumns=f2,f3`, `source=WEB`, `client=WEB` and
`filter=(SECURITY_CODE="{symbol}")`; only `symbol` plus the neutral view is
exposed by this provider contract. The documented interval/change-ratio fields
are percent values, holder counts and share-base changes are integer fields,
and the market-value/average-holding fields retain the provider's raw scale
without an inferred currency conversion.

The provider validates the exact response schema, six-digit code equality,
non-decreasing `股东户数统计截止日` order, nullable/parseable announcement
dates, integer count/share-base fields, finite numeric values and non-negative
holder-count/market-value/share-base fields. The official response fixture is a
real 61-row snapshot for `600000`, covering `2013-03-07` through `2026-06-30`;
the response is already upstream-filtered by symbol and the adapter records
that scope plus the row-derived observation range.

| Raw upstream item | Phase 2.84 treatment |
| --- | --- |
| `股东户数统计截止日` | Required historical observation date; retained as row-level evidence and sorted non-decreasingly, not treated as an accounting or governance period. |
| `区间涨跌幅` | Raw percent field; no canonical return, valuation or market metric is inferred. |
| `股东户数-本次`, `股东户数-上次`, `股东户数-增减`, `股东户数-增减比例` | Raw holder-count/change evidence; counts are integer-like and the ratio remains provider-defined percent context, with no concentration or ownership calculation. |
| `户均持股市值`, `户均持股数量`, `总市值`, `总股本`, `股本变动` | Raw provider market-value, average-holding and share-base/change fields; no issuer cash, diluted-share or valuation fact is admitted. |
| `股本变动原因`, `股东户数公告日期`, `代码`, `名称` | Raw reason, announcement date and explicit listing identity; dates are nullable/validated and identity remains bound to the requested upstream symbol. |
| request `view=holder_count_detail`, `symbol` | Explicit endpoint selector, six-digit A-share symbol and historical published-dataset replay scope; no synthetic date or post-hoc cross-listing substitution is added. |

The normalizer emits `AKSHARE_SHAREHOLDER_COUNT_DETAIL_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical ownership,
concentration, governance, valuation or diluted-share fact. The response
remains outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 2.85 A-share CNINFO management-holding-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
document `stock_hold_management_detail_cninfo` as a CNINFO full-universe
management-holding-detail endpoint. Its official `symbol` parameter accepts
`增持` or `减持` and returns a rolling near-one-year response. This adapter
exposes that choice as the explicit provider-neutral `direction` parameter under
`INSIDER_SHARE_CHANGES` with `view=cninfo_management_detail`, maps it back to
the official `symbol`, validates the complete response, and filters the universe
to the requested A-share code. The checked-in fixture contains eight rows copied
from an official `增持` response, including two selected `000019` rows and
non-selected codes, while preserving the official 16-field output order.

| Raw upstream item | Phase 2.85 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Exact six-digit provider identity and name fields used for conservative A-share filtering; they do not establish ownership or share-count facts. |
| `截止日期`, `公告日期` | Validated date fields; the cut-off date is the observed event/reporting context and neither date is silently promoted to an accounting or legal-effective period. |
| `高管姓名`, `董监高姓名`, `董监高职务`, `变动人与董监高关系` | Raw person, role and relationship evidence only; no beneficial-control or governance conclusion is inferred. |
| `期初持股数量`, `期末持股数量`, `变动数量` | Raw provider quantities, with documented holdings in 万股; they do not establish a company-level fully diluted share series or settled issuance/buyback amount. |
| `变动比例` | Raw provider percentage; no canonical ownership, concentration, dilution or return metric is calculated. |
| `成交均价`, `期末市值` | Raw price/value fields in the documented 元/万元 scales; they do not establish settled transaction cash, market cap or valuation input. |
| `持股变动原因`, `数据来源` | Raw provider reason and source labels; they are not collapsed into a canonical corporate-action, filing or governance classification. |
| request `view=cninfo_management_detail`, `direction` / upstream `symbol` | Explicit endpoint selector and `增持`/`减持` scope retained in request/evidence metadata, together with the rolling-window, source-order, units, row-count and observed-date replay boundary. |

The slice emits `AKSHARE_CNINFO_MANAGEMENT_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical fact. The
response remains outside the calculation, gate, pipeline, CLI and input-loader
contracts; filing-backed person identity, legal relationship and point-in-time
interpretation remain outside this acquisition contract.

## Phase 2.86 H-share Eastmoney historical stock-hot-rank raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_hot_rank_em.py)
document `stock_hk_hot_rank_detail_em` as a symbol-scoped Eastmoney H-share
historical-rank endpoint. The request uses an unprefixed five-digit `symbol`
such as `00700`; the implementation posts `marketType=000003` to the historical
H-share rank source and returns exactly `时间`, `排名` and `证券代码` in that
order. The adapter exposes it only under `MARKET_ACTIVITY` with explicit
`view=hk_hot_rank_detail`. The checked-in official response fixture contains
120 rows for `00700` from `2026-05-15` through `2026-09-11`; the upstream call is
already symbol-scoped, so selected/non-selected universe rows and adapter-side
listing filtering do not apply.

| Raw upstream item | Phase 2.86 treatment |
| --- | --- |
| `时间` | Required `YYYY-MM-DD` historical observation date; dates must be strictly ascending and remain row-level rank evidence, not a report or accounting period. |
| `排名` | Required positive integer provider popularity rank; retained as raw rank context and not converted into a return, liquidity, valuation or canonical market metric. |
| `证券代码` | Required exact five-digit H-share identity matching the requested symbol; used for response identity validation only. |
| request `view=hk_hot_rank_detail`, `symbol` | Explicit H-share endpoint selector and unprefixed five-digit upstream symbol; `marketType=000003`, source field order, symbol-scoped request, row counts and observed date bounds remain replay metadata. |

The provider validates the full symbol-scoped payload before retaining it and
rejects missing/extra/reordered fields, invalid or duplicate dates, descending
date order, wrong code identity and non-integer/non-positive ranks. The
normalizer emits `AKSHARE_HK_HOT_RANK_DETAIL_RAW_ONLY`, creates no canonical
facts and leaves the dated popularity observations outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 2.9 corporate-action raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes `stock_repurchase_em` as an A-share Eastmoney endpoint with no
request parameters. It returns an all-company response containing planned and
completed repurchase quantities and amounts, a repurchase-start date, an
implementation status and a latest-announcement date. The documentation
labels the monetary columns in yuan, and the implementation source exposes
both planned and completed states.

The provider filters the universe by the requested A-share code before
creating the raw record and retains every matching row. It records the
upstream and selected row counts; a response row without a listing code is a
provider-response error, while no matching row is retained as an empty raw
snapshot. The normalizer emits no canonical buyback or share-reduction fact:
the completed amount may be cumulative, the latest announcement is an update
date rather than a settled cash-flow period, and planned versus completed
status cannot be collapsed into one annual amount.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `计划回购金额区间-下限`, `计划回购金额区间-上限` | Raw-only; planned ranges are not realized shareholder cash. |
| `已回购金额`, `已回购股份数量` | Raw-only; completion status and cumulative scope do not establish an accepted period fact. |
| `回购起始时间` | Raw-only; start date is not the cash settlement/reporting period. |
| `实施进度` | Raw-only; status is not sufficient to classify a settled transaction or recurrence. |
| `最新公告日期` | Raw-only; announcement/update date is not an economic event period. |

The slice emits `AKSHARE_CORPORATE_ACTIONS_RAW_ONLY`, marks
`buyback_cash` as critically missing and does not emit `buyback_recurring`,
`net_diluted_share_reduction_verified` or a valuation credit. H-share
repurchase coverage and filing-backed action classification remain unresolved.

## Phase 2.10 rights-issue corporate-action raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_allotment_cninfo` as a CNINFO endpoint with `symbol`,
`start_date` and `end_date` inputs. Its response contains dated rights-issue
plan/result rows, share quantities, prices, proceeds, fees and multiple action
dates. The endpoint's tabular output does not establish one canonical effective
period, planned-versus-completed outcome, amount unit/scaling or fully diluted
share-class scope for the strict input contract.

The Phase 2 adapter therefore passes an explicit A-share code and date range,
retains the complete response as a `RawProviderRecord`, and emits only
structured-data evidence. The normalizer sets `share_issuance_cash` as
critically missing and emits `AKSHARE_ALLOTMENT_RAW_ONLY`; it creates no
issuance-cash, dilution, buyback, split or share-count fact. H-share rights
issues and any filing-backed classification remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| action dates (`公告日期`, `股权登记日`, `配股上市日`, etc.) | Raw-only; announcement, record, ex-rights, payment and listing dates are not silently collapsed into one period. |
| planned/actual quantities and proceeds | Raw-only; outcome status, units/scaling and cash-flow meaning are not established for canonical issuance cash. |
| `配股比例`, `配股价格` and fees | Raw-only; no share-issuance, split or return metric is derived. |
| `证券代码`, `证券简称`, `机构名称` | Used only for conservative listing identity validation; they do not create a normalized corporate-action fact. |

## Phase 2.11 company share-change raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_share_changes_cninfo.py)
document `stock_share_change_cninfo` as a CNINFO endpoint with A-share
`symbol`, `start_date` and `end_date` inputs in `YYYYMMDD` form. Its rows
contain change and announcement dates, total/circulation holdings, multiple
share-class holdings and change-reason fields. The documented numeric output
types do not define a unit or a fully diluted economic share scope, and the two
dates do not by themselves define the accepted event period.

When an explicit date range is supplied to the `SHARE_CAPITAL` category, the
adapter passes the six-digit A-share code and range, preserves every returned
row and records the range and row count. The normalizer validates explicit row
identity, retains structured-data evidence, sets
`normalized_diluted_economic_shares` in the critical-missing inventory and
emits `AKSHARE_SHARE_CAPITAL_CHANGE_RAW_ONLY`. It emits no canonical share,
issuance, buyback or split fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `变动日期`, `公告日期` | Raw-only; change/effective-date and announcement-period semantics are not silently collapsed. |
| `总股本`, `已流通股份`, `流通受限股份` | Raw-only; documented numeric types do not settle units or fully diluted economic scope. |
| share-class holdings such as `人民币普通股`, `境外上市外资股-H股` | Raw-only; A/H/class equivalence and dilution treatment remain unresolved. |
| `变动原因`, `变动原因编码` | Raw-only; reason text/codes are not classified as buyback, issuance, split or another economic action. |
| `证券代码`, `证券简称`, `机构名称` | Used only for conservative listing identity validation; they do not create a normalized share or action fact. |

## Phase 2.11 A-share ownership-pledge snapshot raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gpzy_pledge_ratio_em` as an Eastmoney A-share universe
endpoint with a required `date` input in `YYYYMMDD` form. Its response is a
date-specific snapshot containing listing code, trading date, pledge ratio,
pledged-share count/value, pledge count, restricted/unrestricted pledged
shares, one-year performance and an industry code.

The provider passes the exact requested date, validates every returned row's
listing code and trading date, filters the universe to the requested A-share
code and retains the matching row as raw evidence. The normalizer marks
`governance_risk_level` as critically missing and emits
`AKSHARE_OWNERSHIP_PLEDGE_RAW_ONLY`; it emits no governance-risk, pledged-cash,
debt-equivalent or valuation fact. A ratio and share count do not establish
the affected holder, controlling-shareholder status, enforceability,
accessibility or an accepted economic period.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码`, `交易日期` | Used for conservative listing and exact-snapshot validation; they do not create a governance or financial fact. |
| `质押比例`, `质押股数`, `质押市值` | Raw-only; affected holder, market-value timing, units and pledged-cash accessibility are not established. |
| `质押笔数`, `无限售股质押数`, `限售股质押数` | Raw-only; pledge structure and legal/economic enforceability remain unresolved. |
| `近一年涨跌幅`, `所属行业代码` | Raw-only context; no performance, sector or governance conclusion is inferred. |

## Phase 2.12 A-share dividend-distribution snapshot raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_fhps_em.py)
document `stock_fhps_em` as an Eastmoney A-share distribution endpoint. It
accepts a report date in `YYYYMMDD` form, documented as a June 30 or December
31 period, and returns a universe row set with listing code, distribution
ratios, multiple event/announcement dates, progress and per-share context.

The provider requires an explicit supported report date, validates that every
universe row has a listing code, filters the response to the requested A-share
listing and retains the selected rows as raw evidence. The normalizer marks
`ordinary_dividend_cash` as critically missing and emits
`AKSHARE_DIVIDEND_SNAPSHOT_RAW_ONLY`; it emits no canonical dividend cash,
special-dividend or payout-ratio fact. The report-date filter, ratio columns,
progress status and several event dates do not by themselves establish a
settled cash amount, ordinary-versus-special policy or a payout denominator.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称` | Used for conservative listing selection and evidence context; they do not create a dividend fact. |
| `送转股份-*` | Raw-only; share-distribution ratios are not converted into a split, dilution or share-count fact. |
| `现金分红-现金分红比例`, `现金分红-股息率` | Raw-only; the response does not settle a total cash amount, declared-versus-paid status or the canonical payout denominator. |
| `预案公告日`, `股权登记日`, `除权除息日`, `最新公告日期` | Raw-only; announcement, record and ex-rights dates are not silently collapsed into a cash-flow period. |
| `方案进度`, `总股本`, per-share indicators | Raw-only context; progress, unit/scope and accounting basis are not sufficient for canonical shareholder-return facts. |

## Phase 2.13 A-share earnings-forecast raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_yjyg_em` as an Eastmoney A-share universe endpoint. It accepts
an explicit quarterly report date in `YYYYMMDD` form, with documented coverage
starting at `20081231`, and returns forecast indicators, forecast values or
ranges, change reasons, forecast type, prior-period values and announcement
dates. The endpoint's forecast values are estimates rather than reported
statement facts, and the announcement date is publication metadata rather than
the statement period.

The provider requires an exact quarter-end date, validates explicit listing
identity on every upstream row, filters the universe to the requested A-share
code and retains all matching rows. The normalizer keeps the selected response
as structured evidence, marks `parent_net_profit` and
`consolidated_net_profit` as critically missing and emits
`AKSHARE_EARNINGS_FORECAST_RAW_ONLY`; it emits no profit, revenue, margin, CDC
or valuation fact. H-share forecasts remain outside this slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `预测指标`, `业绩变动`, `预测数值`, `业绩变动幅度` | Raw-only; forecast ranges and change percentages are not reported parent or consolidated profit. |
| `业绩变动原因`, `预告类型` | Raw-only; provider text and forecast type are not treated as a filing-backed earnings classification. |
| `上年同期值` | Raw-only; a prior-period comparison value does not establish the current reported statement amount or entity basis. |
| `公告日期` | Raw-only; publication date is not silently substituted for the requested report period or filing availability timestamp. |
| `股票代码`, `股票简称` | Used only for conservative listing selection and evidence context; they do not create a normalized profit fact. |

## Phase 2.14 A-share performance-report raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_yjbb_em` as an Eastmoney A-share universe endpoint. It accepts
an explicit quarterly report date in `YYYYMMDD` form, with documented coverage
starting at `20100331`, and returns per-listing headline performance fields
including revenue, net profit, per-share operating cash flow, ratios, industry
and the latest announcement date.

The provider requires an exact quarter-end date, validates explicit listing
identity on every upstream row, filters the universe to the requested A-share
code and retains all matching rows. The report's `净利润-净利润` field does
not identify an admitted parent-versus-consolidated entity basis, while
`每股经营现金流量` is a per-share value rather than the canonical total CFO
fact. The normalizer therefore keeps the selected response as structured
evidence, marks `parent_net_profit`, `consolidated_net_profit` and
`reported_cfo` as critically missing and emits
`AKSHARE_PERFORMANCE_REPORT_RAW_ONLY`; it emits no profit, revenue, margin,
CFO, CDC or valuation fact. H-share performance reports remain outside this
slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `净利润-净利润` | Raw-only; the documented headline does not establish parent-attributable versus consolidated entity scope for the canonical profit fields. |
| `每股经营现金流量` | Raw-only; per-share CFO cannot be renamed to a total operating cash-flow fact without an accepted share denominator and period basis. |
| `营业总收入-营业总收入`, growth and margin fields | Raw-only; headline/ratio semantics and report presentation basis are not admitted as canonical income facts in this slice. |
| `每股收益`, `每股净资产` | Raw-only; per-share values do not establish the engine's diluted economic-share or profit contracts. |
| `最新公告日期` | Raw-only; publication/update date is not silently substituted for a report-period or point-in-time availability fact. |
| `股票代码`, `股票简称` | Used only for conservative listing selection and evidence context; they do not create a normalized profit or CFO fact. |

## Phase 2.15 A-share earnings-quick-report raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_yjyg_em.py)
document `stock_yjkb_em` as an Eastmoney A-share universe endpoint. It accepts
an explicit quarterly report date in `YYYYMMDD` form, with documented coverage
starting at `20100331`, and returns headline revenue and net-profit values,
prior-period comparisons, per-share indicators, return on equity, industry and
announcement-date metadata.

The provider requires an exact quarter-end date, validates explicit listing
identity on every upstream row, filters the response to the requested A-share
code and retains all matching rows. The report's `净利润-净利润` field does
not identify an admitted parent-versus-consolidated entity basis, while the
revenue headline, per-share indicators and ratios do not establish the
canonical period, unit or diluted-share scope. The normalizer therefore keeps
the selected response as structured evidence, marks `parent_net_profit` and
`consolidated_net_profit` as critically missing and emits
`AKSHARE_EARNINGS_QUICK_REPORT_RAW_ONLY`; it emits no profit, revenue, margin,
CFO, CDC or valuation fact. H-share quick reports remain outside this slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `净利润-净利润`, `净利润-去年同期` | Raw-only; headline and comparison values do not establish parent-attributable versus consolidated entity scope for canonical profit facts. |
| `营业收入-营业收入`, `营业收入-去年同期` and growth fields | Raw-only; headline/comparison semantics and presentation units are not admitted as canonical revenue facts in this slice. |
| `每股收益`, `每股净资产`, `净资产收益率` | Raw-only; per-share and ratio values do not establish the engine's diluted economic-share, entity or period contracts. |
| `公告日期` | Raw-only; publication date is not silently substituted for the requested report period or filing availability timestamp. |
| `股票代码`, `股票简称` | Used only for conservative listing selection and evidence context; they do not create a normalized profit or revenue fact. |

## Phase 2.16 A-share business-composition raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zygc_em` as an Eastmoney A-share listing-scoped endpoint. It
accepts a market-prefixed `symbol` such as `SH688041` and returns all
historical rows with report date, classification type, business constituent,
revenue/cost/profit amounts, ratios and gross-margin context. The endpoint
contains overlapping product, industry and geographic views rather than one
additive revenue table.

The provider passes the canonical A-share listing identifier, validates an
explicit listing code on every returned row and validates any non-null report
date. It retains every row as an opaque raw payload and records the row count
and distinct report-period count. The normalizer emits
`AKSHARE_BUSINESS_COMPOSITION_RAW_ONLY`, marks `revenue` and `core_revenue` as
critically missing and emits no canonical revenue, operating-profit, margin or
business-quality fact. H-share business composition remains outside this
slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码` | Used for conservative listing identity validation; it does not create a normalized fact. |
| `报告日期` | Raw-only historical context; the endpoint's report presentation is not silently adopted as the canonical statement period. |
| `分类类型`, `主营构成` | Raw-only; product, industry and geographic views are not automatically classified as the company's core business or added together. |
| `主营收入`, `主营成本`, `主营利润` | Raw-only; row grain, entity basis, unit/scaling and overlapping classifications do not establish canonical totals. |
| `收入比例`, `成本比例`, `利润比例`, `毛利率` | Raw-only ratios; denominator and presentation semantics are not admitted as canonical revenue or margin facts. |

## Phase 2.17 A-share financial-abstract raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_financial_abstract` as a Sina A-share listing-scoped
endpoint. It accepts a six-digit `symbol` and returns all historical key
indicators in a wide matrix with `选项`, `指标` and report-period columns. The
documented output mixes amount-like rows, per-share indicators and ratios
without defining one canonical statement entity, unit/scaling or diluted-share
basis for the normalized contract.

The provider passes the requested A-share code, validates explicit metric
identity and date-shaped period columns, retains the complete response as an
opaque raw payload and records row and distinct-period counts. The normalizer
emits `AKSHARE_FINANCIAL_ABSTRACT_RAW_ONLY`, marks `revenue`,
`parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as critically
missing and emits no canonical revenue, profit, CFO, ratio or valuation fact.
H-share financial abstracts remain outside this slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `选项`, `指标` | Used only to validate metric identity and preserve evidence context; they do not create normalized facts. |
| report-period columns such as `20241231` | Raw-only historical context; the wide matrix's period presentation is not silently adopted as a canonical statement period. |
| amount-like rows such as `归母净利润`, `净利润`, `营业总收入` | Raw-only; the response does not establish the accepted entity, unit/scaling or statement semantics for canonical profit/revenue facts. |
| per-share rows such as `每股经营现金流` | Raw-only; per-share values do not establish a total reported CFO or diluted-share basis. |
| ratio rows such as `净资产收益率` | Raw-only; provider ratios are not imported as canonical metrics or used to derive valuation inputs. |

## Phase 2.18 A-share financial-indicator raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_financial_analysis_indicator_em` as an Eastmoney A-share
listing-scoped endpoint. Its official financial-analysis page exposes an
`indicator` choice of `按报告期` or `按单季度` and returns explicit listing
identity, report date, amount fields, per-share fields and provider-calculated
ratios. The response does not define one canonical statement entity,
unit/scaling, period availability basis or calculation methodology for the
normalized contract.

The provider passes the market-suffixed A-share symbol and the documented
indicator choice, validates explicit listing identity and parseable report
dates, retains the complete response as an opaque raw payload and records row,
period and indicator metadata. The normalizer emits
`AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY`, marks `revenue`,
`parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as critically
missing and emits no canonical financial fact or metric. H-share financial
indicators are covered by the Phase 2.22 H-share extension below.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `SECUCODE`, `SECURITY_CODE`, `SECURITY_NAME_ABBR` | Used for conservative listing identity validation and evidence context; they do not create normalized facts. |
| `REPORT_DATE`, `REPORT_TYPE`, `REPORT_DATE_NAME` | Raw-only report context; report presentation and availability do not establish the canonical point-in-time period. |
| amount fields such as `TOTALOPERATEREVE`, `PARENTNETPROFIT`, `MLR` | Raw-only; entity basis, unit/scaling and statement semantics are not settled for canonical revenue or profit facts. |
| per-share fields such as `EPSJB`, `MGJYXJJE`, `BPS` | Raw-only; per-share values do not establish total amounts or a verified diluted-share basis. |
| ratio fields such as `ROEJQ`, `XSJLL`, `ZCFZL` | Raw-only provider-derived ratios; calculation inputs and methodology are not imported as canonical metrics or valuation inputs. |

## Phase 2.22 H-share financial-indicator raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_financial_hk_analysis_indicator_em` as the Eastmoney
historical H-share financial-analysis indicator endpoint. It accepts a
five-digit H-share `symbol` and an `indicator` choice of `年度` or `报告期`, and
returns listing identity, report dates, amount fields, per-share indicators,
provider-calculated ratios and currency metadata.

The provider passes the five-digit code and requested mode, retains the
complete listing-scoped response as an opaque raw payload, validates explicit
H-share identity and parseable report dates, and records row, period and mode
metadata. The normalizer emits `AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY`, marks
`revenue`, `parent_net_profit`, `consolidated_net_profit` and `reported_cfo` as
critically missing and emits no canonical financial fact, metric or valuation
input. Amount, unit/scaling, point-in-time and provider-ratio semantics remain
unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `SECUCODE`, `SECURITY_CODE`, `SECURITY_NAME_ABBR`, `ORG_CODE` | Used for conservative H-share listing identity and evidence context; they do not create normalized facts. |
| `REPORT_DATE`, `DATE_TYPE_CODE`, `START_DATE`, `FISCAL_YEAR` | Raw-only report context; the mode and report date do not establish the canonical point-in-time period. |
| `OPERATE_INCOME`, `GROSS_PROFIT`, `HOLDER_PROFIT` | Raw-only amount fields; entity basis and unit/scaling are not admitted for canonical revenue or profit facts. |
| `PER_NETCASH_OPERATE`, `PER_OI`, `BPS`, `BASIC_EPS`, `DILUTED_EPS` | Raw-only per-share fields; they do not establish total amounts or a verified diluted-share basis. |
| `GROSS_PROFIT_RATIO`, `NET_PROFIT_RATIO`, `ROE_AVG`, `ROA`, `OCF_SALES`, `DEBT_ASSET_RATIO`, `CURRENT_RATIO` | Raw-only provider-calculated ratios; calculation inputs and methodology are not imported as canonical metrics or valuation inputs. |
| `CURRENCY`, `IS_CNY_CODE` | Raw currency metadata only; currency/unit scaling and cross-listing equivalence remain unresolved. |

## Phase 2.23 H-share latest-indicator raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hk_financial_indicator_em` as the Eastmoney H-share
“latest indicators” endpoint. It accepts a five-digit `symbol` and returns one
symbol-scoped row containing per-share, share-capital, dividend, headline
financial and valuation fields. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_em.py)
selects the published output columns without retaining a row-level listing code
or a canonical statement period.

The provider passes the five-digit code, retains the complete symbol-scoped
response as an opaque raw payload, records the returned row count and rejects
an ambiguous multi-row response. The normalizer emits
`AKSHARE_LATEST_INDICATORS_RAW_ONLY`, marks `revenue`, `parent_net_profit`,
`consolidated_net_profit` and `reported_cfo` as critically missing and emits no
canonical financial, share, dividend, market-cap, metric or valuation fact.
Entity, period, unit/scaling, diluted-share and provider-calculation semantics
remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `基本每股收益(元)`, `每股净资产(元)`, `每股经营现金流(元)` | Raw-only per-share values; they do not establish total profit, CFO or a verified diluted-share basis. |
| `法定股本(股)`, `每手股`, `已发行股本(股)`, `已发行股本-H股(股)` | Raw-only capital context; share-class, point-in-time and dilution semantics are not settled. |
| `每股股息TTM(港元)`, `派息比率(%)`, `股息率TTM(%)` | Raw-only dividend context; the snapshot does not establish settled cash, period or ordinary-versus-special classification. |
| `营业总收入`, `净利润` | Raw-only headline amounts; canonical statement entity, period and unit/scaling are not established. |
| `总市值(港元)`, `港股市值(港元)`, `市盈率`, `市净率` | Raw-only provider valuation context; market cap and valuation metrics remain deterministic engine outputs. |
| `营业总收入滚动环比增长(%)`, `净利润滚动环比增长(%)`, `销售净利率(%)`, `股东权益回报率(%)`, `总资产回报率(%)` | Raw-only provider-calculated ratios; calculation inputs, period and methodology are not imported as canonical metrics. |

## Phase 2.19–2.21 A-share insider share-change raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_share_hold_change_sse`, `stock_share_hold_change_szse` and
`stock_share_hold_change_bse` as exchange-specific endpoints for a specific
Shanghai, Shenzhen or Beijing A-share symbol. The SSE response returns company
code/name, insider name and role, share class and currency labels, before/after
holdings, changed quantity and average price, change reason, change date and
filing date. The SZSE response returns security code/name, insider and
related-person roles, change date, changed quantity, average price, change
reason, change ratio and same-day holdings; its quantity is documented in
ten-thousand shares and its ratio in thousandths. The BSE response returns
security code/name, insider name and role, change date, before/after holdings,
changed quantity, average price and change reason; its holding quantities are
documented in ten-thousand shares and its average price in yuan.

The provider passes the six-digit exchange-specific code, validates that every
returned row is explicitly bound to that listing and validates any non-null
event dates. It retains every row as an opaque listing-scoped raw record. The
normalizer emits `AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no company share
count, dilution, governance, buyback or issuance fact. Insider roles and
transactions require later context and filing review; H-share coverage remains
outside this slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `公司代码`, `公司名称` | Used only for explicit listing-boundary validation and evidence context. |
| `姓名`, `职务`, `股票种类`, `货币种类` | Raw-only; holder identity, role and share class do not establish a governance judgment or economic attribution. |
| `本次变动前持股数`, `变动数`, `变动后持股数`, `本次变动平均价格` | Raw-only; event holdings and price do not establish a company-level fully diluted share series or settled buyback/issuance cash flow. |
| `变动原因` | Raw-only; the reason label does not establish intent, materiality or governance severity. |
| `变动日期`, `填报日期` | Raw-only event metadata; neither date is silently promoted to a financial-statement period or point-in-time governance conclusion. |
| SZSE `证券代码`, `证券简称`, `董监高姓名`, `股份变动人姓名`, `职务`, `变动人与董监高的关系` | Used only for explicit listing-boundary validation and evidence context; holder identity and relationship do not establish a governance judgment. |
| SZSE `变动股份数量`, `成交均价`, `变动比例`, `当日结存股数` | Raw-only; documented units and event holdings do not establish a company-level fully diluted share series or settled buyback/issuance cash flow. |
| SZSE `变动日期` | Raw-only event metadata; it is not silently promoted to a financial-statement period or point-in-time governance conclusion. |
| BSE `代码`, `简称`, `姓名`, `职务` | Used only for explicit listing-boundary validation and evidence context; holder identity and role do not establish a governance judgment. |
| BSE `变动日期` | Raw-only event metadata; it is not silently promoted to a financial-statement period or point-in-time governance conclusion. |
| BSE `变动股数`, `变动前持股数`, `变动后持股数`, `变动均价` | Raw-only; documented 万股/元 units and event holdings do not establish a company-level fully diluted share series or settled buyback/issuance cash flow. |
| BSE `变动原因` | Raw-only; the reason label does not establish intent, materiality or governance severity. |

## Phase 2.24 A-share disclosure-notice raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_disclosure_report_cninfo` as a CNINFO endpoint for a
specified A-share `symbol`. Its documented inputs include the `沪深京` market,
optional keyword/category filters and `YYYYMMDD` start/end dates; its output
contains listing code, short name, announcement title, announcement time and a
disclosure link.

The provider passes only the requested six-digit A-share code with the
documented `沪深京` market and filters, validates every returned row's explicit
listing identity and any non-null announcement date, and retains the complete
listing-bound response as raw evidence. The normalizer marks
`accounting_opinion` and `governance_risk_level` as critically missing and
emits `AKSHARE_DISCLOSURE_NOTICES_RAW_ONLY`; it does not fetch, parse or
classify the linked announcement and creates no filing-derived financial or
governance fact. H-share disclosure coverage remains outside this slice.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `简称` | Used only for explicit listing-boundary validation and evidence context; they do not create a normalized company or listing fact. |
| `公告标题` | Raw-only discovery metadata; title text is not classified as an accounting, governance or corporate-action conclusion. |
| `公告时间` | Raw-only publication metadata; it is not silently promoted to a financial-statement period or point-in-time fact. |
| `公告链接` | Raw-only retrieval locator; the linked document is outside this structured-data slice and requires the Phase 3 filing/evidence workflow. |

The slice deliberately leaves `accounting_opinion` and
`governance_risk_level` unresolved: announcement metadata alone does not
establish filing contents, audit language, materiality or governance severity.

## Phase 2.25 H-share dividend-event detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hk_fhpx_detail_ths` as a Tonghuashun H-share dividend-event
detail endpoint. It accepts a five-digit H-share `symbol` and returns
symbol-scoped historical rows with announcement date, plan, ex-date, payment
date, transfer-date range, event type, progress and scrip-dividend context. The
same documentation does not define a general H-share disclosure-notice
counterpart to the A-share CNINFO endpoint; this slice is therefore an
explicitly narrow dividend-event boundary, not general filing discovery.

The provider selects the endpoint only for the provider-neutral request view
`view=event_detail`, passes the listing code, validates any non-null event
dates, retains every returned row and records that the response is scoped by
the requested symbol. The published rows do not carry a canonical listing code,
so the provider does not invent one per row. The normalizer emits
`AKSHARE_HK_DIVIDEND_DETAIL_RAW_ONLY`, marks `ordinary_dividend_cash` as
critically missing and emits no canonical dividend, payout, share, filing or
governance fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `公告日期` | Raw-only announcement metadata; it is not silently promoted to a financial-statement period or a settled cash period. |
| `方案` | Raw-only plan text; a per-share plan or “不分红” label does not establish total cash, ordinary-versus-special status or payment completion. |
| `除净日`, `派息日`, `过户日期起止日-起始`, `过户日期起止日-截止` | Raw-only event dates; multiple event dates do not establish one canonical dividend period. |
| `类型`, `进度`, `以股代息` | Raw-only status and scrip context; these labels do not establish a filing classification, payout ratio or diluted-share adjustment. |

The slice deliberately leaves `ordinary_dividend_cash` unresolved: the
symbol-scoped event detail does not establish a settled total amount, unit,
ordinary-versus-special policy classification or canonical period. General
H-share disclosure retrieval remains a Phase 3 filing/evidence concern.

## Phase 2.26 A-share risk-warning-status raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_zh_a_st_em` as a no-argument Eastmoney risk-warning-board
universe endpoint. It returns the current trading-day universe with explicit
`代码`, `名称` and current market-observation fields. The endpoint is not a
dated status history and does not define a complete assertion about listings
absent from the response.

The provider validates every returned row's explicit A-share listing code,
filters the universe to the requested six-digit A-share code, and retains the
selected rows and upstream/selected counts as raw evidence. The normalizer
emits `AKSHARE_RISK_WARNING_STATUS_RAW_ONLY`, marks `special_treatment` as
critically missing and emits no canonical special-treatment fact; an empty
selected result does not become `special_treatment=False`.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称` | Used only for explicit listing-boundary validation, filtering and raw evidence context; they do not create a canonical status fact. |
| `最新价`, `涨跌幅`, `涨跌额`, `成交量`, `成交额`, `振幅`, `最高`, `最低`, `今开`, `昨收`, `量比`, `换手率` | Retained as raw current-market context; this slice does not replace the canonical quote or history categories. |
| `市盈率-动态`, `市净率` | Retained as raw provider fields only; no canonical metric, eligibility or valuation inference is made. |

The slice deliberately leaves `special_treatment` unresolved: current
risk-warning-board membership is positive raw evidence, while absence, dated
history and the filing-backed reason remain outside this acquisition contract.

## Phase 2.27 A-share main-shareholder raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_main_stock_holder` as a Sina A-share listing-scoped endpoint
with a required six-digit `stock` input. It returns all historical main-
shareholder rows with holder name, holding quantity, holding ratio, share-class
label, as-of date, announcement date and holder context. The rows are scoped by
the requested symbol but do not carry a canonical company identity in every
record.

The provider passes the requested A-share code, retains the complete response
as a `RawProviderRecord`, validates any non-null documented dates and records
the row count. The normalizer emits structured-data evidence only, marks
`governance_risk_level` as critically missing and emits
`AKSHARE_MAIN_SHAREHOLDERS_RAW_ONLY`; it creates no ownership, share-count,
dilution, buyback, issuance or valuation fact. H-share main-shareholder data
and filing-backed beneficial-control interpretation remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股东名称`, `股东说明` | Raw-only holder context; names and descriptions do not establish beneficial ownership, control or governance severity. |
| `持股数量`, `持股比例`, `股本性质` | Raw-only holding context; holder quantities and share classes do not establish the company's fully diluted economic share count or a canonical ownership fact. |
| `截至日期`, `公告日期` | Raw-only period/publication metadata; the dates are not silently collapsed into a financial-statement or governance period. |
| `股东总数`, `平均持股数` | Raw-only aggregate context; no concentration, valuation or governance metric is calculated. |

The slice deliberately leaves `governance_risk_level` unresolved: historical
holder rows do not establish beneficial control, materiality, related-party
context or a filing-backed governance conclusion.

## Phase 2.28 A-share trading-suspension raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_tfp_em` as an Eastmoney A-share endpoint with a required
`YYYYMMDD` `date` input. It returns the requested-date suspension/resumption
universe with listing code, name, suspension start/end dates, duration, reason,
market and expected resume date. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_tfp_em.py)
also shows that nullable suspension/resume dates are converted to date values
when available.

The provider validates the exact date request, rejects rows without an
explicit listing code or with invalid non-null event dates, filters the
universe to the requested A-share listing and retains every matching row as a
`RawProviderRecord`. The normalizer emits structured-data evidence only,
marks `special_treatment` and `governance_risk_level` as critically missing
and emits `AKSHARE_TRADING_SUSPENSIONS_RAW_ONLY`; it creates no canonical
status, governance, accounting or valuation fact. H-share suspension data and
filing-backed interpretation remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `代码`, `名称`, `所属市场` | Used only for explicit listing-boundary validation and raw event context; they do not create a canonical listing or status fact. |
| `停牌时间`, `停牌截止时间`, `预计复牌时间` | Preserved as nullable raw event dates; they are not collapsed into a complete current status or accounting period. |
| `停牌期限`, `停牌原因` | Preserved as raw event context; the reason does not establish special treatment, governance severity or filing content. |
| `序号` | Retained in the opaque upstream row; no ordering or duration metric is calculated. |

The slice deliberately leaves `special_treatment` and
`governance_risk_level` unresolved: a requested-date suspension universe is
not a complete status history and does not establish the legal, accounting or
governance reason behind an event.

## Phase 2.29 A-share restricted-share-release raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_restricted_release_queue_em` as a symbol-scoped Eastmoney
A-share endpoint. It accepts a six-digit `symbol` and returns historical
restricted-share release batches with release dates, shareholder counts,
planned/actual/remaining quantities, market-value and market-value-ratio
context, lock-up type and pre/post release observations. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_restricted_em.py)
shows that the endpoint is fetched for one requested symbol and that the
returned table may not retain a row-level security code.

The adapter selects this endpoint only when `SHARE_CAPITAL` carries the
explicit `view=restricted_release_queue` selector, passes the six-digit code,
retains every returned row and validates an optional row code plus the required
release date. The documentation labels the principal quantity fields in
shares and the market-value field in yuan, but the response does not establish
one canonical diluted-economic-share treatment, a settled share-count event
or a planned-versus-actual outcome suitable for a canonical fact.

The normalizer emits `AKSHARE_RESTRICTED_SHARE_RELEASES_RAW_ONLY`, marks
`normalized_diluted_economic_shares` as critically missing and creates no
canonical share, dilution, issuance, buyback or valuation fact. H-share
restricted-release coverage and filing-backed action interpretation remain
unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `解禁时间` | Required raw event identity; it is not silently treated as a financial-statement period or settled action date. |
| `解禁数量`, `实际解禁数量`, `未解禁数量` | Raw-only quantities; planned, actual and remaining states are not collapsed into one canonical share count. |
| `实际解禁数量市值`, `占总市值比例`, `占流通市值比例` | Raw market-value context; units and economic scope do not establish valuation or dilution facts. |
| `解禁股东数`, `限售股类型` | Raw release context; holder count and lock-up type do not classify issuance, buyback, split or dilution. |
| pre/post release change fields and prior close | Raw observations; no return, price-impact or governance metric is calculated. |

## Phase 2.30 A-share goodwill-impairment raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_sy_jz_em` as an Eastmoney A-share goodwill-impairment detail
endpoint. It accepts a required `YYYYMMDD` `date` and returns a report-date
universe with listing code/name, goodwill (`商誉`) and goodwill impairment
(`商誉减值`) amounts in yuan, provider ratios, net profit, announcement date
and market. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_sy_em.py)
shows the requested report date is passed to the upstream report-date filter;
the returned table itself does not provide a separate canonical report-period
field, so the adapter records the requested date in response metadata.

The provider validates explicit A-share listing codes and nullable announcement
dates, filters the returned universe to the requested listing and retains every
matching row as a `RawProviderRecord`. The amounts are useful discovery
evidence, but they do not establish the accounting entity, statement scope,
period basis or reconciliation required for canonical `goodwill` or
`impairment`. The normalizer therefore emits
`AKSHARE_GOODWILL_IMPAIRMENT_RAW_ONLY`, marks both fields as critically missing
and creates no canonical goodwill, impairment, profit, ratio or business-quality
fact. H-share goodwill coverage and filing-backed impairment interpretation
remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码`, `股票简称`, `交易市场` | Identity and market context only; the provider checks the code boundary but creates no canonical accounting fact. |
| `商誉`, `商誉减值` | Raw-only amount evidence. Both `goodwill` and `impairment` are `REQUIRES_PRIMARY_FILING`; entity, accounting scope, report period and reconciliation are not established. |
| `商誉占净资产比例`, `商誉减值占净资产比例`, `商誉减值占净利润比例` | Raw-only provider ratios; denominator, units and entity/period basis are not accepted as canonical metrics. |
| `净利润` | Raw-only profit context; the row does not establish parent versus consolidated entity, statement period or a canonical profit fact. |
| `公告日期` | Raw-only publication metadata; it is not silently treated as the report period or an impairment-recognition date. |
| `序号` | Retained in the opaque upstream row; no ordering or metric is calculated. |

## Phase 2.31 A/H ESG-rating raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents the no-argument Sina `stock_esg_rate_sina` endpoint. Its published
columns are component stock code (`成分股代码`), rating agency (`评级机构`),
rating (`评级`), rating quarter (`评级季度`), marker (`标识`) and trading
market (`交易市场`); the documented response mixes A-share `cn` and H-share
`hk` rows. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_esg_sina.py)
fetches a paginated response containing multiple agencies and quarters.

The provider validates the explicit code plus `cn`/`hk` market for every row,
filters the universe to the requested A/H listing and retains all matching
agency/quarter rows as raw structured evidence. Rating values may use
agency-specific letter or numeric scales, and `评级季度` is a provider
reporting label rather than an admitted financial-statement period. The
normalizer therefore emits `AKSHARE_ESG_RATINGS_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no canonical ESG
score, governance, Business Quality, financial or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `成分股代码`, `交易市场` | Required A/H identity boundary; code and `cn`/`hk` market must agree before provider filtering. |
| `评级机构` | Raw agency context; different providers are not treated as one comparable scoring system. |
| `评级` | Raw rating value only; letters, numeric values and agency-specific scales are not normalized into an ESG score or governance fact. |
| `评级季度` | Raw provider period label; it is not silently treated as a canonical statement period. |
| `标识` | Raw provider marker; it does not establish a governance conclusion or metric. |

## Phase 2.32 SSE margin-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_margin_detail_sse` as an SSE endpoint accepting an exact
`YYYYMMDD` `date`. Its full requested-date universe contains an explicit
security code/name, financing balance and financing/short-sale quantities. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_sse.py)
passes the date to the SSE detail request and renames the published columns.

The provider supports Shanghai A-share identifiers only, validates an explicit
security code and exact credit-transaction date on every returned row, filters
the universe to the requested listing and retains every matching row with
endpoint, date and row-count provenance. BSE detail and market-level margin
summaries are not part of this slice.

The fields describe customer financing against a security. They are not issuer
accounting debt, cash, leverage or a settled issuer reporting period. The
normalizer therefore emits `AKSHARE_MARGIN_TRADING_RAW_ONLY`, marks
`financial_debt` as critically missing and creates no canonical debt, cash,
margin, leverage or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `信用交易日期` | Exact requested observation boundary only; it is not an issuer accounting period. |
| `标的证券代码`, `标的证券简称` | Security identity, filtering and evidence context only; no issuer fact is inferred. |
| `融资余额`, `融资买入额`, `融资偿还额` | Raw amount evidence documented in yuan; customer financing positions/flows are not issuer financial debt, cash or issuer CFO. |
| `融券余量`, `融券卖出量`, `融券偿还量` | Raw security-lending quantities; they do not establish issuer shares, dilution, debt or valuation. |

## Phase 2.33 A-share external-guarantee raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_cg_guarantee_cninfo` as a CNINFO company-governance
external-guarantee endpoint. Its inputs are a board/universe `symbol` and
`YYYYMMDD` `start_date`/`end_date`; the documented defaults are `全部`,
`20180630` and `20210927`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_guarantee.py)
returns A-share universe rows containing code/name, announcement-statistics
interval, guarantee count and amount, parent-company equity and the published
guarantee-to-net-assets ratio.

The provider calls the documented `symbol="全部"` universe and filters every
row to the requested A-share code after requiring an explicit code. It retains
all matching rows and records the upstream symbol, date range, scope, and
upstream/selected row counts. There is no H-share endpoint in this slice.
The documented amount and equity fields are in 万元, but the date-range
aggregate does not establish a settled quasi-debt amount, guarantee purpose,
legal status, canonical period/entity scope or a governance judgment. The
normalizer therefore emits `AKSHARE_EXTERNAL_GUARANTEES_RAW_ONLY`, marks
`material_quasi_debt`, `major_illegal_guarantee` and `governance_risk_level` as
critically missing, and creates no canonical fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Explicit A-share identity, filtering and evidence context only. |
| `公告统计区间` | Raw aggregate interval; it is not silently used as a canonical statement or event period. |
| `担保笔数`, `担保金额` | Raw date-range count and amount; the amount is not promoted to settled quasi-debt. |
| `归属于母公司所有者权益` | Raw provider denominator in 万元; it is not a canonical equity period/entity mapping. |
| `担保金融占净资产比例` | Raw published ratio; it does not establish a canonical ratio, illegal-guarantee status or governance level. |

## Phase 2.34 A-share individual ownership-pledge detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_gpzy_individual_pledge_ratio_detail_em` as an Eastmoney
symbol-scoped A-share endpoint. It accepts a six-digit `symbol` and returns
historical important-shareholder pledge rows with explicit code, holder,
quantity/ratio, pledge institution, prices, announcement/start/end dates and
status. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gpzy_em.py)
applies a `SECURITY_CODE` filter to the documented detail dataset.

The provider selects this endpoint only for an explicit
`OWNERSHIP_PLEDGE` request with `view=individual_pledge_detail`, passes only
the six-digit code, validates the explicit code and any populated event dates,
and preserves all rows as a listing-scoped raw response. The quantities,
ratios, prices and status do not establish a canonical diluted share count,
settled pledged cash/debt-equivalent amount or governance judgment. The
normalizer therefore emits `AKSHARE_INDIVIDUAL_PLEDGE_DETAIL_RAW_ONLY`, marks
`governance_risk_level` critically missing and creates no canonical fact.
H-share coverage and filing-backed pledge interpretation remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码`, `股票简称` | Listing identity/context; explicit code is checked against the request. |
| `股东名称`, `质押机构`, `状态` | Raw holder/counterparty/status context; no beneficial-control or governance conclusion. |
| `质押股份数量`, `占所持股份比例`, `占总股本比例` | Raw quantity/ratios; no fully diluted share, dilution or canonical pledge amount is inferred. |
| `最新价`, `质押日收盘价`, `预估平仓线` | Raw price/collateral context; no liquidation-risk, debt or valuation metric is calculated. |
| `公告日期`, `质押开始日期`, `质押结束日期` | Raw event dates; no single canonical action/statement period is selected. |

## Phase 2.35 A-share company-litigation raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_cg_lawsuit_cninfo` as a CNINFO company-governance
litigation endpoint. Its inputs are a board/universe `symbol` and
`YYYYMMDD` `start_date`/`end_date`; the documented defaults are `全部`,
`20180630` and `20210927`. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_lawsuit.py)
returns A-share universe rows containing code/name, an announcement-statistics
interval, lawsuit count and lawsuit amount, with the amount documented in 万元.

The provider calls the documented `symbol="全部"` universe and filters every
row to the requested A-share code after requiring an explicit code. It retains
all matching rows and records the upstream symbol, date range, scope and
upstream/selected row counts. There is no H-share endpoint in this slice. The
date-range aggregate does not establish a canonical event or statement period,
legal status, accounting entity/scope or a material expected cash obligation.
The normalizer therefore emits `AKSHARE_LITIGATION_RAW_ONLY`, marks
`material_quasi_debt` and `governance_risk_level` as critically missing, and
creates no canonical litigation, quasi-debt, governance or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Explicit A-share identity, filtering and evidence context only. |
| `公告统计区间` | Raw aggregate interval; it is not silently used as a canonical statement or event period. |
| `诉讼次数` | Raw date-range count; it does not establish materiality or a governance conclusion. |
| `诉讼金额` | Raw amount documented in 万元; it is not promoted to settled quasi-debt or a valuation adjustment. |

## Phase 2.36 A-share CNINFO equity-mortgage raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_cg_equity_mortgage_cninfo` as a CNINFO company-governance
equity-pledge endpoint. It accepts a `YYYYMMDD` `date` parameter (documented
default `20210930`) and returns rows with explicit A-share code, announcement
date, pledgor/pledgee, pledge quantities, percentage fields and an opaque
pledge-event description. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_cg_equity_mortgage.py)
uses the CNINFO thematic-statistics response and preserves those rows as
tabular output.

The provider selects this endpoint only for an explicit
`OWNERSHIP_PLEDGE` request with `view=equity_mortgage`, passes the documented
date (or its documented default), validates explicit listing identity and any
populated announcement date, filters the universe to the requested A-share
code and preserves every matching row. The query date is a source request
boundary, not an event or accounting period. The documented quantities and
ratios do not establish a fully diluted share count, settled pledged
cash/debt-equivalent amount, beneficial control or a governance judgment. The
normalizer therefore emits `AKSHARE_EQUITY_MORTGAGE_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no canonical fact.
H-share coverage and filing-backed pledge interpretation remain unresolved.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `股票代码`, `股票简称` | Explicit A-share identity, filtering and evidence context only. |
| `公告日期` | Validated publication/event metadata; it is not silently selected as a canonical pledge or statement period. |
| `出质人`, `质权人`, `质押事项` | Raw holder, counterparty and event-description context; no control, legal-status or governance conclusion. |
| `质押数量`, `质押解除数量` | Raw quantities documented in 万股; no fully diluted share, issuance, buyback or pledged-cash fact is inferred. |
| `占总股本比例`, `累计质押占总股本比例` | Raw published ratios; no canonical dilution, debt-equivalent or governance metric is calculated. |

## Phase 2.37 SZSE margin-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_margin_detail_szse` as an SZSE endpoint accepting an exact
`YYYYMMDD` `date`. Its full requested-date universe contains an explicit
security code/name, financing balance and financing/short-sale quantities in
the documented yuan and share/lot units. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_szse.py)
passes the date to the SZSE report request and returns the published columns;
the documented rows do not include a row-level observation date.

The provider supports Shenzhen A-share identifiers, validates an explicit
security code on every returned row, filters the universe to the requested
listing and retains the matching row with endpoint, request-date and row-count
provenance. The request date is the observation boundary for this endpoint;
the adapter does not add a synthetic date to the opaque payload. BSE detail and
market-level margin summaries remain outside this slice.

The fields describe customer financing against a security. They are not issuer
accounting debt, cash, leverage or a settled issuer reporting period. The
normalizer therefore emits `AKSHARE_MARGIN_TRADING_RAW_ONLY`, marks
`financial_debt` as critically missing and creates no canonical debt, cash,
margin, leverage or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Security identity, filtering and evidence context only; no issuer fact is inferred. |
| `融资买入额`, `融资余额`, `融券余额`, `融资融券余额` | Raw amount evidence documented in yuan; customer financing positions/flows are not issuer financial debt, cash or issuer CFO. |
| `融券卖出量`, `融券余量` | Raw security-lending quantities documented in shares/lots; they do not establish issuer shares, dilution, debt or valuation. |
| request `date` | Exact upstream observation boundary retained in request and response metadata; it is not an issuer accounting period or a fabricated row field. |

## Phase 2.38 A-share shareholder-count raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hold_num_cninfo` as a CNINFO thematic-statistics endpoint
accepting an exact quarter-end `date` from `20170331` onward. The [official
implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_num_cninfo.py)
returns the A-share universe with explicit listing code/name, `变动日期`,
current/prior shareholder counts, count change percentage, current/prior
average holdings and average-holdings change percentage.

The provider selects this endpoint only when the `SHAREHOLDER_HOLDINGS`
request includes `date`, validates the supported quarter-end date and every
row's explicit code and matching `变动日期`, then filters the universe to the
requested A-share listing. The selected rows and request/observation dates are
retained as raw evidence; the no-parameter request continues to use the
symbol-scoped main-shareholder endpoint.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Explicit A-share identity, listing filtering and evidence context only. |
| `变动日期` | Validated against the requested exact quarter-end date and retained as raw observation metadata; it is not silently promoted to a statement or governance period. |
| `本期股东人数`, `上期股东人数`, `股东人数增幅` | Raw shareholder-count evidence; no canonical concentration, ownership or governance metric is calculated. |
| `本期人均持股数量`, `上期人均持股数量`, `人均持股数量增幅` | Raw average-holding evidence; the documented unit/aggregation does not establish a company-level diluted-economic-share fact. |
| request `date` | Exact CNINFO quarter-end boundary retained in request and response metadata; it does not become a fabricated provider field. |

The slice deliberately leaves `governance_risk_level` unresolved and emits
`AKSHARE_SHAREHOLDER_COUNTS_RAW_ONLY`. H-share shareholder-count coverage,
beneficial-control interpretation and filing-backed analysis remain outside
this acquisition contract.

## Phase 2.39 BSE margin-detail raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_margin_detail_bse` as a Beijing Stock Exchange endpoint
accepting an exact `YYYYMMDD` `date`. Its full requested-date universe contains
explicit security code/name, financing balances, financing/short-sale
quantities and financing/short-sale balances; amounts are documented in yuan
and quantities in shares. The [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_margin_bse.py)
paginates the BSE detail endpoint, zero-pads security codes and returns the
published columns.

The provider supports explicit Beijing A-share identifiers, validates every
returned security code, filters the full universe to the requested listing and
retains endpoint, request-date and row-count provenance. BSE rows do not
contain a row-level observation date, so the exact request date remains the
metadata observation boundary; the adapter does not add a synthetic date to
the opaque payload.

These fields describe customer financing against a security rather than the
issuer's accounting debt, cash or leverage. The normalizer therefore emits
`AKSHARE_MARGIN_TRADING_RAW_ONLY`, leaves `financial_debt` critically missing
and creates no canonical debt, cash, margin, leverage or valuation fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Explicit BSE security identity and listing-filter context only; no issuer fact is inferred. |
| `融资买入额`, `融资余额`, `融券余额`, `融资融券余额` | Raw amount evidence documented in yuan; customer financing positions/flows are not issuer financial debt, cash or issuer CFO. |
| `融券卖出量`, `融券余量` | Raw security-lending quantities documented in shares; they do not establish issuer shares, dilution, debt or valuation. |
| request `date` | Exact BSE observation boundary retained in request and response metadata; it is not an issuer accounting period or a fabricated row field. |

## Phase 2.40 A/H HSGT individual-holdings raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
documents `stock_hsgt_individual_em` as an Eastmoney endpoint accepting a
`symbol` for either an A-share or H-share listing. It publishes a historical
holding-date series with closing price, change percentage, holding quantity,
holding market value, holding ratio and market-specific change fields. The
[official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hsgt_em.py)
dispatches six-digit symbols to the A-share path and five-digit symbols to the
H-share path, then drops the row-level security identity from the returned
columns.

The provider selects this endpoint only for an explicit
`SHAREHOLDER_HOLDINGS` request with `view=hsgt_individual`, passes the
canonical listing code and retains the complete symbol-scoped response. It
validates each holding date and any optional returned identity, while the
request scope remains the binding entity boundary. The data describes
north-/southbound investor holdings, not complete beneficial ownership or a
company share-capital series. The normalizer emits
`AKSHARE_HSGT_INDIVIDUAL_HOLDINGS_RAW_ONLY`, marks
`governance_risk_level` as critically missing and creates no canonical fact.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `持股日期` | Validated historical observation date; it is not silently treated as a statement, ownership or governance period. |
| `当日收盘价`, `当日涨跌幅` | Raw market context; this slice does not replace the canonical quote/history categories. |
| `持股数量`, `持股市值`, `持股数量占A股百分比` | Raw investor-position quantity/value/ratio; no beneficial-control, concentration or diluted-share fact is inferred. |
| A-share `今日增持股数`, `今日增持资金`, `今日持股市值变化` | Raw daily change fields; they are not issuer buyback, issuance, shareholder-return or cash-flow facts. |
| H-share `持股市值变化-1日`, `持股市值变化-5日`, `持股市值变化-10日` | Raw lookback changes; they are not collapsed into a common A/H return or ownership metric. |
| request `symbol` and `view` | Listing and endpoint-selection scope retained in the request/evidence provenance; no row-level listing code is invented after the official implementation removes it. |

The slice deliberately leaves `governance_risk_level` unresolved. Investor
holding quantities, market values, ratios and changes do not establish
beneficial control, shareholder concentration, issuer corporate-action cash or
a company-level diluted-share series.

## Phase 2.41 A-share actual-controller holding-change raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_cninfo.py)
document `stock_hold_control_cninfo` as a CNINFO A-share full-universe endpoint.
Its `symbol` selector accepts `单独控制`, `实际控制人`, `一致行动人`, `家族控制`
or `全部`; the provider exposes that selector through the explicit
`view=control_changes` request and optional `control_type` parameter.

The provider validates an explicit `证券代码` and `变动日期` on every upstream
row, filters the full universe to the requested A-share listing, and preserves
the selected rows plus endpoint, control-scope and row-count provenance. The
response is retained as raw evidence only. Controller names, holding quantity,
holding ratio and control type are not promoted into beneficial-control,
concentration, governance, share-count or dilution facts without filing-backed
legal, entity and point-in-time interpretation.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `证券代码`, `证券简称` | Explicit A-share identity, listing filtering and evidence context only. |
| `变动日期` | Validated change-date field and retained as raw historical observation metadata; it is not silently treated as a filing, legal-effective or accounting period. |
| `实际控制人名称`, `直接控制人名称` | Raw controller-name evidence only; no beneficial-control or governance conclusion is inferred. |
| `控股数量` | Raw published quantity in 万股; its entity, share-class and point-in-time semantics do not establish canonical shares or dilution. |
| `控股比例` | Raw published percentage; it is not a canonical ownership, concentration or control metric. |
| `控制类型` and request `control_type` | Raw provider classification and query scope; provider categories are not collapsed into a legal control conclusion. |
| request `view=control_changes` and upstream `symbol` | Explicit endpoint-selection and control-scope provenance retained in the request/evidence metadata. |

The slice emits `AKSHARE_CONTROL_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical fact.
Filing-backed control, governance and economic-scope analysis remains outside
this acquisition contract.

## Phase 2.42 A-share management-holding raw slice

The current [AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hold_control_em.py)
document `stock_hold_management_detail_em` as a no-argument Eastmoney
management/related-person holding-change universe. The adapter selects it only
with `view=management_detail`, validates every returned `代码` and `日期`,
filters the full response to the requested A-share listing and preserves the
upstream and selected row counts in response metadata.

| Raw upstream item | Phase 2 treatment |
| --- | --- |
| `日期`, `代码`, `名称` | Validated change date and explicit A-share listing identity used for universe filtering; the date is not silently treated as a filing, legal-effective or accounting period. |
| `变动人`, `董监高人员姓名`, `职务`, `变动人与董监高的关系` | Raw person, management-role and relationship evidence only; no beneficial-control or governance conclusion is inferred. |
| `变动股数`, `成交均价`, `变动金额`, `变动比例` | Raw transaction quantity, price, amount and ratio; no issuer buyback, issuance, cash-flow, return or dilution fact is inferred. |
| `变动原因`, `持股种类` | Raw provider reason and share-class labels; they are not collapsed into a canonical corporate-action classification. |
| `变动后持股数`, `开始时持有`, `结束后持有` | Raw beginning/ending holdings; they do not establish a company-level share count, fully diluted economic shares or beneficial ownership. |
| request `view=management_detail` | Explicit endpoint-selection scope retained in request/evidence provenance; the documented endpoint receives no upstream arguments. |

The normalizer emits `AKSHARE_MANAGEMENT_HOLDINGS_RAW_ONLY`, leaves
`governance_risk_level` critically missing and creates no canonical ownership,
share-count, dilution, buyback, issuance, return or valuation fact. Filing-
backed person identity, legal relationship and point-in-time interpretation
remain outside this acquisition contract.

## Eligibility, identity and market context

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `listing_years` | `DERIVED_DETERMINISTIC` | Derive from a verified listing/first-trading date and `as_of`; do not infer from available history length. |
| `special_treatment` | `STRUCTURED_AUTO` | Exchange/provider status can be imported when the listing and observation date are explicit. |
| `parent_equity` | `STRUCTURED_AUTO` | Reported parent-attributable equity for the matching period. |
| `current_price` | `STRUCTURED_AUTO` | Quote for the requested listing and timestamp. |
| `current_market_cap` | `DERIVED_DETERMINISTIC` | Prefer canonical price × normalized share count; a provider headline market cap is a cross-check, not a replacement. |
| `listing_equivalent_market_cap` | `DERIVED_DETERMINISTIC` | Derive for the selected listing, including any explicit FX/share mapping. |
| `actual_aggregate_company_market_cap` | `DERIVED_DETERMINISTIC` | Aggregate A/H listings only under the existing multi-listing contract; never merge listing prices. |
| `normalized_diluted_economic_shares` | `DERIVED_DETERMINISTIC` | Derive only from verified share-capital facts and corporate actions after entity/class, unit and dilution treatment are explicit; the current AKShare raw slices do not supply it. |

Company `primary_listing`, `other_listings`, sector and reporting currency are
identity/context fields, not valuation facts. A sector-specific `special_model`
classification is `UNAVAILABLE` for automatic Phase 2 inference when it cannot
be established by a stable policy; it must not be guessed from a provider's
free-text industry label.

## CDC inputs and diagnostics

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `reported_cfo` | `STRUCTURED_AUTO` | Reported operating cash flow for the exact statement period and entity. |
| `parent_net_profit` | `STRUCTURED_AUTO` | Parent-attributable net profit for the exact period. |
| `consolidated_net_profit` | `STRUCTURED_AUTO` | Consolidated net profit for the exact period. |
| `parent_economic_share` | `DERIVED_DETERMINISTIC` | Derive from explicit parent/consolidated facts only when the ownership basis is compatible. |
| `cash_interest_paid_total` | `REQUIRES_PRIMARY_FILING` | Cash-versus-accrual and statement classification must be verified from the statement/notes. |
| `cash_interest_in_cfo` | `REQUIRES_PRIMARY_FILING` | Structured interest expense is not proof of cash-flow classification. |
| `cash_interest_outside_cfo` | `DERIVED_DETERMINISTIC` | Difference only after the two filing-supported interest facts are accepted. |
| `non_recurring_operating_inflows` | `REQUIRES_PRIMARY_FILING` | Grants, disposals and other one-offs require line-item/note review. |
| `operating_outflows_misclassified_outside_cfo` | `REQUIRES_PRIMARY_FILING` | Requires a filing-supported economic reclassification. |
| `ppe_purchase_cash` | `STRUCTURED_AUTO` | Use a matching cash-flow line when it clearly represents cash purchases. |
| `intangible_purchase_cash` | `STRUCTURED_AUTO` | Use a matching line only when capitalization scope is clear. |
| `other_operating_long_term_asset_cash` | `REQUIRES_PRIMARY_FILING` | Aggregates can hide operating reinvestment and require note review. |
| `capex_payables_change` | `REQUIRES_PRIMARY_FILING` | Requires non-cash capex/payables disclosure; do not derive from total payables. |
| `lease_principal_outside_cfo` | `REQUIRES_PRIMARY_FILING` | Lease cash-flow classification is not safe to infer from total lease debt. |
| `capitalized_dev_already_in_capex` | `REQUIRES_PRIMARY_FILING` | The no-double-counting claim needs accounting-note support. |
| `capitalized_development_cash_outside_capex` | `REQUIRES_PRIMARY_FILING` | Requires explicit disclosure and scope reconciliation. |
| `acquisition_cash` | `STRUCTURED_AUTO` | A clearly reported acquisition cash-flow line may be imported; unusual transactions still need review. |
| `strategic_investment_cash` | `REQUIRES_PRIMARY_FILING` | Economic classification between operating investment and strategic assets is filing-derived. |
| `working_capital_contribution` | `REQUIRES_PRIMARY_FILING` | The sign and distortion interpretation require component-level cash-flow review. |
| `equity_financing`, `debt_financing`, `other_financing` | `STRUCTURED_AUTO` | Reported financing cash-flow categories may be retained as diagnostics; they are not used to manufacture CDC or shareholder return. |
| `core_cdc` | `DERIVED_DETERMINISTIC` | Engine-derived diagnostic; never accept a provider's precomputed “cash generation” as authoritative. |

The normalized five-year continuity, normalized CDC and CDC yield are engine
outputs, not provider-supplied facts. If any required annual input is null, the
normalizer must preserve that null and let the existing CDC stage expose the
established missing-data flag.

## Net-cash inputs

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `book_cash` | `STRUCTURED_AUTO` | Reported cash and equivalents for the matching consolidated period. |
| `reported_interest_bearing_debt` | `STRUCTURED_AUTO` | Reported aggregate debt, retained as a reported fact. |
| `hard_cash` | `REQUIRES_PRIMARY_FILING` | C0 accessibility classification requires notes and restriction review. |
| `near_cash` | `REQUIRES_PRIMARY_FILING` | C1 haircut/eligibility requires instrument and liquidity details. |
| `liquid_financial_assets` | `REQUIRES_PRIMARY_FILING` | C2 treatment requires instrument, liquidity and ownership review. |
| `strategic_investments` | `REQUIRES_PRIMARY_FILING` | C3 assets are not automatically cash-equivalent. |
| `restricted_cash` | `REQUIRES_PRIMARY_FILING` | The amount and release conditions must come from primary disclosure. |
| `pledged_deposits` | `REQUIRES_PRIMARY_FILING` | Pledges and enforceability cannot be inferred from total cash. |
| `financial_debt` | `STRUCTURED_AUTO` | A reported interest-bearing debt total may be imported when its scope matches the contract; debt-equivalent additions remain explicit. |
| `lease_debt` | `REQUIRES_PRIMARY_FILING` | Requires lease-liability scope and economic treatment. |
| `supplier_finance` | `REQUIRES_PRIMARY_FILING` | Requires supplier-finance or reverse-factoring disclosure. |
| `recourse_factoring` | `REQUIRES_PRIMARY_FILING` | Recourse and derecognition treatment require notes. |
| `debt_like_hybrids` | `REQUIRES_PRIMARY_FILING` | Convertibles, perpetuals and preferred-like instruments require terms review. |
| `material_quasi_debt` | `REQUIRES_PRIMARY_FILING` | Guarantees and other quasi-debt require economic interpretation of primary facts. |
| `subsidiary_cash` | `REQUIRES_PRIMARY_FILING` | Consolidated cash must be decomposed by subsidiary and ownership. |
| `subsidiary_debt` | `REQUIRES_PRIMARY_FILING` | Same scope and basis as subsidiary cash are required. |
| `subsidiary_ownership` | `STRUCTURED_AUTO` | Legal ownership can be imported when the entity and class are explicit; economic attribution may still need review. |
| `upstreamability_factor` | `REQUIRES_JUDGMENT` | Accessibility to ordinary shareholders is not a database ratio. |
| `debt_due_within_one_year` | `REQUIRES_PRIMARY_FILING` | Maturity and refinancing exposure require the debt schedule/notes. |
| `normalized_ebitda` | `REQUIRES_JUDGMENT` | Reported EBITDA is not automatically normalized EBITDA. |
| `cash_interest_expense` | `REQUIRES_PRIMARY_FILING` | Cash interest and accrual interest need reconciliation. |
| `minority_profit` | `STRUCTURED_AUTO` | Reported non-controlling-interest profit for the matching period. |
| `minority_equity` | `STRUCTURED_AUTO` | Reported non-controlling-interest equity for the matching period. |
| `total_equity` | `STRUCTURED_AUTO` | Reported total equity for the matching period. |
| `cash_authenticity_verified` | `REQUIRES_PRIMARY_FILING` | Verification requires bank/cash notes, audit context and restriction review. |
| `cash_upstreamability_verified` | `REQUIRES_PRIMARY_FILING` | Verification requires subsidiary and legal/accessibility evidence. |
| `cash_governance_factor` | `REQUIRES_JUDGMENT` | A governance haircut is an explicit interpretation, not a vendor field. |
| `cash_governance_class` | `REQUIRES_JUDGMENT` | Classification requires capital-allocation and governance evidence. |

`strict_cash`, `owner_realizable_net_cash`, `valuation_net_cash`, adjusted EV,
coverage ratios and the owner net-cash ratio are deterministic outputs. They
are `UNAVAILABLE` to Phase 2 provider classes and must not be imported as
provider “metrics.”

## Through Return and capital actions

### Phase 2.7 dividend event boundary

The AKShare `DIVIDENDS` category currently retains A-share and H-share
dividend event rows, plus the explicit-date A-share distribution snapshot, as
raw structured evidence only. The normalizer does not map a canonical cash
fact because the documented feeds expose per-share or per-10-share plans,
distribution ratios, plan strings, fiscal years and event dates with different
period and classification semantics. In particular, an event row or snapshot
is not silently converted into `ordinary_dividend_cash`,
`special_dividend_cash` or `payout_ratio`; the unresolved amount, entity,
period and ordinary-versus-special questions remain for a filing-backed
mapping review.

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `ordinary_dividend_cash` | `STRUCTURED_AUTO` | Reported declared/paid amount may be imported when ordinary versus special and period are explicit; the current AKShare event and distribution-snapshot feeds remain raw-only. |
| `special_dividend_cash` | `REQUIRES_PRIMARY_FILING` | Special-return classification and payment period require formal disclosure. |
| `formal_payout_floor` | `REQUIRES_PRIMARY_FILING` | A policy floor must be supported by a formal company disclosure. |
| `payout_ratio` | `DERIVED_DETERMINISTIC` | Derive from accepted dividend and profit facts; do not trust a vendor ratio with a different denominator. |
| `payout_policy_formal` | `REQUIRES_PRIMARY_FILING` | Formality is a disclosure claim, not a time series statistic. |
| `payout_policy_confidence` | `REQUIRES_JUDGMENT` | Confidence records the quality of the policy interpretation. |
| `fully_diluted_shares` | `DERIVED_DETERMINISTIC` | Normalize share classes, dilution and corporate actions before using the count; the current A-share share-capital history is raw-only. |
| `buyback_cash` | `STRUCTURED_AUTO` | A reported buyback amount may be imported only when its settled period, action status, currency/unit and economic scope are explicit; the current AKShare repurchase slice remains raw-only. |
| `share_issuance_cash` | `STRUCTURED_AUTO` | Reported issuance proceeds may be imported for the matching action/period. |
| `share_split_factor` | `STRUCTURED_AUTO` | A formal split/consolidation factor can be imported when effective date is clear. |
| `buyback_recurring` | `REQUIRES_PRIMARY_FILING` | Recurrence is a policy/history conclusion, not a single transaction amount. |
| `net_diluted_share_reduction_verified` | `REQUIRES_PRIMARY_FILING` | Requires issued shares, cancellations and dilution reconciliation. |
| `special_dividend` | `REQUIRES_PRIMARY_FILING` | Formal event classification is required. |

Normalized parent profit, distributable base, conservative payout ratio,
dividend Through Return, verified buyback credit and total Through Return are
engine results or filing-supported inputs to the engine. A provider class must
not calculate or inject those outputs.

## Valuation inputs and safeguards

Valuation consumes canonical quote/listing context plus deterministic CDC,
Through Return and net-cash results. In particular:

- `current_price` may be structured data;
- market-cap and share-count equivalents are deterministic projections;
- `normalized_parent_core_cdc`, `distributable_base`, recurring shareholder
  cash, owner-realizable net cash, valuation net cash and adjusted EV are
  engine-owned results;
- `cash_governance_factor` remains judgment-dependent and cannot be inferred
  from a cash balance;
- a missing or unresolved operating base keeps the existing valuation state
  unavailable; it is never replaced by zero.

## Governance, data quality and Business Quality

| Normalized field | Status | Boundary note |
| --- | --- | --- |
| `accounting_opinion` | `REQUIRES_PRIMARY_FILING` | Use the formal audit opinion, not an aggregator label. |
| `governance_risk_level` | `REQUIRES_JUDGMENT` | Requires evidence synthesis and counter-evidence. |
| `controlling_shareholder_fund_occupation` | `REQUIRES_PRIMARY_FILING` | Requires formal disclosure or regulator/exchange evidence. |
| `major_illegal_guarantee` | `REQUIRES_PRIMARY_FILING` | Requires formal disclosure or regulator/exchange evidence. |
| `revenue` | `STRUCTURED_AUTO` | Reported revenue for the matching statement period. |
| `core_revenue` | `REQUIRES_JUDGMENT` | Core-business scope is an analytical classification. |
| `operating_profit` | `STRUCTURED_AUTO` | Reported operating profit where the accounting definition is explicit. |
| `gross_margin`, `ebit_margin`, `roic` | `DERIVED_DETERMINISTIC` | Derive from accepted numerator/denominator facts. |
| `recurring_revenue_ratio` | `REQUIRES_JUDGMENT` | Recurrence requires business-model interpretation. |
| `largest_customer_ratio`, `top5_customer_ratio` | `REQUIRES_PRIMARY_FILING` | Customer concentration belongs to notes/operating disclosures. |
| `channel_concentration`, `critical_supplier_concentration` | `REQUIRES_PRIMARY_FILING` | Requires primary operating disclosures and scope checks. |
| `asp`, `asp_change`, `volume`, `volume_change` | `REQUIRES_PRIMARY_FILING` | Product-level operating data needs company/industry disclosure. |
| `market_share` | `REQUIRES_JUDGMENT` | Definition, market boundary and source quality require judgment. |
| `capex_intensity`, `invested_capital`, `nopat` | `DERIVED_DETERMINISTIC` | Derive only after the relevant economic classifications are accepted. |
| `normalized_operating_nwc` | `REQUIRES_PRIMARY_FILING` | Working-capital normalization needs line-item and business context. |
| `m_and_a_cash`, `goodwill`, `impairment` | `REQUIRES_PRIMARY_FILING` | Reported amounts may be structured, but material transaction/impairment scope needs primary review. |
| `revenue_cagr_5y`, `profit_cv`, `core_cdc_cv` | `DERIVED_DETERMINISTIC` | Derive from complete, point-in-time annual series. |
| `cycle_phase` | `REQUIRES_JUDGMENT` | A recent price or one strong year is not a cycle classification. |
| `demand_classification` | `REQUIRES_JUDGMENT` | Demand durability is a Business Quality judgment. |
| `structural_demand_decline` | `REQUIRES_JUDGMENT` | Requires evidence of structural rather than temporary change. |
| `sustainable_core_profit_ratio`, `core_profit_ratio`, `core_profit_to_normalized_total_profit` | `REQUIRES_JUDGMENT` | Core/non-core and sustainability classifications belong to filing/evidence review. |
| `non_core_profit_ratio`, `normalized_core_profit`, `core_operating_profit`, `normalized_total_profit` | `REQUIRES_PRIMARY_FILING` | Amounts require primary line-item and one-off reconciliation before deterministic ratios. |
| `non_core_profit_non_recurring`, `non_recurring_profit_dependence`, `non_core_profit_is_non_recurring` | `REQUIRES_JUDGMENT` | Hard business-gate triggers require explicit evidence and interpretation. |
| `core_business_cash_generation` | `DERIVED_DETERMINISTIC` | May be derived only from complete canonical CDC history; a provider label is not enough. |
| `structural_disruption`, `structural_disruption_revenue_ratio`, `displaced_product_revenue_ratio`, `rapidly_displaced_revenue_ratio` | `REQUIRES_JUDGMENT` | Disruption exposure and replacement economics are evidence judgments. |
| `replacement_earnings_engine` | `REQUIRES_JUDGMENT` | Requires a credible replacement path assessment. |
| `single_point_survival_dependency`, `single_point_dependency_ratio` | `REQUIRES_JUDGMENT` | Dependency and survivability are not structured ratios. |

The `BusinessQuality` eight-dimension score and its evidence lineage are not
structured-provider outputs. They remain an explicit assessment consumed by
the existing deterministic scorer. Until the filing/evidence layer exists,
these judgments stay `UNAVAILABLE` to automatic Phase 2 normalization and the
existing gate remains `NOT_EVALUATED` when no assessment is supplied.

## Phase 3.56 Sina index daily-history raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_zh.py)
document `stock_zh_index_daily` as a Sina index-level full-history endpoint.
The adapter selects it only under `MARKET_HISTORY` with explicit
`view=index_daily`, accepts Shanghai 000xxx or Shenzhen 399xxx index-shaped
IDs, and preserves the exact six-field response before returning the raw
record. The official wrapper fetches Sina's encrypted JavaScript K-line result
with `d=2020_2_4` and decodes it with `hk_js_decode` and `py_mini_racer`.

| Raw upstream item | Phase 3.56 treatment |
| --- | --- |
| `date` | Required parseable observation date; rows must be strictly ascending and are retained as row-level history metadata. |
| `open`, `high`, `low`, `close`, `volume` | Required finite numeric or null fields; the documentation does not declare a canonical unit for these values, so they remain raw evidence only. |
| request `view=index_daily` and listing-shaped index ID | Explicit Shanghai 000xxx/Shenzhen 399xxx index routing; `index_scoped_request=true`, `listing_scoped_request=false`, `date_binding=row_only` and full-history replay scope are recorded. |
| upstream `symbol` and fixed `d=2020_2_4` | Lower-prefixed dynamic symbol, fixed parameter, source URL, decoder steps, field order and row counts remain replay metadata. |

The provider rejects stock-listing, B-share, H-share, Beijing, missing or
unexpected-parameter requests, missing/unexpected/reordered fields, invalid or
non-ascending dates and non-finite/non-numeric values. The normalizer emits
`AKSHARE_INDEX_DAILY_HISTORY_RAW_ONLY` and creates no canonical daily-history,
return, valuation or accounting fact: an index-level series has no
listing/entity accounting scope. The response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 3.57 Tencent index daily-history raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_zh.py)
document `stock_zh_index_daily_tx` as a Tencent index-level daily-history
endpoint with optional `start_date` and `end_date` bounds. The adapter selects
it only under `MARKET_HISTORY` with explicit `view=tencent_index_daily`, accepts
Shanghai 000xxx or Shenzhen 399xxx index-shaped IDs, and preserves the exact
six-field response order before returning the raw record. The official wrapper
fetches yearly qfq data, uses an earliest-date lookup when the start bound is
empty, prefers the qfq series and filters the inclusive requested range.

| Raw upstream item | Phase 3.57 treatment |
| --- | --- |
| `date` | Required parseable observation date; rows must stay within any explicit inclusive bounds and be strictly ascending. |
| `open`, `close`, `high`, `low` | Required finite numeric or null front-adjusted index OHLC fields; the documentation does not declare a canonical unit, so they remain raw evidence only. |
| `amount` | Required finite numeric or null amount field; the documentation declares the unit as `lots`, and it remains raw evidence only. |
| request `view=tencent_index_daily` and listing-shaped index ID | Explicit Shanghai 000xxx/Shenzhen 399xxx index routing; `index_scoped_request=true`, `listing_scoped_request=false`, `date_binding=row_and_request` and requested-range replay scope are recorded. |
| request `start_date`/`end_date` and Tencent qfq fetch | Empty defaults are preserved as empty provider arguments; normalized explicit dates, qfq adjustment, yearly partitioning, source/auxiliary URLs, fixed/dynamic parameters and wrapper transformations remain replay metadata. |

The provider rejects stock-listing, B-share, H-share, Beijing, missing or
unexpected-parameter requests, malformed or reversed date ranges,
missing/unexpected/reordered fields, invalid or out-of-range dates and
non-finite/non-numeric values. The normalizer emits
`AKSHARE_TENCENT_INDEX_DAILY_HISTORY_RAW_ONLY` and creates no canonical
daily-history, return, valuation or accounting fact: the always-front-adjusted
index series has no listing/entity accounting scope. The response remains
outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.58 Eastmoney index daily-history raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_zh.py)
document `stock_zh_index_daily_em` as an Eastmoney index-level daily-history
endpoint with optional `start_date` and `end_date` bounds. The adapter selects
it only under `MARKET_HISTORY` with explicit `view=index_daily_em`, accepts
Shanghai 000xxx, Shenzhen 399xxx or Beijing 899xxx index-shaped IDs, maps
market prefixes to Eastmoney `secid` values and preserves the exact seven-field
response order. The official wrapper requests daily K-lines with `fqt=0`, drops
the internal eighth column and converts the six numeric fields.

| Raw upstream item | Phase 3.58 treatment |
| --- | --- |
| `date` | Required parseable observation date; rows must stay within the inclusive requested bounds and be strictly ascending. |
| `open`, `close`, `high`, `low`, `volume`, `amount` | Required finite numeric or null fields; the documentation does not declare canonical units for these values, so they remain raw evidence only. |
| request `view=index_daily_em` and index-shaped ID | Explicit Shanghai 000xxx/Shenzhen 399xxx/Beijing 899xxx routing; `index_scoped_request=true`, `listing_scoped_request=false`, `date_binding=row_and_request` and requested-range replay scope are recorded. |
| Eastmoney `secid`, `fields1`, `fields2`, `klt`, `fqt`, `beg`, `end` | Market-code mapping, unadjusted `fqt=0`, dynamic range, source URL, fixed/dynamic parameters, response decoder, dropped internal field and wrapper transformations remain replay metadata. |

The provider rejects stock-listing, H-share, unsupported index-shaped IDs,
missing or unexpected-parameter requests, malformed or reversed ranges,
missing/unexpected/reordered fields, invalid or out-of-range dates and
non-finite/non-numeric values. The normalizer emits
`AKSHARE_INDEX_DAILY_EM_RAW_ONLY` and creates no canonical daily-history,
return, valuation or accounting fact: the index series has no listing/entity
accounting scope. The response remains outside the calculation, gate, pipeline,
CLI and input-loader contracts.

## Phase 3.59 Generic Eastmoney index-history raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_zh_em.py)
document `index_zh_a_hist` as an Eastmoney index-code history endpoint with
`daily`, `weekly` and `monthly` periods, default dates `19700101` through
`22220101`, and a raw index-code `symbol` without a market prefix. The adapter
selects it only under `MARKET_HISTORY` with explicit `view=index_zh_a_hist`,
derives the code from supported Shanghai 000xxx, Shenzhen 399xxx or Beijing
899xxx index-shaped IDs, preserves the index-code-map and market-fallback
resolution, and retains the exact eleven-field response order.

| Raw upstream item | Phase 3.59 treatment |
| --- | --- |
| `日期` | Required parseable observation date; rows must stay within the inclusive requested bounds and be strictly ascending. |
| `开盘`, `收盘`, `最高`, `最低` | Required finite numeric or null index-price fields; the documentation does not declare canonical units, so they remain raw evidence only. |
| `成交量`, `成交额`, `振幅`, `涨跌幅`, `涨跌额`, `换手率` | Required finite numeric or null fields; documented units are lots, CNY, percent, percent, CNY and percent respectively, with no canonical fact mapping. |
| request `view=index_zh_a_hist`, `period`, raw code and date bounds | Explicit period/date validation and Shanghai 000xxx/Shenzhen 399xxx/Beijing 899xxx routing; `index_scoped_request=true`, `listing_scoped_request=false`, `date_binding=row_and_request` and requested-range replay scope are recorded. |
| Eastmoney index-code map and K-line requests | Auxiliary map URL, fallback market resolution, `klt` period code, unadjusted `fqt=0`, full-history bounds, inclusive wrapper filtering, source URLs, fixed/dynamic parameters and transformations remain replay metadata. |

The provider rejects stock-listing, H-share, unsupported index-shaped IDs,
missing or unexpected-parameter requests, unsupported periods, malformed or
reversed ranges, missing/unexpected/reordered fields, invalid or out-of-range
dates and non-finite/non-numeric values. The normalizer emits
`AKSHARE_INDEX_ZH_A_HIST_RAW_ONLY` and creates no canonical daily-history,
return, valuation or accounting fact: the multi-period index series has no
listing/entity accounting scope. The response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 3.60 Eastmoney index minute-history raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_zh_em.py)
document `index_zh_a_hist_min_em` as an Eastmoney index intraday-history
endpoint with periods `1`, `5`, `15`, `30` and `60`, default datetimes
`1979-09-01 09:32:00` through `2222-01-01 09:32:00`, and a raw index-code
`symbol` without a market prefix. The adapter selects it only under
`MARKET_HISTORY` with explicit `view=index_zh_a_hist_min_em`, derives the code
from supported Shanghai 000xxx, Shenzhen 399xxx or Beijing 899xxx
index-shaped IDs, and preserves the index-code-map and market-fallback
resolution.

| Raw upstream item | Phase 3.60 treatment |
| --- | --- |
| one-minute `时间`, `开盘`, `收盘`, `最高`, `最低`, `成交量`, `成交额`, `均价` | Required exact eight-field order; `时间` must be a parseable in-range timestamp and numeric fields finite or null. |
| multi-period `时间`, `开盘`, `收盘`, `最高`, `最低`, `涨跌幅`, `涨跌额`, `成交量`, `成交额`, `振幅`, `换手率` | Required exact eleven-field output order after the official wrapper's field reorder; `时间` must be a parseable in-range timestamp and numeric fields finite or null. |
| `成交量`, `成交额` | Documented as lots and CNY respectively; no canonical fact mapping is admitted. |
| request `view=index_zh_a_hist_min_em`, `period`, raw code and datetime bounds | Explicit period/range validation and Shanghai 000xxx/Shenzhen 399xxx/Beijing 899xxx routing; `index_scoped_request=true`, `listing_scoped_request=false`, `date_binding=row_and_request` and requested-range replay scope are recorded. |
| trends/K-line and index-code-map requests | One-minute trends or other-period K-line endpoint, `fqt=1` for non-one-minute data, map/fallback resolution, inclusive datetime filtering, source URLs, fixed/dynamic parameters and transformations remain replay metadata. |

The provider rejects stock-listing, H-share, unsupported index-shaped IDs,
missing or unexpected-parameter requests, unsupported periods, malformed or
reversed datetime ranges, missing/unexpected/reordered fields, invalid or
out-of-range timestamps and non-finite/non-numeric values. The normalizer emits
`AKSHARE_INDEX_ZH_A_HIST_MIN_EM_RAW_ONLY` and creates no canonical daily-history,
return, valuation or accounting fact: recent index intraday bars have no
listing/entity accounting scope. The response remains outside the calculation,
gate, pipeline, CLI and input-loader contracts.

## Phase 3.61 Eastmoney index spot raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_zh.py)
document `stock_zh_index_spot_em` as a real-time mainland-index universe with
the selectors `沪深重要指数`, `上证系列指数`, `深证系列指数`, `指数成份` and
`中证系列指数`. The adapter exposes it under `MARKET_QUOTE` with explicit
`view=index_spot`, passes the required selector, and retains the complete
provider universe rather than filtering rows to the listing context.

| Raw upstream item | Phase 3.61 treatment |
| --- | --- |
| `序号`, `代码`, `名称`, `最新价`, `涨跌幅`, `涨跌额`, `成交量`, `成交额`, `振幅`, `最高`, `最低`, `今开`, `昨收`, `量比` | Required exact fourteen-field order. `序号` must be a positive, strictly ascending integer; `代码` and `名称` must be non-empty strings; numeric fields must be finite numbers or null. Duplicate index codes are rejected. |
| `涨跌幅`, `振幅` | Documented as percentages and recorded as `percent`; the remaining numeric fields retain `not_documented` units rather than invented scales. |
| request `view=index_spot`, `symbol` | Exact selector validation, A-share listing-context routing, no listing filtering, `index_scoped_request=true`, `listing_scoped_request=false`, retrieval-only current-day snapshot scope and selector replay metadata. |
| Eastmoney `33.push2` / `48.push2` JSON `clist/get` requests | The important-index and general-index endpoint choice, category filter, page size 100, fixed/dynamic parameters, wrapper field mapping, pagination and source URLs remain replay metadata. |

The provider rejects H-share/unsupported listing contexts, missing or unexpected
parameters, unsupported selectors, malformed or reordered rows, invalid ranks,
duplicate codes and non-finite/non-numeric values. The normalizer emits
`AKSHARE_INDEX_SPOT_RAW_ONLY` and creates no canonical current-price,
liquidity, valuation or accounting fact: the market-wide index snapshot has no
listing/entity accounting scope or stable observation timestamp. The response
remains outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.62 Sina index spot raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_zh.py)
document `stock_zh_index_spot_sina` as a no-argument real-time mainland-index
universe for the `hs_s` node. The adapter exposes it under `MARKET_QUOTE` with
explicit `view=index_spot_sina`, discovers the provider-reported page count,
requests 80-row pages sorted by `symbol` ascending, and retains the complete
universe without listing filtering.

| Raw upstream item | Phase 3.62 treatment |
| --- | --- |
| `代码`, `名称`, `最新价`, `涨跌额`, `涨跌幅`, `昨收`, `今开`, `最高`, `最低`, `成交量`, `成交额` | Required exact eleven-field order. Codes must be lowercase `sh`/`sz` plus six digits, non-decreasing and unique; names must be non-empty strings; numeric fields must be finite numbers or null. |
| `涨跌幅`, `成交量`, `成交额` | Documented as percent, lots and CNY respectively; other numeric fields retain `not_documented` units and no canonical fact mapping. |
| request `view=index_spot_sina` | Exact A-share listing-context routing, no upstream selector or listing filtering, `index_scoped_request=true`, `listing_scoped_request=false`, retrieval-only current-day snapshot scope and complete-universe replay metadata. |
| Sina count/data requests | `Market_Center.getHQNodeStockCountSimple?node=hs_s`, 80-row `Market_Center.getHQNodeDataSimple` pagination, `node=hs_s`, `symbol` ascending sort, `demjson` decoding, comma removal, numeric conversion, positional field mapping and dropped provider fields remain replay metadata. |

The provider rejects H-share/unsupported listing contexts, missing or unexpected
parameters, malformed or reordered rows, invalid or descending codes, duplicate
codes and non-finite/non-numeric values. The normalizer emits
`AKSHARE_INDEX_SPOT_SINA_RAW_ONLY` and creates no canonical current-price,
liquidity, valuation or accounting fact: the market-wide index snapshot has no
listing/entity accounting scope or stable observation timestamp. The response
remains outside the calculation, gate, pipeline, CLI and input-loader contracts.

## Phase 3.63 Sina Hong Kong-index spot raw slice

The current [AKShare index-data documentation](https://akshare.akfamily.xyz/data/index/index.html)
and [official implementation](https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_hk.py)
document `stock_hk_index_spot_sina` as a no-argument real-time Hong Kong-index
universe. The adapter selects it only under `MARKET_QUOTE` with explicit
`view=hk_index_spot_sina`, accepts H-share listing context and preserves the
fixed Sina `hq.sinajs.cn` symbol list and complete output without listing
filtering.

| Raw upstream item | Phase 3.63 treatment |
| --- | --- |
| `代码`, `名称`, `最新价`, `涨跌额`, `涨跌幅`, `昨收`, `今开`, `最高`, `最低` | Required exact nine-field order. Codes must be uppercase alphanumeric strings with no duplicates and non-decreasing source order; names must be non-empty strings; numeric fields must be finite numbers or null. |
| `涨跌幅` | Documented as percent and recorded as `percent`; the remaining numeric fields retain `not_documented` units rather than inventing a currency or per-share scale. |
| request `view=hk_index_spot_sina` | Exact H-share listing-context routing, no upstream selector or listing filtering, `index_scoped_request=true`, `listing_scoped_request=false`, retrieval-only current-day snapshot scope and complete-universe replay metadata. |
| Sina quoted-text request | Fixed `rn=mtf2t` and 38-symbol `list`, one `hq.sinajs.cn` request, quoted-line parsing, positional wrapper mapping, ten dropped `_` columns, numeric conversion and source row identity order remain replay metadata. |

The provider rejects A-share/unsupported listing contexts, missing or unexpected
parameters, malformed or reordered rows, invalid or descending codes, duplicate
codes and non-finite/non-numeric values. The normalizer emits
`AKSHARE_HK_INDEX_SPOT_SINA_RAW_ONLY` and creates no canonical current-price,
liquidity, valuation or accounting fact: the market-wide Hong Kong-index
snapshot has no listing/entity accounting scope or stable observation timestamp.
The response remains outside the calculation, gate, pipeline, CLI and
input-loader contracts.

## Phase 2 enforcement rule

For every field not marked `STRUCTURED_AUTO` or `DERIVED_DETERMINISTIC`, a
Phase 2 adapter must do one of the following:

1. omit the raw-to-fact mapping and retain the field in the critical-missing
   inventory;
2. preserve an explicit `null` fact with evidence explaining why it is
   unresolved; or
3. wait for the Phase 3 primary-filing/evidence workflow.

It must not fill the field with zero, copy a neighboring aggregate, use a
provider-specific calculated ratio, or turn an unverified headline into an
accepted adjustment. This matrix is a guardrail against accidentally turning
Phase 2 screening convenience into Phase 3 filing analysis.
