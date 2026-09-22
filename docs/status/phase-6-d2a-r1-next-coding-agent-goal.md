# Phase 6-D2A-R1 coding-agent handoff — Lease hardening

Status: **ACTIVE / NOT IMPLEMENTED**

Canonical goal:
`docs/goals/phase-6-d2a-r1-lease-hardening.md`

Selection audit:
`docs/status/phase-6-d2a-r1-review-2026-09-22.md`

## Goal

Implement only Phase 6-D2A-R1.

Start by reading `AGENTS.md`, the canonical R1 goal, the D2A goal/closure, and
the current `monitoring_runner/lease.py`, `service.py` and tests. Sync main
fast-forward-only, prove a clean tree, record the exact baseline SHA and verify
its CI is green before changing code.

Required corrections:

- make the non-blocking OS `flock` the first authoritative liveness check;
- map only real contention errno to `RunnerLeaseBusyError` / `LEASE_BUSY`;
- map unrelated open/flock failures to precise fail-closed
  `RunnerLeaseError`;
- after lock acquisition, reject a canonical prior lease whose `runner_id`
  does not match the slot;
- make lease-record writes robust to short writes;
- keep all D2A activation/PIT/D1/receipt semantics unchanged.

Automatically add deterministic tests for live-lock-vs-corrupt-metadata
precedence, abandoned corruption, non-contention flock OS failure, lease-slot
identity mismatch and short-write handling. Prove every failing path performs
zero provider/model/D1 work.

Run all focused tests plus the **entire repository gate** from the goal. Do not
delegate automatable validation to the owner. There is no planned manual
acceptance for R1.

After push, inspect GitHub Actions for the **exact closing implementation SHA**.
Do not call R1 closed from local tests alone. Record the exact SHA, run id, URL
and result in a dated closure document and update the active-goal pointers only
after that exact run succeeds.

Stop before D2B: do not implement any notification transport/receipt ledger,
Dashboard monitoring view, owner VPS deployment, CNINFO expansion, Bridge
adapter, Cloudflare mutation, trading/brokerage behavior or investment-rule
change.
