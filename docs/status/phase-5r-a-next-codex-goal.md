# Next coding-agent goal

The active package is now **Phase 6-D2A-R1 — Lease Classification and
Slot-Integrity Hardening**.

Canonical handoff:
`docs/status/phase-6-d2a-r1-next-coding-agent-goal.md`

Canonical implementation goal:
`docs/goals/phase-6-d2a-r1-lease-hardening.md`

Post-closure review / selection audit:
`docs/status/phase-6-d2a-r1-review-2026-09-22.md`

Phase 6-D2A's main implementation remains accepted at
`2fb682f991b70f3f6bb4e3cce8cd2fe3b69a50ac`, with successful exact-SHA
Actions run `35677839752`. A subsequent code-level audit at main
`81b2ac2bb07711eab03fc594aabeab4293c99ec2` found a narrow lease correctness
gap that is fully automatable and must be closed before notification delivery.

R1 is deliberately small:

- truthful `flock` contention vs non-contention OS-error classification;
- kernel lock before mutable lease metadata validation;
- lease-record runner-slot identity binding;
- complete/checked lease-record writes;
- deterministic regression tests plus the complete existing CI gate;
- exact closing-SHA Actions verification.

No manual owner acceptance is planned.

**Phase 6-D2B remains queued, not active**, until R1 closes. D2B will own
external notification delivery and its delivery/receipt ledger; D3 remains the
read-only monitoring Dashboard projection and 6-E remains owner live unattended
acceptance.
