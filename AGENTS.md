# Agent Guide — turtle-value-engine

This file is the repository-facing guide for coding and research agents such as Codex, ChatGPT, Hermes, and other tool-using agents.

The human-facing introduction is `README.md` (Chinese-first). This file is intentionally English-first so code identifiers, schemas, CLI contracts, and cross-agent instructions remain stable and unambiguous.

## 1. Mission

`turtle-value-engine` turns the Turtle value-investing method into an auditable, deterministic A/H-share analysis system.

Agents may help with data collection, filing research, evidence analysis, Business Quality assessment, explanation, orchestration, and code changes. Agents must not become the owner of deterministic investment math.

The core separation is:

```text
Agents / providers / filing research
        -> evidence, normalized facts, proposed adjustments,
           structured Business Quality assessment

Deterministic engine
        -> CDC, Net Cash, Through Return, hard gates,
           valuation, final deterministic state
```

## 2. Source-of-truth order

Before changing behavior, read the relevant sources in this order:

1. `docs/spec/`
2. `rules/strict-v1.yaml`
3. `schemas/`
4. `docs/architecture/`
5. the active goal under `docs/goals/`
6. `docs/roadmap.md`
7. `README.md`

If a lower-priority document conflicts with a higher-priority frozen contract, do not silently change the contract. Stop, report the conflict, and prefer an additive design.

Chat history is not a project specification.

## 3. Non-negotiable invariants

Preserve these boundaries unless an explicit specification change is requested:

- no fabricated facts;
- no silent defaults for missing financial data;
- no future-data leakage beyond the requested `as_of` boundary;
- no hidden network calls from deterministic analysis;
- no ad-hoc LLM recomputation of CDC, Net Cash, Through Return, hard gates, or valuation;
- no direct LLM approval or application of adjustments;
- only explicitly accepted adjustments may affect effective input;
- original source facts and provenance must remain auditable;
- ambiguous period, unit, entity scope, or economic meaning must fail closed;
- Business Quality requires evidence and counter-evidence;
- valuation must remain downstream of eligibility/business-quality gates.

`LLM` may propose an adjustment. `HUMAN` or `RULE_ENGINE` may approve according to the existing adjustment contract.

## 4. Current repository state

Phases 1, 2, and 3 are closed at the top-level integration boundary.

Available deterministic/replayable flow:

```text
A/H listing + as_of
  -> provider/cache preparation
  -> NormalizedCompanyInput
  -> optional explicitly accepted adjustment materialization
  -> offline deterministic analysis
  -> CompanyAnalysis
  -> deterministic decision trace
```

Key public boundaries include:

- `tve prepare`
- `tve analyze --input ... --profile strict-v1`
- `NormalizedCompanyInputBuilder`
- `materialize_effective_input`
- `run_analyze_with_accepted_adjustments`
- `build_decision_trace`

Phase 4 adds these model-neutral research boundaries:

- `AnalystClient` / `CallableAnalystClient` for injected external runtimes;
- `EvidencePacketBuilder` for bounded, reproducible, point-in-time packets;
- `run_business_quality_dimension` and `run_business_quality_research` for the
  Quality Analyst → Skeptic → Adjudicator workflow;
- `ResearchWorkspace` for immutable JSON packets, tasks, runs, sessions,
  validated Business Quality results, analyses, traces and reports;
- `ResearchOrchestrator` for research → explicit accepted-adjustment materialization
  → deterministic analysis → report;
- `compose_report` for a non-mutating human-readable projection.

Phase 6-A adds the offline deterministic monitoring-planning boundaries:
`WatchlistSpecV1`/`MonitoringEventV1`/`MonitoringEventBatchV1`/
`WatchlistStateV1`/`EventImpactDecisionV1`/`ReanalysisRequestV1`/
`ReanalysisPlanV1`/`MonitoringRunV1`, the monitoring-only `event-impact-v1`
policy, `run_monitoring` for deterministic point-in-time planning, and the
atomic local `MonitoringWorkspace` behind `tve watch validate|replay|status`.
These boundaries are orchestration state only: they never invoke a provider,
model, research or analysis runtime, never approve adjustments and never
change investment semantics.

