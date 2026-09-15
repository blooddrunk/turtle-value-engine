# Goal: Phase 5 — Point-in-Time Backtesting and Calibration

Status: ACTIVE

## Objective

Build an auditable, deterministic evaluation layer that can answer two separate questions without changing the frozen investment-rule core:

1. **Signal evaluation:** historically, when the engine produced a given deterministic state/gate/metric pattern using only information available at that time, what happened afterward?
2. **Portfolio simulation:** under an explicitly versioned portfolio/execution policy, what would a realizable long-only A/H portfolio have done after transaction costs, liquidity constraints, corporate actions and delistings?

Phase 5 must validate the strategy before Phase 6 unattended monitoring amplifies it. It must not silently rewrite `strict-v1`, introduce hidden portfolio rules into the investment specification, or use today's knowledge to reconstruct historical decisions.

The target architecture is:

```text
historical source snapshots / filings / market data
        -> point-in-time availability layer
        -> frozen NormalizedCompanyInput / validated research artifacts
        -> unchanged deterministic engine
        -> SignalSnapshot / DecisionSnapshot
        -> forward-return evaluation
        -> optional versioned PortfolioPolicy simulation
        -> BacktestResult / FailureAttribution
        -> CalibrationExperiment
        -> candidate profile proposal only
```

## Source of truth

Before implementation, read and follow:

- `AGENTS.md`
- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/runtime-and-automation.md`
- `docs/architecture/provider-and-cache.md`
- `docs/goals/phase-4-agentic-analysis.md`
- `docs/roadmap.md`

Do not change deterministic formulas, gate precedence, valuation definitions or `strict-v1` thresholds merely to make a backtest look better.

## Preflight hardening inherited from Phase 4

Close these narrow safety gaps before trusting historical evaluation:

1. **Undated evidence policy.** Evidence without a provable publication/availability date must not influence a historical point-in-time decision by default. Keep an explicit opt-in policy only for sources whose availability is independently frozen and auditable.
2. **External analyst execution budgets.** Keep provider/model execution outside deterministic analysis, but make timeout/context/output budgets explicit and fail closed at the runtime adapter boundary rather than recording them only as metadata.
3. **Persisted-schema strictness.** Tighten Phase 4 persisted JSON Schemas so nested packets/tasks/runs/business-quality/report structures are validated through explicit `$ref` contracts instead of generic `object` placeholders where practical.
4. Add regression tests proving these changes do not alter frozen Phase 1–4 deterministic results.

These are Phase 5 preflight tasks, not a reopening of Phase 4 semantics.

## Non-goals

Do not use Phase 5 to:

- build an autonomous trading or brokerage system;
- add short selling, leverage, derivatives or intraday execution;
- optimize a strategy directly against the final holdout period;
- use live LLM calls in ordinary backtests or CI;
- let calibration mutate `strict-v1` in place;
- hide network calls inside `tve analyze` or the backtest simulator;
- treat provider-adjusted prices plus separately credited dividends/splits as valid total return;
- claim survivorship-bias-free results when the historical universe contract cannot prove it;
- bulk-expand AKShare endpoints without a concrete point-in-time evaluation requirement.

## Design principles

### 1. Point-in-time truth is a first-class contract

For every historical datum, distinguish at minimum:

```text
period_end       # economic/accounting period
published_at     # when issuer/provider published it, if known
available_at     # earliest time the backtest may legally consume it
retrieved_at     # when TVE captured it
source_hash      # exact frozen source identity
```

A historical run may consume only artifacts with `available_at <= decision_time`.

Unknown availability must fail closed for historical signal generation unless an explicit, auditable policy says otherwise.

### 2. Separate investment semantics from portfolio mechanics

`strict-v1` answers whether a company/listing passes the investment rules. It does not define rebalance frequency, position sizing, cash drag, transaction costs, slippage or benchmark choice.

Portfolio mechanics therefore live in a separate versioned contract such as:

```text
portfolio-policy-v1
```

This prevents portfolio assumptions from silently becoming investment rules.

### 3. Evaluate signals before optimizing a portfolio

The first useful output is not CAGR. It is whether deterministic states/gates/metrics have predictive and risk-control value under point-in-time data.

Examples:

```text
PASS vs WATCH vs FAIL forward returns
valuation tier vs forward return
Through Return bucket vs forward return
Business Quality bucket vs drawdown/failure rate
hard-gate failure reason vs subsequent outcome
```

Only after this layer is trustworthy should portfolio construction be evaluated.

### 4. Historical Business Quality must be reproducible

Ordinary historical backtests must not call a live model to recreate old Business Quality judgments.

A historical decision may use Business Quality only when one of these is available and persisted with point-in-time provenance:

- a frozen scripted research fixture;
- a human-reviewed historical assessment;
- an archived Phase 4 analyst run/evidence packet whose evidence is point-in-time valid.

Otherwise Business Quality remains `NOT_EVALUATED` / manual-review according to existing semantics. Do not fill the gap with hindsight.

### 5. Data preparation and simulation remain separate

```text
NETWORKED / REPLAYABLE
historical acquisition -> raw cache -> PIT normalization -> dataset manifest

