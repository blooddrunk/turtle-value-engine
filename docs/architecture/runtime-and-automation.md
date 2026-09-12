# Runtime, Data Sources and Automation Architecture

> Status: design decision record

## 1. Core decision: Engine + Skill + Agent, not one or the other

`turtle-value-engine` should use a layered architecture.

### Layer A — deterministic engine (source of truth)

Implementation target: Python package + CLI.

Responsibilities:

- load normalized company-analysis input;
- calculate Core CDC / All-in CDC;
- calculate strict / owner-realizable net cash;
- calculate Through Return;
- evaluate hard gates;
- calculate strict-v1 valuation tiers;
- validate schemas and rule profiles;
- produce deterministic JSON output.

The formulas and thresholds must not live primarily inside an LLM prompt or Skill.

Suggested future CLI surface:

```text
tve analyze --input company.json --profile strict-v1
tve evaluate --input company-analysis.json --profile strict-v1
tve screen --universe ah --profile strict-v1
tve watch --watchlist watchlist.yaml
```

### Layer B — data adapters

Adapters translate external data into the engine's normalized Fact/Evidence contracts.

The engine must remain usable without them so that calculations can be unit-tested against frozen fixtures.

### Layer C — Skill / agent interface

A ChatGPT Skill (and optionally a Hermes-compatible Skill) should be a thin orchestration interface that:

- understands user intent;
- retrieves reports or evidence;
- invokes the deterministic engine where execution is available;
- explains results;
- asks for or proposes explicit adjustments;
- never reimplements financial formulas in prose.

### Layer D — automation / scheduler

Schedulers run data refresh, event monitoring and re-analysis. They should invoke the same deterministic engine rather than duplicating strategy logic.

Potential schedulers:

- GitHub Actions;
- Hermes Agent cron on a VPS;
- ChatGPT Scheduled tasks for monitoring, research summaries and user-facing alerts.

---

## 2. Which agent should do what?

### Codex

Best default for **building and maintaining the repository**:

- implementation;
- tests;
- refactors;
- data adapters;
- CI;
- PRs.

Codex is a development agent, not the runtime dependency of the investment engine.

### ChatGPT

Best default for **interactive research and judgment-heavy analysis**:

- annual-report reading;
- evidence-based business-quality analysis;
- governance/anomaly analysis;
- interpretation and explanation;
- ad-hoc company research;
- user-facing scheduled monitoring where supported.

### Hermes Agent

Best candidate for **self-hosted unattended orchestration**:

- persistent VPS runtime;
- shell/CLI execution;
- recurring cron jobs;
- watchlist processing;
- persistent context/memory;
- notifications to messaging channels;
- optional skill learning.

### GitHub Actions

Best neutral scheduler for deterministic early automation:

- reproducible;
- no LLM required;
- versioned with the repository;
- suitable for periodic tests, data refresh and scheduled screening.

Recommended long-term arrangement:

```text
Codex              -> develops engine
Python CLI          -> executes investment math
ChatGPT             -> research / evidence / interactive analysis
Hermes or Actions   -> unattended execution / monitoring
Skill               -> reusable user-facing workflow adapter
```

---

## 3. Data-source strategy

Use a two-tier policy:

```text
structured source for speed
+
primary filing for final verification
```

No single free source should be treated as authoritative for every field.

### 3.1 A-share official disclosures

Primary evidence:

- CNINFO / 巨潮资讯;
- Shanghai Stock Exchange;
- Shenzhen Stock Exchange;
- Beijing Stock Exchange;
- listed-company formal announcements.

Use these for final verification of:

- annual/interim reports;
- audit opinion;
- dividend policy;
- buybacks;
- restricted cash;
- guarantees;
- related-party transactions;
- material acquisitions/disposals;
- accounting notes.

### 3.2 Hong Kong official disclosures

Primary evidence:

- HKEXnews;
- listed-company formal reports and announcements.

Use for:

- annual/interim reports;
- results announcements;
- dividend announcements;
- share movements;
- repurchases/issuance;
- material transactions;
- governance disclosures.

### 3.3 Free/low-cost structured market-data layer

Initial adapter candidate: **AKShare**.

Useful because it exposes A-share and Hong Kong stock market/history/fundamental interfaces through Python and is suitable for research/prototyping.

Important limitation:

AKShare aggregates upstream public web sources. Interfaces can break when upstream sites change and therefore must not be treated as the final evidence source for hard financial conclusions.

### 3.4 Tushare Pro

Strong optional A-share structured provider for:

- daily/basic metrics;
- income statement;
- balance sheet;
- cash flow;
- dividends;
- audit opinion;
- disclosure dates;
- financial indicators.

However many useful APIs require a points threshold, so it should be considered an optional low-cost provider rather than the guaranteed zero-cost foundation.

### 3.5 BaoStock

Potential free A-share historical-price/backtest adapter.

Treat as an optional provider and validate coverage/current maintenance before depending on it for production fundamentals.

### 3.6 Other public aggregators

Yahoo Finance / Eastmoney / Sina / Tencent-derived data may be useful for price cross-checks and prototyping but must be isolated behind adapters because availability, terms and field definitions can change.

---

## 4. Recommended data-source profile by stage

### v0.1 deterministic core

No live data dependency.

Use frozen fixture JSON only.

Purpose: prove the investment rules are deterministic and testable.

### v0.2 structured data

Add:

- AKShare A/H quote/history adapter;
- optional Tushare A-share adapter;
- local cache.

Purpose: automated screening and price refresh.

