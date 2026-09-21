# Phase 6-D1 — Deterministic Monitoring Cycle and Alert-Outbox Foundation

Status: **CLOSED / IMPLEMENTED**
Date: 2026-09-21
Selected after: Phase 6-C CLOSED
Selection audit: `docs/status/phase-6-d1-selection-2026-09-21.md`

Parent context:

- `AGENTS.md`
- `docs/goals/phase-6-a-watchlist-event-foundation.md`
- `docs/goals/phase-6-b-live-event-acquisition.md`
- `docs/goals/phase-6-c-reanalysis-executor.md`
- `docs/status/phase-6-c-2026-09-21.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/architecture/agent-api-web-surface.md`
- `config/project.example.toml`

## 1. Objective

Create the smallest synchronous, scheduler-neutral orchestration boundary that
turns one explicit monitoring-cycle request into durable, auditable results:

```text
explicit cycle spec + watchlist + current committed state
  -> Phase 6-B acquisition boundary
  -> Phase 6-A deterministic planning/atomic commit
  -> Phase 6-C controlled execution for the committed plan
  -> deterministic alert batch/outbox
  -> terminal cycle result + atomic latest pointer
```

D1 exists so later cron/Hermes/GitHub Actions and notification transports call
one proven operation instead of reimplementing provider, cursor, execution,
retry or alert semantics.

D1 is **not** the scheduler and does **not** deliver a notification.

## 2. Mandatory automatic baseline

Before editing, the coding agent must automatically:

1. switch to `main` and fast-forward only;
2. prove the working tree is clean;
3. record local HEAD and `git ls-remote origin refs/heads/main`;
4. verify GitHub Actions is green for that exact synchronized baseline;
5. run:
   ```bash
   python -m ruff check .
   python -m pytest
   ```
6. run every generated-contract, Dashboard, client-secret, Wrangler and
   cross-stack gate currently enforced by `.github/workflows/ci.yml`.

No routine baseline check may be delegated to the owner.

Phase 6-B real CNINFO live acceptance is already closed. Do not repeat a live
probe merely for ceremony. Repeat bounded real CNINFO acceptance only if D1
modifies Phase 6-B provider/acquisition/mapping/transport code.

## 3. Package boundary

Prefer a new package outside both frozen lower-level domains, for example:

`src/turtle_value_engine/monitoring_cycle/`

It may depend on:

- `monitoring_acquisition`;
- `monitoring`;
- `monitoring_execution`;
- project runtime configuration.

The dependency direction must be one-way. Phase 6-A `monitoring`, Phase 6-B
acquisition and Phase 6-C execution packages must not import D1.

Do not modify `strict-v1`, deterministic investment formulas, hard-gate
semantics, Business Quality semantics, valuation semantics, Phase 5R
acceptance semantics or adjustment approval rules.

## 4. One-cycle contract

Add the minimum typed/versioned contracts and checked-in JSON schemas required
for a durable single-cycle API.

The cycle request/spec must record, directly or by validated reference:

- watchlist identity/content hash;
- explicit cycle `as_of` / PIT boundary;
- source/acquisition policy identity;
- the exact resolved acquisition window;
- network permission;
- Phase 6-A event-impact policy identity;
- Phase 6-C execution-policy identity;
- explicit local workspace/job/cycle-store identities or roots where needed;
- explicit non-secret per-listing execution bindings when preparation requires
  company context or prepared/prior artifacts.

Wall clock must never silently become the investment or event PIT boundary.
If a CLI helper derives a source calendar date from `as_of`, it may do so only
through an existing documented source-calendar rule and must persist the exact
resolved value in the cycle artifact.

Do not put resolved secrets, cookies, tokens, signed URLs or model credentials
in a cycle contract.

## 5. Explicit execution bindings; no guessed company context

Unattended execution cannot guess `Company.name`, sector, reporting currency,
prepared input, prior analysis or research-runtime availability.

Introduce the smallest explicit, typed, non-secret binding mechanism needed by
the cycle runner, for example a `MonitoringExecutionBindingV1` /
`MonitoringExecutionCatalogV1`, or an equivalent injected resolver.

It may bind one listing to explicitly supplied:

- company context required by the existing preparation boundary;
- prepared-input artifact/path for a controlled offline path;
- prior-analysis artifact/path;
- other non-secret resolver metadata already accepted by Phase 6-C.

Do not overload `WatchlistSpecV1` with unrelated runtime fields merely for
convenience unless a higher-priority contract requires it.

Missing execution context must fail closed with a stable D1 blocker and alert;
it must not fabricate a company field or silently skip a requested re-analysis.

A real model runtime is not required for D1 closure. FULL_REANALYSIS must
continue to use the existing injected Phase 6-C research boundary and may
produce the existing `BLOCKED_RESEARCH_RUNTIME` result when no runtime is
explicitly available.

## 6. Cycle execution order and mutation ownership

A D1 cycle must have one clear mutation order.

### 6.1 Acquisition

Use the existing Phase 6-B service.

- default network policy remains deny;
- live access requires explicit allow;
- offline/frozen replay must work with sockets blocked;
- acquisition alone never advances Phase 6-A cursors.