Phase 6-B adds the implemented and CI-verified opt-in live event-acquisition
boundaries:
`providers/cninfo_disclosure.py` (bounded credential-free CNINFO
announcement client behind the frozen `FilingDiscoverySourceClient`
contract), the `monitoring_acquisition` package (provider-neutral
deny-by-default orchestration plus the deterministic fail-closed
filing-to-event mapping with the conservative end-of-disclosure-day
availability policy) and `tve watch acquire-events --network=allow`
(or `--from-cache` offline replay). Acquisition writes only raw-cache
provenance and a canonical `MonitoringEventBatchV1`; it never advances a
committed cursor and never invokes a model, research or analysis runtime.

The Phase 4 goal is implemented and its closure review is recorded in
`docs/goals/phase-4-agentic-analysis.md`. Phase 5 is implemented at its
documented integration boundary and its closure review is recorded in
`docs/goals/phase-5-backtesting-calibration.md`. Phase 4 contracts remain the
stable input/output boundary for ChatGPT, Codex, Hermes or another external
runtime; Phase 5 consumes their frozen artifacts without live-model
reconstruction.

Phase 5 adds the offline, model-neutral backtesting boundary described in
`docs/goals/phase-5-backtesting-calibration.md` and
`docs/architecture/backtesting-and-calibration.md`: `BacktestDatasetManifest`,
`HistoricalDecisionArtifact`, `DecisionSnapshot`, signal/return evaluation,
the versioned `portfolio-policy-v1` simulator, benchmark/metric attribution,
and chronological calibration proposals. These contracts consume frozen
artifacts only; they do not change `strict-v1` or recalculate deterministic
investment semantics.

Phase 5R adds the source-aware production historical boundary described in
`docs/goals/phase-5r-production-historical-corpus.md` and
`docs/architecture/production-historical-data-and-research-archive.md`.
`HistoricalDatasetManifest` declares a named, bounded A/H target scope and
source/coverage evidence, while `HistoricalArtifactStore` persists large
collections as verified content-addressed JSONL shards. The offline compiler
projects only validated rows into the Phase 5 manifest. A historical or
survivorship-free claim requires complete source-backed membership and
coverage evidence, established authority/licensing and an independent
reconciliation. Production source descriptors must retain license-evidence
URI/hash and restricted sources must retain an access-grant reference; a prose
license label is insufficient. The compact Git corpus is an acceptance fixture
and does not make a market-wide production claim. Delisted/terminal listings
and unresolved terminal economics remain explicit. The research archive
validator is the only permitted path for historical Business Quality artifacts.
No provider or
live model is invoked by dataset validation, freezing, snapshotting, backtest
or calibration commands.

Current Phase 5R status is `ACTIVE / PARTIAL`: the offline replay and
validation boundary plus the Phase 5R-A project-owned opt-in acquisition,
credential, raw provenance and deterministic compiler foundation are
implemented. An owner-authorized A-only Hithink probe/acquire and offline
replay have completed, but a real private A/H corpus has not been accepted,
so H-share capability, historical membership, terminal economics, source terms
and full category coverage remain fail-closed blockers. This is not a
requirement for the user to manually assemble market data. Phase 5R primarily
needs historical
data; real-time/event-driven acquisition belongs to Phase 6. Ordinary CI
remains offline and model-independent.

