# Phase 6-C — Controlled Re-analysis Executor

Status: **IMPLEMENTED — CLOSURE EVIDENCE RECORDED IN `docs/status/phase-6-c-2026-09-21.md`**
Date: 2026-09-21
Selected after: Phase 6-B CLOSED
Selection audit: `docs/status/phase-6-c-selection-2026-09-21.md`

Parent context:

- `AGENTS.md`
- `docs/goals/phase-6-a-watchlist-event-foundation.md`
- `docs/goals/phase-6-b-live-event-acquisition.md`
- `docs/status/phase-6-b-2026-09-21.md`
- `docs/architecture/runtime-and-automation.md`
- `src/turtle_value_engine/monitoring/`
- `src/turtle_value_engine/preparation.py`
- `src/turtle_value_engine/research/`
- `src/turtle_value_engine/pipeline.py`
- `src/turtle_value_engine/surface/`

## 1. Objective

Consume a committed Phase 6-A `ReanalysisPlanV1` and execute the permitted
preparation/research/analysis slice without turning monitoring into another
investment engine.

Phase 6-C must:

1. execute only requests belonging to a persisted and committed
   `MonitoringRunV1`;
2. derive deterministic, auditable re-analysis job identities;
3. apply explicit behavior for every `ImpactClass`;
4. keep provider-network permission and analyst/model availability separate
   and fail-closed;
5. persist restart-safe job lifecycle, blockers/failures and exact output
   artifact references;
6. preserve the existing adjustment approval/materialization boundary;
7. project every successful analysis through the existing
   `ResearchSurfaceSnapshotV1`;
8. leave Phase 6-A event/cursor state immutable.

This is an executor package. It is not a scheduler, notifier, daemon, Dashboard
mutation endpoint or brokerage workflow.

## 2. Baseline preflight

Before edits the coding agent must automatically:

1. fast-forward `main` only;
2. record `git status --short --branch`, local HEAD and
   `git ls-remote origin refs/heads/main`;
3. verify GitHub Actions is green for the exact synchronized baseline;
4. run:
   ```bash
   python -m ruff check .
   python -m pytest
   ```

Phase 6-B already has hardened real-CNINFO live evidence, byte-identical
offline replay and exact-head green CI. Do **not** repeat live CNINFO as
ceremony. Repeat that bounded live smoke only if Phase 6-C changes Phase 6-B
provider/acquisition/mapping/`watch acquire-events` code.

No baseline check is delegated to the user.

## 3. Package boundary

Prefer a new package outside the pure Phase 6-A planner, for example:

`src/turtle_value_engine/monitoring_execution/`

The pure `turtle_value_engine.monitoring` package must remain free of provider,
analyst/model, research and deterministic-analysis imports.

Phase 6-C may call the existing preparation, research, pipeline, traceability
and surface-projection boundaries from the new execution layer only.

Do not modify `strict-v1`, CDC, Net Cash, Through Return, hard-gate,
Business Quality or valuation semantics.

## 4. Committed-plan eligibility

An arbitrary standalone plan JSON is not executable.

Starting from `MonitoringWorkspace` + `run_id`, the executor must:

1. load and fully validate the persisted `MonitoringRunV1`;
2. validate the embedded `ReanalysisPlanV1` and its run/watchlist identity;
3. load the exact persisted watchlist snapshot referenced by
   `watchlist_content_sha256`;
4. load the exact persisted event batch referenced by `event_batch_id`;
5. resolve every request `event_id` against that event batch;
6. reject missing events, cross-listing events, identity/hash mismatches and
   non-canonical artifacts;
7. prove the run is committed rather than merely present as an orphan artifact.
   Add the smallest explicit commit-proof metadata/read helper necessary; do not
   guess commitment from filename existence;
8. set `execution_as_of = MonitoringRunV1.as_of`. Wall clock must never
   replace the committed PIT boundary.

If the current workspace representation cannot prove historical commitment
without ambiguity, introduce an additive typed commit record/index rather than
weakening the check or pretending an orphan run is committed.

## 5. Versioned execution policy

Introduce a monitoring-only execution policy, e.g.
`reanalysis-execution-v1`, separate from `event-impact-v1` and
`strict-v1`.

### NO_REANALYSIS

Result: `NO_ACTION`.

Required proof:

- zero preparation/provider calls;
- zero analyst/model calls;
- zero deterministic-analysis calls;
- no Phase 6-A workspace mutation.

### PARTIAL_REANALYSIS

- prepare a fresh `NormalizedCompanyInput` at `execution_as_of` through the
  existing preparation boundary;
- run deterministic `CompanyAnalysis` and decision trace;
- do **not** automatically invoke an analyst/model;
- prior Business Quality may be reused only when an explicit prior-analysis
  resolver supplies an artifact whose listing, profile and PIT boundary match;
  record the source analysis id and a stable `REUSED_PRIOR_BQ` reason;
