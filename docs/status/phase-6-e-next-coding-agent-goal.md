# Phase 6-E coding-agent handoff — owner live unattended acceptance

Status: **SELECTED**

Canonical goal:
`docs/goals/phase-6-e-owner-live-unattended-acceptance.md`

Selection record:
`docs/status/phase-6-e-selection-2026-09-24.md`

Predecessor:
Phase 6-D3-R1 is CLOSED at
`40a75d89c2863b74a3e44ecfbad4fe432959fc5b`, Actions run
`35948785496` (`success`, exact `head_sha`); closure record
`docs/status/phase-6-d3-r1-2026-09-24.md`.

## Goal

Implement and execute only **Phase 6-E — Owner Live Unattended Acceptance**.

Start from a fast-forward-only synchronized `main`; record the exact baseline
SHA and working-tree state. Read `AGENTS.md`, the Phase 6-E goal, the R1
closure, the D2A deployment templates, D2B/R1/R2 delivery contracts, D3/R1
projection contracts and current project configuration before editing.

This is primarily an acceptance/deployment-automation package, not a feature
expansion. Preserve every closed Phase 6 semantic.

Build the smallest coherent automation needed so the owner does not have to
hand-edit systemd units, manually assemble logs or translate internal states
into evidence. Prefer a dedicated helper (for example
`scripts/monitoring_live_acceptance.py`) with equivalent
preflight/render-or-dry-run/apply/verify/live-smoke behavior if no existing
helper owns the workflow.

Automation must:

1. run the full deterministic repository gate before live mutation;
2. validate the real Linux/systemd host, explicit checkout/runtime/service-user
   and private configuration inputs without printing secrets;
3. automatically prove that the actual runner and D3/status/API contexts see
   the same authoritative flock truth through the D3-R1 passive
   `/proc/locks` observation path; do not assume container/PID-namespace
   visibility;
4. render deterministic owner-specific systemd material from explicit
   non-secret inputs, run `systemd-analyze verify`, and produce a redacted
   no-mutation plan;
5. apply/reload/enable units automatically when privilege exists, then verify
   the effective installed unit/timer state from `systemctl show`, not from
   templates;
6. use an isolated acceptance workspace and one/two public listings with a
   short explicit CNINFO date window containing a known disclosure; perform
   bounded real acquisition, persist raw data only in the private cache,
   canonicalize, validate provenance/hashes, replay offline with sockets
   blocked and prove byte/hash equality;
7. prove committed cursor movement occurs only after successful monitoring
   commit and capture the resulting D1/runner activation/cycle/receipt
   identities;
8. automate a contract-supported restart/replay/idempotency proof from durable
   runner artifacts using the safest existing boundary/hook; do not add an
   unsafe general-purpose production crash switch and do not call two exit-0
   commands an idempotency proof;
9. run the existing generic HTTPS webhook delivery for the selected terminal
   activation, record secret-free delivery id/state/attempt count/
   dispatch-claim count/unresolved claims/pointer state, repeat the delivered
   identity and prove no extra outbound dispatch is authorized;
10. verify the real D3 monitoring API/Worker/Dashboard projection is read-only,
    secret/path-free, preserves UNKNOWN truthfully, separates attempt vs
    dispatch counts, rejects mutation methods, and repeated polling cannot
    interfere with the runner;
11. write a bounded secret-free machine-readable acceptance report under the
    ignored private runtime tree; commit only a redacted closure summary.

Run and fix every machine-verifiable check yourself. At minimum:

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

Add deterministic tests for any new helper: dry-run/no-mutation, redaction,
bad paths/config, missing secret references, insufficient privilege,
idempotent rerun, lock-visibility preflight and acceptance-report generation.

### Human boundary

Do **not** delegate ordinary verification to the owner.

Human intervention is allowed only when unavoidable. Use one of the precise
markers below (or an equally precise new marker):

- `MANUAL_OWNER_INPUT_REQUIRED`
- `MANUAL_SECRET_REFERENCE_REQUIRED`
- `MANUAL_SUDO_INSTALL_REQUIRED`
- `MANUAL_NOTIFICATION_RECEIPT_REQUIRED`
- `MANUAL_IDP_ACCEPTANCE_REQUIRED`
- `DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN`

At any marker, write all of:

1. exact command/state immediately before the stop;
2. exact human action;
3. exact secret/data that must not enter Git/logs/chat;
4. exact resume command;
5. exact expected machine-verifiable success output/state;
6. exact remaining unverified boundary if the owner stops there.

If owner inputs are missing, finish all software/harness work and mark the live
phase exactly `READY_FOR_OWNER_AUTHORIZED_PHASE_6E`; do not claim CLOSED and
do not write vague "evidence incomplete" text.

After every implementation push, query GitHub Actions for the exact
implementation SHA and fix failures yourself. Software changes are accepted
only with a required successful run whose `head_sha` exactly matches.

Phase 6-E is CLOSED only after both exact-SHA CI and the bounded owner live
acceptance report pass. Record implementation SHA/run id, host/runtime facts,
lock-visibility result, bounded live acquisition + offline replay equality,
runner restart/replay identities, systemd effective state, delivery
idempotency evidence, D3 projection result and every manual marker actually
crossed.

Stop after Phase 6-E. Do not start vendor-specific notifications, scheduled
GitHub Actions monitoring, Bridge/FQGate expansion, M4-D/M4-E/M2-D,
brokerage/trading or investment-rule changes.