Phase 5R-A acquisition commands are separate from replay:
`tve historical source probe` and `tve historical acquire` require explicit
`--network=allow`; `tve historical compile` only reads local raw CAS and batch
receipts. Credentials may come only from declared environment/keyring
references or an injected resolver, never from chat. The exact remaining
blockers are recorded in `docs/operations/phase-5r-a-acquisition.md`.
`tve historical accept` is an additional offline-only A6 audit; it reads the
persisted batch, probe report, raw CAS, compiled manifest and shard store,
replays compilation, and writes exact blockers before failing closed. It does
not resolve credentials, access the network, invoke a provider, or invoke a
model.
The built-in CLI live transport additionally requires every required request
credential to be declared as an `ENVIRONMENT` reference and resolved to a
non-empty value before any network request; keyring/injected resolution is
limited to explicitly controlled library runners or fake transports. This
repository does not treat a chat value as a credential.
The FQGate historical boundary keeps the legacy
`fqgate-local-market-history` adapter readable and also supports the additive
`fqgate-market-history` adapter with explicit `LOCAL_DIRECT` or
`REMOTE_BRIDGE` endpoint parameters. Remote endpoints require an explicit
HTTPS operation URI and never fall back to loopback; remote auth/transport
diagnostics remain separate from FQGate entitlement diagnostics. The companion `blooddrunk/fqgate-remote-bridge` has now closed its Phase 5
remote-machine read-only boundary with an authenticated, registry-derived
machine API and one bounded instrument-lookup operation. It still publishes no
Bridge-owned quote, market-history or monitoring-event operation, so it is not
yet a live market-history/event provider for this repository and
`REMOTE_BRIDGE_LIVE_UNPROVEN` remains explicit for that capability. Phase 6-B
must keep its event-acquisition contract provider-neutral so a later stable
Bridge operation can be added as an optional, and potentially preferred,
source without coupling Turtle to Bridge lifecycle or Cloudflare provisioning.
M6-A is complete at `ad864510`: the repository now exposes the frozen
`ResearchSurfaceSnapshotV1` contract, checked-in schema, explicit projection
API and offline `tve surface build|validate` CLI. M6-B is now complete at its
documented integration boundary: a framework-neutral registry/service, lazy
optional FastAPI/uvicorn read-only adapter and `tve surface serve` over
explicitly supplied, already-validated surface snapshots. It does not read
raw provider stores, recompute investment math, silently discover workspace
files, or require A6 production eligibility. M5-C remains optional until a
concrete artifact class needs remote mirroring. M6-C1 is now complete at its
local/preview integration boundary: a typed React/Vite Dashboard, generated
OpenAPI client contract, bounded same-origin Cloudflare Worker proxy and real
cross-stack smoke over `tve surface serve`. It remains read-only and does not
read raw stores or recompute investment semantics. M6-C2 is now implemented at
its offline/deployment integration boundary: remote origins are HTTPS-only and
server-authenticated with Worker-held Access service-token secrets, the
preferred Tunnel ingress remains loopback-only, workers.dev/preview routes are
disabled in the checked-in Wrangler config, and deterministic deployment/live
smoke tools are provided. Owner-specific Cloudflare/account/domain/identity/
origin-host/snapshot inputs remain intentionally absent from ordinary CI; the
owner-authorized live deployment and final browser acceptance are recorded as
`CLOSED / OWNER_ACCEPTED`. M6-C3 is now complete at its presentation-only
integration boundary: the read-only Dashboard is Chinese-first through a
centralized typed presentation/copy layer, semantic states such as
`SPECIAL_REVIEW`, `NOT_EVALUATED`, `PARTIAL`, `BLOCKED` and `NOT_AVAILABLE`
carry plain-language labels and explanations with raw codes retained,
empty/partial/error states are distinct, and API/contract/hash/rule
identifiers are de-emphasized behind a technical/audit details affordance
without deleting or rewriting any payload value. It did not change the frozen
surface schema, M6-B API, M6-C2 Access/Worker/Tunnel boundary or deterministic
investment semantics. The exact M6-C3 build was redeployed through the
existing M6-C2 path and the machine-verifiable live smoke passed. Phase 6-A —
Watchlist State and Deterministic Event Planning Foundation — is complete
at its offline integration boundary: typed watchlist/event/state/cursor/
impact-decision/re-analysis-plan/monitoring-run contracts, the monitoring-only
versioned `event-impact-v1` policy kept separate from `strict-v1`, point-in-time
filtering on the canonical event availability boundary, canonical event
ordering, idempotent duplicate handling with hard failure on conflicting event
content, source/listing-scoped cursors that advance only through the atomically
committed next state, an atomic/idempotent hash-verified local
`MonitoringWorkspace`, offline `tve watch validate|replay|status`, an additive
non-secret `[monitoring]` ProjectConfig section and checked-in monitoring
schemas with drift tests. The monitoring package performs no provider, model,
research, analysis, Cloudflare or brokerage calls. Phase 6-B — Opt-in Live
Event Acquisition and Canonicalization — is complete at its live acquisition
integration boundary: `providers/cninfo_disclosure.py` implements the frozen
`FilingDiscoverySourceClient` contract against the public credential-free
CNINFO announcement search (bounded requests, fixed timeout, response byte
cap, fail-closed org resolution and truncation rejection); the
`monitoring_acquisition` package provides the provider-neutral
deny-by-default acquisition orchestration and the deterministic fail-closed
filing-to-`MonitoringEventV1` mapping (only probe-verified CNINFO document
class codes map to typed events, everything else is
`INFORMATIONAL_DISCLOSURE`; `published_at` is never fabricated for date-level
evidence and `available_at` uses the conservative end-of-disclosure-day policy
on the fixed UTC+8 calendar); `tve watch acquire-events` requires explicit
`--network=allow` or runs `--from-cache` offline replay, writes raw provenance
only into the existing raw-cache envelope and never advances a committed
cursor — cursors move only through the unchanged Phase 6-A atomic commit.
Live CNINFO evidence (real annual/interim reports, byte-identical offline
replay, cursor proof) is recorded in `docs/status/phase-6-b-2026-09-21.md`.
This does not change the separate Phase 5R strict A6 `ACTIVE / PARTIAL` state.
Phase 6-C — Controlled Re-analysis Executor — is implemented and closed at its
separate library/store/CLI boundary; exact gate and CI evidence is recorded in
`docs/status/phase-6-c-2026-09-21.md`. It consumes only committed monitoring
runs, persists terminal typed jobs and immutable output artifacts separately,
and does not mutate Phase 6-A state. Phase 6-D1 — Deterministic Monitoring
Cycle and Alert-Outbox Foundation — is implemented and closed at its separate
synchronous library/store/CLI boundary; exact automatic verification and CI
evidence is recorded in
`docs/status/phase-6-d1-2026-09-21.md`. D1 composes exactly one explicit
point-in-time cycle through the existing Phase 6-B acquisition, Phase 6-A
atomic commit and Phase 6-C executor, then persists deterministic terminal
cycle/result/outbox artifacts and a repairable atomic latest pointer. It
requires explicit typed execution bindings and blocks advancement when the
current committed run has unresolved `BLOCKED` or `FAILED` jobs. D1 has no
scheduler, notification delivery, Dashboard monitoring mutation, Cloudflare
mutation, or brokerage operation. Phase 6-D2A — Persistent Unattended Runner
Foundation — is implemented and closed at its separate runner library/store/CLI
boundary; exact automatic verification and CI evidence is recorded in
`docs/status/phase-6-d2a-2026-09-22.md`. D2A keeps D1 unchanged and adds the
`monitoring_runner/` package: a durable typed activation intent persisted
BEFORE entering D1 (freezing the resolved PIT/`as_of` and a full D1 request
fingerprint), an exclusive flock-backed single-host lease whose losing
invocation exits `LEASE_BUSY` with zero provider/model/D1 work, and a
terminal receipt binding the activation to the exact D1 result/outbox
identities and hashes plus an atomic repairable latest pointer. A crash after
the intent resumes the same activation and PIT; D1 terminal artifacts repair
the runner layer without repeating provider/model work; corrupt or ambiguous
runner state and changed watchlist/config under an unfinished activation fail
closed. The surface is `tve watch unattended-run` (exit 0 completed /
3 lease busy / 2 fail-closed) and `tve watch unattended-status`; runner inputs
are one explicit typed non-secret `RunnerConfigV1` JSON file
(`config/monitoring-runner.example.json`), network stays deny-by-default
through the existing D1/6-B opt-ins, and reference systemd service/timer
templates under `deploy/monitoring/` pass `systemd-analyze verify` in ordinary
CI. No scheduled GitHub Actions monitoring workflow exists. A post-closure
review at main `81b2ac2` found a narrow lease-classification hardening gap;
**Phase 6-D2A-R1 — Lease Classification and Slot-Integrity Hardening** closed
it at `2f9aae2` (Actions run 35679461520, success; evidence in
`docs/status/phase-6-d2a-r1-2026-09-22.md`): the non-blocking `flock` is now
the first and only liveness authority (no pre-lock lease-JSON validation),
only real contention errno maps to `RunnerLeaseBusyError`/`LEASE_BUSY` while
every other open/flock failure fails closed as `RunnerLeaseError`,
`probe()`/status obey the same truthfulness rules, a decoded lease record is
bound to its slot's `runner_id` (a foreign canonical record is never
overwritten), and holder-record writes prove full-byte persistence through a
complete write loop. **Phase 6-D2B — External Notification Delivery and
Delivery/Receipt Ledger** is implemented and closed at its durable delivery
boundary (`1abb2973e3f26d2db373f60b63da8c62a2bc530c`, Actions run
35694475358, `success`); exact automatic verification and CI evidence is
recorded in
`docs/status/phase-6-d2b-2026-09-22.md`. D2B keeps D1/D2A unchanged and adds
the `monitoring_delivery/` package: delivery consumes only a re-validated
terminal `RunnerReceiptV1` plus the exact D1 result/alert-batch pair it binds,
derives a deterministic `delivery_id` from runner/activation/alert-batch/
destination/payload-contract inputs, persists an immutable delivery intent
before any outbound I/O, and performs bounded attempts through one generic
HTTP webhook transport (canonical bounded JSON body, deterministic
`Idempotency-Key`, no redirects, bounded timeout/response bytes, response
persisted only as a digest). Its separate `DeliveryLedgerStore` keeps
immutable intents/attempts plus an atomic latest state derived purely from
immutable artifacts (byte-identical crash repair), distinguishes
`PENDING`/`DELIVERED`/`RETRYABLE_FAILURE`/`AMBIGUOUS`/`PERMANENT_FAILURE`/
`NOOP` with explicit status semantics (2xx delivered; 429/5xx retryable;
other 4xx/3xx permanent; post-dispatch uncertainty `AMBIGUOUS` and never
automatically resent unless receiver-enforced idempotency is explicitly
declared; retry exhaustion terminal; empty outbox a zero-I/O `NOOP`), and
replays an already-`DELIVERED` identity with zero outbound requests. D2B
claims no exactly-once semantics for arbitrary HTTP receivers. A post-closure
review then selected **Phase 6-D2B-R1 — Dispatch Durability, Single-Flight and
Timeout Truthfulness Hardening** before D3: the current implementation has an
uncovered process-death window after possible HTTP dispatch but before the
immutable attempt is saved, no per-delivery local single-flight lock, no true
end-to-end monotonic transport deadline, and the read-only delivery-status path
checks only pointer existence rather than validating the published state.
Canonical R1 scope and automatic acceptance are in
`docs/goals/phase-6-d2b-r1-dispatch-hardening.md`; no manual owner acceptance is
planned for R1. **Phase 6-D2B-R1 is implemented** from baseline
`3545794aa1a192374e5ce90c8fd806bc7b851923` (baseline Actions run 35695543233,
`success`): the ledger persists the additive immutable canonical hash-validated
`MonitoringDispatchClaimV1` before any request byte may be written
(deterministic content, so a resumed attempt re-saves byte-identically); an
orphaned claim (no terminal attempt) restarts as terminal
`AMBIGUOUS`/`ORPHANED_DISPATCH` with zero automatic resend by default, and
only the explicit `receiver_idempotency_declared=true` policy permits a
bounded retry of the same deterministic delivery key with monotonic attempt
numbering. Each `delivery_id` is guarded by a non-blocking per-delivery flock
single-flight lock held across intent persistence, state validation/repair,
dispatch claim, transport, attempt persistence and latest-state publication;
only real lock contention maps to the additive CLI `DELIVERY_BUSY` exit 3
with zero outbound requests, every other open/flock/filesystem error fails
closed, and the receiver's `Idempotency-Key` is never relied on for local
concurrency. `timeout_seconds` is now one injectable monotonic overall
deadline bounding connect/TLS, request/header wait and every bounded body
read from the same remaining budget; pre-dispatch expiry is honestly
retryable (`DEADLINE_EXHAUSTED_PRE_DISPATCH`) and post-dispatch expiry,
including mid-body-read, is `AMBIGUOUS`. `tve watch delivery-status` now
validates the published latest-state pointer truthfully
(`CURRENT`/`MISSING`/`STALE_REPAIRABLE`, read-only) and fails closed with
`DELIVERY_POINTER_CONFLICT` on corrupt/non-canonical/foreign/contradictory
state. Nineteen new deterministic tests (62 delivery cases total; full suite
6655 passed / 2 skipped) include a real two-process barrier proof that only
one process can enter the transport. R1 is closed at implementation
`6c039266083de015535f3f05dce0cf9aba2f0042` (Actions run 35805665083,
`success`, exact head-SHA match; implementation record
`docs/status/phase-6-d2b-r1-2026-09-23.md`). A 2026-09-23 post-closure audit
(`docs/status/phase-6-d2b-r1-post-closure-review-2026-09-23.md`) found one residual retry-budget defect under
`receiver_idempotency_declared=true`: recovery currently gates a resend from
the count of persisted attempt outcomes, so repeated process death after a
durable dispatch claim but before attempt persistence can re-enter transport
without consuming `max_attempts`. **Phase 6-D2B-R2 — Orphaned Dispatch
Retry-Budget Accounting Hardening** is selected before D3; canonical scope is
`docs/goals/phase-6-d2b-r2-orphan-retry-budget-hardening.md` and the coding-agent handoff is
`docs/status/phase-6-d2b-r2-next-coding-agent-goal.md`. Webhook
endpoints and bearer tokens are `SecretReference`s under the typed
`[monitoring.delivery]` ProjectConfig section (disabled by default in the
checked-in example), resolved only in process memory and proven absent from
every persisted artifact, CLI output, exception text and safe summary.
`tve watch deliver` requires the explicit `--network allow` opt-in and an
HTTPS endpoint on the live path (plain-http loopback is a test-only
injection); `tve watch delivery-status` reads a bounded secret-free ledger
projection. Delivery failure never reruns D1, a provider, a model or
re-analysis, and no owner live endpoint or manual acceptance was required
for closure. Phase 6-D3 Dashboard monitoring views, Phase 6-E
owner live unattended acceptance and the optional Bridge adapter are not
started. Exact gate, deployment
and remaining-input evidence is recorded in
`docs/status/phase-5r-a-2026-09-20.md` and
`docs/status/phase-6-a-2026-09-21.md`. Project-wide non-secret runtime
configuration is defined by `config/project.example.toml` and the ignored
`.tve-private/project.toml`; later phases extend this typed configuration
instead of adding phase-local environment files.

