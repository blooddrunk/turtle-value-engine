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
Retry-Budget Accounting Hardening** was selected before D3; canonical scope is
`docs/goals/phase-6-d2b-r2-orphan-retry-budget-hardening.md` and the coding-agent handoff is
`docs/status/phase-6-d2b-r2-next-coding-agent-goal.md`. **R2 is implemented**
from baseline `3e4e6355cdaafc7e2bb5341c13c9f830a4f8dc58` (baseline Actions
run 35811279067, `success`): the durable `MonitoringDispatchClaimV1` set
`1..N` of one `delivery_id` is now itself the retry-budget ledger — every
claim consumes exactly one `max_attempts` position whether or not its attempt
outcome ever became durable, so `max_attempts` is a hard upper bound on
authorized outbound transport entries across the ledger lifetime. Budget
derivation, retry-exhaustion and AMBIGUOUS-retry terminality all come from
consumed durable slots (never `len(attempts)` alone); every new transport
entry allocates and first persists a NEW monotonic slot
(`len(claims) + 1`, never reusing an orphan claim as a budget token) while
the receiver `Idempotency-Key` stays the deterministic `delivery_id`; an
unresolved claim below a later persisted attempt is superseded by that
outcome but still consumes budget, so the attempt set may legitimately
contain gaps. The fail-closed `validate_dispatch_evidence` boundary rejects
over-budget claim counts, claims not bound to this intent/payload and
attempt outcomes without their durable dispatch slot before any transport
entry, while claims stay strictly contiguous from one. The default
non-idempotent policy is unchanged (orphan -> terminal `AMBIGUOUS`, zero
resend; a legitimate multi-orphan crash loop stays conservatively terminal),
no persisted contract field changed (the two delivery schemas were
regenerated with description-only diffs), no mutable retry counter exists,
and `delivery-status` gained the additive `unresolved_claim_numbers`
projection. Four new deterministic tests plus three rewritten to the R2
truth (66 delivery cases total; full suite 6659 passed / 2 skipped) prove
the max-attempts-one orphan restart sends zero, the repeated crash loop
never exceeds `max_attempts` transport entries, every retry takes a new
durable slot before transport with an unchanged key, and completed attempts
plus orphan slots consume one shared budget exactly once. R2 is closed at
implementation `69326c95543c92e28e288edadc781236fced2b65` (Actions run
35812884688, `success`, exact head-SHA match; full suite 6659 passed /
2 skipped; implementation and CI-closure record
`docs/status/phase-6-d2b-r2-2026-09-23.md`). A 2026-09-23 independent
post-closure review accepts R2 without reopening it and selects **Phase 6-D3 —
Read-only Monitoring Operations Dashboard Projection**; canonical scope is
`docs/goals/phase-6-d3-read-only-monitoring-dashboard.md`, the selection audit
is `docs/status/phase-6-d2b-r2-post-closure-review-2026-09-23.md`, and the
coding-agent handoff is `docs/status/phase-6-d3-next-coding-agent-goal.md`. Webhook
endpoints and bearer tokens are `SecretReference`s under the typed
`[monitoring.delivery]` ProjectConfig section (disabled by default in the
checked-in example), resolved only in process memory and proven absent from
every persisted artifact, CLI output, exception text and safe summary.
`tve watch deliver` requires the explicit `--network allow` opt-in and an
HTTPS endpoint on the live path (plain-http loopback is a test-only
injection); `tve watch delivery-status` reads a bounded secret-free ledger
projection. Delivery failure never reruns D1, a provider, a model or
re-analysis, and no owner live endpoint or manual acceptance was required
for closure. **Phase 6-D3 — Read-only Monitoring Operations Dashboard
Projection** is implemented at its read-only projection boundary
(implementation and CI-closure record
`docs/status/phase-6-d3-2026-09-23.md`): the framework-neutral
`monitoring_operations/` package projects one explicitly configured chain
(MonitoringWorkspace status, runner/lease read-only state, the active
activation otherwise the latest terminal one, that activation's D1 cycle,
only the jobs that cycle references and only the D2B deliveries bound to that
activation) into the versioned secret-free `MonitoringOperationsProjectionV1`
with a checked-in drift-checked schema. Sources are exactly one
`RunnerConfigV1` plus the typed `[monitoring.delivery]` `delivery_root` via
`tve surface serve --monitoring-runner-config ...`; the request path never
repairs or mutates any store and never invokes a provider, model, research,
cycle-execution or delivery-transport path, and local roots, endpoint/auth
secrets, lease holder tokens and raw response bodies are proven absent from
the serialized projection. The D2B-R2 accounting distinction is part of the
UI contract: `attempt_count` (persisted outcomes) and `dispatch_claim_count`
(consumed authorized outbound slots) are exposed and labelled separately with
`unresolved_claim_numbers`, `AMBIGUOUS`/`ORPHANED_DISPATCH` and pointer
states `CURRENT`/`MISSING`/`STALE_REPAIRABLE` kept explicit. The typed read
model reaches `GET /v1/monitoring/operations` (deterministic OpenAPI), the
fixed Worker allowlist route `/api/v1/monitoring/operations` and the
Chinese-first read-only `/monitoring` Dashboard page with zero mutation
controls; verification is fully automatic (26 new projection/API cases, 54
Dashboard/Worker tests, extended R2-orphan cross-stack smoke, automated
1440x900/390x844 browser layout verification). D3 is closed at implementation
`eb5f199437cba1d9747f87da7a6591943cbbacab` (Actions run 35860274042,
`success`, exact head-SHA match). A 2026-09-24 post-closure audit found that the D3 call to `RunnerLease.probe()` can transiently acquire the same exclusive flock used by the real runner and can therefore induce a false `LEASE_BUSY` outcome. **Phase 6-D3-R1 — Non-interfering Lease Observation Hardening** closed that defect at `40a75d89c2863b74a3e44ecfbad4fe432959fc5b` (Actions run 35948785496, `success`, exact head-SHA match; implementation and CI-closure record `docs/status/phase-6-d3-r1-2026-09-24.md`): `RunnerLease.probe()` now acquires no OS lock at all — it reads the slot read-only, proves liveness passively from the kernel `/proc/locks` table (granted `FLOCK` entries bound to the lease file's device/inode; blocked requests and non-flock domains ignored; missing/truncated/unparseable tables are capability-unavailable), re-observes on byte-evidence of an in-flight writer, and returns the explicit additive conservative `UNKNOWN` lease state wherever passive proof is impossible instead of fabricating `LIVE`/`FREE`/`ABANDONED`; `ABANDONED`/`corrupt` remain proven statements (trustworthy lock-free table plus byte-stable reads). The authoritative `held()` path, true-holder fail-fast `LEASE_BUSY`, unrelated-failure fail-closed classification and slot/record semantics are unchanged, and the projection schema, Surface OpenAPI and generated Dashboard types were regenerated additively for `UNKNOWN`. Deterministic proofs verified to fail on the pre-R1 probe include flock-forbidden observation, two-process observer-vs-runner barriers (no holder: D1 entered exactly once with zero observer lock attempts; real holder: competing runner still `LEASE_BUSY` with zero work) and a ten-iteration coordinated matrix with zero observer-induced busy outcomes; full suite 6695 passed / 2 skipped, monitoring glob 344 passed, Dashboard 55 tests, cross-stack smoke green, no manual owner action. **Phase 6-E — Owner Live Unattended Acceptance** is implemented and executed to its automation boundary at implementation `7a5da1996c53bcd77bbccb3c05ccd14a5e87e50f` (Actions run `35955876489`, `success`, exact `head_sha`; 6719 passed / 2 skipped; canonical record `docs/status/phase-6-e-2026-09-24.md`): `scripts/monitoring_live_acceptance.py` provides the deterministic `gate` (exact goal §9 command list, artifact bound to HEAD SHA), non-mutating `preflight` (host/systemd//proc/locks, typed config inputs, secret-reference presence without values, tracked-file secret scan, reference-unit verify and the real two-context flock-truth proof — holder subprocess via `RunnerLease.held()`, observer via the read-only `unattended-status` CLI, runner-context contention subprocess — failing closed as `DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN`), `render` (deterministic owner-specific units + `systemd-analyze verify` + redacted mutation-free install plan), `apply` (user scope installs directly; system scope stops at the exact six-item `MANUAL_SUDO_INSTALL_REQUIRED` payload; privilege probing respects injected runners and fake installs fail closed), `verify` (`systemctl show` effective state, timer fire evidence via `ExecMainStartTimestamp`, bounded redacted journal), `live-smoke`, `disable` and `report`. The executed real-host acceptance proved: shared kernel flock truth (observer LIVE/ABANDONED around a real holder with the runner context BUSY/ACQUIRED and the observer never locking); bounded live CNINFO acquisition of the known 2026-04-15..17 Moutai disclosure window (canonical batch `a9892c80…`, byte-equal to the Phase 6-B live evidence) with raw payload only in the private cache; socket-guarded offline replay byte-identity; cursor movement only after the monitoring commit; `COMPLETED_NEW`→`COMPLETED_REUSED` identity/idempotency; SIGKILL-after-durable-intent crash resume with a kernel-released lease (`COMPLETED_RESUMED`, same frozen PIT); generic HTTPS webhook delivery (`DELIVERED`, 1 attempt / 1 dispatch claim / 0 unresolved, pointer `CURRENT`) whose repeated identity authorized zero additional dispatch slots with a receiver-journal Idempotency-Key match; the read-only D3 operations API (200, contract-valid, 405 on every mutation method, byte-immutable under repeated polling, delivery identity projected, zero secret/path leakage) and a user-systemd timer fire at cadence driving the real unit to `COMPLETED_REUSED` with zero duplicate work (timer disabled afterwards, units left installed). The single marker crossed is `MANUAL_SECRET_REFERENCE_REQUIRED`: the owner webhook endpoint reference `TVE_MONITORING_WEBHOOK_URL` was not resolvable, so delivery was proven against a harness-local HTTPS receiver and the phase is exactly `READY_FOR_OWNER_AUTHORIZED_PHASE_6E` — not CLOSED — with the six disclosure items and the one-command resume recorded in the status doc. The optional Bridge adapter remains not started. Exact gate, deployment
and remaining-input evidence is recorded in
`docs/status/phase-5r-a-2026-09-20.md` and
`docs/status/phase-6-a-2026-09-21.md`. Project-wide non-secret runtime
configuration is defined by `config/project.example.toml` and the ignored
`.tve-private/project.toml`; later phases extend this typed configuration
instead of adding phase-local environment files.

Phase 6-E resume-path hardening is implemented at
`2095f187bbb11dd022b249b1c025f72772440267` (Actions run `36369283826`,
`success`, exact `head_sha`). The owner resume command now uses the actual
private config passed to `--acceptance-config`; when
`TVE_MONITORING_WEBHOOK_URL` is available, the harness automatically selects
the owner receiver and a stable destination ID distinct from the local test
receiver. Do not ask the owner to edit the private acceptance JSON. Phase
6-E was recorded as `READY_FOR_OWNER_AUTHORIZED_PHASE_6E` under that original
acceptance rule. On 2026-09-28 the owner explicitly changed the rule: the
already proven harness-local HTTPS receiver is sufficient for Phase 6-E
delivery acceptance, with `external_notification_verified: false`; an owner
Webhook URL is no longer required. The current goal and status record govern
the revised closure. The additive implementation
`8565621777762c601172aee562b2523a37ce02a6` passed the full local gate
and exact-head Actions run `36375649575`; refreshed host acceptance returned
`LIVE_ACCEPTANCE_COMPLETE` with zero failures and markers, so Phase 6-E is
`CLOSED / OWNER_ACCEPTED` under the revised rule.
An optional `telegram-v1` preset is additive at the existing delivery ledger;
its real personal-account delivery is not claimed without a bot token and chat
ID supplied outside Git/chat.

The 2026-09-28 post-merge audit accepts the Phase 6-E closure and PR #3 at
merge commit `b0eca4c2f518a7562b6209833f85bf3de553842f`; it found no
merge-blocking ledger, compatibility or secret-boundary regression. **Phase
6-F — Persistent Owner Operations Hardening** was then selected
(`docs/goals/phase-6-f-persistent-owner-operations.md`) and is now
implemented and `CLOSED / OWNER_ACCEPTED` at final implementation
`065b53a17bcb4f009a57ef918ffa3d59de135107` (exact-head Actions run
`36515225218`, `success`; superseded exact-head-green pushes `bb074de3`,
`4e68090e` and `0ee74e21` each closed a live-deployment-exposed defect).
`scripts/monitoring_production_ops.py` provides the automation-first
production lifecycle (non-mutating `preflight`/`plan`, deterministic
`render`, idempotent `apply`/`converge` that never starts recurring work,
explicit `activate` converging enable+start, effective-state `verify`,
bounded `live-proof`, `recover-proof`, safe idempotent `deactivate`,
secret-free `report`) behind the typed `monitoring_production_config_v1`
with hard acceptance/production separation (phase6e roots, runner ids and
unit namespaces are refused at parse time; the live-proof additionally
proves the acceptance tree byte-unchanged). The real WSL2 host deployment
(user units `tve-production-monitor.{service,timer}`, runner
`production-owner`, watchlist `SH600519`+`SZ000858`, rolling 7-day window,
daily cadence, delivery disabled — a monitoring-only closure is explicitly
allowed) is intentionally left enabled and active with `Linger=yes`
enabled automatically; bounded firing/replay proved `CYCLE_TERMINAL` +
`d1_status: NO_CHANGE` with no duplicate D1 work, D3 polling stayed
read-only/non-interfering, daemon-reload/reexec plus timer stop/start
proved durable recovery with unchanged configuration identity, and a
real-host deactivate/reactivate drill proved the rollback path. The single
recorded marker is the non-blocking `WINDOWS_HOST_BOOTSTRAP_UNPROVEN`
capability boundary: persistence is claimed only while the WSL
distro/user manager runs, never Windows-reboot autostart. If the owner
later enables Telegram/webhook notifications for production, the only
typed credential source is the private systemd `EnvironmentFile` (path
rendered in the unit, values never in Git/units/argv/ledgers/reports),
refused at render time and proven resolvable under the service identity
after manager refresh. Canonical closure evidence:
`docs/status/phase-6-f-2026-09-29.md`. A 2026-09-29 post-closure audit
keeps Phase 6-F closed and selects the narrow **Phase 6-F-R1 — Production
Credential Boundary and Manual-Resume Hardening** follow-on
(`docs/goals/phase-6-f-r1-production-credential-boundary-hardening.md`):
EnvironmentFile-only secrets must participate in leak scans/redaction, the
private EnvironmentFile boundary must be machine-enforced, and every manual
boundary must emit an exact parser-valid resume command using the real config
path. R1 must not start Phase 7, provider/Bridge expansion, new notification
vendors, brokerage/trading or investment-rule work. **Phase 6-F-R1 is
implemented and CLOSED** at implementation
`42304cf86db6fb2d8b177f3d7d13a4b89531103b` (exact-head Actions run
`36519413717`, `success`; full suite 6787 passed / 2 skipped; closure record
`docs/status/phase-6-f-r1-2026-09-29.md`): `scripts/monitoring_production_ops.py`
now derives the effective scan/redaction set for every secret-checking path
(preflight tracked files, verify/live-proof journal redaction, D3 payload
scan, live-proof/recover-proof/report artifact scans and serialized-report
guards) from both the harness process environment and the private systemd
`EnvironmentFile`, keeping both values when the sources diverge (values stay
memory-only; hit reports carry reference names only); the typed credential
contract is machine-enforced (parse-time in-private-root containment plus
runtime regular-file/symlink-escape/owner-only-permission checks, never
auto-chmod, metadata-only reporting, precise `MANUAL_SECRET_REFERENCE_REQUIRED`
boundary in preflight/render/live-proof delivery); and the Windows-bootstrap,
linger and missing-secret render boundaries all emit exact
`_resume_command()`-built commands that round-trip through `_build_parser()`.
Twelve deterministic regressions prove the defects (15 failures on pre-R1
main). Non-destructive production checks at the implementation HEAD stayed
green (gate GREEN, preflight/verify green, report `PRODUCTION_DEPLOYED`);
no live firing/recovery/delivery was rerun as ceremony and no real secret
was requested or exposed. A fresh post-R1 review (`docs/status/phase-6-f-r1-post-closure-review-2026-09-29.md`) identified a narrower dormant credential-file semantic/render-gating gap and selected **Phase 6-F-R2 — Canonical EnvironmentFile Semantics and Render Gating** (`docs/goals/phase-6-f-r2-environmentfile-semantic-hardening.md`). **Phase 6-F-R2 is implemented and CLOSED** at implementation `c064cda68a0e31b0dc1b47ed451bd59977e7c931` (exact-head Actions run `36533726274`, `success`; closure record `docs/status/phase-6-f-r2-2026-09-29.md`): rather than a home-grown full systemd parser, `environment_file_values()` is now the one canonical parser/validator machine-enforcing a deliberately unambiguous EnvironmentFile subset — exactly one physical `NAME=VALUE` line per referenced secret name (column 0, non-empty value, no quoting, backslash escaping, continuation, whitespace or control characters, no duplicates, no unknown/unrelated keys, no `export` forms), with `= # ; ? & %` and other URL punctuation preserved byte-for-byte as data — so every accepted value is byte-identical under the harness and the service manager. That single parser feeds render gating, preflight, the effective scan/redaction set, D3 payload scans and delivery completeness; a file with any syntax-level violation contributes no values at all, while an otherwise-canonical file missing a referenced name keeps its present unambiguous bytes in the fail-safe R1 scan/redaction set and fails every gating path closed. `cmd_render()` proves the metadata boundary, actual readability, canonical syntax and referenced-name completeness before creating the output directory or writing any unit/config/render-plan artifact, stopping at `MANUAL_SECRET_REFERENCE_REQUIRED` with the full six-item disclosure and the exact parser-valid `_resume_command(..., "render")`; configured paths carrying control characters/newlines are rejected at parse time and by the metadata validator. Sixteen deterministic regressions prove the defects (13 failures on pre-R2 main, covering both the semantic-mismatch and render-completeness classes); the full suite moved from 6787 to 6803 passed / 2 skipped. Non-destructive production checks at the implementation HEAD stayed green (gate GREEN, preflight/verify green, report `PRODUCTION_DEPLOYED`); delivery stays disabled (an explicit owner decision, now requiring a canonical credential file through the unchanged render/apply path) and no live firing/recovery/delivery or Windows reboot was rerun as ceremony. A fresh post-R2 review (`docs/status/phase-6-f-r2-post-closure-review-2026-09-29.md`) accepts R2 but identifies a narrower run-time credential-drift boundary plus the systemd-invalid Unicode noncharacter/U+FEFF gap, and selects **Phase 6-F-R3 — Runtime Credential Drift and Service-Effective Gate Hardening** (`docs/goals/phase-6-f-r3-runtime-credential-drift-hardening.md`). **Phase 6-F-R3 is implemented and CLOSED** at implementation `4f3fa0df9381649c0929135dd7b9480a43d5ea91` (exact-head Actions run `36542078579`, `success`; closure record `docs/status/phase-6-f-r3-2026-09-29.md`): the one canonical parser now rejects `U+0000`, `U+FEFF`, `U+FDD0..U+FDEF` and every plane-ending `FFFE`/`FFFF` code point anywhere in the decoded EnvironmentFile (comments included), so every file TVE calls canonical is valid under systemd; one current-credential validation primitive (`validate_current_credential`/`CurrentCredentialState`) combining the R1 metadata boundary, R2 canonical parsing/completeness and the R3 Unicode boundary is reused by render, preflight, apply/converge (fail-closed before any install/reload/enable/linger mutation on post-render drift), activate (zero enable/start actions on drift), verify (live `credential.current-contract` plus effective `service.prestart-gate` checks), report (secret-free current credential summary; cannot emit `PRODUCTION_DEPLOYED` on drift regardless of green historical records) and the live-proof/recover-proof boundaries, while deactivate stays deliberately credential-independent. Every delivery-enabled service unit renders an `ExecStartPre=` credential gate — the dedicated non-secret `scripts/monitoring_credential_gate.py` CLI carrying only the environment-file path, production root and referenced names — that re-reads the private file and compares every referenced value with the environment systemd actually injected byte-for-byte in memory before the unchanged `unattended-notify` `ExecStart=` may run, printing only status/category/reference names; no secret value or credential-derived hash/digest/fingerprint is persisted anywhere for drift detection, and delivery-disabled units stay byte-compatible (no gate). The recover-proof restart probe now runs the actual gate through `systemd-run` and proves byte equality instead of mere presence. Twenty deterministic regressions (18 fail on pre-R3 main; the two passing are the preservation guarantees) include a real transient user-manager proof that a drifted-to-quoted file leaves the notify sentinel uncreated; the full suite moved from 6803 to 6823 passed / 2 skipped. Non-destructive production checks at the implementation HEAD stayed green (gate GREEN, preflight/verify green, report `PRODUCTION_DEPLOYED`); delivery stays disabled (an explicit owner decision; enabling it later requires a canonical credential file through the unchanged render/apply path, whose runtime behavior R3 now guards) and no live firing/recovery/delivery or Windows reboot was rerun as ceremony. A fresh post-R3 review (`docs/status/phase-6-f-r3-post-closure-review-2026-09-29.md`) accepts R3 but finds a narrower production artifact serialization-parity gap: supported owner paths/strings are broader than the currently proven systemd/TOML serializers. The selected next package is **Phase 6-F-R4 — Production Artifact Serialization Parity Hardening** (`docs/goals/phase-6-f-r4-production-artifact-serialization-hardening.md`), which must replace shell-oriented/raw systemd interpolation with systemd-native literal serialization, prove manager-effective argv/path equality, make generated project TOML round-trip through `tomllib`, add fail-on-main edge-character regressions and close only on the full automatic gate plus exact-head Actions success. **Phase 6-F-R4 is implemented and CLOSED** at implementation `a09b9c101b6f7c7d0800fd844450652fbcfd19dc` (exact-head Actions run `36555555882`, `success`; closure record `docs/status/phase-6-f-r4-2026-09-29.md`; the superseded first push `466bdfb` failed CI by exposing that the transient proof also runs on the Actions runner, where the proof helper's `env python3` shebang resolved to the dependency-less system interpreter — fixed by pinning the shebang to the test interpreter with no production-code change): one explicit systemd-native serialization boundary now governs every execution-critical generated value — `ExecStartPre=`/`ExecStart=` argv elements are serialized per systemd.syntax(7) quoting (whole-item double quotes, backslash doubling, `\"` escaping) with `$$`/`%%` doubling for the two expansions quoting does not disable, `EnvironmentFile=`/`WorkingDirectory=` use percent doubling only (quoting is unsupported there; spaces, quotes, dollar, semicolon, hash and non-ASCII stay raw), `Description=` percent-doubles the runner id, `Documentation=` emits a URL-encoded percent-doubled file URL, and `OnCalendar=` stays verbatim as an intentional systemd calendar expression; `shlex` remains reserved for human resume commands. `render_service_unit()` mirror-parses its own serialized lines and fails closed unless the effective values restore the intended argv/paths exactly, and `render_project_config()` routes every owner string through a real TOML basic-string encoder and proves the `tomllib` round-trip before returning. `cmd_verify` now compares the manager-effective `ExecStart`/`ExecStartPre` argv arrays and `EnvironmentFiles` paths structurally through `busctl --json=short` (element-by-element against `credential_gate_argv()`/`main_exec_argv()`/the typed credential path) instead of substring presence, staying non-mutating. The genuinely unrepresentable is rejected at parse time: control characters in unit-serialized fields, quote/backslash/dollar characters in `python_executable` (the only owner-controlled systemd Exec executable token, where systemd refuses them), and backslash in the delivery `EnvironmentFile` path (the exec-time loader treats it as an escape). Ordinary inputs render byte-identical — `plan` against the live production deployment reports `unchanged` for both units, `runner.json` and `project.toml`. Thirty-eight focused R4 regressions (30 failing on pre-R4 main; the eight pre-R4 passes are the intentional preservation cases) cover the full parser-significant matrix (space, single/double quote, backslash, literal `$HOME`/`${HOME}`/`%n`/`%`, standalone and embedded `;`/`#`, non-ASCII, all classes at once), exact manager-effective argv in both delivery modes, EnvironmentFile parity across the unit directive, the gate argv and `validate_current_credential()`, `tomllib` round-trips, ordinary-input byte compatibility and all R3 drift/Unicode/gate preservation, including a real transient user-manager proof: the rendered delivery unit for a hostile `pro duction $HOME%n 'q'"x"` root executes the exact intended runtime argv, loads the credential file from the `%%`-escaped path (gate proves byte equality), and a drifted (systemd-quoted, TVE-noncanonical) file leaves the main command unexecuted. The full suite moved from 6823 to 6861 passed / 2 skipped. Non-destructive production checks at the implementation HEAD stayed green (gate GREEN, clean-tree preflight green, verify green including the new structural checks, report `PRODUCTION_DEPLOYED`); delivery stays disabled and no live firing/recovery/delivery or Windows reboot was rerun as ceremony. A fresh post-R4 review (`docs/status/phase-6-f-r4-post-closure-review-2026-09-30.md`) accepts R4 with no R5 blocker and selects **Phase 7-A — Controlled Evolution Evaluation Foundation** (`docs/goals/phase-7-a-controlled-evolution-evaluation-foundation.md`): add a deterministic, offline, non-mutating evaluation dossier/admission gate for `CandidateProfileProposal` plus separate holdout evidence before any profile materialization, PR packaging or human approval. Phase 7-A must not mutate `strict-v1` or any rule profile; provider expansion, Bridge/FQGate integration, new notification vendors and brokerage/trading remain separate work. **Phase 7-A is implemented and CLOSED** at its offline evaluation/admission boundary (implementation `04984bc764441a8d258b4c8c71fe31fec122275f`, exact-head Actions run `36658008383`, `success`; closure record `docs/status/phase-7-a-2026-09-30.md`): the `evolution/` package adds the versioned immutable `ControlledEvolutionEvaluationV1` (`controlled_evolution_evaluation_v1`, checked-in drift-parity schema `schemas/controlled-evolution-evaluation.schema.json`) binding the frozen dataset identity and content hash, the experiment identity/content hash, the embedded proposal id plus a canonical SHA-256 over the proposal payload, the candidate id and exact parameter overrides, the separate holdout content identity, the frozen-observation content identity and the exact base-profile bytes/hash behind one deterministic `evaluation_id` and `content_sha256` with no wall-clock fields. `evaluate_controlled_evolution()` is a pure offline function over already-validated typed inputs; it recomputed thirteen named checks at its original boundary (profile bytes hash, base-profile identity agreement, manifest identity, experiment/proposal/holdout content hashes, proposal embedding in the selected trial, selected-trial/candidate/override agreement, search-holdout isolation, chronology disjointness, `PROPOSAL_ONLY` status, holdout binding, canonical reproduction and holdout reproduction; the canonical check set is nineteen after Phase 7-A-R1 below) and emits only `READY_FOR_HUMAN_REVIEW` when every check passes or `BLOCKED` naming the failing checks, with `requires_human_approval=true` and `automatic_application_allowed=false` fixed in the contract. The admissible scoring path is exactly the repository's canonical built-in calibration scorer: the evaluator re-runs `CalibrationRunner` from the frozen observations and recorded search space/split and requires deterministic equality with the admitted experiment/proposal and holdout artifact, so an experiment produced with an unrecorded custom scorer is `BLOCKED`, not guessed reproducible. The offline `tve evolution evaluate --manifest ... --experiment ... --holdout ... --observations ... --base-profile ... --output ...` boundary constructs no provider, model, transport or network client, refuses any output path that would overwrite a supplied input, never writes a rule/profile, PR or approval state, exits 0 for an admitted dossier and 1 for a `BLOCKED` dossier (both print and persist the full dossier). Adversarial coverage spans profile/manifest/proposal/experiment/holdout/observation substitution, selected-trial mismatch, holdout leakage, corrupt chronology (library predicate and CLI fail-closed), non-`PROPOSAL_ONLY` status, custom-scorer non-reproducibility, deterministic rerun/hash equality, schema drift parity, socket-guarded no-network execution and byte identity of `rules/strict-v1.yaml` plus every supplied artifact across evaluation. A 2026-09-30 post-closure review (`docs/status/phase-7-a-post-closure-review-2026-09-30.md`) preserved that closure but found three blockers before any 7-B materialization: a same-`dataset_id` manifest with different valid content was not tied to the calibration run, non-scoring frozen-observation provenance (`CalibrationObservation.source_hash`) could be substituted while canonical replay stayed identical, and the persisted dossier could validate with a truncated check set or an arbitrary `evaluation_id` after recomputing `content_sha256`. **Phase 7-A-R1 — Frozen Evidence Binding and Dossier Integrity Hardening is implemented and CLOSED** at its frozen-evidence binding and dossier-integrity boundary (implementation `aea01cb8e8aee17b4d7fcbaddbed31d6db3ec776`, exact-head Actions run `36663577065`, `success`; closure record `docs/status/phase-7-a-r1-2026-09-30.md`): the additive immutable `CalibrationEvidenceBindingV1` (`calibration_evidence_binding_v1`, checked-in drift-parity schema `schemas/calibration-evidence-binding.schema.json`) binds the exact manifest id/content hash, experiment id/content hash, canonical observation-set content hash and count, base-profile id/hash and proposal id/payload hash behind one deterministic `binding_id` (recomputed from the bound identities) and `content_sha256`; `build_calibration_evidence_binding()` produces it only at the calibration/freeze boundary where the exact manifest, observation rows and resulting experiment are simultaneously available (fail-closed across a foreign manifest or a proposal-less experiment), the canonical observation/proposal payload hashes are shared with the evaluator, and neither the evaluator nor any other path synthesizes the expected identity from untrusted evaluation-time inputs. Normal calibration persists the binding without manual JSON assembly through the additive `tve calibrate --evidence-binding-output` flag and the immutable `BacktestWorkspace.save_calibration_evidence_binding` store kind; `tve evolution evaluate` now requires the prior binding (`--evidence-binding`). `evaluate_controlled_evolution()` gains the additive `evidence_binding` parameter and six new named checks (`EVIDENCE_BINDING_PRESENT`, `EVIDENCE_BINDING_MANIFEST_IDENTITY`, `EVIDENCE_BINDING_EXPERIMENT_IDENTITY`, `EVIDENCE_BINDING_OBSERVATIONS_IDENTITY`, `EVIDENCE_BINDING_BASE_PROFILE_IDENTITY`, `EVIDENCE_BINDING_PROPOSAL_IDENTITY`), moving the canonical check set from thirteen to nineteen: a missing binding fail-closes to `BLOCKED` (never `READY_FOR_HUMAN_REVIEW`), a same-id/different-content manifest blocks on `EVIDENCE_BINDING_MANIFEST_IDENTITY`, and a `source_hash`-only observation substitution blocks on `EVIDENCE_BINDING_OBSERVATIONS_IDENTITY` even when every derived calibration/holdout score is unchanged. `ControlledEvolutionEvaluationV1` itself now carries `evidence_binding_id`/`evidence_binding_sha256` (both required for `READY_FOR_HUMAN_REVIEW`, supplied together or not at all), recomputes `evaluation_id` from the bound identities including the binding identity, and accepts only the exact canonical required-check set in canonical order (no omission, duplicate, unknown substitution or reordering) in the Pydantic model validator; the R1 checked-in schema enforces the nineteen-item count plus the allowed name enum but does not yet encode exact per-position order/uniqueness, a post-closure gap selected for R2; all existing Phase 7-A scorer/chronology/leakage/proposal/holdout/reproduction checks are unchanged. Four fail-on-pre-R1-main regression proofs were executed on the pristine baseline `32f77c57a58f1b350d5871165958bd0de443bd4c` before implementation (same-id manifest substitution and `source_hash` substitution both returned `READY_FOR_HUMAN_REVIEW`; truncated-check and wrong-`evaluation_id` dossiers both validated after rehashing), and the same committed file passes on the hardened tree; thirty-three focused R1 tests and the full suite (6920 passed / 2 skipped) are green with `rules/strict-v1.yaml` byte-identical throughout.

A same-day post-R1 audit (`docs/status/phase-7-a-r1-post-closure-review-2026-09-30.md`) preserves the R1 closure but blocks 7-B on two narrower integrity gaps. First, the R1 binding is self-consistent rather than uniquely authoritative for one `experiment_id`: because `build_calibration_evidence_binding()` can be rerun and the workspace stores bindings by content-derived `binding_id`, a caller can substitute same-id manifest content or non-scoring observation provenance, build a fresh matching binding, and remove the mismatch that R1 catches only against the original binding. Second, schema-only validation does not yet enforce the exact nineteen-check sequence even though the Pydantic model does. **Phase 7-A-R2 — Authoritative Calibration Freeze Anchor and Schema Semantic Parity Hardening** (`docs/goals/phase-7-a-r2-authoritative-freeze-anchor-hardening.md`) is selected before any candidate profile, `strict-v2`, profile PR or approval workflow. R2 must add one immutable experiment-keyed freeze anchor in the authoritative calibration workspace, make READY resolve/verify that anchor rather than trust an arbitrary sidecar binding path, and make the Draft 2020-12 schema reject reordered and count-preserving duplicate/omission dossiers. No manual owner action is planned; fail-on-R1 proofs and the full automatic gate remain mandatory.

A 2026-09-30 post-closure audit keeps the 7-A closure but selects **Phase 7-A-R1 — Frozen Evidence Binding and Dossier Integrity Hardening** before any profile materialization or 7-B work (`docs/status/phase-7-a-post-closure-review-2026-09-30.md`, goal `docs/goals/phase-7-a-r1-frozen-evidence-binding-hardening.md`). The current evaluator proves canonical replay but does not yet prove that a same-id manifest or non-scoring observation provenance is the exact calibration-time evidence; additionally, the persisted evaluation model does not yet require the complete canonical READY check set or a recomputed deterministic `evaluation_id`. R1 must add an additive calibration-time evidence binding and harden the dossier contract. Until then, do not treat a persisted `READY_FOR_HUMAN_REVIEW` dossier as sufficient authority for candidate-profile materialization, `strict-v2`, PR creation or human-approval recording.

**Phase 7-A-R2 — Authoritative Calibration Freeze Anchor and Schema Semantic Parity Hardening** is implemented from the reviewed R1 baseline `cbcf4cab5f361eb45d5be83a846e74c3b7f085cd` (goal `docs/goals/phase-7-a-r2-authoritative-freeze-anchor-hardening.md`, selection audit `docs/status/phase-7-a-r1-post-closure-review-2026-09-30.md`): the additive immutable `CalibrationFreezeRecordV1` (`calibration_freeze_record_v1`, checked-in drift-parity schema `schemas/calibration-freeze-record.schema.json`) binds the exact experiment id/content and the authoritative binding id/content behind one deterministic `freeze_id`/`content_sha256`, and is persisted by `experiment_id` — never by the content-derived `binding_id` — through the new authoritative `calibration-freeze-records` `BacktestWorkspace` store kind, so one frozen experiment identity carries exactly one committed freeze (first valid freeze commits, byte-identical repeat is idempotent, a conflicting freeze fails closed before any authoritative byte changes). The explicit workspace boundary `backtest/calibration_freeze.py` provides `commit_calibration_freeze` (manifest -> experiment -> binding prerequisites first, anchor published last, so a crash can leave unreferenced prerequisites but never a dangling anchor) and `resolve_anchored_calibration_evidence` (the fail-closed loader: missing/corrupt/foreign anchors and anchors referencing missing, mismatched or foreign bindings raise `CalibrationFreezeError`). Normal calibration persists the whole chain without manual JSON assembly through the additive `tve calibrate --workspace <root>` flag with non-destructive export paths; `tve evolution evaluate` takes exactly one anchor source — `--calibration-workspace` (authoritative, the only path that can reach `READY_FOR_HUMAN_REVIEW`) or the R1 `--evidence-binding` sidecar (compatibility input that can only produce a `BLOCKED` dossier). The pure evaluator gains the `freeze_record` parameter and three additive checks (`FREEZE_ANCHOR_PRESENT`, `FREEZE_ANCHOR_EXPERIMENT_IDENTITY`, `FREEZE_ANCHOR_BINDING_IDENTITY`; canonical set nineteen -> twenty-two), and the dossier records `freeze_anchor_id`/`freeze_anchor_sha256` (required together and for READY) inside a `evaluation_id` derivation that now includes the anchor identity. The generated checked-in evaluation schema encodes the exact canonical check sequence through a Draft 2020-12 `prefixItems` per-position `const` constraint with `items: false` (derived at class-definition time from the check model and `REQUIRED_EVALUATION_CHECK_NAMES`, so schema-only validation rejects reordered, count-preserving duplicate/omission, truncated, unknown-name and extra-item dossiers exactly like the model validator; cryptographic recomputation stays a model/runtime responsibility). Four fail-on-R1 regression proofs were executed on the pristine R1 baseline before implementation (fresh-binding same-id manifest substitution and fresh-binding `source_hash` provenance substitution both reached `READY_FOR_HUMAN_REVIEW`; schema-only validation accepted reordered and count-preserving duplicate/omission check dossiers), and the same committed file passes on the hardened tree; forty-two focused R2 tests plus the updated Phase 7-A/R1 suites are green. **Phase 7-A-R2 is closed** at implementation `3ac7684e6be483cc1a411478826797696c7951cf` (Actions run `36679050588`, `success`, exact `head_sha` match; full suite 6966 passed / 2 skipped; closure record `docs/status/phase-7-a-r2-2026-09-30.md`).

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