### v0.3 filing verification

The Phase 3.84 filing-discovery contract provides metadata-only discovery
through injected official-source clients:

```text
A shares -> CNINFO / matching SSE/SZSE/BSE exchange / issuer announcements
H shares -> HKEXnews / issuer reports and announcements
```

The result is bounded by listing, source, publication-date filters, a result
limit and optional point-in-time cutoff. It creates deterministic filing IDs
and replayable raw provenance but does not download or parse document bodies.
Document retrieval, extraction and Evidence generation remain subsequent
deliverables.

### v0.4 resilient multi-source mode

For critical numeric fields:

```text
structured source A
structured source B (when available)
primary filing verification
```

Store disagreements as explicit data-quality flags.

---

## 5. Event monitoring architecture

A watchlist should not continuously recompute every company for every piece of news.

Use two phases:

### Phase 1 — event detection

Detect events such as:

```text
ANNUAL_REPORT
INTERIM_REPORT
EARNINGS_PREANNOUNCEMENT
DIVIDEND_POLICY_CHANGE
DIVIDEND_DECLARATION
BUYBACK
SHARE_ISSUANCE
MAJOR_ACQUISITION
MAJOR_DISPOSAL
AUDIT_OPINION_CHANGE
REGULATORY_PENALTY
CONTROLLING_SHAREHOLDER_EVENT
MATERIAL_LITIGATION
PROFIT_WARNING
TRADING_SUSPENSION
```

### Phase 2 — impact classification

Classify:

```text
NO_REANALYSIS
PARTIAL_REANALYSIS
FULL_REANALYSIS
URGENT_MANUAL_REVIEW
```

Examples:

- ordinary product press release -> usually `NO_REANALYSIS`;
- quarterly/interim update -> `PARTIAL_REANALYSIS`;
- annual report -> `FULL_REANALYSIS`;
- audit qualification / major governance event -> `URGENT_MANUAL_REVIEW`.

---

## 6. Scheduler choices

### ChatGPT Scheduled

Good for:

- daily/weekly watchlist summaries;
- web monitoring;
- detecting meaningful changes;
- checking supported connected apps such as GitHub;
- notifying the user only when something changes.

Do not make the deterministic engine dependent on project-uploaded files or a chat transcript. The repository or a deployable service must remain the source of truth.

### Hermes cron

Good for:

- executing the local `tve` CLI directly on a VPS;
- persistent caches and downloaded filings;
- scheduled company re-analysis;
- event polling;
- messaging delivery;
- multi-step unattended pipelines.

### GitHub Actions

Recommended first automation implementation because it can execute the exact repository version under CI and is independent of any particular LLM agent.

---

## 7. Self-improvement: allowed and forbidden scope

The engine may become more capable over time, but the investment rule core must **not self-mutate directly**.

### Layer 1 — locked strategy core

Includes:

```text
rules/*.yaml
financial formulas
hard-gate semantics
JSON schemas
normalization rules
```

Changes require:

```text
branch / PR
unit tests
regression fixtures
backtest or validation where applicable
human approval
```

No autonomous direct commit to the default branch.

### Layer 2 — evolvable research layer

Agents may propose improvements to:

- report parsing heuristics;
- source adapters;
- prompt wording;
- evidence search procedures;
- business-quality question sets;
- anomaly detectors;
- document-locator heuristics.

These improvements still enter through PRs and evaluation.

### Layer 3 — automatically learnable company state

Safe to update automatically with provenance:

- known payout policy;
- latest filing IDs;
- historic source mappings;
- company-specific accounting quirks;
- previous analysis result;
- known unresolved questions;
- watchlist event cursor.

This is **state/memory**, not a strategy rule mutation.

---

## 8. Controlled evolution loop

A future evolution pipeline should look like:

```text
Execution traces / failures
        ↓
Candidate improvement
        ↓
Evaluation dataset
        ↓
Unit + regression tests
        ↓
Historical point-in-time validation
        ↓
Compare against baseline
        ↓
PR
        ↓
Human review
        ↓
Merge as new version
```

Evaluation must optimize measurable qualities such as:

- extraction accuracy;
- evidence coverage;
- false-positive/false-negative gate behavior;
- reproducibility;
- source reliability;
- backtest stability.

Never optimize merely for higher historical returns without strong safeguards against overfitting and look-ahead bias.

---

## 9. Final recommended target architecture

```text
                    ┌─────────────────────┐
                    │ User / Scheduler    │
                    └──────────┬──────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │ Orchestration Layer        │
                 │ ChatGPT Skill / Hermes     │
                 └─────────────┬─────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       │                       │                       │
┌──────▼──────┐        ┌───────▼────────┐      ┌──────▼───────┐
│ Data Adapter │        │ Evidence / LLM │      │ Event Monitor │
└──────┬──────┘        └───────┬────────┘      └──────┬───────┘
       │                       │                       │
       └───────────────┬───────┴───────────────────────┘
                       │
               ┌───────▼────────┐
               │ Normalized Data │
               │ + Evidence      │
               └───────┬────────┘
                       │
               ┌───────▼────────┐
               │ Python Engine   │
               │ deterministic   │
               └───────┬────────┘
                       │
               ┌───────▼────────┐
               │ CompanyAnalysis │
               │ JSON            │
               └───────┬────────┘
                       │
               ┌───────▼────────┐
               │ Alert / Report  │
               └────────────────┘
```

The key architectural invariant is:

> **Agents collect, interpret and orchestrate. The engine calculates and decides according to versioned rules.**