OFFLINE / DETERMINISTIC
manifest + frozen artifacts -> signal evaluation / portfolio simulation
```

The simulator must be runnable with zero network/model access.

---

## Work package A — Backtest public contracts and schemas

Add typed, persisted contracts under a dedicated module, approximately:

```text
src/turtle_value_engine/backtest/
  contracts.py
  dataset.py
  signals.py
  returns.py
  portfolio.py
  metrics.py
  calibration.py
  workspace.py
  orchestration.py
```

Recommended public concepts:

```text
HistoricalAvailability
ListingLifecycle
UniverseMembership
MarketBar
CorporateAction
FXObservation
BenchmarkObservation
BacktestDatasetManifest
DecisionSnapshot
ForwardReturnObservation
PortfolioPolicy
TransactionCostPolicy
LiquidityPolicy
PortfolioEvent
PortfolioSnapshot
BacktestRunSpec
BacktestResult
CalibrationSearchSpace
CalibrationTrial
CalibrationExperiment
```

Persisted artifacts should have deterministic IDs/content hashes and JSON Schemas consistent with the repository's existing conventions.

## Work package B — Point-in-time availability and dataset manifest

Create an offline manifest that freezes exactly what a backtest is allowed to see.

The manifest must include:

- dataset ID/version/hash;
- date range and timezone/calendar assumptions;
- listing universe source and lifecycle coverage;
- source/cache artifact IDs;
- price/corporate-action/benchmark/FX series identities;
- financial/filing availability timestamps;
- Business Quality artifact identities when used;
- missing-data coverage summary;
- explicit limitations such as incomplete delisting history or uncertain publication times.

Add deterministic validation that rejects:

- future financial/filing evidence;
- future corporate actions used before their effective/known boundary;
- a listing before listing date or after terminal delisting handling;
- current-universe substitution for a claimed historical universe;
- ambiguous adjusted-price + dividend double counting.

## Work package C — Historical universe and listing lifecycle

Represent A/H listings separately even when they refer to the same economic company.

Support at minimum:

```text
listing_date
delisting_date / terminal_status
market
currency
trading_calendar identity
historical universe membership intervals
suspension / unavailable-price behavior
```

Do not claim full survivorship-bias removal unless the source can reconstruct historical membership. If only a fixed research universe is available, label the run accordingly.

Create frozen fixtures containing at least:

- a continuously listed A-share;
- a continuously listed H-share;
- a later-listed company;
- a delisted/terminal company;
- a suspended or temporarily untradeable observation.

## Work package D — Market returns and corporate actions

Build one canonical return path. Prefer unadjusted listing prices plus explicit corporate actions when the data contract supports them.

Handle and test:

- cash dividends;
- splits/consolidations;
- rights/issuance treatment as supported by the portfolio policy;
- delisting/terminal value;
- missing/suspended trading days;
- A/H listing-specific prices;
- optional FX conversion for cross-market portfolio reporting.

If an adjusted price series is used, encode exactly what it adjusts for and forbid separately crediting the same action.

Signal timing must be explicit. A decision produced after a market close cannot fill at that same close. When publication time is only a date rather than a timestamp, default to the next eligible trading session rather than assuming intraday knowledge.

## Work package E — Decision snapshots and signal evaluation

Create a deterministic `DecisionSnapshot` projected from existing validated artifacts. It should include:

- listing + company identity;
- decision timestamp / `as_of`;
- rule profile/version;
- normalized-input artifact/hash;
- optional Business Quality/research artifact/hash;
- `CompanyAnalysis.analysis_id`;
- final deterministic state;
- valuation tier;
- gate statuses/failure reasons;
- selected deterministic metrics;
- unresolved/missing-data flags.

Then implement forward-return evaluation over configurable horizons such as 1M/3M/6M/12M without making those horizons part of `strict-v1`.

Primary Phase 5 value should come from bucket/attribution analysis, not only a portfolio equity curve.

## Work package F — Versioned portfolio simulator

Add a small, auditable event-driven long-only simulator instead of introducing a large third-party backtesting framework unless profiling proves it necessary.

Keep the first policy deliberately simple and explicit:

- cash + long positions only;
- no leverage;
- no shorting;
- configurable rebalance schedule;
- configurable eligible decision states;
- configurable sizing rule;
- configurable max position/sector exposure;
- configurable transaction-cost model;
- configurable liquidity/participation limits;
- deterministic order/fill rules.

The default policy must be documented as a simulation assumption, not part of the Turtle investment specification.

Persist every trade/fill/cash-flow event so portfolio P&L can be replayed.

## Work package G — Benchmarks, metrics and failure attribution

Support explicit benchmark identities and distinguish price-return from total-return benchmarks.

At minimum compute:

```text
CAGR
max drawdown
volatility
Sharpe
Sortino
turnover
hit rate
excess return
tracking error where meaningful
sector concentration
position concentration
cash exposure
coverage / missingness
```

Add failure-mode attribution:

- which hard gate excluded later winners;
- which passed names caused the largest losses;
- which missing-data/manual-review states dominate coverage;
- contribution by valuation tier;
- contribution by Business Quality dimension/bucket;
- contribution by sector/market/listing type;
- sensitivity to transaction-cost/liquidity assumptions.

## Work package H — Calibration experiments without rule mutation

Only after the PIT backtest foundation is green, add calibration experiments.

Requirements:

1. `strict-v1` remains immutable.
2. Calibration operates on an explicit candidate search space.
3. Use chronological train/validation/holdout boundaries; never random-shuffle time-series observations.
4. Prefer walk-forward/stability analysis where feasible.
5. Persist every candidate parameter set and result.
6. Penalize unstable parameters and tiny-sample improvements.
7. Report sensitivity surfaces, not only the single best score.
8. The final output is a **candidate profile proposal**, never an automatic replacement.

A proposed new profile must follow:

```text
proposal
-> frozen PIT evaluation
-> robustness/sensitivity review
-> tests
-> PR
-> human approval
-> new versioned profile (for example strict-v2)
```

Do not optimize Business Quality prose/prompts against the holdout set.

## Work package I — CLI/orchestration boundary

Keep backtesting offline once a dataset manifest exists.

Possible thin CLI wrappers:

```bash
tve backtest \
  --manifest datasets/frozen-ah-v1.json \
  --run-spec backtests/strict-v1-eval.json \
  --output runs/backtest-001

