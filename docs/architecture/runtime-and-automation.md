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

### Layer C.1 — Phase 4 bounded research contracts

Phase 4 implements the reusable boundary underneath any Skill or external
runtime. It is intentionally model-neutral; a runtime injects an
`AnalystClient` and receives/returns JSON-serializable typed contracts:

```text
NormalizedCompanyInput
  -> EvidencePacketBuilder
  -> ResearchTask (bounded question, evidence and read-only metrics)
  -> AnalystClient: Quality Analyst / Skeptic / Adjudicator
  -> AnalystRun + ResearchFinding
  -> deterministic Business Quality validation
  -> existing adjustment proposal workflow (PROPOSED only)
  -> explicit HUMAN/RULE_ENGINE approval when applicable
  -> existing deterministic analysis pipeline
  -> DecisionTrace + ResearchReport
```

`EvidencePacket` is assembled deterministically from the normalized input and,
when already available, metrics produced by the deterministic engine. It keeps
source evidence/filing provenance distinct from read-only derived metrics,
limits context size, and excludes evidence published after `as_of`. Each packet,
task and run carries a stable identity; `ResearchWorkspace` persists them along
with the validated Business Quality result, session, final analysis, trace and
report so a different process can resume without chat history.

The Quality Analyst, Skeptic and Adjudicator are separate injected roles. The
Adjudicator receives only the packet and persisted findings supplied by the
orchestrator; additional retrieval, if ever needed, must be a new persisted
research task. Invalid IDs, future evidence, unsupported adjustment targets and
model attempts to approve adjustments fail closed. No provider or model call is
performed by `tve analyze`, and no model output owns CDC, Net Cash, Through
Return, hard gates, valuation or the final deterministic state. A runtime-specific
Skill is optional; external agents can consume these contracts directly.

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
The Phase 3.85 document boundary now permits an injected, source-scoped
download into a content-hashed local cache: bytes and a JSON manifest can be
replayed offline without parsing the report. Phase 3.86 adds a bounded
parser-injected text-block extraction boundary for cached PDF/HTML bytes.
Phase 3.87 adds a deterministic local evidence store that binds caller-
supplied Evidence statements to exact page/section blocks and preserves
filing, document-hash and parser provenance. Phase 3.88 adds the offline
`AdjustmentProposalWorkflow`, which persists caller-supplied proposals only
after resolving their evidence IDs and permits explicit human/rule-engine
approval or rejection without mutating engine facts. Both boundaries perform
no hidden network access and do not interpret extracted text as a financial
fact.

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

### Phase 6-A — offline deterministic foundation (implemented)

The first implemented monitoring slice is deliberately offline. It makes a
watchlist and already-frozen canonical events machine-processable before any
live polling exists:

```text
WatchlistSpecV1 + MonitoringEventBatchV1 + prior WatchlistStateV1 + as_of
  -> deterministic planning (event-impact-v1, canonical ordering, PIT filter)
  -> MonitoringRunV1 { decisions, deferred, skipped, excluded,
                       ReanalysisPlanV1, planned next WatchlistStateV1 }
  -> atomic MonitoringWorkspace commit (run/state/batch artifacts + pointer)
```

Key contracts live in `turtle_value_engine.monitoring`:

- `event-impact-v1` is a monitoring-only, versioned policy isolated from
  `rules/strict-v1`; its severity precedence is orchestration state, never an
  investment PASS/FAIL/WATCH result.
- Events are canonically ordered by `(available_at, source_id, event_id,
  listing_id)`; point-in-time eligibility uses the normalized UTC
  `available_at` against the explicit `as_of` boundary (naive datetimes are
  interpreted as UTC).
- The same `(listing_id, event_id)` with identical content is idempotent;
  with different content it is a hard `EVENT_CONFLICT` failure.
- Events for out-of-watchlist or disabled listings are recorded with explicit
  reasons (`OUT_OF_WATCHLIST`, `LISTING_DISABLED`) and never silently applied.
- Source/listing-scoped cursors advance only inside the committed next state
  and only to the maximum `available_at` of events processed in that run;
  deferred (future) and stale (late) events never move them.
- The local `MonitoringWorkspace` persists canonical JSON with verified
  content hashes, immutable create-only artifacts, an atomically replaced
  current-state pointer that moves last, and fail-closed corruption checks.

The offline CLI surface is `tve watch validate`, `tve watch replay` and
`tve watch status`. The monitoring package imports no provider transport,
analyst client, research orchestrator, analysis pipeline, Cloudflare or
brokerage code, and ProjectConfig gains only a non-secret `[monitoring]`
section. Live provider adapters (Phase 6-B) and the re-analysis executor
(Phase 6-C) are separate packages; schedulers/notifications remain Phase
6-D.