## 5. Working with company data

Keep networked preparation and deterministic analysis separate:

```text
NETWORKED / REPLAYABLE
listing + as_of -> provider acquisition -> raw cache -> normalization

OFFLINE / DETERMINISTIC
NormalizedCompanyInput -> accepted-adjustment materialization -> analysis

OFFLINE / DETERMINISTIC BACKTEST
BacktestDatasetManifest + frozen decisions -> signals -> optional portfolio
policy replay -> metrics / calibration proposal
```

Provider-specific field names must not leak into calculation modules.

Raw-only provider slices must stay raw-only until period, unit, entity scope, and economic meaning are sufficiently explicit for canonical mapping.

## 6. Filing and evidence workflow

The intended traceability chain is:

```text
Official filing
  -> cached document
  -> bounded extraction
  -> evidence item
  -> adjustment proposal or Business Quality claim
  -> explicit review/adjudication where required
  -> effective input / structured assessment
  -> deterministic analysis
  -> Decision -> Gate -> Metric -> Fact -> Evidence -> Filing
```

The agent research path is bounded and persisted:

```text
NormalizedCompanyInput
  -> EvidencePacket -> ResearchTask -> AnalystRun
  -> deterministic evidence/score validation
  -> optional Phase 3 adjustment workflow
  -> CompanyAnalysis -> DecisionTrace -> ResearchReport
```

