# Phase 6-D3 — Read-only Monitoring Operations Dashboard Projection

Status: **CLOSED / IMPLEMENTED**
Implementation record:
`docs/status/phase-6-d3-2026-09-23.md`
Date: 2026-09-23
Selected after: Phase 6-D2B-R2 post-closure review

> Closed at implementation `eb5f199437cba1d9747f87da7a6591943cbbacab`
> (Actions run 35860274042, `success`, exact head SHA match); see the
> implementation record for the full evidence.

Selection audit:
`docs/status/phase-6-d2b-r2-post-closure-review-2026-09-23.md`

Coding-agent handoff:
`docs/status/phase-6-d3-next-coding-agent-goal.md`

## 1. Objective

Expose the already-proven Phase 6 monitoring runtime as a **bounded read-only
operations projection** in the existing private API/Worker/Dashboard stack.

D3 does not create a second monitoring engine. It reads validated durable state
from Phase 6-A, 6-C, D1, D2A/R1 and D2B/R1/R2 and projects that state without
re-running providers, models, cycles or delivery.

The public application contract for this slice should be a typed versioned
read model, preferably:

```text
MonitoringOperationsProjectionV1
contract = monitoring_operations_projection_v1
```

This projection is an API/read model, not a new authoritative persisted runtime
ledger. The underlying stores remain the source of truth.

## 2. Frozen boundaries

Preserve all of the following:

1. `strict-v1`, deterministic investment math, hard gates, valuation and A6/PIT
   semantics are unchanged.
2. Phase 6-A remains the owner of monitoring state/cursors.
3. Phase 6-C remains the owner of re-analysis job/attempt artifacts.
4. D1 remains the owner of cycle/result/alert-outbox artifacts.
5. D2A/R1 remains the owner of runner intent/lease/receipt/latest state.
6. D2B/R1/R2 remains the owner of delivery intent/claims/attempts/latest state.
7. D3 may **read and validate** those stores; it may not repair, rewrite,
   acknowledge, retry or advance them.
8. No provider, analyst/model, research orchestrator, acquisition adapter,
   webhook transport or scheduler call is permitted from a D3 read request.
9. No new remote state database is introduced merely for Dashboard projection.
10. Existing M6-B/C read-only API, Cloudflare Access/Worker security and
    Chinese-first presentation boundaries remain intact.
11. Phase 6-E live owner deployment/cadence/notification acceptance remains
    outside D3.
12. No Bridge/source expansion, brokerage/order/funds operation or investment
    rule change is in scope.

## 3. Explicit source binding: no arbitrary discovery

D3 must be anchored to one explicit configured runner/runtime set.

Preferred inputs are the existing typed `RunnerConfigV1` plus the typed
`ProjectConfig`:

- monitoring workspace/watchlist identity;
- re-analysis job root;
- cycle store root;
- runner root and runner identity;
- delivery root from `[monitoring.delivery]`.

If one required non-secret path/identity is not available from those contracts,
add one small typed `MonitoringOperationsSourcesV1` configuration rather than
guessing paths, scanning CWD, walking `.tve-private`, or recursively
discovering "latest" artifacts.

The projection service must never expose those local root paths in the returned
payload.

## 4. Bounded projection chain

The first D3 package should intentionally project one current operational chain,
not an unbounded history browser:

```text
explicit source binding
  |
  +-> MonitoringWorkspace.status(configured watchlist)
  |
  +-> RunnerStore + RunnerLease.probe(configured runner)
        |
        +-> active activation when one exists
        |   otherwise latest terminal receipt/activation
        |
        +-> cycle_id
              |
              +-> MonitoringCycleStore read-only status
              |
              +-> only re-analysis jobs referenced by that cycle/result
              |
              +-> DeliveryLedgerStore filtered by activation_id
  |
  v
MonitoringOperationsProjectionV1
```

Do not implement global recursive job/cycle/delivery history discovery in D3.
A later bounded history package can be added if there is a concrete owner need.

When an existing helper has hidden repair/write behavior, do not call it from
D3. Add or use an explicit read-only validation/projection function instead.

## 5. Required projection semantics

The typed projection should expose enough information for the owner to answer:

- Is monitoring state available for the configured watchlist?
- Is the runner free/live/busy/attention-required according to the existing
  truthful lease probe?
- Is there an active/unfinished activation, or what was the latest terminal
  activation?