# Optional only after calibration contracts are stable
tve calibrate \
  --manifest datasets/frozen-ah-v1.json \
  --base-profile strict-v1 \
  --search-space calibration/search-v1.yaml \
  --output runs/calibration-001
```

Do not make network access implicit in these commands. Dataset acquisition/preparation should remain a separate provider/cache workflow.

## Work package J — Frozen acceptance and adversarial tests

Ordinary CI must remain fully offline.

Add frozen tests for at least:

1. a financial statement whose period ends before the decision date but whose publication date is after it — must be unavailable;
2. undated evidence — unavailable by default in a historical decision;
3. a newly listed company — absent before listing;
4. a delisted company — remains in the historical universe and receives explicit terminal handling;
5. a suspension/missing-price interval — no fabricated fill;
6. a cash dividend — credited exactly once;
7. a split/consolidation — share/price economics preserved exactly once;
8. adjusted-price plus explicit-dividend double-count attempt — rejected;
9. A/H listings for one company — distinct listing prices/currencies;
10. signal after close — cannot fill at the same close;
11. transaction costs increase monotonically and cannot improve raw portfolio return;
12. benchmark identity and return type are explicit;
13. backtest replay from the same manifest/spec produces byte-equivalent structured results where contracts require it;
14. calibration cannot mutate `strict-v1`;
15. holdout observations are not visible to the parameter-search stage;
16. live analyst/provider calls are never required by ordinary CI;
17. historical Business Quality without a valid frozen artifact remains not evaluated rather than being reconstructed with hindsight.

Add one frozen end-to-end A/H mini-universe scenario spanning enough dates to include a filing publication, a dividend, a suspension or missing session, and a terminal/delisting case.

## Work package K — Documentation and roadmap hygiene

- Keep `README.md` concise and user-facing.
- Keep `AGENTS.md` as the stable operating guide and point it to this active Phase 5 goal.
- Keep `docs/roadmap.md` milestone-level. Do not append new endpoint-by-endpoint implementation logs to it.
- The existing very long provider endpoint history should eventually move to a dedicated historical/provider-coverage document in a separate documentation-only change; do not mix a giant roadmap rewrite into core Phase 5 implementation unless necessary.
- Document PIT/backtest/calibration boundaries under `docs/architecture/`.

---

## Recommended implementation order

Deliver Phase 5 as one large goal with reviewable commits/work units:

1. preflight Phase 4 hardening;
2. backtest contracts + schemas;
3. PIT availability model + dataset manifest;
4. universe/listing lifecycle;
5. market bars + corporate actions + return engine;
6. `DecisionSnapshot` + forward-return signal evaluation;
7. frozen signal-evaluation E2E;
8. versioned portfolio policy + simulator;
9. benchmarks/metrics/failure attribution;
10. frozen A/H portfolio E2E and adversarial suite;
11. calibration experiment contracts and chronological split/holdout guards;
12. candidate-profile proposal/reporting;
13. optional CLI wrappers;
14. documentation reconciliation and Phase 5 closure review.

Do not begin threshold search before items 1–10 are complete and point-in-time leakage tests are green.

## Verification

Before declaring Phase 5 complete, run at minimum:

```bash
python -m ruff check .
python -m pytest
```

Also execute the frozen Phase 5 signal-evaluation and portfolio E2E scenarios.

Any live provider acquisition used to build a dataset must be opt-in and must produce replayable frozen artifacts. Ordinary backtest/calibration tests must not depend on the network or a live model.

## Exit criteria

Phase 5 is complete only when all of the following are true:

1. A versioned, schema-valid PIT dataset manifest can freeze the exact historical inputs used by a run.
2. Historical decisions cannot consume evidence/facts/corporate actions that were unavailable at the decision time.
3. Historical universe/lifecycle limitations are explicit and survivorship claims are not overstated.
4. A deterministic `DecisionSnapshot` can be generated from existing engine artifacts without recomputing investment semantics in the backtest layer.
5. Signal-level forward-return and failure-attribution reports are reproducible.
6. A separate versioned portfolio policy can simulate long-only A/H positions with explicit costs, liquidity and corporate-action handling.
7. Adjusted-price/corporate-action double counting is structurally prevented and tested.
8. Delistings, suspensions/missing prices and A/H listing distinctions are handled explicitly rather than silently dropped.
9. Historical Business Quality uses only frozen point-in-time-valid artifacts; no live-model hindsight is required.
10. Benchmarks and performance metrics are explicit, reproducible and auditable.
11. Calibration uses chronological train/validation/holdout or walk-forward boundaries and cannot see the holdout during search.
12. `strict-v1` remains unchanged; any improved thresholds are emitted only as a separately versioned candidate profile proposal.
13. `tve analyze` remains offline/model-independent, and backtest simulation is offline once its manifest is frozen.
14. Ordinary CI is network/model independent and includes frozen Phase 5 adversarial/E2E coverage.

## Closure output

At completion, summarize:

- PIT contracts and dataset semantics added;
- universe/lifecycle coverage and known survivorship limitations;
- return/corporate-action assumptions;
- signal-evaluation findings;
- portfolio policy assumptions;
- benchmark and metric coverage;
- calibration methodology and whether any candidate profile is justified;
- proof that `strict-v1` was not mutated;
- test/CI results;
- unresolved gaps before Phase 6 watchlist/event-driven monitoring.