### 6.2 Monitoring plan/commit

Feed only the canonical acquired `MonitoringEventBatchV1` to the existing
Phase 6-A planner.

The Phase 6-A workspace remains the sole owner of watchlist state, processed
events and event cursors. D1 must call its public commit boundary rather than
writing those files itself.

### 6.3 Re-analysis

After a monitoring run is committed, execute **every**
`ReanalysisRequestV1` in its committed plan in deterministic/canonical order
through Phase 6-C.

D1 must not copy Phase 6-C execution logic into the cycle package.

For each request persist/reference the exact terminal Phase 6-C job result.

### 6.4 Alert projection

After execution, build a deterministic, schema-valid, secret-free alert batch.

At minimum distinguish factual states equivalent to:

- newly processed material event(s);
- manual review required;
- re-analysis blocked;
- re-analysis failed;
- re-analysis succeeded with exact output/surface reference.

Alerts may copy validated deterministic states and identifiers; they must not
invent BUY/SELL language, overwrite `CompanyAnalysis`, auto-approve an
adjustment or turn a monitoring severity into an investment conclusion.

### 6.5 Cycle commit

Persist the cycle result and alert batch in a separate D1 store using immutable
artifacts plus an atomic latest pointer (or an equivalently fail-safe design).

Prefer terminal-only cycle records. Do not leave a durable false `RUNNING`
state after a process crash.

## 7. Important unresolved-run gate

The current Phase 6-C proof deliberately requires the current monitoring
pointer to reference the committed run/state.

Therefore D1 must protect retryability.

Before committing a **new** monitoring run, inspect the current committed run
and its required Phase 6-C dispositions in the D1/Phase 6-C stores.

Default D1 rule:

- `SUCCEEDED` -> resolved;
- `NO_ACTION` -> resolved;
- `MANUAL_REVIEW_REQUIRED` -> resolved as execution state, but must emit an
  attention alert;
- `BLOCKED` -> unresolved;
- `FAILED` -> unresolved.

If the current run contains unresolved BLOCKED/FAILED requests, fail closed
before advancing the Phase 6-A pointer. Do not add a default
"acknowledge/skip/continue" switch in D1.

This conservative rule avoids making an older run non-executable merely because
a scheduler polled again.

If non-blocking historical execution is later required, design an explicit
historical commit journal in a separate goal rather than weakening
`MonitoringWorkspace.load_committed_run()`.

## 8. Cycle statuses and idempotency

Define stable, non-secret terminal cycle outcomes. Exact names are an
implementation choice, but the semantics must distinguish at least:

- successful no-change/no-action cycle;
- successful cycle with durable alerts;
- attention-required cycle because one or more execution results are manual,
  blocked or failed;
- acquisition/planning/commit/store failure.

A deterministic cycle identity must be derived only from explicit request
inputs and versioned policy identities, never the current clock.

Idempotency requirements:

- retrying an already successful identical cycle reuses its recorded result and
  alert batch;
- a successful identical retry performs zero duplicate provider/model calls;
- immutable content conflicts under an existing identity fail closed;
- a pointer-write crash can be repaired from immutable artifacts without
  rerunning already completed provider/model work when the underlying
  lower-level artifacts prove the result;
- no duplicate alert item may be created for the same deterministic semantic
  event/job identity.

Do not claim "exactly once" external delivery in D1. D1 has no delivery
transport.

## 9. Alert outbox contract

Persist a typed `AlertBatchV1` / equivalent with deterministic identities.

Each alert item should contain only the minimum auditable facts, such as:

- watchlist/listing;
- source run/cycle;
- triggering event IDs and canonical event types;
- impact class;
- Phase 6-C job ID/status/failure code when applicable;
- validated surface/analysis reference when available;
- stable machine reason;
- source/event availability time when already known.

Messages must be bounded and secret-free.

The alert outbox is immutable derived state. Delivery attempts/receipts belong
to D2 and must not be mixed into the D1 schema unless needed solely to identify
an alert.

## 10. CLI/library surface

Expose an injected library API plus a non-interactive one-cycle CLI, for
example:

```text
tve watch cycle --config ... --as-of ... [explicit acquisition/execution inputs]
tve watch cycle-status --cycle-root ... --cycle-id ...
```

Exact flags may differ, but:

- every network permission remains explicit;
- no hidden daemon/background loop is started;
- no scheduler is installed;
- output is bounded and secret-free;
- a cycle can be run entirely offline from persisted/fake inputs in tests;
- missing model runtime or company/preparation binding becomes a typed blocker,
  never an interactive prompt.

Do not create generic remote command execution.

## 11. Automatic verification matrix

Verification is part of implementation, not a follow-up suggestion.

Add deterministic tests that automatically prove at least:

1. arbitrary/orphan lower-level artifacts cannot be treated as a valid cycle;
2. deterministic cycle identity and schema drift;
3. explicit `as_of` propagation through acquisition filtering, Phase 6-A
   run and Phase 6-C execution;
