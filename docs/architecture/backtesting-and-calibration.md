# Point-in-Time Backtesting and Calibration Architecture

> Status: Phase 5 integration boundary

Phase 5 evaluates the unchanged deterministic investment engine with frozen
historical inputs. It does not add investment formulas, gate authority,
valuation logic or portfolio assumptions to `strict-v1`.

## Boundary and replay flow

```text
networked / replayable acquisition
    -> raw cache and point-in-time normalization
    -> BacktestDatasetManifest
    -> frozen decision artifacts / DecisionSnapshot
    -> offline signal evaluation
    -> optional offline PortfolioPolicy simulation
    -> metrics and failure attribution
    -> chronological calibration proposal
```

Once a manifest exists, the backtest, portfolio and calibration APIs do not
instantiate providers or analyst clients. `tve analyze` remains the offline
deterministic analysis boundary. Historical acquisition is a separate
preparation workflow.

## Point-in-time semantics

`HistoricalAvailability` and the related manifest records keep
`period_end`, `published_at`, `available_at`, `retrieved_at` and `source_hash`
distinct. An accounting period ending before a decision does not make its
facts usable: the source must also have been available by the decision
boundary. Timestamped availability is usable when it is at or before the
boundary. Date-only availability is conservative and becomes usable only
after that calendar date, so a date-only filing published on the decision date
cannot provide intraday knowledge.

Unknown evidence availability is rejected by default. A manifest may opt into
undated evidence only with an explicit frozen-availability attestation.
Decision artifacts, normalized evidence and research references are validated
again at the signal boundary. Corporate-action data used to change a
portfolio at an effective date must have a known availability time by that
event; otherwise simulation fails closed. Future prices are outcome data for
forward-return labels, not inputs to the historical decision.

## Universe and listing identity

`ListingLifecycle` and `UniverseMembership` are listing-level contracts.
A-share and H-share listings remain separate assets with their own prices,
currencies, calendars and lifecycle. Historical membership intervals and
terminal/delisted listings are retained instead of being replaced by the
current constituent list or silently dropped.

The manifest labels its coverage as `HISTORICAL` or
`FIXED_RESEARCH_UNIVERSE`; current-universe substitution is rejected, and a
survivorship-free claim is allowed only for a manifest labelled
`HISTORICAL`. A fixed or synthetic universe must carry limitations and a
survivorship note describing what it cannot prove.

## Returns and corporate actions

The canonical return path uses unadjusted listing prices plus explicit
listing-level actions. Cash dividends, splits/consolidations and terminal
values are applied once. Adjusted bars must declare their adjustment scope;
the manifest and return engine reject adjusted prices combined with explicit
actions that represent the same economics. The generic forward-return engine
marks rights and share issuance observations invalid until their economics are
explicitly supported; the separate portfolio policy must choose whether to
fail, ignore or apply those actions rather than guessing.

Suspended or missing bars cannot produce a fill. A signal uses the first
strictly later executable bar; a signal after the close therefore cannot fill
at that same close. Portfolio valuation may retain a stale mark for audit, but
execution remains restricted to a tradable bar. Optional cross-currency
reporting uses point-in-time FX observations and fails when no usable rate is
available.

## Snapshots, portfolio policy and metrics

`DecisionSnapshot` is a non-mutating projection of an existing validated
`CompanyAnalysis`; the backtest layer never recomputes CDC, Net Cash, Through
Return, gates, valuation or final state. Historical Business Quality is
accepted only when the decision artifact names a frozen, point-in-time-valid
research artifact. Otherwise the historical judgment is not reconstructed
from a live model.

Portfolio mechanics are isolated in the versioned `portfolio-policy-v1`
contract: long-only, unlevered positions, explicit rebalance and execution
rules, lot sizes, sizing and exposure caps, transaction costs, liquidity and
corporate-action policies. Every fill, fee, cash flow, action and mark is a
typed event. The resulting snapshots and events are sufficient for a
deterministic cash/P&L replay. Benchmarks carry an explicit identity and
`PRICE_RETURN`/`TOTAL_RETURN` type. Performance output covers CAGR, drawdown,
volatility, Sharpe, Sortino, turnover, hit rate, excess return, tracking
error, concentration, cash exposure and coverage; failure attribution keeps
exclusions, losses, missing/manual-review states and signal buckets
structured.

## Calibration guardrails

Calibration consumes typed observations and an explicit finite search space.
Train, validation and holdout periods are chronological and disjoint; search
trials contain no holdout rows or scores. Stability and sample-size penalties
are recorded with every candidate. Holdout evaluation is a separate operation
after selection. The only calibration output is a versioned
`CandidateProfileProposal` with `PROPOSAL_ONLY` status. It cannot mutate
`strict-v1` or authorize automatic application; a future profile requires the
repository's proposal, review, tests and human-approval path.

All public Phase 5 persisted contracts have corresponding JSON Schemas and
deterministic IDs/content hashes. The frozen tests use synthetic, offline
fixtures and do not require a network or live model.
