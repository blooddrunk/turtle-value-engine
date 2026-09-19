# Phase 5R-A Next Codex Goal — M6-C1 Personal Dashboard Foundation

Status: **M6-A/B COMPLETE; M6-C1 ACTIVE NEXT; M5-A/B COMPLETE; A6 PENDING**
Date: 2026-09-19
Baseline: `dda3a0d`

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

Read and follow `AGENTS.md` and the source-of-truth order. Read at least:

- `docs/goals/phase-5r-a-m6-c1-personal-dashboard-foundation.md`
- `docs/goals/phase-5r-a-m6-b-read-only-api-adapter.md`
- `docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/status/phase-5r-a-2026-09-19.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`

Implement **M6-C1 only**.

Build a local/preview-first personal read-only Dashboard under
`apps/dashboard` using React 19 + TypeScript + Vite, the official Cloudflare
Vite/Workers Static Assets path, TanStack Router and TanStack Query. Consume only
the existing M6-B read-only API through a same-origin Worker allowlist proxy.
Do not read raw stores or repository files from the browser/Worker, do not
recompute investment semantics and do not add write endpoints.

Generate Dashboard API types from a deterministic checked-in OpenAPI export of
the real M6-B FastAPI app. Do not hand-maintain a second API model. Preserve
`PARTIAL`, `BLOCKED`, `NOT_AVAILABLE`, `NOT_EVALUATED`, nulls, blockers,
warnings and limitations exactly; do not turn missing/blocked state into green
UI.

The minimum UI is a responsive surfaces overview/list plus a detail view showing
identity, company/listing/as-of/profile, decision/valuation, CDC/Net Cash/Through
Return, all hard-gate states/blockers, data quality, Business Quality status,
historical/A6 readiness/acceptance/validation status and source artifact
identities/hashes. Keep the first version read-only.

Verification is part of the implementation, not owner homework. Before editing,
run the Python baseline and record exact results:

```bash
python3 -m ruff check .
python3 -m pytest
node --version
pnpm --version
```

Automatically bootstrap/install declared Dashboard dependencies when the
environment permits it. After implementation run all required gates from the
M6-C1 goal, including:

```bash
python3 -m ruff check .
python3 -m pytest tests/test_research_surface.py -q
python3 -m pytest tests/test_surface_api.py -q
python3 -m pytest
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
python3 scripts/export_surface_openapi.py --check
```

Also implement and run the required **real cross-stack smoke**: start the actual
`tve surface serve` process on loopback, start the actual local
Cloudflare/Vite preview, fetch the Dashboard root, then exercise same-origin
health/list/known-detail/unknown-ID/mutation-rejection paths and shut both
processes down cleanly. Mock-only tests are not sufficient.

Do not ask the owner to deploy to Cloudflare, click a browser, create D1/R2,
configure Access/OIDC or manually run checks that Codex can run. Live Cloudflare
deployment/authentication is **M6-C2**, not C1.

If package installation, loopback/process spawning or the local Workers runtime
is genuinely forbidden by the execution environment, do not write vague
"evidence incomplete" prose and do not close the milestone. Record the exact
failing command/error, the gates that did pass, the single unverified acceptance
item and the exact owner-machine fallback sequence; mark the state
`BLOCKED_BY_EXECUTION_ENVIRONMENT`.

Update the dated status document with exact commands, exit codes, versions,
pass/skip counts and smoke evidence. Update goal/roadmap status only after all
required automated acceptance gates pass.

Stop after M6-C1. Do not start M6-C2, M5-C, Phase 6, M4-D/M4-E or M2-D in the
same goal.
