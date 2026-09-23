# Phase 6-D2B-R2 coding-agent handoff — orphan retry-budget hardening

Status: **IMPLEMENTED / CLOSED**

Canonical goal:
`docs/goals/phase-6-d2b-r2-orphan-retry-budget-hardening.md`

Selection audit:
`docs/status/phase-6-d2b-r1-post-closure-review-2026-09-23.md`

## Goal

Implement only **Phase 6-D2B-R2 — Orphaned Dispatch Retry-Budget Accounting
Hardening**.

Start by reading `AGENTS.md`, the R2 canonical goal, the R1 canonical goal,
the R1 implementation closure and the R1 post-closure audit. Sync `main`
fast-forward-only, prove the working tree is clean, record the exact baseline
SHA and verify the baseline's CI state before editing.

Critical invariant:

> For one `delivery_id`, `max_attempts` is a hard upper bound on outbound
> transport entries across the complete durable ledger lifetime, including
> dispatches whose claim is durable but whose terminal attempt outcome is
> missing because the process died.

Do not use only `len(attempts)` to decide remaining budget. A durable
dispatch-start slot represents one authorized possible outbound side effect and
must consume one retry-budget position even if no attempt outcome became
durable.

Preserve the default non-idempotent behavior exactly: orphan -> terminal
`AMBIGUOUS`, zero resend.

When `receiver_idempotency_declared=true`, a retry is allowed only if a real
budget slot remains. Before every new transport entry, persist a **new
monotonic durable dispatch-budget slot**; keep the receiver-facing
`Idempotency-Key` equal to the same deterministic `delivery_id`. Never
re-use the same orphan claim as a fresh retry-budget token. Never fabricate a
successful/failed HTTP outcome merely to advance accounting.

Add deterministic tests that prove at minimum:

- `max_attempts=1` + orphan claim 1 -> restart sends zero requests;
- repeated crash-after-dispatch-before-attempt-save with `max_attempts=3`
  yields at most three total transport entries across repeated restarts, then
  zero;
- one permitted recovery retry creates/uses a new monotonic durable dispatch
  slot while the receiver idempotency key remains unchanged;
- completed attempts plus orphaned dispatch slots consume one shared finite
  budget without double spending;
- non-idempotent zero-resend remains unchanged;
- over-budget, non-monotonic, foreign or contradictory evidence fails closed
  before transport;
- all prior D2B/R1 tests remain green.

Run every focused and full automatic gate listed in
`docs/goals/phase-6-d2b-r2-orphan-retry-budget-hardening.md`. Do not hand any automatable validation to the owner.

There is **no planned manual verification** for R2. If an unexpected manual
boundary truly appears, document the exact reason automation is impossible,
the exact owner command/UI steps, the exact expected pass/fail evidence, what
remains unproven and whether it blocks closure. Never substitute a vague
“evidence not fully recorded” note.

After pushing, query GitHub Actions for the **exact implementation SHA**.
Do not mark R2 CLOSED from local tests alone. Record the exact SHA, Actions run
id/conclusion, focused-test counts and full-suite pass/skip counts only after an
Actions run with matching `head_sha` succeeds.

Stop before Phase 6-D3, Phase 6-E, Dashboard/API/Cloudflare work, owner live
webhook/VPS acceptance, source/Bridge expansion, brokerage/trading behavior or
investment-rule changes.