4. network deny causes zero live transport calls;
5. cache-only acquisition and cycle execution work with sockets blocked;
6. fake live acquisition -> canonical batch -> Phase 6-A commit -> Phase 6-C
   execution -> alert batch succeeds end to end;
7. no-event/no-change cycle performs zero re-analysis/model calls;
8. acquisition failure leaves the existing Phase 6-A pointer/state
   byte-identical and creates no false re-analysis result;
9. monitoring commit failure leaves the previous committed state readable;
10. every committed re-analysis request is executed once in canonical order;
11. NO_REANALYSIS, PARTIAL, FULL and URGENT outcomes are folded into the cycle
    without changing their Phase 6-C semantics;
12. FULL with no research runtime remains the exact typed Phase 6-C blocker;
13. missing execution/company binding is a stable D1 blocker and no facts are
    guessed;
14. manual-review alerts require zero provider/model/analysis work beyond the
    lower-level zero-call contract;
15. BLOCKED/FAILED current-run jobs prevent a subsequent cycle from advancing
    the Phase 6-A pointer;
16. resolved SUCCEEDED/NO_ACTION/MANUAL dispositions permit the next cycle;
17. no automatic adjustment approval or implicit accepted-adjustment reuse;
18. repeated successful identical cycle performs zero duplicate
    provider/model work;
19. deterministic alert IDs and duplicate suppression;
20. alert batches contain no resolved secrets and have bounded messages;
21. cycle artifact/content conflicts fail closed;
22. failure injection around cycle immutable artifacts/latest pointer is
    restart-safe;
23. pointer-only crash repair does not repeat already proven expensive work;
24. Phase 6-A and Phase 6-C stores remain individually valid/canonical after a
    D1 cycle;
25. D1 introduces no notification transport, scheduler loop, Dashboard write
    endpoint or brokerage operation;
26. CLI success/failure output is machine-readable enough for D2 and is
    bounded/secret-free.

Before declaring D1 complete, run the full repository gate:

```bash
python -m ruff check .
python -m pytest
```

Then run **every** generated-contract/Dashboard/security/Cloudflare dry-run and
cross-stack check currently enforced by `.github/workflows/ci.yml`.

After push, verify GitHub Actions `success` for the **exact closing SHA** and
record both the SHA and Actions run ID in the D1 closure document.

A focused test run is not a substitute for the full gate.

## 12. Live-source verification policy

D1 must not rely on the network for ordinary CI.

Because Phase 6-B live CNINFO acquisition is already accepted, D1 closure
requires automatic fake-transport and persisted-cache composition tests.

If D1 changes any Phase 6-B provider/acquisition/mapping/transport code, Codex
must also automatically run the bounded owner-authorized real CNINFO smoke,
record the exact command, source/listing/window, output identities, replay
result and exact resulting CI SHA.

If D1 does not change Phase 6-B code, repeating the live probe is unnecessary
ceremony.

## 13. Human verification boundary

**None is required for Phase 6-D1 software closure.**

No browser check, Cloudflare click-through, live LLM call or notification
receipt is needed in D1.

If an unexpected CAPTCHA/login/interactive-consent boundary is genuinely
unavoidable, Codex must stop at that exact boundary and record:

1. exact command before the boundary;
2. exact URL/screen and exact human action required;
3. exact resume command;
4. exact expected successful output/state;
5. exact automatic checks that run after resumption;
6. precise unproved remainder.

Do not use vague statements such as "manual verification recommended",
"evidence incomplete", "owner should validate" or unexplained internal
shorthand.

## 14. Explicitly out of scope

Do not start in D1:

- cron/systemd installation;
- GitHub Actions `schedule:` automation;
- Hermes cron wiring;
- email/Slack/Telegram/webhook/push delivery;
- delivery retries/receipts;
- Dashboard monitoring pages;
- new monitoring HTTP endpoints;
- Cloudflare/Tunnel/Access mutation;
- remote object storage solely to make an ephemeral scheduler work;
- historical-commit journal redesign;
- extra CNINFO event taxonomy;
- BJ/H disclosure-source expansion;
- FQGate Bridge event/history adapter before its typed source contract exists;
- automatic model/LLM vendor integration;
- automatic adjustment approval;
- brokerage/trading/order/funds operations;
- `strict-v1` changes.

## 15. D1 closure criteria

Phase 6-D1 may be marked CLOSED only when:

1. Phase 6-C remains closed and unchanged unless a concrete defect is proven;
2. one explicit synchronous cycle composes 6-B -> 6-A -> 6-C without copying
   their semantics;
3. explicit execution bindings prevent guessed company/preparation context;
4. unresolved current-run jobs are fail-closed before a new monitoring commit;
5. cycle/result/outbox contracts are typed, schema-checked, immutable and
   restart-safe;
6. alert projection is deterministic, auditable and secret-free;
7. successful retries do not duplicate expensive lower-level work;
8. every D1 automatic test and full repository CI gate is green;
9. exact closing SHA CI is green and recorded;
10. no D2/D3/6-E, trading or unrelated source expansion is mixed in.

Stop after D1 closure. Select D2 only in a separate audit/planning step.
