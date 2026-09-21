# Phase 6-A next Codex goal — watchlist/event foundation

Status: **PHASE 6-A IMPLEMENTED / CLOSED at the offline integration boundary (2026-09-21)**

M6-C3 is verified complete on main. The Phase 6-A selection audit is recorded
in docs/status/phase-6-a-2026-09-21.md, and the same file now carries the
implementation closure record.

## Completed package

**Phase 6-A — Watchlist State and Deterministic Event Planning Foundation**

Source of truth:

docs/goals/phase-6-a-watchlist-event-foundation.md

Delivered: deterministic typed watchlist/event/state/cursor/re-analysis-plan
contracts, `event-impact-v1`, point-in-time filtering on the canonical event
availability boundary, canonical event ordering, idempotent duplicate and
hard-conflict event handling, source/listing cursors that advance only through
committed state, an atomic/idempotent hash-verified local MonitoringWorkspace,
offline `tve watch validate|replay|status`, an additive non-secret
`[monitoring]` ProjectConfig section, checked-in schemas with drift tests and
85 focused deterministic tests alongside the unchanged full regression suite.

## Next selection

The next package is **not** selected yet. Per the Phase 6 roadmap the natural
follow-ons are Phase 6-B (opt-in live event acquisition feeding
MonitoringEventV1) or another audited priority; a separate selection audit on
main must choose it. Do not start Phase 6-B, 6-C, 6-D or 6-E without that
audit.

## Verification discipline (applies to every future package)

Before edits:

1. synchronize main with fast-forward only;
2. record git status, HEAD and remotes;
3. discover the owner test checkout under D:\code\research (or
   /mnt/d/code/research under WSL) when available;
4. prove GitHub Actions is green for the exact baseline commit;
5. run the existing baseline tests.

Automate every machine-verifiable acceptance case; never close a goal with
vague "manual verification recommended" or "evidence incomplete" language.
After push, require green GitHub Actions for the exact closing commit before
marking any goal complete.