- What cycle does that activation bind and what terminal D1 status did it
  produce?
- Which re-analysis jobs were required by that cycle and what are their exact
  latest dispositions/statuses?
- What deliveries belong to the activation, and are they delivered, retryable,
  ambiguous, permanently failed or NOOP?
- Is each delivery latest-state pointer current, missing or stale-repairable?
- How many persisted delivery outcomes exist versus how many durable dispatch
  budget slots have been consumed?
- Which dispatch slots are unresolved?

Do not invent a single generic "healthy" boolean that hides these states.

### 5.1 R2 accounting must remain explicit

For each delivery shown in D3:

- `attempt_count` / persisted outcome count and
  `dispatch_claim_count` / consumed authorized transport slots are different
  concepts and must have different field/label semantics;
- `unresolved_claim_numbers` must be retained;
- numbering gaps in persisted attempts are legitimate after orphan recovery;
- `AMBIGUOUS / ORPHANED_DISPATCH` must never be rendered as delivered,
  retryable-unsent or harmless;
- `CURRENT / MISSING / STALE_REPAIRABLE` pointer state must remain visible;
- contradictory/corrupt pointer or ledger evidence must fail closed instead of
  being omitted from the page.

### 5.2 No sensitive/local implementation leakage

The projection/API/browser payload must not contain:

- local absolute store paths;
- webhook endpoint URLs;
- bearer/auth token values;
- Cloudflare Access client secrets;
- runner lease holder tokens;
- raw response bodies;
- raw provider payloads;
- arbitrary environment values.

IDs and hashes needed for audit may be returned, but the Chinese-first UI should
place long machine identifiers in technical/audit details rather than dominant
primary copy.

## 6. API integration

Extend the existing read-only FastAPI application with one bounded first-slice
endpoint:

```http
GET /v1/monitoring/operations
```

Preferred response model: `MonitoringOperationsProjectionV1`.

Requirements:

- no query parameters in the first slice unless a concrete bounded need is
  proven;
- `Cache-Control: no-store` or equivalently conservative live-status caching;
- configured-but-empty/not-yet-run state returns a typed available/unavailable
  projection rather than fake success;
- corrupt/contradictory source evidence returns a stable machine-readable
  fail-closed error and no partial fabricated "OK" payload;
- unsupported POST/PUT/PATCH/DELETE remains 404/405 with the read-only error
  contract;
- existing `/healthz` and `/v1/surfaces*` behavior stays backward compatible;
- generated OpenAPI and generated Dashboard TypeScript types remain the only
  contract source — do not hand-copy a second TS interface.

If adding the monitoring service to `create_surface_app`, make it optional so
existing surface-only consumers/tests remain valid. Do not force monitoring
state to exist merely to serve research surfaces.

## 7. Worker boundary

Add exactly the fixed same-origin route:

```text
/api/v1/monitoring/operations
```

to the existing Worker allowlist.

Requirements:

- GET/HEAD only according to the upstream capability;
- no arbitrary `/api/v1/monitoring/*` forwarding;
- no browser-supplied upstream URL;
- no new client-visible secret;
- preserve the existing origin/Cloudflare Access service-token policy;
- preserve fail-closed origin validation;
- reject unsupported methods before upstream invocation;
- do not add a mutation or generic proxy route.

## 8. Dashboard UI

Add a Chinese-first read-only route, preferably:

```text
/monitoring
```

and a corresponding navigation entry.

Minimum useful page:

1. **运行概览**
   - monitoring availability;
   - runner/lease state;
   - active or latest activation;
   - current/latest cycle status;
   - explicit attention/error state.
2. **重分析任务**
   - only jobs bound to the projected cycle;
   - exact disposition/status with existing friendly state explanations;
   - IDs/hashes behind technical details.
3. **通知投递**
   - delivery status and pointer status;
   - destination identity/transport without endpoint secret;
   - persisted outcome count;
   - consumed dispatch-slot count;
   - unresolved dispatch-slot numbers;
   - last safe HTTP/error classification where available.
4. **审计详情**
   - watchlist/run/activation/cycle/job/delivery IDs and content hashes needed to
     trace the durable chain.

The page must distinguish unavailable, empty, blocked, failed, manual-review,
ambiguous, retryable, delivered, missing-pointer and stale-pointer states.
Never turn null/unavailable into zero or PASS.

