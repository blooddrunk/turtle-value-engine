# Phase 6-D2A coding-agent handoff — Persistent Unattended Runner Foundation

Status: **CLOSED / IMPLEMENTED**

Canonical goal:
`docs/goals/phase-6-d2a-persistent-runner-foundation.md`

Implementation closure:
`docs/status/phase-6-d2a-2026-09-22.md`

Selection audit:
`docs/status/phase-6-d2a-selection-2026-09-22.md`

## Goal command prompt

Implement **Phase 6-D2A only** on the latest synchronized `main`.

Read and obey `AGENTS.md`, the canonical D2A goal, the D2A selection audit,
the closed Phase 6-A/6-B/6-C/D1 goals/status records,
`docs/architecture/runtime-and-automation.md`, the current
`.github/workflows/ci.yml`, and the affected source contracts before editing.
Chat history is not a specification.

### Required result

Add a scheduler-neutral, durable single-host unattended runner around the
existing Phase 6-D1 synchronous cycle. The selected reference deployment is a
persistent Linux host with systemd timer/service; do not add a scheduled
GitHub Actions monitoring workflow and do not invent remote state merely to
make Actions persistent.

Persist a typed/versioned/hash-verified runner activation intent before D1 so
the resolved PIT/as_of is frozen. Add explicit single-host lease semantics to
prevent overlap. Persist a terminal runner receipt that binds the activation to
the exact D1 cycle result/outbox identities and hashes. Retry after a crash must
resume the unfinished activation; if D1 terminal artifacts already exist but
the runner receipt/pointer does not, repair the runner layer without repeating
provider/model work.

Expose a non-interactive runner/status CLI and add reference systemd
service/timer templates with persistent state paths and no embedded secrets.
Keep all D1/6-A/6-B/6-C semantics behind their existing public boundaries.

### Automatic verification is mandatory

Do not stop at implementation or prose evidence. Automatically verify:

- fast-forward-only sync, clean tree and exact baseline SHA;
- exact-baseline GitHub Actions success;
- focused D2A tests covering first run, no duplicate work, overlap exclusion,
  stale/abandoned lease recovery, crash before D1 terminal, crash after D1
  terminal but before runner receipt, corruption/conflict fail-closed behavior,
  unresolved-current-run preservation, no-event zero-call behavior and secret-
  free bounded status output;
- socket/network denial when network is not explicitly allowed;
- checked-in schema drift for every new persisted contract;
- at least one real subprocess black-box runner CLI test;
- `systemd-analyze verify` on the checked-in D2A service/timer;
- the complete existing CI command matrix from `.github/workflows/ci.yml`;
- after push, the GitHub Actions run for the **exact closing implementation
  SHA**, recording its run id/result in a dated D2A closure/status document.

Use `python3` instead of `python` if the environment lacks a `python`
executable; do not treat that as a manual blocker.

### Manual boundary

There is **no planned manual functional acceptance** for D2A. Do not ask the
owner to deploy a VPS, choose a real cadence, enter credentials, trigger a real
CNINFO event or inspect a screen just to close this software slice. Those are
Phase 6-E concerns.

If a genuinely unavoidable external boundary appears, document the exact
command, exact screen/URL/system state, exact human action, exact resume
command, expected success state, automatic post-resume checks and the precise
remaining unproved boundary. Never write only "manual verification required"
or "evidence not fully recorded".

### Stop boundary

Do **not** start D2B/D3/6-E: no webhook/email/Slack/Telegram transport, no
notification acknowledgement state, no Dashboard monitoring page/API
projection, no owner live unattended deployment, no remote derived-state store,
no Hermes-specific coupling, no Bridge event adapter, no new CNINFO taxonomy,
no trading/brokerage operation, and no `strict-v1`/valuation/hard-gate/
adjustment-approval change.

Update the canonical goal/status/architecture/roadmap/AGENTS documentation only
as needed to reflect the implementation and exact automatic evidence.
