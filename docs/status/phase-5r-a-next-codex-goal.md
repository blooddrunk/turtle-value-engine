# Phase 6-A next Codex goal — watchlist/event foundation

Status: **SELECTED / IMPLEMENTATION NOT STARTED**

M6-C3 is verified complete on main. The current baseline audit and next-package decision are recorded in docs/status/phase-6-a-2026-09-21.md.

## Current next package

Implement:

**Phase 6-A — Watchlist State and Deterministic Event Planning Foundation**

Source of truth:

docs/goals/phase-6-a-watchlist-event-foundation.md

The package is deliberately offline-first. It must implement deterministic typed watchlist/event/state/cursor/re-analysis-plan contracts, event-impact-v1, an atomic/idempotent local MonitoringWorkspace, ProjectConfig monitoring fields and offline CLI validate/replay/status.

Do **not** start live provider polling, scheduler deployment, notifications, Dashboard mutation/run controls, model calls, automatic adjustment approval, trading, M4-D/M4-E, M2-D or M5-C/R2.

## Verification discipline

Before edits:

1. synchronize main with fast-forward only;
2. record git status, HEAD and remotes;
3. discover the owner test checkout under D:\code\research (or /mnt/d/code/research under WSL) when available;
4. prove GitHub Actions is green for the exact baseline commit;
5. run the existing baseline tests.

During and after implementation, automate every machine-verifiable case in the goal, especially PIT filtering, duplicate/conflict handling, cursor advancement, atomic workspace rollback, corruption failure, byte-stable replay and proof that no network/model/analysis call occurs.

There is **no planned owner manual acceptance** for Phase 6-A. If a supposedly required manual step appears, record the exact failed automated command and bounded reason instead of closing with vague "evidence incomplete" language.

After push, require green GitHub Actions for the exact implementation/closure commit before marking the goal complete.