### Phase 6-B — opt-in live event acquisition (implemented)

Phase 6-B connects one bounded live source to the Phase 6-A boundary
without changing investment semantics:

```text
committed WatchlistStateV1 (read-only cursor consultation)
  -> bounded source/listing window (explicit or cursor-derived, <= 366 days)
  -> tve watch acquire-events --network=allow   (deny by default)
  -> CNINFO official announcement query (2 bounded POSTs per listing,
     credential-free, fixed timeout, response byte cap, truncation fail-closed)
  -> existing filing-discovery provider boundary -> raw cache envelope
  -> deterministic mapping -> MonitoringEventBatchV1 (canonical artifact)
  -> existing tve watch replay -> atomic MonitoringWorkspace commit
  -> source/listing cursors advance only here
```

Key contracts:

- `providers/cninfo_disclosure.py` implements the frozen
  `FilingDiscoverySourceClient` contract for the public CNINFO announcement
  search; it is the only live transport in this phase and carries no
  credential, cookie or session.
- `monitoring_acquisition/` (outside the pure `monitoring` package, whose
  import isolation is frozen by test) provides the provider-neutral
  orchestration: deny-by-default `network_allowed`, offline `--from-cache`
  replay from the persisted raw record, listing/window/limit scope bounds,
  optional explicit `as_of` point-in-time filtering, and canonical batch
  construction with duplicate/conflict semantics.
- Classification is fail-closed: only probe-verified CNINFO document-class
  leaf codes map to typed events (`010301 -> ANNUAL_REPORT`,
  `010303 -> INTERIM_REPORT`); every other document class becomes
  `INFORMATIONAL_DISCLOSURE` with an explicit unverified-rule id.  Nothing is
  inferred from titles.
- Timestamp honesty: CNINFO stamps scheduled disclosures at Beijing
  midnight, indistinguishable from date-only normalization, so
  `published_at` stays `None`; `available_at` is the last microsecond of the
  publication date on the fixed UTC+08:00 disclosure calendar — the latest
  instant guaranteed available, never the fetch clock and never a fake
  midnight UTC instant.
- Acquisition never writes a `MonitoringWorkspace` and never advances a
  cursor; repeated acquisition of identical source records reproduces
  byte-identical canonical batches, and the raw cache key folds in the CNINFO
  client version so normalization changes can never replay stale shapes.

The FQGate remote bridge remains a future optional source consumed through
the same provider-neutral interface once it publishes a typed, bounded,
read-only machine operation with sufficient source timestamps; Turtle owns
no Bridge Cloudflare/FQGate lifecycle.

### Phase 6-C — controlled re-analysis execution (implemented)

Phase 6-C consumes only a machine-proven committed `MonitoringRunV1`; an
orphan `run` file or standalone plan is not executable:

```text
committed MonitoringWorkspace proof + run/plan/watchlist/batch/state
  -> validated ReanalysisRequestV1 at run.as_of
  -> separate immutable ReanalysisJobStore
  -> CACHE_ONLY/LIVE preparation boundary
  -> PARTIAL deterministic analysis or FULL injected research runtime
  -> DecisionTrace + ResearchSurfaceSnapshotV1
  -> terminal job attempt + atomic latest pointer
```

The additive `MonitoringCommitProofV1` is written before the existing state
pointer and the executor requires that pointer to reference the proven state;
therefore a failed pointer write cannot be mistaken for a committed run. The
execution package never imports into the pure Phase 6-A planner. Its job,
attempt, pointer, capability and output contracts are typed, hash-verified
and schema-checked. `NO_REANALYSIS` and `URGENT_MANUAL_REVIEW` persist
zero-call terminal results; `PARTIAL_REANALYSIS` does not invoke research;
`FULL_REANALYSIS` is blocked unless model permission and an injected research
runtime are both available. Live preparation permission, model permission and
accepted-adjustment materialization are independent boundaries.

`tve watch execute-reanalysis` is non-interactive and supports explicit
prepared-input/prior-analysis paths; `tve watch reanalysis-status` reads one
job projection. The store persists no `PENDING` or `RUNNING` state, repairs an
orphaned latest pointer after a crash, reuses successful jobs without repeating
provider/model calls, and leaves monitoring cursors and processed-event state
byte-identical. Scheduling, notification and Dashboard mutation remain Phase
6-D work.

### Phase 6-D1 — synchronous monitoring cycle and alert outbox (implemented)

Phase 6-D1 adds one scheduler-neutral, synchronous composition boundary. It
does not add a scheduler or a delivery transport:

```text
explicit MonitoringCycleSpecV1 (including immutable as_of/PIT and bindings)
  -> existing Phase 6-B acquisition boundary
  -> existing Phase 6-A run_monitoring + MonitoringWorkspace.commit_run
  -> existing Phase 6-C ReanalysisExecutor for every committed request
  -> deterministic MonitoringAlertBatchV1 outbox
  -> terminal MonitoringCycleResultV1 + atomic cycle latest pointer
```

The additive `monitoring_cycle/` package owns only this composition and its
separate immutable cycle store. `MonitoringExecutionBindingV1` and
`MonitoringExecutionCatalogV1` carry explicit, non-secret company,
prepared-input, prior-analysis or injected-resolver context; no company name,
sector, currency, input, prior analysis or research runtime is inferred. The
cycle records source/run/job/surface identities and never changes impact
severity into an investment recommendation or approves an adjustment.

Before a new Phase 6-A commit, D1 verifies every required disposition of the
current committed run. `SUCCEEDED`, `NO_ACTION` and
`MANUAL_REVIEW_REQUIRED` are resolved; the manual state still emits an
attention alert. `BLOCKED` and `FAILED` (including a missing/corrupt required
disposition) stop the cycle before the Phase 6-A pointer can advance. A
successful identical retry reuses the terminal cycle/outbox and lower-level
artifacts. Immutable cycle/result/outbox artifacts are hash-validated and a
pointer-only crash can be repaired without repeating provider/model work.

The non-interactive surface is `tve watch cycle` and `tve watch cycle-status`.
It remains offline/test-injectable by default; live acquisition still requires
the existing explicit `--network=allow` policy, while `--from-cache` replays
the existing Phase 6-B raw cache. The next selected slice is Phase 6-D2A:
a durable single-host unattended runner around this unchanged D1 command.
External notification delivery/receipts are deferred to 6-D2B; Phase 6-D3
Dashboard monitoring views and Phase 6-E owner live unattended acceptance
remain outside D2A.

---

## 6. Scheduler choices

### Current Phase 6 decision

For Phase 6-D2A, select a **persistent Linux host with a host-native systemd
timer/service** as the first monitoring deployment model. The reason is
storage, not preference: Phase 6-A, 6-C and 6-D1 intentionally keep cursor,
job and cycle state in durable local stores. A persistent host can reuse those
stores directly and prove restart/idempotency without inventing a remote state
layer.

The application runner remains scheduler-neutral. systemd is only the first
reference wakeup mechanism. Hermes cron may invoke the same CLI later. GitHub
Actions is deliberately **not** selected for the monitoring runtime at this
stage because its ephemeral workspace would require a separately designed
remote durable-state boundary. Actions remains the CI verifier.

D2A must persist a runner activation intent before entering D1 so a crash or
service restart reuses the same resolved PIT/as_of and does not manufacture a
second cycle merely because wall-clock time advanced. A single-host lease must
prevent overlapping activations; terminal receipts must be repairable from D1
terminal artifacts without repeating provider/model work.

### systemd timer/service (selected D2A reference)

Good for:

- persistent local monitoring/job/cycle stores;
- direct non-interactive `tve` CLI execution;
- host restart recovery with `Persistent=true` timer semantics;
- OS-level logs and service supervision without an agent runtime dependency.

The checked-in unit/timer is a reference template only. The real owner VPS,
watchlist, cadence, credentials and live network acceptance belong to Phase
6-E, not D2A CI.

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

Keep GitHub Actions as the repository CI / exact-SHA verification boundary and
for stateless scheduled jobs. Do not use it as the Phase 6 monitoring runner
while monitoring/job/cycle state is local-only; that would either lose state
between runs or force an unrelated remote-storage design into D2A.

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

## 10. Project-wide runtime configuration

Runtime/deployment configuration is separate from `rules/*.yaml` strategy
profiles. The checked-in template is `config/project.example.toml`; an
owner-specific copy belongs at `.tve-private/project.toml`, which is ignored by
Git. `ProjectConfig` is versioned and additive so later historical, storage,
provider, research-surface and monitoring phases extend the same project file
instead of introducing unrelated phase-local configuration files.

The file may contain non-secret paths, hostnames, resource names, network
policy and credential references such as `{ env = "CLOUDFLARE_API_TOKEN" }`.
It must never contain resolved API tokens, Access client secrets, signed URLs,
passwords or session material. Secret values are resolved only in process
memory from the referenced environment/secret manager. `tve config validate`
prints a safe summary containing references, never values.

The default network policy remains `deny`; each live provider or deployment
command must retain its existing explicit opt-in. A project configuration does
not change deterministic analysis semantics, source selection, PIT/A6 rules or
the loopback-only M6-B binding.
