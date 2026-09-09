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
