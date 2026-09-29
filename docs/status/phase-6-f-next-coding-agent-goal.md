# Phase 6-F coding-agent handoff — Persistent Owner Operations Hardening

Status: **CLOSED / OWNER_ACCEPTED — no active implementation package**

Canonical goal: `docs/goals/phase-6-f-persistent-owner-operations.md`

Closure record: `docs/status/phase-6-f-2026-09-29.md`

## Phase 6-F outcome (2026-09-29)

Final implementation `065b53a17bcb4f009a57ef918ffa3d59de135107`; exact-head
Actions run `36515225218` `success`; the owner-authorized real WSL2
production deployment passed automated preflight, plan, render,
apply/converge (idempotent, never starting recurring work), explicit
activation, bounded firing, replay/no-duplicate, D3 read-only observation,
restart/recovery and verification, with the production timer
`tve-production-monitor.timer` intentionally left enabled and active and
the persistence claim narrowed to the running WSL distro/user manager
(`WINDOWS_HOST_BOOTSTRAP_UNPROVEN` is the single, non-blocking recorded
marker). Delivery is disabled (monitoring-only closure); the typed
`EnvironmentFile` credential path is implemented and deterministically
tested for a future owner opt-in.

Superseded pushes `bb074de3`, `4e68090e` and `0ee74e21` (each with its own
green exact-head CI run) closed defects the live deployment itself
exposed; see the closure record for the exact sequence.

Live production facts a future agent must respect:

- the production timer is enabled/active under the owner user manager with
  `Linger=yes`; never disable it casually — `deactivate` exists for real
  rollback and `activate` re-converges enable+start;
- the Phase 6-E acceptance tree and its units stay untouched and disabled;
- the production root is `.tve-private/monitoring/production/` with its
  own runner `production-owner`, watchlist and delivery ledger;
- the repo gate artifact used by production preflight binds to the current
  clean HEAD (rerun the harness `gate` after any new commit before
  rerunning `preflight`).

## Next package

No next package is selected yet. The Phase 6-F goal's stop boundary
explicitly excludes Phase 7 controlled evolution, provider expansion,
Bridge/FQGate integration, M4-D/M4-E/M2-D, additional notification vendors,
brokerage/trading behavior and investment-rule/profile mutation. A
post-closure review (like `docs/status/phase-6-f-selection-2026-09-28.md`)
should select the next package and write a fresh handoff document before
any implementation begins.