`tve analyze` remains offline and does not instantiate an analyst client.

Evidence identity, source identity, locators, hashes, and provenance are first-class data. Do not replace them with prose-only citations.

Phase 5 backtest artifacts persist manifest IDs/content hashes, snapshot and
analysis identities, run specifications, policy version/hash, replayable
portfolio events and calibration experiment/holdout boundaries. Calibration
may emit only a candidate profile proposal; it cannot apply a rule change.

## 7. Business Quality rules for agents

Read `docs/spec/04-business-quality.md` before implementing or running any Business Quality agent.

The eight dimensions are fixed by the specification. Agents must:

1. explain how the company makes money;
2. identify major business-model risks;
3. search for counter-evidence before scoring;
4. gather supporting evidence;
5. attach quantitative metrics from deterministic/validated sources;
6. score each dimension only after evidence collection;
7. assign confidence and unresolved questions.

For high-priority candidates, preserve the specification's adversarial pattern:

```text
Quality Analyst -> strongest evidence-based durability case
Skeptic Analyst -> attempts to falsify it
Adjudicator      -> may use only evidence supplied by the analysts
```

An agent may produce a structured Business Quality assessment, but deterministic validation remains responsible for score caps, evidence references, confidence handling, and gate semantics.

## 8. Coding-agent protocol

