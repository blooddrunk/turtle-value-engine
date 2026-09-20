# Phase 5R-A next Codex goal — M6-C3

Status: **M6-C3 SELECTED / NOT_STARTED**

Baseline before planning: `8be5d511d432c08424077dbc142a4e86468b215f`.
GitHub Actions run `35503386115` completed successfully for that baseline.

M6-C2 is closed as `CLOSED / OWNER_ACCEPTED`. Its private Cloudflare
Access/Worker/Tunnel deployment and automated live smoke are not blockers and
must not be redesigned by the next package.

The selected next package is:

`docs/goals/phase-5r-a-m6-c3-dashboard-ux-localization.md`

## Goal

Turn the technically correct but developer-oriented private Dashboard into a
Chinese-first owner-facing research UI while preserving the exact
`ResearchSurfaceSnapshotV1`, M6-B read-only API, M6-C2 security boundary and
all deterministic investment semantics.

The package should centralize user-facing state/copy presentation, explain
`SPECIAL_REVIEW`, `NOT_EVALUATED`, `PARTIAL`, `BLOCKED` and unavailable
values in plain language, distinguish empty/partial/error states, and move
hashes/API/rule/artifact diagnostics behind progressive disclosure.

Do not change the API merely to make the UI easier to implement. Do not infer
missing units, values or positive states.

## Automation requirement

Use the permanent owner test environment rooted at `D:\code\research` when
it is available. Discover the real repository checkout beneath that root
(`/mnt/d/code/research` under WSL where applicable) and run routine validation
there rather than delegating it to the owner.

Before editing and after implementation, run the complete Python + Dashboard
regression gates from the goal, including Ruff, full pytest, frozen pnpm
install, OpenAPI/API/Wrangler type drift checks, lint, typecheck, Vitest,
production build, client-bundle secret scan and real local cross-stack smoke.

For UX verification, prefer available browser automation/headless screenshots.
Only if the execution environment truly lacks an automatable browser path may
the owner be asked for the bounded desktop/mobile visual check written verbatim
in the goal.

If the existing ignored project config and Cloudflare credential reference are
available, verify/redeploy the existing private Dashboard and rerun live smoke
automatically without changing Access/Tunnel policy. If they are not available,
record the exact skipped live-only step; do not treat missing cloud credentials
as a local implementation blocker and do not ask for tokens in chat.

After push, inspect GitHub Actions for the exact pushed commit. Do not claim
completion while CI is red or in progress.

## Explicitly deferred

- Phase 6 watchlist/event-driven re-analysis;
- M4-D/M4-E;
- M2-D;
- M5-C/R2 absent a separately demonstrated artifact need;
- any `strict-v1`, A6/PIT/source-selection or investment-semantic change.

A6 remains the separate strict production-claim audit and is not a prerequisite
for this personal read-only Dashboard UX package.

Stop after M6-C3 closure and return a precise verification record plus any
genuine remaining blocker.
