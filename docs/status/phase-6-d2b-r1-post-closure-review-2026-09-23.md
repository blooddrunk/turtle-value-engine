# Phase 6-D2B-R1 post-closure review / R2 selection — 2026-09-23

Status: **REVIEWED / R2 SELECTED**

Audited main head:
`081f4bd84d59c163492c753a1726e3e5fce6d7cc`

R1 implementation SHA:
`6c039266083de015535f3f05dce0cf9aba2f0042`

Exact R1 implementation Actions run:
`35805665083` — **success**, exact head-SHA match

Canonical R1 goal:
`docs/goals/phase-6-d2b-r1-dispatch-hardening.md`

Selected corrective goal:
`docs/goals/phase-6-d2b-r2-orphan-retry-budget-hardening.md`

Coding-agent handoff:
`docs/status/phase-6-d2b-r2-next-coding-agent-goal.md`

## 1. What remains accepted

The R1 implementation is real and its recorded CI closure is valid for the
implementation that ran:

- the durable `MonitoringDispatchClaimV1` is persisted before transport entry;
- default non-idempotent orphan recovery is conservative `AMBIGUOUS` with zero
  automatic resend;
- per-`delivery_id` non-blocking `flock` single-flight prevents concurrent
  local transport entry and distinguishes contention from unrelated OS errors;
- the webhook transport uses one injectable monotonic overall deadline across
  connect/TLS, request/header and repeated bounded body reads;
- `delivery-status` validates the latest-state pointer read-only and
  distinguishes missing/current/stale-repairable while failing closed on
  corrupt, non-canonical, foreign or contradictory state;
- Actions run 35805665083 is a completed successful push run whose `head_sha`
  is exactly `6c039266083de015535f3f05dce0cf9aba2f0042`; the job passed Ruff,
  project-config validation, the complete Python suite (6655 passed / 2
  skipped), systemd verification, generated API checks, Dashboard
  lint/typecheck/tests/build, client-bundle secret scan, Wrangler validation
  and cross-stack smoke.

Those R1 boundaries are not being reopened.

## 2. Residual correctness finding

### F5 — an idempotent orphan can bypass the configured retry budget

R1 correctly makes a dispatch claim durable before transport entry, but the
idempotent-orphan recovery branch currently decides whether another send is
allowed from the number of **persisted terminal attempt outcomes**:

`derive_delivery_state(...)` permits retry while
`len(attempts) < intent.max_attempts`.

The mutating path then invokes:

`_perform_attempt(intent, attempt_number=len(attempts) + 1)`.

If a process has already persisted claim N, may have written request bytes, and
then dies before saving attempt N, the next invocation still sees only N-1
persisted attempts. With `receiver_idempotency_declared=true`, it re-enters
the same numbered attempt and byte-identically re-saves the existing claim
before sending again.

This creates two concrete violations of the R1 goal's “existing retry budget”
requirement:

1. with `max_attempts=1`, claim 1 can be durable and request bytes may have
   been sent, yet a crash before attempt 1 persistence allows a second
   transport entry on restart;
2. if each restarted process dies after possible dispatch but before saving the
   attempt outcome, `len(attempts)` never advances, so scheduler wakes can
   repeatedly send while never consuming `max_attempts`.

Receiver-side idempotency may suppress duplicate **effects** when the receiver
honors the key, but it does not make an unbounded local retry loop truthful or
bounded. `max_attempts` must remain a hard upper bound on outbound transport
entries for one delivery identity across crash recovery.

## 3. Why the existing R1 tests do not prove this boundary

`test_orphaned_claim_retries_only_under_declared_receiver_idempotency` first
persists attempt 1, then crashes after claim 2. Its restart reuses claim 2 and
successfully saves attempt 2, so it never exercises repeated crash-before-
attempt-save on the same orphaned slot.

`test_orphaned_claim_with_exhausted_budget_stays_terminal_ambiguous` constructs
an already-persisted attempt plus a later orphaned claim and calls state
derivation directly. It does not exercise the real `max_attempts=1`, claim-1,
zero-persisted-attempt restart case.

The 6655-test green CI result therefore does not cover F5.

## 4. Decision

Do **not** start Phase 6-D3 yet.

Select one narrow corrective package:

**Phase 6-D2B-R2 — Orphaned Dispatch Retry-Budget Accounting Hardening**

R2 changes only the retry-budget accounting / crash-recovery state machine
needed to make durable dispatch evidence consume a truthful bounded outbound
budget. It must preserve R1's default zero-resend behavior, local single-flight,
overall deadline, status-pointer truthfulness, secret boundary, deterministic
payload/idempotency key and all D1/D2A/6-A/6-B/6-C semantics.

After R2 passes focused deterministic tests, the complete repository gate and
an exact-closing-SHA successful GitHub Actions run, Phase 6-D3 becomes the next
candidate package again.

## 5. Automatic verification requirement

R2 has **no planned manual verification**. The coding agent must automatically
prove at least:

- `max_attempts=1` + declared receiver idempotency + orphaned claim 1:
  restart performs zero new transport calls;
- repeated crash-after-possible-dispatch / before-attempt-save cannot produce
  more than `max_attempts` total transport entries;
- any permitted retry uses the same deterministic receiver idempotency key but
  consumes a new monotonic durable dispatch-budget slot before transport entry;
- completed attempts plus orphaned dispatch slots are accounted together
  without double-spending or skipping budget;
- default non-idempotent orphan handling remains terminal `AMBIGUOUS` with
  zero resend;
- contradictory/corrupt recovery evidence fails closed;
- all existing R1/D2B delivery tests and the full repository CI matrix stay
  green;
- the exact pushed R2 closing SHA has a successful Actions run whose id,
  conclusion and head-SHA match are recorded.

No owner webhook, VPS, credentials, browser screenshot, public Internet request,
or other manual acceptance is required for R2.