For implementation tasks:

1. inspect the active goal and affected contracts before editing;
2. make the smallest coherent change that closes the requested acceptance criteria;
3. prefer typed models and explicit boundaries over implicit dictionaries;
4. keep provider, evidence, orchestration, and calculation responsibilities separated;
5. add frozen deterministic tests for new orchestration behavior;
6. use injected/fake provider or analyst clients in ordinary tests;
7. keep live-provider or live-LLM integration opt-in and outside ordinary CI;
8. update architecture/goal documentation when public contracts change.

Do not expand provider endpoint coverage merely because an endpoint exists. Add data only when it closes a clearly stated analysis requirement.

## 9. Verification

At minimum, before declaring a coding goal complete, run:

```bash
python -m ruff check .
python -m pytest
```

For model/agent integrations, ordinary CI must remain deterministic. Use scripted/fake analyst responses and frozen evidence fixtures for acceptance tests. Any live-model evaluation must be opt-in and must not be required for a green test suite.

## 10. Output discipline for research agents

When producing an investment analysis from this repository:

- cite exact evidence IDs / filing provenance when available;
- clearly separate deterministic engine results from agent judgment;
- surface missing data and unresolved questions;
- never convert `NOT_EVALUATED`, `WATCH`, or `SPECIAL_REVIEW` into a confident pass by prose;
- do not invent a recommendation that contradicts the validated `CompanyAnalysis` state;
- state the `as_of` date and rule profile used;
- preserve reproducibility by referencing the normalized input / analysis artifact identities when available.

## 11. Documentation ownership

- `README.md`: concise human-facing Chinese-first introduction and usage.
- `AGENTS.md`: stable agent-facing repository operating guide.
- `docs/spec/`: investment semantics and evidence rules.
- `docs/architecture/`: system boundaries and runtime design.
- `docs/goals/`: active implementation packages and acceptance criteria.
- `docs/roadmap.md`: milestone-level development direction and historical phase record.

Keep detailed implementation history out of the root README and this file.
