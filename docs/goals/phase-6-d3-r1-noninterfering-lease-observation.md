# Phase 6-D3-R1 — Non-interfering Lease Observation Hardening

Status: **CLOSED**
Date: 2026-09-24
Selected after: Phase 6-D3 post-closure review
Closed by: `40a75d89c2863b74a3e44ecfbad4fe432959fc5b` (Actions run 35948785496, success)

Selection audit:
`docs/status/phase-6-d3-post-closure-review-2026-09-24.md`

Closure record:
`docs/status/phase-6-d3-r1-2026-09-24.md`

Predecessor:
`docs/goals/phase-6-d3-read-only-monitoring-dashboard.md`

## 1. Objective

Remove the post-closure D3 observer/runner lock race without weakening the
authoritative D2A-R1 single-host lease.

A monitoring read must be observational not only at the file-byte level but
also at the concurrency-authority level: it must not take a lock that can make
an otherwise uncontended `MonitoringRunnerService.run()` return
`RunnerLeaseBusyError`.

## 2. Frozen boundaries

Preserve all of these:

- D2A-R1 `RunnerLease.held()` remains the authoritative single-flight
  boundary for work;
- a genuine live holder must still make a competing runner fail fast as
  `LEASE_BUSY` with zero provider/model/D1 work;
- D1, D2B/R1/R2, Phase 6-A/6-B/6-C, `strict-v1`, valuation, monitoring
  cursor, delivery and secret/network semantics do not change;
- D3 remains read-only and must not repair, rewrite, acknowledge, retry,
  resend, publish, schedule or invoke provider/model/research/delivery paths;
- no remote state service is introduced;
- no probabilistic sleep/backoff workaround is accepted as the fix.

## 3. Required lease-observation semantics

Introduce or refactor to a **non-interfering observation path** for D3/status.

Hard requirement:

> Calling the observation path must never acquire any OS lock whose presence
> can cause `RunnerLease.held()` to classify an otherwise free slot as busy.

The implementation may use a passive platform capability or a conservative
typed state. If exact liveness cannot be established without competing for the
authoritative lock, return an explicit conservative state such as `UNKNOWN`
(or an equivalent well-defined typed status) rather than fabricating
`LIVE`/`FREE`/`ABANDONED`.

Do not silently weaken the meaning of existing states.

If the public D3 projection contract changes, regenerate and drift-check the
monitoring projection JSON Schema, Surface OpenAPI, Dashboard generated API
types and Chinese/English presentation copy/tests.

## 4. Deterministic automatic proof

Add focused tests that fail on the current implementation and pass only after
the protocol is fixed.

### 4.1 Observer vs runner — no real holder

Use deterministic barriers/processes, not timing luck:

1. create a valid runner slot/config with no live holder;
2. hold the D3 observation in its critical read section;
3. start the real `MonitoringRunnerService.run()` concurrently;
4. assert the observer does not own/conflict with the authoritative lease;
5. assert the runner does **not** raise `RunnerLeaseBusyError`;
6. assert D1 is entered exactly once and the invocation reaches its expected
   deterministic terminal result.

### 4.2 Real holder remains authoritative

1. process A owns `RunnerLease.held()`;
2. D3 observes concurrently without acquiring a conflicting lock;
3. process B attempts the real runner path;
4. process B must still receive `RunnerLeaseBusyError` and perform zero D1
   work;
5. D3 must report only the liveness classification it can actually prove.

### 4.3 Repeated concurrency regression

Run a bounded deterministic stress/regression loop or equivalent coordinated
multi-process matrix over observer + runner starts. With no real holder there
must be zero observer-induced `LEASE_BUSY` results.

### 4.4 Existing invariants

Retain/prove:

- projection reads write/repair nothing;
- corrupt/foreign lease evidence fails closed or becomes an explicitly
  conservative typed status according to the new contract;
- holder token/local roots/secrets never reach API/browser output;
- existing runner contention/error classification remains unchanged;
- D3 fixed-route GET/HEAD API/Worker boundary and zero mutation controls remain
  unchanged;
- D2B-R2 attempt/dispatch-claim semantics remain unchanged.

## 5. Full automatic gate

Run every machine-verifiable check in the environment. At minimum:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest tests/test_monitoring_runner.py tests/test_monitoring_dashboard.py
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

Use `python3` only when the environment requires it and record the
substitution.

## 6. CI closure rule

After pushing the implementation, query Actions for the exact implementation
SHA. R1 is CLOSED only when the required CI run has `head_sha` equal to that
SHA and conclusion `success`.

Record exact implementation SHA, Actions run id/conclusion, focused concurrency
results, monitoring/full-suite counts, Dashboard count if applicable,
cross-stack smoke result and confirmation that no manual intervention was used.

## 7. Manual boundary

**No planned manual verification.** Do not ask the owner to reproduce the race,
inspect a lock, deploy a VPS, refresh a browser, configure Cloudflare or send a
real webhook.

If the agent claims automation is impossible, it must first document the exact
missing local capability and why deterministic process/barrier testing cannot
replace it. R1 must not be closed with vague "evidence incomplete" wording.

## 8. Stop boundary

Stop before Phase 6-E live owner deployment/cadence/notification acceptance,
vendor-specific notification adapters, scheduled GitHub Actions monitoring,
Bridge/FQGate source expansion, M4-D/M4-E/M2-D, brokerage/trading behavior or
investment-rule changes.
