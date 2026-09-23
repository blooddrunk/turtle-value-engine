# Phase 6-D2B-R2 — Orphaned Dispatch Retry-Budget Accounting Hardening

Status: **IMPLEMENTED / CI_PENDING**
Date: 2026-09-23
Selected after: Phase 6-D2B-R1 post-closure review

Post-closure audit:
`docs/status/phase-6-d2b-r1-post-closure-review-2026-09-23.md`

Coding-agent handoff:
`docs/status/phase-6-d2b-r2-next-coding-agent-goal.md`

Implementation record:
`docs/status/phase-6-d2b-r2-2026-09-23.md`

## 1. Objective

Close one residual crash-recovery correctness defect in the R1 delivery
boundary before Phase 6-D3 starts.

For one `delivery_id`, `max_attempts` must be a hard upper bound on
**outbound transport entries over the lifetime of the durable delivery ledger**,
including entries whose request may have been dispatched but whose
`MonitoringDeliveryAttemptV1` outcome never became durable because the
process died.

The invariant is:

> One possible outbound dispatch consumes exactly one durable retry-budget slot
> before another outbound dispatch may be entered.

Receiver-declared idempotency permits a later bounded resend with the same
deterministic `Idempotency-Key`; it must not permit reuse of one orphaned
dispatch slot as an unlimited source of new sends.

## 2. Required behavior

### 2.1 Account dispatch evidence, not only completed attempts

Do not decide remaining retry budget only from `len(attempts)`.

A durable dispatch-start claim is evidence that one transport entry was
authorized and may already have produced an external side effect. Its budget
slot is therefore consumed even if the process dies before the corresponding
attempt outcome is saved.

The recovery model must make it impossible for repeated process death after
dispatch-start persistence to keep the effective retry counter unchanged.

### 2.2 Idempotent orphan recovery remains bounded and monotonic

For `receiver_idempotency_declared=false`, preserve R1 exactly: an orphaned
dispatch is terminal/fail-closed `AMBIGUOUS` with zero automatic resend.

For `receiver_idempotency_declared=true`:

- an orphan may be retried only if a retry-budget slot remains after accounting
  for already-authorized dispatches;
- before every new transport entry, persist durable evidence for a **new
  monotonic dispatch-budget slot**;
- keep the receiver-facing `Idempotency-Key` equal to the deterministic
  `delivery_id` across retries;
- never reuse the same orphan claim as the budget token for another outbound
  request;
- never exceed `max_attempts` transport entries, even if every invocation
  crashes after possible dispatch and before attempt-outcome persistence.

The exact additive artifact/state representation is implementation-defined.
Prefer extending the existing claim/ledger model rather than inventing mutable
counters. Preserve immutable/canonical/hash-validated recovery evidence.

Do not fabricate an HTTP outcome, response status, completion timestamp or
proof of delivery merely to consume the budget. An orphan remains
post-dispatch uncertain.

### 2.3 Fail closed on impossible evidence

Validate the relationship among intent, dispatch slots/claims and terminal
attempt outcomes. At minimum reject contradictory states such as:

- more authorized dispatch slots than the configured maximum;
- non-monotonic or duplicate semantic budget slots;
- an attempt outcome bound to the wrong slot/intent/payload;
- evidence that would require silently renumbering or deleting an already
  durable immutable record.

Crash recovery must be deterministic from immutable artifacts.

## 3. Scope

Expected implementation scope is intentionally narrow:

- `src/turtle_value_engine/monitoring_delivery/contracts.py` only if an
  additive recovery field/contract is necessary;
- `src/turtle_value_engine/monitoring_delivery/store.py`;
- `src/turtle_value_engine/monitoring_delivery/service.py`;
- additive checked-in schema(s) only if a persisted contract changes;
- `tests/test_monitoring_delivery.py`;
- closure/status documentation.

Do **not** change:

- D1 or D2A/R1 identities/source binding;
- Phase 6-A / 6-B / 6-C semantics;
- webhook payload meaning or deterministic `delivery_id` /
  `Idempotency-Key`;
- R1 single-flight lock semantics;
- R1 overall monotonic HTTP deadline;
- R1 read-only delivery-status pointer truthfulness;
- secret handling / network deny-by-default;
- `strict-v1`, valuation, hard gates, monitoring cursors or re-analysis;
- Dashboard/API/Cloudflare projection (Phase 6-D3);
- owner live deployment/acceptance (Phase 6-E);
- Bridge/source expansion or brokerage/trading behavior.

## 4. Mandatory deterministic tests

Add focused regression coverage that automatically proves all of the following:

1. **max_attempts=1 / orphan claim 1** — with
   `receiver_idempotency_declared=true`, crash after durable claim / possible
   transport dispatch but before attempt save; restart performs zero new
   transport calls and exposes a truthful terminal exhausted/ambiguous state;
2. **repeated crash loop is bounded** — with e.g. `max_attempts=3`, force every
   allowed transport entry to die after durable dispatch evidence and before
   attempt-outcome persistence; across repeated service restarts, total
   transport entries never exceed 3, and the next wake performs zero;
3. **successful bounded recovery** — before budget exhaustion, an orphaned
   dispatch may cause one new transport entry only after a new monotonic durable
   dispatch slot exists; receiver idempotency key remains byte-identical;
4. **mixed completed + orphan accounting** — completed retryable outcomes and
   orphaned dispatch slots consume the same finite `max_attempts` budget
   exactly once each;
5. **non-idempotent policy unchanged** — orphaned dispatch remains terminal
   `AMBIGUOUS` and zero-resend;
6. **contradictory recovery evidence** — over-budget, non-monotonic, foreign or
   otherwise impossible slot/attempt relationships fail closed before
   transport;
7. all existing D2B/R1 crash, lock, deadline, pointer, secret, NOOP, retry and
   replay tests remain green;
8. D2A runner/cycle/CLI regressions and the full repository gate remain green.

Use deterministic failure injection, subprocess barriers and fake/local
transports. No public Internet, real-time sleeps for race acceptance, owner
credentials or manual observation.

## 5. Full automatic gate

Before editing:

- fast-forward-only sync with `main`;
- prove a clean tree and record the exact baseline SHA;
- verify baseline CI state.

After focused tests, automatically run:

```text
python3 -m ruff check .
python3 -m turtle_value_engine config validate --input config/project.example.toml
python3 -m pytest tests/test_monitoring_delivery.py
python3 -m pytest tests/test_monitoring_runner.py tests/test_monitoring_cycle.py tests/test_monitoring_cli.py
python3 -m pytest
python3 scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python3 scripts/dashboard_cross_stack_smoke.py
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
```

Equivalent executable names are acceptable only when the environment genuinely
lacks the documented one; record the substitution.

Do not delegate any automatable criterion to the owner.

## 6. Closure rule and manual boundary

Manual intervention boundary for R2: **NONE planned**.

After pushing the implementation, query GitHub Actions for the exact closing
implementation SHA. R2 may be marked CLOSED only when a completed successful
CI run has `head_sha` exactly equal to that implementation SHA.

The closure record must contain the exact implementation SHA, Actions run id
and conclusion, focused-test counts, full-suite pass/skip counts and any
environmental substitution.

If an unexpected condition genuinely cannot be automated, do not write
“evidence not fully recorded.” State all of the following explicitly:

1. why automation is impossible in the current environment;
2. the exact owner action/command/UI sequence required;
3. the exact pass/fail observation to capture;
4. what remains unproven until that observation exists;
5. whether the missing evidence blocks closure.

Stop before Phase 6-D3 and Phase 6-E.