- when no valid prior BQ is supplied, keep it absent and record
  `BUSINESS_QUALITY_NOT_REFRESHED`; do not fabricate it and do not silently
  promote the request to FULL;
- do not carry prior adjustments implicitly.

### FULL_REANALYSIS

- prepare fresh input at `execution_as_of`;
- execute Business Quality research through an injected existing
  `ResearchOrchestrator` / `AnalystClient` boundary;
- run the deterministic final analysis, trace and report;
- ordinary CI uses `ScriptedAnalystClient` or an equivalent deterministic
  injected client;
- if no research runtime is configured, persist
  `BLOCKED_RESEARCH_RUNTIME`; never silently downgrade FULL to PARTIAL.

### URGENT_MANUAL_REVIEW

Result: `MANUAL_REVIEW_REQUIRED`.

Persist the exact triggering event ids/types and policy reason, with:

- zero preparation/provider calls;
- zero analyst/model calls;
- zero deterministic-analysis calls;
- no Phase 6-A workspace mutation.

This status is a **domain decision requiring later human investment review**.
It is not permission for the coding agent to skip automated software
verification.

## 6. Network, model and adjustment permissions

Fail closed by default.

- Live preparation requires an explicit network allow capability.
- Offline/cache preparation requires no network permission and must be testable
  with sockets blocked.
- Analyst/model execution is independently injected/allowed; network allow does
  not imply model permission.
- No executor path may approve an adjustment.
- LLM-originated adjustments remain proposals.
- Accepted adjustments may affect analysis only when explicitly supplied by
  the caller and validated through the existing
  `materialize_effective_input` /
  `run_analyze_with_accepted_adjustments` boundary.
- Never infer adjustment acceptance from a previous analysis, report, job or
  monitoring state.

## 7. Durable job contracts and store

Add the minimum typed, versioned, hash-verified contracts and checked-in JSON
schemas needed for a durable re-analysis job store.

Persist at least:

- deterministic `job_id`, derived from source run id + request id +
  execution-policy id + `execution_as_of`;
- watchlist/listing/source-run/request identities;
- impact and event ids;
- source watchlist hash, event-batch id and committed-run proof;
- execution-policy id/version;
- non-secret capability summary (network allowed/denied; research runtime
  available/unavailable);
- lifecycle/result status;
- stable blocker/failure code plus bounded non-secret message;
- prior-analysis/BQ reference when reused;
- normalized-input identity/hash when persisted;
- output `CompanyAnalysis` id/hash;
- decision-trace id/hash;
- optional FULL research-session/report ids/hashes;
- output `ResearchSurfaceSnapshotV1` id/hash.

Recommended terminal states:

- `NO_ACTION`
- `MANUAL_REVIEW_REQUIRED`
- `BLOCKED`
- `FAILED`
- `SUCCEEDED`

If `PENDING`/`RUNNING` are persisted, use an injected clock and make
restart behavior explicit. Wall-clock timestamps must not enter deterministic
job identity.

Use immutable job/attempt/result artifacts plus an atomic latest pointer, or an
equivalent fail-safe design.

Idempotency rule:

- executing an already-successful identical job must reuse the recorded result
  without repeating provider/model calls;
- conflicting bytes under an existing deterministic identity fail closed.

Keep this store separate from `MonitoringWorkspace`. Phase 6-C does not
rewrite `WatchlistStateV1`, event cursors or processed-event history. Phase
6-D may later join monitoring status with the latest re-analysis status for
scheduler/notification/Dashboard projections.

## 8. Prior-analysis resolution

A prior analysis is optional and must be explicit.

Permitted resolver sources include:

- an explicit analysis artifact path/id supplied by the caller;
- an explicit `current_analysis_id` from the watchlist specification when an
  artifact resolver can prove it;
- the latest successful Phase 6-C result for the same watchlist/listing.

Do not scan arbitrary folders and pick a "latest" file.

Reject prior artifacts when:

- listing differs;
- profile differs;
- prior `as_of` is later than `execution_as_of`;
- hash/identity validation fails.

Missing prior analysis must not become fabricated Business Quality or
implicitly accepted adjustments.

## 9. Surface output

For every successful PARTIAL/FULL job, call the existing
`build_research_surface_snapshot`.

- PARTIAL may project analysis + decision trace without a research report.
- FULL should include its validated research report.
- Persist the surface as an explicit Phase 6-C output artifact.
- Do not mutate Cloudflare, Tunnel, Access, M6-B service state or Dashboard
  deployment configuration.

## 10. CLI and library API

Expose a small injected library API plus a non-interactive CLI surface,
approximately:

