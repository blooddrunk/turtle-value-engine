# Next coding-agent goal

The active package is now **Phase 6-D2B — External Notification Delivery and
Delivery/Receipt Ledger**.

Canonical implementation goal:
`docs/goals/phase-6-d2b-notification-delivery-ledger.md`

Selection audit:
`docs/status/phase-6-d2b-selection-2026-09-22.md`

Canonical coding-agent handoff:
`docs/status/phase-6-d2b-next-coding-agent-goal.md`

Phase 6-D2A-R1 is closed at
`2f9aae27afb8cb95c6fed7ee20cdf47d7ad09d1e`, with exact-SHA GitHub Actions run
`35679461520` successful (6593 Python tests passed, 2 skipped; full repository
CI gate successful). Closure evidence remains
`docs/status/phase-6-d2a-r1-2026-09-22.md`.

D2B owns one bounded next step: generic HTTP webhook notification delivery plus
a durable delivery/receipt ledger over the already-immutable D1 alert outbox.
It must be fully automatically testable using loopback HTTP/failure injection,
remain network-deny-by-default, preserve secret hygiene, avoid duplicate resend
after a terminal delivery receipt, and record ambiguous post-dispatch failures
truthfully instead of claiming exactly-once semantics.

No manual owner endpoint acceptance is required. Real owner deployment,
credentials/cadence and live end-to-end acceptance stay in Phase 6-E. Phase
6-D3 Dashboard monitoring projection remains unopened until D2B closes.
