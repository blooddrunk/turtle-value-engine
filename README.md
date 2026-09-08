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
Through Return, valuation and hard-gate primitives. It does not yet provide a
complete `tve analyze` command or assemble a `CompanyAnalysis` decision.
Business-quality scoring, final decision orchestration and live data adapters
remain intentionally unimplemented; partial-stage outputs must not be read as
investment recommendations.

Implementation-oriented assets will later live under:

- `rules/` — deterministic thresholds and parameter sets
- `schemas/` — machine-readable JSON Schemas
- `agents/` — LLM roles, prompts and evidence contracts
- `src/` — calculation and orchestration code
- `tests/` — formula, rule and regression tests

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
