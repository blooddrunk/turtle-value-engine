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
