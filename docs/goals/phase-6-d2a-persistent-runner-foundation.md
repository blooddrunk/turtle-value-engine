# Phase 6-D2A — Persistent Unattended Runner Foundation

Status: **IMPLEMENTED / POST-CLOSURE R1 HARDENING REQUIRED BEFORE D2B**
Date: 2026-09-22
Selected after: Phase 6-D1 CLOSED
Selection audit: `docs/status/phase-6-d2a-selection-2026-09-22.md`
Implementation closure: `docs/status/phase-6-d2a-2026-09-22.md`
Post-closure review: `docs/status/phase-6-d2a-r1-review-2026-09-22.md`
Required follow-up: `docs/goals/phase-6-d2a-r1-lease-hardening.md`

Coding-agent handoff:
`docs/status/phase-6-d2a-next-coding-agent-goal.md`

## 1. Objective

Add the smallest unattended execution boundary around the already-proven
Phase 6-D1 synchronous monitoring cycle.

D2A must answer one operational question reliably:

> When an external scheduler wakes the process on a persistent host, can one
> durable activation enter D1 exactly once, survive overlap/crash/restart, and
> leave machine-verifiable terminal evidence without changing D1 semantics?

D2A is **not** the notification phase. External delivery and receipt semantics
are deliberately deferred to D2B.

## 2. Runtime decision

The first monitoring deployment model is a **persistent Linux host using a
host-native systemd timer/service**.

Reasons:

- Phase 6-A cursor/event state is already a durable local store;
- Phase 6-C job/artifact state is already a durable local store;
- Phase 6-D1 cycle/result/outbox state is already a durable local store;
- a persistent host can reuse those stores directly;
- GitHub Actions would have an ephemeral workspace and would force an unrelated
  remote-state migration before unattended monitoring is even proven;
- Hermes is optional later, but deterministic D2A does not need an agent runtime
  just to wake a CLI.

The core runner must remain scheduler-neutral. systemd is the reference wakeup
mechanism, not a dependency of the Python contracts.

## 3. Required architecture

Add a separate runner package/boundary (name may vary, but do not mix delivery
state into `monitoring_cycle/`).

The runner must persist three concepts:

1. **activation intent** — created atomically before entering D1; freezes the
   resolved PIT/`as_of`, explicit input/config identities and a stable
   activation id;
2. **single-host lease** — prevents overlapping activations for the same runner
   identity and has explicit, testable stale/recovery behavior;
3. **terminal runner receipt** — binds the activation to the D1
   `MonitoringCycleResultV1` and `MonitoringAlertBatchV1` identities/hashes
   plus a terminal runner classification.

Exact class names are implementation details, but all persisted contracts must
be typed, versioned, canonical, hash-verified and schema-backed.

### Activation identity / retry rule

A retry after a crash must reuse the unfinished activation intent and therefore
reuse the same resolved `as_of` and D1 request identity. It must not create a
new cycle just because wall-clock time advanced.

A new scheduler wake may create a new activation only after the previous
activation has a valid terminal runner receipt.

### D1 composition rule

D2A calls the existing D1 public boundary. It must not copy or reimplement:

- Phase 6-B acquisition;
- Phase 6-A planning/commit/cursor semantics;
- Phase 6-C re-analysis execution;
- D1 alert construction;
- D1 unresolved-current-run rules.

If D1 returns a terminal attention/failure state, D2A records it factually. It
must not reinterpret that state as an investment recommendation or silently
advance monitoring state.

## 4. CLI and reference deployment

Add one non-interactive runner CLI surface, for example:

```text
tve watch unattended-run --runner-config <path>
tve watch unattended-status --runner-root <path> [--activation-id <id>]
```

Exact flags may differ, but:

- all file/store inputs are explicit;
- no directory scanning guesses company/prepared-input/prior-analysis context;
- network access remains deny-by-default and can reach the existing live
  acquisition boundary only through the existing explicit D1/6-B allow policy;
- stdout/status output is bounded and secret-free;
- the command exits with documented machine-readable classifications.

Add reference systemd service/timer files under a deployment/operations path.
The reference unit must:

- call only the non-interactive runner CLI;
- use explicit persistent working/state paths;
- avoid embedding credentials;
- use restart-safe timer semantics (including `Persistent=true` where
  appropriate);
- remain a template; real owner host/cadence/credentials are Phase 6-E inputs.

Do **not** add a scheduled GitHub Actions workflow for monitoring.

## 5. Crash / overlap semantics

