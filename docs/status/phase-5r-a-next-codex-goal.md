# Next coding-agent goal

The active package is now **Phase 6-D2A — Persistent Unattended Runner Foundation**.

Canonical handoff:
`docs/status/phase-6-d2a-next-coding-agent-goal.md`

Canonical implementation goal:
`docs/goals/phase-6-d2a-persistent-runner-foundation.md`

Selection / D1 audit:
`docs/status/phase-6-d2a-selection-2026-09-22.md`

Phase 6-D1 is CLOSED at implementation commit
`e452eadc866035a7a784d7862956a3f24e3985b8`, with successful Actions run
`35602785093`. Do not reopen or rewrite D1 unless D2A proves a concrete defect.

D2 is deliberately split again:

- **D2A (active):** persistent single-host unattended runner, durable activation
  intent/receipt/lease semantics, reference systemd service/timer, no external
  notification transport;
- **D2B (future):** external notification delivery + delivery/receipt ledger;
- **D3 (future):** read-only monitoring views in the existing API/Cloudflare/
  Dashboard stack;
- **6-E (future):** owner live unattended deployment/acceptance.

The selected monitoring runtime model is a persistent Linux host. GitHub Actions
remains CI and exact-SHA verification, not the D2A monitoring scheduler, because
the current Phase 6 stores are intentionally local and durable.
