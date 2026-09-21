# Phase 6-D1 selection audit — 2026-09-21

Status: **SELECTED / NOT IMPLEMENTED**

Audited main head:
`74337ac4882b6a5bd99ff2eef7a318e7f98cac94`

## 1. Phase 6-C audit result

Phase 6-C is accepted as **CLOSED** at the controlled re-analysis executor boundary.

Repository evidence independently checked through GitHub:

- implementation commit:
  `02d3fab6383a081dc7ee48cd80a11aa328b757ba`;
- push CI run:
  `35588244900`;
- workflow conclusion:
  `success`;
- Python gate in that run:
  `6537 passed, 2 skipped`;
- Dashboard gate:
  3 test files / 44 tests passed;
- Ruff, project-config validation, generated OpenAPI/types, Wrangler types,
  Dashboard lint/typecheck/build, client-bundle secret scan, Wrangler dry-run
  and the real cross-stack smoke all completed successfully;
- the later documentation-only commit
  `74337ac4882b6a5bd99ff2eef7a318e7f98cac94` records that implementation
  evidence in the canonical status file.

The implementation matches the Phase 6-C stop boundary:

- only a machine-proven committed `MonitoringRunV1` is executable;
- `MonitoringCommitProofV1` binds the committed monitoring artifacts;
- `ReanalysisJobStore` is separate from `MonitoringWorkspace`;
- all four impact classes have explicit terminal behavior;
- network, model/research availability and accepted-adjustment materialization
  remain independent fail-closed capabilities;
- successful PARTIAL/FULL paths project validated
  `ResearchSurfaceSnapshotV1` artifacts;
- successful identical jobs are reusable without duplicate provider/model
  work;
- Phase 6-A event/cursor state is not rewritten by execution;
- no scheduler, notification transport, Dashboard monitoring mutation,
  brokerage operation, extra CNINFO taxonomy or Bridge adapter was mixed into
  Phase 6-C.

No structural defect was found that requires reopening Phase 6-C.

## 2. Selected next package

**Phase 6-D1 — Deterministic Monitoring Cycle and Alert-Outbox Foundation**

Canonical implementation goal:

`docs/goals/phase-6-d1-monitoring-cycle-alert-outbox.md`

Canonical coding-agent handoff:

`docs/status/phase-6-d1-next-coding-agent-goal.md`

## 3. Why Phase 6-D is split

The roadmap describes Phase 6-D as scheduler + notifications + Dashboard
monitoring status. Implementing all three in one coding goal would mix four
different failure domains:

1. provider polling and point-in-time acquisition;
2. deterministic monitoring commit;
3. re-analysis execution;
4. external scheduling/delivery/UI infrastructure.

The first missing contract is not cron or a webhook. It is a **single,
synchronous, durable monitoring cycle** that composes the already-proven
Phase 6-B -> Phase 6-A -> Phase 6-C boundaries and emits a deterministic,
secret-free alert outbox.

Therefore Phase 6-D is deliberately decomposed:

- **6-D1 — now:** one-cycle orchestration, terminal cycle evidence and typed
  alert outbox; no scheduler and no notification delivery;
- **6-D2 — later:** choose a persistent unattended runner and add notification
  delivery/receipt semantics around the proven D1 cycle;
- **6-D3 — later:** expose read-only monitoring/cycle/job status through the
  existing API/Cloudflare/Dashboard stack;
- **6-E — later:** bounded owner live unattended acceptance including real
  scheduling, restart/replay/idempotency and notification acceptance.

This keeps each package automatically testable and prevents scheduler, webhook
or frontend code from inventing orchestration semantics.

## 4. Runtime/storage decision for D1

D1 must remain scheduler-neutral.

The repository currently keeps monitoring workspace and Phase 6-C job state in
persistent local stores. Do **not** select GitHub Actions merely because an
Actions scheduler exists and then invent remote storage to compensate for its
ephemeral filesystem. D2 must choose GitHub Actions, Hermes, cron/systemd or
another runner only after D1 proves the single-cycle boundary and the actual
persistent-state placement is explicit.

D1 may add only local, deployment-neutral derived state:

- immutable cycle attempts/results;
- an atomic latest pointer;
- deterministic alert-batch/outbox artifacts;
- explicit non-secret execution bindings needed to avoid guessing company
  context or preparation inputs.

Raw provider bytes remain owned by the existing Phase 6-B cache. Monitoring
cursor/event state remains owned by Phase 6-A. Re-analysis artifacts remain
owned by Phase 6-C.

## 5. Important unresolved-run rule

The current Phase 6-C commitment proof intentionally requires the current
monitoring pointer to reference the proven committed state. D1 must not
silently advance to another committed monitoring run while the current run has
retryable/unresolved `BLOCKED` or `FAILED` re-analysis requests.

The first D1 policy should therefore fail closed:

- execute the committed plan synchronously inside the cycle;
- `SUCCEEDED`, `NO_ACTION` and `MANUAL_REVIEW_REQUIRED` are durable
  execution dispositions;
- a `BLOCKED` or `FAILED` request makes the cycle attention-required and
  prevents the next cycle from advancing the monitoring pointer until the
  unresolved current-run state is handled by the same proven boundary;
- do not add a silent "skip/acknowledge and continue" escape hatch in D1.

If a later phase needs non-blocking concurrent monitoring while an older job is
unresolved, design an explicit historical-commit journal as a separate
contract change rather than weakening Phase 6-C commitment proof.

## 6. Verification policy

Codex owns every verification step that can be automated.

D1 software closure must require **no manual functional acceptance** and no
live LLM call. Scripted/injected clients, fake source transports and persisted
Phase 6-B cache replay are the deterministic acceptance boundaries.

Before closure Codex must automatically run:

- exact baseline synchronization/clean-tree checks;
- exact-baseline GitHub Actions verification;
- focused D1 tests;
- `python -m ruff check .`;
- `python -m pytest`;
- every generated-contract/Dashboard/security/cross-stack gate currently
  enforced by `.github/workflows/ci.yml`;
- exact-closing-SHA GitHub Actions verification after push.

Do not repeat the already-closed real CNINFO Phase 6-B probe as ceremony unless
D1 changes Phase 6-B acquisition/provider/mapping code. Cache replay and fake
transport integration remain mandatory.

If an unexpected external CAPTCHA/login/consent boundary is genuinely
unavoidable, the coding agent must record all of the following rather than
writing "manual verification required" or "evidence not fully recorded":

1. the exact command that reaches the boundary;
2. the exact URL/screen and exact human action;
3. the exact resume command;
4. the expected successful output/state;
5. the automatic verification commands that run after resumption;
6. the precise remaining unproved boundary.