```text
tve watch execute-reanalysis --workspace ... --run-id ...
tve watch reanalysis-status --job-root ... --job-id ...
```

Useful execution options may include:

- `--listing` to select one request from the committed plan;
- explicit network deny/allow;
- explicit cache/preparation paths;
- explicit job/research output roots;
- explicit prior-analysis input.

Reuse existing provider/config constructors instead of building a parallel data
stack.

Do not add:

- scheduler loops;
- cron installation;
- webhooks;
- notifications;
- background daemons;
- Dashboard write endpoints.

A FULL job without a research runtime must terminate non-interactively with the
stable blocker above.

## 11. Automatic verification requirements

The coding agent owns verification. Add deterministic tests for at least:

1. arbitrary/uncommitted/orphan plan rejection;
2. committed-run proof success and missing/corrupt commit-proof failure;
3. run/plan/watchlist/event-batch identity mismatch;
4. missing/cross-listing event-id rejection;
5. `NO_REANALYSIS` zero-call behavior;
6. `URGENT_MANUAL_REVIEW` zero-call behavior;
7. PARTIAL prepare/analyze happy path;
8. PARTIAL prior-BQ reuse only with exact listing/profile/PIT checks;
9. PARTIAL missing-BQ explicit limitation;
10. FULL scripted-research happy path;
11. FULL missing-runtime `BLOCKED_RESEARCH_RUNTIME`;
12. network deny with zero provider transport calls;
13. offline/cache execution while socket access is blocked;
14. no automatic adjustment approval or implicit reuse;
15. explicitly accepted adjustments use only the existing materialization
    boundary;
16. deterministic job identity;
17. repeated successful execution performs no duplicate provider/model work;
18. conflicting persisted content under one identity fails closed;
19. crash/write-failure injection around immutable artifacts and latest pointer;
20. restart/resume behavior if non-terminal states are persisted;
21. provider/preparation/research/analysis exceptions map to stable failure
    codes and do not corrupt prior successful artifacts;
22. successful surface snapshot validates and matches analysis/trace/report;
23. Phase 6-C execution leaves the Phase 6-A monitoring workspace byte-identical;
24. JSON-schema drift checks for every new persisted contract;
25. CLI output is bounded and secret-free.

Before closure run the full repository gate, not only focused tests:

```bash
python -m ruff check .
python -m pytest
```

Also run every generated-contract/Dashboard gate currently enforced by CI.
After push, verify GitHub Actions green for the **exact closing SHA** and record
the SHA and Actions run id in the closure document.

Do not close with phrases such as "manual verification recommended",
"evidence not fully recorded" or unexplained internal shorthand.

## 12. Human verification boundary

**None is required for Phase 6-C software closure.**

- A live LLM call is not required; scripted injected analyst clients are the
  deterministic CI acceptance boundary.
- Phase 6-B live acquisition is already closed.
- Phase 6-D owns scheduler/notification/Dashboard monitoring behavior.
- Phase 6-E owns unattended owner live acceptance.

If Phase 6-C unexpectedly introduces a genuinely unavoidable external
CAPTCHA/login/consent boundary, the coding agent must stop at that boundary and
record all of the following, concretely:

1. exact command that reaches the boundary;
2. exact screen/URL and exact human action required;
3. exact resume command;
4. expected successful output/state;
5. automatic verification that will run after resumption;
6. what remains outside the proved boundary.

A generic "manual verification required" statement is not an acceptable
handoff.

## 13. Explicitly out of scope

Do not start within Phase 6-C:

- Phase 6-D scheduler, notifications or Dashboard monitoring views;
- Phase 6-E unattended owner acceptance;
- extra CNINFO taxonomy merely to create more typed events;
- BJ/H disclosure-source expansion;
- FQGate Bridge event/history adapters before the Bridge publishes a
  compatible typed read-only operation;
- Cloudflare/Tunnel/Access mutation;
- brokerage/trading/order/funds operations;
- `strict-v1` changes;
- automatic adjustment approval;
- generic remote command execution.

## 14. Closure criteria

Phase 6-C may be CLOSED only when:

1. exact synchronized baseline CI and local gates are green;
2. committed-run eligibility is machine-proven;
3. all four impact classes have explicit executor behavior;
4. network/model/adjustment capabilities fail closed;
5. durable idempotent/restart-safe job evidence exists;
6. PARTIAL and FULL produce validated outputs in deterministic injected tests;
7. successful jobs produce validated `ResearchSurfaceSnapshotV1` artifacts;
8. Phase 6-A monitoring workspace remains unchanged by execution;
9. focused and full repository gates are green;
10. exact closing commit CI is green and recorded;
11. no Phase 6-D/6-E or unrelated source expansion is mixed in.