Automatically prove at least these cases:

1. wake before any prior activation -> one intent -> one D1 call -> one receipt;
2. repeated invocation after terminal receipt -> new activation only when the
   scheduler actually invokes again, never by replaying the same unfinished
   intent;
3. two overlapping processes for the same runner identity -> exactly one owns
   the lease; the other performs zero provider/model/D1 work;
4. stale/abandoned lease recovery is explicit and cannot steal a live lease;
5. crash after intent but before D1 terminal -> retry reuses the same intent
   and PIT;
6. crash after D1 terminal artifacts but before runner receipt/pointer -> repair
   the runner receipt from D1 artifacts without repeating provider/model work;
7. corrupt/conflicting intent, lease, receipt or pointer fails closed;
8. unresolved D1 current-run state remains a D1 blocker; D2A does not add a
   bypass;
9. no-event D1 cycles still make zero re-analysis/model calls;
10. runner restart never mutates existing Phase 6-A/6-C/D1 artifacts except
    through their already-defined public boundaries.

## 6. Configuration / secrets

Extend the existing typed project configuration only if needed. Do not add
phase-local dotenv files.

Configuration may contain non-secret paths, runner identity, lease policy and
reference schedule metadata. Credentials must remain existing explicit
environment/keyring/injected references and must not be copied into runner
artifacts, logs, receipts or systemd unit files.

## 7. Mandatory automatic verification

The coding agent owns every verification step that can be automated.

Before editing:

- synchronize `main` fast-forward-only;
- prove clean tree and exact baseline SHA;
- verify the baseline GitHub Actions run is green.

During implementation:

- focused D2A unit/integration tests for the full activation/lease/recovery
  matrix above;
- fake/injected D1 boundary tests;
- at least one real subprocess black-box test of the runner CLI;
- schema drift checks for every new persisted contract;
- socket/network denial test when network is not explicitly allowed;
- bounded-output and secret-scan tests;
- validate the reference systemd unit/timer automatically with
  `systemd-analyze verify` in CI;
- prove no scheduled GitHub Actions monitoring workflow was introduced.

Before closure, automatically run the entire existing repository gate:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
systemd-analyze verify <the checked-in D2A service/timer units>
```

After push, verify the **exact closing implementation SHA** GitHub Actions run
and record the run id/result in the D2A closure document. Do not claim closure
from local tests alone.

## 8. Manual intervention boundary

D2A has **no planned manual functional acceptance**.

Do not deploy to the owner's VPS, choose a real watchlist cadence, enter
credentials, or perform a live unattended run just to close D2A. Those are
Phase 6-E acceptance inputs.

If an unexpected external boundary genuinely prevents automatic verification,
the closure document must record all of the following, not a vague "manual
verification required":

1. exact command that reaches the boundary;
2. exact screen/URL/system state;
3. exact human action;
4. exact resume command;
5. expected successful output/state;
6. automatic checks that run after resumption;
7. precise remaining unproved boundary.

## 9. Explicit non-goals / stop boundary

Do not start or mix in:

- Phase 6-D2B external webhook/email/Slack/Telegram delivery;
- notification acknowledgement/read state;
- Phase 6-D3 Dashboard monitoring pages/API projection;
- Phase 6-E real unattended owner deployment/acceptance;
- GitHub Actions scheduled monitoring;
- remote derived-state storage solely to support Actions;
- Hermes-specific runtime coupling;
- new CNINFO taxonomy/source coverage;
- FQGate Bridge event adapter;
- trading/brokerage actions;
- `strict-v1`, valuation, hard-gate or adjustment-approval changes.

## 10. Acceptance criteria

D2A is complete only when:

1. one persistent-host scheduler wake can enter D1 non-interactively;
2. activation intent freezes PIT/as_of before D1 and is durable;
3. retries reuse unfinished activation identity instead of manufacturing a new
   wall-clock-derived cycle;
4. overlapping invocations are automatically excluded with zero duplicate D1
   work;
5. crash/restart recovery is proven before and after D1 terminal publication;
6. terminal runner receipts bind exact D1 result/outbox identities and hashes;
7. all new persisted contracts have checked-in schemas and drift tests;
8. network remains deny-by-default and secrets never enter runner artifacts or
   unit files;
9. reference systemd files pass automatic verification;
10. full repository CI gates pass;
11. exact closing-SHA GitHub Actions success is recorded;
12. no D2B/D3/6-E or unrelated scope is mixed in.
