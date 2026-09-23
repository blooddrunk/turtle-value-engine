# Phase 6-D3 coding-agent handoff — read-only monitoring operations Dashboard

Status: **IMPLEMENTED / CLOSED**

Canonical goal:
`docs/goals/phase-6-d3-read-only-monitoring-dashboard.md`

Selection audit:
`docs/status/phase-6-d2b-r2-post-closure-review-2026-09-23.md`

## Goal

Implement only **Phase 6-D3 — Read-only Monitoring Operations Dashboard
Projection**.

Read and obey `AGENTS.md`, the canonical D3 goal, the R2 post-closure review,
and the Phase 6-A / 6-C / D1 / D2A-R1 / D2B-R2 contracts/status records before
editing. Chat history is not the specification.

Start by fast-forward-only syncing `main`, inspecting the working tree and
recording the exact baseline SHA. Do not overwrite unrelated owner changes.
Verify baseline CI truthfully: the current selection/doc HEAD may have no
Actions run; if so, cite the latest code-affecting ancestor with an exact green
run and execute the complete local baseline gate before editing. Never invent
an exact-head CI result.

Build one versioned, secret-free, framework-neutral
`MonitoringOperationsProjectionV1` (name may vary only if repository
conventions strongly require it) over **explicit** configured monitoring
sources. Prefer existing `RunnerConfigV1` + `ProjectConfig`; do not scan CWD,
recursively discover `.tve-private`, guess "latest" files or add a remote
database.

Keep the first slice bounded to the configured runner's current operational
chain:

```text
monitoring workspace status
+ runner/lease read-only status
+ active activation, otherwise latest terminal activation
+ that activation's cycle
+ only re-analysis jobs referenced by that cycle
+ only deliveries bound to that activation
= one typed operations projection
```

Expose it through exactly one first-slice read endpoint:
`GET /v1/monitoring/operations`, then the fixed Worker route
`/api/v1/monitoring/operations`, then a Chinese-first read-only
`/monitoring` page.

Critical D2B-R2 invariant for the projection/UI:

> persisted delivery outcome count is NOT the same thing as consumed outbound
> dispatch budget.

Expose/label `attempt_count` separately from `dispatch_claim_count`; preserve
`unresolved_claim_numbers`, legitimate attempt-number gaps,
`AMBIGUOUS / ORPHANED_DISPATCH`, and
`CURRENT / MISSING / STALE_REPAIRABLE` pointer states. Never label
`attempt_count` as total sends/retries. Contradictory evidence must fail
closed, not disappear from the page.

The D3 request path is strictly observational. It must never call provider
acquisition, models/research, re-analysis execution, D1 cycle execution,
delivery transport, pointer repair/publication, retry, resend, acknowledge or
any mutation. If an existing helper writes/repairs as a side effect, add/use a
read-only projection helper instead.

Do not leak local absolute roots, webhook endpoints, tokens, Cloudflare Access
secrets, runner holder tokens, raw response bodies or provider payloads into
the API/browser. Keep long audit IDs/hashes behind technical details in the UI.

Add deterministic tests proving at minimum:

- empty/not-yet-run state is truthful;
- a complete configured chain projects exact identities/statuses;
- active/unfinished activation is not confused with an older latest receipt;
- manual-review/blocked/failed re-analysis/cycle states stay distinct;
- all delivery terminal/retry/ambiguous/NOOP states stay exact;
- an R2 orphan fixture proves outcome count != consumed dispatch-slot count and
  preserves unresolved slot numbers;
- missing/stale delivery pointers remain visible;
- corrupt/foreign/contradictory state fails closed;
- source-store file/byte inventory is unchanged before vs after projection;
- provider/model/cycle/delivery sentinels receive zero calls;
- no local-path/secret sentinel reaches serialized output;
- API/Worker remain fixed-route GET/HEAD read-only;
- Dashboard has no run/retry/resend/repair/acknowledge/trade/order/write
  control.

Extend the real local cross-stack smoke so it creates valid deterministic store
fixtures with real model/store builders, starts the actual API and Dashboard
preview/Worker path, requests the monitoring route through same-origin, verifies
the R2 accounting fields survive end-to-end, proves mutation rejection and
secret/path absence, then shuts down cleanly.

Run **every** automatable check yourself. At minimum run the focused D3 tests and:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
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

Use another interpreter name only if required by the environment and record the
substitution. Do not delegate a command to the owner merely because it is
lengthy.

For layout, automatically use an available browser/computer capability or an
installed headless Chromium/Chrome/Edge path. Check roughly 1440x900 and
390x844, normal + attention/ambiguous state, expanded audit details, no
horizontal overflow and no mutation controls.

**Manual boundary:** only if no usable browser automation/headless browser
exists may the owner perform layout-only verification. If that happens, first
finish all semantic/security/cross-stack automation, then provide the exact
fixture/preview start commands and local URL, and ask the owner to:

1. open `/monitoring` around 1440x900 and check for clipping/overlap;
2. repeat around 390x844 and check horizontal overflow/usability;
3. expand audit details and confirm IDs/hashes remain readable;
4. confirm delivery labels distinguish persisted outcomes from consumed
   dispatch slots and show unresolved slots from the fixture;
5. confirm no run/retry/resend/repair/acknowledge/write control exists;
6. report the exact failed numbered step and visible symptom if any.

That manual check proves layout only. If it is required but not completed, set
`BLOCKED_BY_VISUAL_VERIFICATION`; do not write "evidence not fully recorded"
and declare closure.

Do **not** require a real VPS, owner webhook, live credentials, real provider,
real model, Cloudflare redeployment or real scheduling for D3. Those are Phase
6-E/live boundaries, not excuses to leave D3 software verification vague.

After pushing, query GitHub Actions for the **exact implementation SHA**.
Inspect failures yourself. D3 is CLOSED only when the required run completes
successfully with matching `head_sha`, and the closure record includes exact
SHA/run id/conclusion, focused counts, full-suite counts, Dashboard count,
cross-stack result and browser/manual layout result.

Stop before Phase 6-E, scheduler changes, live notification acceptance,
vendor-specific adapters, Bridge/source expansion, brokerage/trading behavior
or investment-rule changes.
