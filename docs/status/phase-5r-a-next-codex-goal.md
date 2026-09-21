# Phase 5R-A next Codex goal — post-M6-C3 audit

Status: **M6-C3 COMPLETE; next package selection pending a separate audit**

M6-C3 (`docs/goals/phase-5r-a-m6-c3-dashboard-ux-localization.md`) is
complete at its presentation-only integration boundary. The implementation,
local regression, browser layout verification, unchanged-boundary redeploy
and live-smoke evidence are recorded in
`docs/status/phase-5r-a-2026-09-20.md` section 14 and in the goal file's
implementation record.

## What closed with M6-C3

- Chinese-first owner-facing UI through the centralized typed presentation
  layer (`apps/dashboard/src/presentation.ts`) with an optional client-only
  English switch;
- plain-language labels/explanations for `SPECIAL_REVIEW`, `NOT_EVALUATED`,
  `PARTIAL`, `BLOCKED`, `NOT_AVAILABLE` and every other known state, with raw
  codes retained and unknown enums failing safe;
- distinct no-snapshot / no-match / not-evaluated / partial / blocked /
  API-unavailable / surface-not-found states;
- hashes, contract names, rule IDs and artifact identities moved behind
  clearly labeled technical/audit details affordances without deleting or
  rewriting any payload value;
- the exact M6-C3 build redeployed through the unchanged M6-C2 Cloudflare
  path with the machine-verifiable live smoke passing.

## Next package

Phase 6 watchlist/event monitoring is the expected next major functional
phase, but it must be selected through a separate audit/planning step against
the then-current `main`, not started implicitly. Still explicitly deferred:
M4-D/M4-E, M2-D, M5-C/R2 absent a separately demonstrated artifact need, and
any `strict-v1`, A6/PIT/source-selection or investment-semantic change. A6
remains the separate strict production-claim audit.

Before any next implementation: synchronize `main`, require the latest
GitHub Actions run for that exact baseline to be green, re-read
`AGENTS.md`, the roadmap and the then-active goal, and keep using the
permanent owner test environment when available.
