# Phase 6-D2B-R1 coding-agent handoff — dispatch hardening

Status: **READY / ACTIVE**

Canonical goal:
`docs/goals/phase-6-d2b-r1-dispatch-hardening.md`

Selection audit:
`docs/status/phase-6-d2b-r1-review-2026-09-22.md`

## Goal

Implement only Phase 6-D2B-R1.

Before changing code, read `AGENTS.md`, the R1 goal, the original D2B goal and
closure record, then inspect the current `monitoring_delivery/contracts.py`,
`store.py`, `service.py`, `transport.py` and
`tests/test_monitoring_delivery.py`. Sync `main` fast-forward-only, prove a
clean tree, record the exact baseline SHA and verify baseline CI.

Required corrections:

- persist additive immutable dispatch-start evidence **before** request bytes can
  be written so an orphaned in-flight attempt becomes `AMBIGUOUS`, not
  "proven unsent";
- default non-idempotent policy must perform zero automatic resend of an
  orphaned dispatch; existing explicit receiver-idempotency policy may permit a
  bounded retry;
- add a per-`delivery_id` OS single-flight lock held across state
  inspect/repair, dispatch claim, transport, outcome persistence and latest
  state publication;
- classify only real lock contention as busy; unrelated OS errors fail closed;
- enforce one injectable monotonic **overall** HTTP deadline across connect,
  request/header and bounded response reads;
- make `delivery-status` validate the published latest pointer and report
  current/missing/stale-repairable truthfully while failing closed on
  corrupt/foreign/contradictory state; status remains read-only.

Automatically add deterministic tests for both crash windows, receiver
idempotency opt-in, real two-process single-flight exclusion, non-contention
lock failure, end-to-end deadline enforcement and pointer-status truthfulness.
Use barriers/fake clocks/fake or loopback transports; do not use public network
calls or sleep-based flaky acceptance.

Run the focused tests and **the entire repository gate from the canonical R1
goal**. Do not delegate any automatable verification to the owner. There is no
planned manual acceptance for R1.

After push, query GitHub Actions for the **exact closing implementation SHA**.
Do not mark R1 CLOSED from local tests alone. Record exact SHA, Actions run id,
URL/conclusion, targeted test counts and full-suite pass/skip counts in a dated
closure document, then update active-goal pointers.

Stop before Phase 6-D3 / 6-E and do not mix in Dashboard monitoring views,
owner live webhook/VPS acceptance, vendor-specific notification adapters,
source expansion, Bridge/Cloudflare work, trading behavior or investment-rule
changes.