There must be no "run now", "retry", "resend", "repair", "acknowledge",
"dismiss", "approve", "trade", "order" or other state-changing control.

Do not add client-side scheduling as part of D3. A page load/refetch may read
current state; real monitoring cadence remains D2A/6-E.

## 9. Deterministic automatic tests

### 9.1 Projection/service tests

Use real store classes with deterministic fixtures and injected sentinels.

Automatically prove at minimum:

1. completely empty configured stores produce an explicit unavailable/empty
   projection without mutation;
2. a normal committed chain projects the expected watchlist -> runner ->
   activation -> cycle -> job -> delivery identities;
3. active/unfinished activation state is represented without pretending the
   latest prior receipt is current;
4. D1 `MANUAL_REVIEW_REQUIRED`, `BLOCKED` and `FAILED` remain distinct;
5. Phase 6-C job terminal states remain exact;
6. D2B `DELIVERED`, `RETRYABLE_FAILURE`, `AMBIGUOUS`,
   `PERMANENT_FAILURE` and `NOOP` remain exact;
7. an R2 orphan case proves persisted outcome count != consumed dispatch-slot
   count and preserves `unresolved_claim_numbers`;
8. delivery pointer `MISSING` and `STALE_REPAIRABLE` are visible;
9. corrupt/non-canonical/foreign/contradictory evidence fails closed;
10. provider/acquisition/model/research/cycle-execution/delivery-transport
    sentinels are never invoked;
11. byte/file inventory of every source store is identical before and after
    projection reads;
12. no secret or local-root sentinel appears anywhere in serialized output.

### 9.2 API tests

Prove:

- the endpoint returns the generated typed response;
- surface-only app construction still works without monitoring;
- no mutation endpoint exists;
- unknown monitoring subpaths fail rather than proxy/discover;
- stable fail-closed errors contain no local path/secret;
- OpenAPI generation is deterministic and drift-checked.

### 9.3 Worker tests

Prove:

- only `/api/v1/monitoring/operations` is forwarded;
- query/path/method broadening is rejected;
- existing surface routes remain unchanged;
- Access service credentials remain server-side only.

### 9.4 Dashboard tests

Prove:

- Chinese-first monitoring navigation/page;
- every important operational state has intentional copy;
- empty/not-configured and error/conflict states are distinct;
- delivery persisted-outcome count and consumed-dispatch-slot count use distinct
  labels and values;
- unresolved slot numbers are visible when present;
- pointer status remains visible;
- IDs/hashes remain available in technical details;
- no mutation controls exist;
- mobile-safe semantic structure and keyboard-focusable controls remain intact.

## 10. Real automatic integration verification

Extend or add a deterministic real local cross-stack smoke.

The smoke must automatically:

1. create a temporary, valid Phase 6-A/6-C/D1/D2A/D2B store chain using the real
   model/store builders — no hand-written unverifiable JSON;
2. include at least one delivery fixture where R2 accounting is observable
   (for example an orphaned consumed slot distinct from persisted outcomes);
3. start the real Python API on loopback;
4. start/use the real Dashboard Worker/Vite preview path;
5. request `/api/v1/monitoring/operations` through the same-origin Worker;
6. assert known runner/cycle/job/delivery identities and exact status values;
7. assert the R2 counts/unresolved slots survive the complete Python -> OpenAPI
   -> Worker -> client path;
8. assert one mutation request is rejected;
9. assert the response contains none of the injected path/secret sentinels;
10. shut everything down and assert clean process exit.

No public Internet, owner credentials, real provider request, real model call,
real webhook send or real VPS is required for this smoke.

## 11. Full automatic gate

### 11.1 Baseline

Before editing:

- fast-forward-only sync with `main`;
- inspect `git status --short --branch`, `git rev-parse HEAD` and remotes;
- do not overwrite unrelated owner changes;
- truthfully verify baseline CI.

A documentation-only HEAD may legitimately have no Actions run. In that case,
do **not** claim an exact-head CI result that does not exist. Identify the
latest code-affecting ancestor with an exact successful Actions run and record
that fact, then run the full local baseline gate below before editing.

### 11.2 Required commands

