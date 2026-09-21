# Phase 6-D1 coding-agent handoff — Deterministic Monitoring Cycle and Alert Outbox

Status: **SELECTED / NOT IMPLEMENTED**

Canonical goal:
`docs/goals/phase-6-d1-monitoring-cycle-alert-outbox.md`

Selection audit:
`docs/status/phase-6-d1-selection-2026-09-21.md`

## Task

Implement **Phase 6-D1 only** on the latest synchronized `main`.

Read and obey `AGENTS.md`, the canonical D1 goal, Phase 6-A/6-B/6-C
goals/status records, `docs/architecture/runtime-and-automation.md`,
`docs/architecture/agent-api-web-surface.md`, the current
`.github/workflows/ci.yml`, and the affected source contracts before editing.
Chat history is not a specification.

### Mandatory baseline — do it yourself

Automatically:

1. fast-forward `main` only;
2. prove the tree is clean;
3. record local HEAD and remote `origin/main`;
4. verify GitHub Actions is green for that exact baseline;
5. run `python -m ruff check .`;
6. run `python -m pytest`;
7. run every generated-contract/Dashboard/security/Wrangler/cross-stack gate
   currently enforced by CI.

Do not ask the owner to run routine commands or inspect files for you.

### Implement the smallest D1 boundary

Build a scheduler-neutral, synchronous **one-cycle** orchestrator that:

- consumes an explicit cycle spec with an explicit PIT `as_of`;
- uses the existing Phase 6-B acquisition boundary, still deny-by-default;
- feeds only the canonical event batch into the existing Phase 6-A
  plan/atomic-commit boundary;
- after that commit, executes every committed `ReanalysisRequestV1` through
  the existing Phase 6-C executor in deterministic order;
- uses explicit typed per-listing execution bindings/resolvers so company name,
  sector, currency, prepared input, prior analysis and similar context are
  never guessed;
- persists typed/versioned/hash-verified terminal cycle evidence in a separate
  cycle store;
- emits a deterministic, immutable, secret-free alert outbox that references
  exact event/run/job/surface identities and distinguishes material event,
  manual review, blocked, failed and succeeded re-analysis states;
- never changes a monitoring severity into an investment recommendation;
- never approves an adjustment;
- never duplicates provider/model work when an identical successful cycle is
  retried.

### Preserve retryability

The current Phase 6-C commitment proof requires the current monitoring pointer
to reference its committed run/state.

Therefore, before committing a new monitoring run, D1 must automatically check
the current run's Phase 6-C dispositions.

Treat:

- SUCCEEDED / NO_ACTION / MANUAL_REVIEW_REQUIRED as resolved execution
  dispositions (manual review still emits an attention alert);
- BLOCKED / FAILED as unresolved.

If unresolved work exists, fail closed **before** advancing the Phase 6-A
pointer. Do not add a silent skip/acknowledge escape hatch in D1.

### Verification is part of the implementation

Implement the full automatic matrix from the canonical D1 goal. At minimum
prove:

- deny-by-default network = zero transport calls;
- socket-blocked cache-only end-to-end cycle;
- fake acquisition -> 6-A commit -> 6-C execution -> alert outbox;
- no-event cycle = zero re-analysis/model calls;
- failures before commit leave old monitoring state byte-identical;
- every committed request executes in canonical order;
- all four impact classes keep their existing semantics;
- missing model runtime and missing execution binding are typed blockers;
- BLOCKED/FAILED prevent the next pointer advance;
- adjustment approval boundaries are unchanged;
- deterministic IDs, schema drift, conflict detection, crash/pointer repair,
  idempotent replay and duplicate-alert suppression;
- alert/CLI output is bounded and secret-free;
- no scheduler, notification transport, Dashboard write path or trading code is
  introduced.

Then run the **entire** repository gate, not only focused tests:

```bash
python -m ruff check .
python -m pytest
```

Run every other gate in the current CI workflow as well. Push the implementation
and closure evidence, verify GitHub Actions `success` for the **exact closing
SHA**, and record SHA + Actions run ID.

Do not repeat the already-closed live CNINFO probe just for ceremony. If and
only if you modify Phase 6-B provider/acquisition/mapping/transport code, run
the bounded real CNINFO smoke automatically and record its exact evidence.

### Human boundary

D1 requires **no manual functional acceptance**, browser verification,
Cloudflare interaction, live LLM call or notification receipt.

If a genuinely unavoidable external CAPTCHA/login/consent boundary appears,
do not write "manual verification recommended" or "evidence not fully
recorded". Record exactly:

1. command that reaches the boundary;
2. URL/screen and exact human action;
3. resume command;
4. expected successful output/state;
5. automatic verification after resume;
6. precise remaining unproved boundary.

### Stop boundary

Do **not** start D2/D3/6-E: no cron/systemd, no Actions schedule, no Hermes cron,
no webhook/email/Slack/Telegram delivery, no notification receipt logic, no
Dashboard monitoring page/API, no Cloudflare mutation, no remote storage merely
for an ephemeral scheduler, no historical-commit-journal redesign, no new
CNINFO taxonomy/BJ/H source expansion, no FQGate Bridge adapter, no vendor LLM
integration, no trading/funds operations and no `strict-v1` changes.

Stop after D1 closure and leave the repository with an exact next-step status
record rather than silently continuing into D2.
