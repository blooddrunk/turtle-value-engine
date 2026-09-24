# Phase 6-D3-R1 coding-agent handoff — non-interfering lease observation

Status: **CLOSED** — implemented at `40a75d89c2863b74a3e44ecfbad4fe432959fc5b`
(Actions run 35948785496, `success`, exact `head_sha` match); closure record
`docs/status/phase-6-d3-r1-2026-09-24.md`.

Canonical goal:
`docs/goals/phase-6-d3-r1-noninterfering-lease-observation.md`

Selection audit:
`docs/status/phase-6-d3-post-closure-review-2026-09-24.md`

## Goal

Implement only **Phase 6-D3-R1 — Non-interfering Lease Observation Hardening**.

Start from a fast-forward-only synchronized `main`; record the exact baseline
SHA and working-tree state. Read `AGENTS.md`, the R1 goal, D3 goal/closure,
D2A-R1 lease contracts/status and the current runner/projection code before
editing.

The defect to close is concrete: D3 currently calls `RunnerLease.probe()`,
which attempts the same `LOCK_EX | LOCK_NB` flock used by
`RunnerLease.held()`. A D3/API read can therefore transiently own the
authoritative runner lock and cause a concurrent otherwise-free runner
invocation to return `LEASE_BUSY` with zero D1 work.

Fix this structurally. D3/status observation must not acquire any lock that can
conflict with the authoritative work lease. Preserve genuine-holder
single-flight and fail-fast `LEASE_BUSY` behavior. Do not paper over the race
with sleeps, retries or a tiny timeout. If exact liveness cannot be proven
passively, expose an explicit conservative typed state instead of fabricating
LIVE/FREE/ABANDONED; regenerate Schema/OpenAPI/client types/UI copy if the
public contract changes.

Automatic verification is mandatory. Add deterministic barrier/process tests
that prove:

1. no real holder + concurrent D3 observation + real runner => zero
   observer-induced `RunnerLeaseBusyError`, and D1 is entered exactly once;
2. real holder + D3 observation + second runner => the second runner still
   gets `RunnerLeaseBusyError` with zero D1 work, while D3 takes no conflicting
   authority;
3. a bounded repeated concurrency matrix produces zero observer-induced busy
   outcomes;
4. existing no-write/no-repair/secret hygiene, runner error classification,
   D3 API/Worker read-only boundary and D2B-R2 projection semantics remain
   unchanged.

Run every available check yourself, including at minimum:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest tests/test_monitoring_runner.py tests/test_monitoring_dashboard.py
python -m pytest tests/test_monitoring*.py
python -m pytest
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard install --frozen-lockfile
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
```

Use `python3` only if required and record it.

**Manual boundary: NONE.** Do not delegate any race reproduction, lock
inspection, browser check, VPS deployment, webhook send, provider/model call or
Cloudflare action to the owner for this package. If a local tool is missing,
replace it with a deterministic process/barrier test where possible and state
the exact remaining limitation only if no automatic substitute exists.

After pushing, query GitHub Actions for the exact implementation SHA. Inspect
and fix failures yourself. Mark R1 CLOSED only after a successful required run
whose `head_sha` exactly matches the implementation SHA; record exact SHA, run
id/conclusion, focused concurrency results, full-suite counts and smoke
results.

Stop before Phase 6-E and all unrelated source/Bridge/trading/investment-rule
work.