Run the focused new tests plus the existing full gate, at minimum:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest tests/test_monitoring*.py
python -m pytest
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard install --frozen-lockfile
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
```

If D3 adds a dedicated focused smoke/script, run it explicitly as well.

Use `python3` or another executable only when the environment genuinely
requires it; record the actual substitution and result.

Do not delegate any automatable command to the owner.

## 12. Browser/layout verification

Because D3 adds a new owner-facing page, verify layout as well as DOM semantics.

Automation preference:

1. existing browser/computer capability in the agent environment;
2. installed Chromium/Chrome/Edge in headless mode;
3. only if neither exists, the bounded manual fallback below.

Automated browser coverage should include at minimum:

- desktop around 1440x900;
- mobile around 390x844;
- normal operations projection;
- an attention/ambiguous delivery state;
- expanded technical/audit details;
- no horizontal page overflow;
- no mutation controls.

Do not add a heavy new browser framework solely to satisfy one visual check if a
usable browser is already available.

## 13. Manual fallback — exact boundary

Manual verification is permitted **only** for visual/layout behavior when no
browser automation is genuinely available.

All API/data/security/read-only/cross-stack semantics must already be proven
automatically.

The handoff must then provide the owner:

1. the exact command(s) that create/start the deterministic D3 fixture/API/
   preview;
2. the exact local `/monitoring` URL;
3. desktop check at roughly 1440x900: no clipped/overlapping primary content;
4. mobile check at roughly 390x844: no horizontal page overflow or unusable
   control;
5. expand technical details and confirm IDs/hashes remain readable;
6. confirm delivery labels distinguish persisted outcomes from consumed dispatch
   slots and show unresolved slots when the fixture contains them;
7. confirm no run/retry/resend/repair/acknowledge/write control exists;
8. report the exact numbered step and visible symptom on failure.

This manual check proves layout only. It is not evidence for store integrity,
secret hygiene, R2 accounting or API correctness.

If this fallback is required but has not been completed, record
`BLOCKED_BY_VISUAL_VERIFICATION`. Do not write "evidence incomplete" and call
D3 closed.

## 14. Closing CI rule

After pushing the implementation:

- query GitHub Actions for the **exact implementation SHA**;
- wait only in the sense of polling within the agent's current execution until
  the available run reaches a terminal state; do not ask the owner to inspect
  Actions manually;
- D3 may be marked CLOSED only after a successful required run whose
  `head_sha` exactly matches the implementation SHA;
- record exact SHA, run id, conclusion, focused test counts, full-suite
  pass/skip counts, Dashboard test count, smoke result and browser/manual layout
  result.

If CI is red, inspect logs, fix the implementation and rerun. Do not close from
local tests alone.

## 15. Expected implementation scope

Likely files include:

```text
src/turtle_value_engine/monitoring_dashboard/** or equivalent read-only projection module
src/turtle_value_engine/surface/api.py
src/turtle_value_engine/cli.py only if explicit serving/source wiring needs it
schemas/monitoring-operations-projection.schema.json
scripts/export_surface_openapi.py
scripts/dashboard_cross_stack_smoke.py
tests/test_monitoring_dashboard.py
tests/test_surface_api.py
apps/dashboard/worker/index.ts
apps/dashboard/worker/index.test.ts
apps/dashboard/src/api/client.ts
apps/dashboard/src/router.tsx
apps/dashboard/src/views/monitoring.tsx
apps/dashboard/src/presentation.ts
apps/dashboard/src/presentation.test.ts
apps/dashboard/src/app.test.tsx
apps/dashboard/src/styles.css
docs/architecture/runtime-and-automation.md
docs/status/<D3 implementation record>
docs/roadmap.md
AGENTS.md
```

Exact module naming may follow repository conventions, but keep the projection
framework-neutral and the HTTP/UI layers thin.

## 16. Out of scope / stop boundary

Stop before:

- Phase 6-E real owner VPS deployment/cadence/restart acceptance;
- real owner webhook endpoint/token acceptance;
- new scheduler or scheduled GitHub Actions monitoring;
- notification acknowledgement/read-state workflow;
- retry/resend/repair controls;
- Slack/Telegram/email-specific delivery adapters;
- remote monitoring-state persistence invented for Dashboard use;
- Bridge/FQGate event/source expansion;
- CNINFO taxonomy expansion;
- M4-D/M4-E/M2-D;
- brokerage/trading/order/funds behavior;
- investment-rule or valuation changes.

D3 is complete when the owner can **observe** the proven monitoring runtime
truthfully through the existing read-only web stack, with no new authority to
change it.
