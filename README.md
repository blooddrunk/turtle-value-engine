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
