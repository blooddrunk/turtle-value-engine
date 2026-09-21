# Phase 6-C coding-agent handoff — Controlled Re-analysis Executor

Status: **IMPLEMENTED — SEE `docs/status/phase-6-c-2026-09-21.md`**

Canonical goal:
`docs/goals/phase-6-c-reanalysis-executor.md`

Selection audit:
`docs/status/phase-6-c-selection-2026-09-21.md`

## Task

Implement Phase 6-C on the latest synchronized `main`.

Read and obey `AGENTS.md`, the canonical Phase 6-C goal, the Phase 6-A/6-B
goals/status records and the affected source contracts before editing. Chat
history is not a specification.

### Mandatory baseline

Automatically:

1. fast-forward `main` only;
2. prove the working tree is clean;
3. record local HEAD and remote `origin/main`;
4. verify GitHub Actions green for that exact baseline;
5. run `python -m ruff check .`;
6. run `python -m pytest`.

Do not repeat Phase 6-B live CNINFO merely as ceremony. Its hardened live and
cache-replay acceptance is closed. Repeat it only if you modify Phase 6-B
provider/acquisition/mapping/watch-acquire code.

### Required implementation

Build the smallest provider/model-neutral re-analysis executor that:

- executes only requests belonging to a persisted **committed**
  `MonitoringRunV1`;
- machine-proves run/plan/watchlist/event-batch identities and commitment;
- uses the committed monitoring `as_of` as the PIT boundary;
- implements explicit `NO_REANALYSIS`, `PARTIAL_REANALYSIS`,
  `FULL_REANALYSIS` and `URGENT_MANUAL_REVIEW` behavior exactly as the goal
  defines;
- keeps live provider network access and analyst/model execution independently
  fail-closed;
- never auto-approves or implicitly reuses adjustments;
- persists deterministic, typed, hash-verified, idempotent and restart-safe
  job/attempt/result artifacts in a **separate re-analysis store**;
- reuses an already-successful identical job without repeating provider/model
  calls;
- produces validated `CompanyAnalysis`, trace and
  `ResearchSurfaceSnapshotV1` outputs for successful PARTIAL/FULL jobs;
- uses scripted injected analyst clients for deterministic FULL acceptance in
  CI;
- leaves the Phase 6-A `MonitoringWorkspace`, cursors and processed-event
  history byte-unchanged;
- adds only the smallest read helpers/commit proof needed to the monitoring
  workspace;
- does not start scheduler/notification/Dashboard mutation work.

### Verification is part of the task

Implement the full automatic test matrix in the canonical goal. In particular,
prove orphan-plan rejection, zero-call NO/URGENT paths, PARTIAL/FULL happy and
blocked paths, sockets-blocked offline execution, no automatic adjustment
approval, job idempotency, crash/write failure recovery, stable failure codes,
valid surface projection and byte-unchanged Phase 6-A monitoring state.

Before declaring completion run the full repository gates, including:

```bash
python -m ruff check .
python -m pytest
```

and **every generated-contract/Dashboard gate currently enforced by CI**.

Push the implementation and closure evidence, then verify GitHub Actions
`success` for the **exact closing SHA** and record both SHA and run id.

### Human boundary

Phase 6-C requires no manual functional acceptance and no live LLM call.

If a genuinely unavoidable CAPTCHA/login/consent boundary appears, do not write
"manual verification recommended" or "evidence incomplete". Record:

1. exact command before the boundary;
2. exact screen/URL and exact human action;
3. exact resume command;
4. expected successful output/state;
5. automatic checks to run after resume;
6. the precise unproved remainder.

### Stop boundary

Do **not** start Phase 6-D/6-E, new CNINFO taxonomy expansion, BJ/H source
expansion, an unproven FQGate Bridge event adapter, Cloudflare mutation,
brokerage/trading operations, generic remote execution or `strict-v1`
changes.
