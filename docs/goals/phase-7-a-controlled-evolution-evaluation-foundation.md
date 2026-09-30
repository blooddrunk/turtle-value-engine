# Phase 7-A — Controlled Evolution Evaluation Foundation

Status: **SELECTED / NOT IMPLEMENTED**

Selection audit:
`docs/status/phase-6-f-r4-post-closure-review-2026-09-30.md`

Coding-agent handoff:
`docs/status/phase-7-a-next-coding-agent-goal.md`

## 1. Objective

Implement the first executable boundary in the roadmap's Phase 7 controlled
evolution chain:

`proposal -> evaluation -> tests -> point-in-time validation/backtest -> PR -> human approval`.

Phase 7-A owns **evaluation only**. It must turn one existing proposal-only
calibration result and its frozen evidence into an immutable, deterministic,
schema-covered evaluation dossier that can later be reviewed by a human without
trusting filenames, CLI claims or unbound score summaries.

This package does **not** create, edit, activate or approve a rule profile.

## 2. Existing contracts to reuse, not replace

Build on the existing Phase 5 boundaries instead of inventing a second
calibration engine:

- `CandidateProfileProposal`;
- `CalibrationExperiment`;
- `CalibrationHoldoutResult`;
- `CalibrationSearchSpace`;
- `ChronologicalSplit`;
- `CalibrationRunner` / the canonical built-in scorer;
- `BacktestDatasetManifest` and its frozen source identity;
- canonical JSON/hash helpers already used by persisted backtest contracts.

The accepted input proposal for 7-A must be `PROPOSAL_ONLY` and
`automatic_application_allowed == false`. A proposal already marked
`HUMAN_APPROVED` or `REJECTED` is not an admissible 7-A input because this
phase does not yet own an approval-provenance contract.

## 3. New persisted contract

Add a versioned contract, suggested name
`ControlledEvolutionEvaluationV1` with persisted contract id
`controlled_evolution_evaluation_v1`, plus a checked-in JSON Schema and schema
drift tests.

The contract must bind, at minimum:

- deterministic `evaluation_id`;
- base `profile_id` and exact `base_profile_sha256`;
- frozen dataset/manifest identity and content hash where the existing manifest
  contract exposes one;
- `experiment_id` and the experiment's deterministic content identity;
- `proposal_id` plus a SHA-256 over the canonical serialized proposal payload
  (the current proposal contract itself has no content-hash field);
- `candidate_profile_id`;
- the exact `parameter_overrides` being evaluated;
- separate holdout-result content identity;
- machine-readable integrity/evidence checks with stable check names and explicit
  PASS/BLOCKED state plus non-secret detail;
- a top-level admission state such as
  `READY_FOR_HUMAN_REVIEW` or `BLOCKED`;
- `requires_human_approval = true`;
- `automatic_application_allowed = false`;
- deterministic `content_sha256`.

The evaluation dossier may report existing train/validation/holdout/stability
metrics as evidence. **Do not invent an economic pass threshold or decide that a
candidate is a better investment rule.** 7-A's machine decision is only whether
the evidence chain is internally valid and complete enough to enter a later
human-review package.

## 4. Required admission checks

The evaluator must fail closed / emit `BLOCKED` when any required invariant is
false. Required checks include at least:

1. the base profile bytes resolved for evaluation hash exactly to
   `base_profile_sha256`;
2. experiment, proposal and search-space base-profile ids/hashes agree;
3. the supplied frozen manifest identity agrees with
   `CalibrationExperiment.manifest_id`;
4. the proposal embedded in the experiment is the proposal being evaluated;
5. the selected trial exists and its candidate id/parameters agree with the
   proposal;
6. search trials contain no holdout observations/scores;
7. chronological train/validation/holdout ranges remain disjoint and ordered;
8. the proposal is `PROPOSAL_ONLY` and cannot authorize automatic application;
9. a separate `CalibrationHoldoutResult` belongs to the same experiment and
   proposal and covers exactly the experiment's holdout date range;
10. using the **canonical built-in calibration scorer**, frozen observations and
    the recorded search-space/split reproduces the admitted experiment/proposal
    deterministically and recomputing holdout reproduces the supplied holdout
    result;
11. proposal/experiment/holdout canonical hashes are stable across repeated runs;
12. evaluation does not modify `rules/strict-v1.yaml`, any other rule profile,
    the frozen manifest, experiment, proposal or holdout artifacts.

The reproduction check deliberately defines the 7-A admissible scoring path.
Library-created experiments that used an unrecorded custom scorer cannot be
claimed reproducible by guessing; they must be blocked with a precise reason.

## 5. Offline CLI boundary

Add a thin non-network command. Suggested shape:

```bash
tve evolution evaluate \
  --manifest <backtest-dataset-manifest.json> \
  --experiment <calibration-experiment.json> \
  --holdout <calibration-holdout-result.json> \
  --observations <frozen-calibration-observations.json> \
  --base-profile <rules/strict-v1.yaml> \
  --output <controlled-evolution-evaluation.json>
```

Exact spelling may follow the existing CLI organization, but the semantics are
mandatory:

- network is never enabled or silently attempted;
- no provider, model, transport, Dashboard mutation or GitHub client is created;
- no rule/profile file is written;
- no PR is opened;
- no approval state is written;
- repeated execution from byte-identical inputs produces byte-identical
  structured output where timestamps are not part of the contract; preferably
  do not introduce wall-clock fields at all.

## 6. Adversarial and regression tests

Add focused tests covering at least:

- valid canonical proposal -> `READY_FOR_HUMAN_REVIEW`;
- base-profile byte/hash mismatch;
- manifest substitution;
- experiment/proposal substitution with the same candidate id;
- selected-trial parameter mismatch;
- search trial containing holdout data;
- overlapping or reordered chronological split;
- `HUMAN_APPROVED` / `REJECTED` proposal input;
- `automatic_application_allowed=true` rejection through the existing model;
- holdout from another experiment;
- holdout for another proposal;
- holdout date-range mismatch;
- frozen-observation substitution;
- non-canonical/custom-scorer experiment that cannot reproduce under the
  canonical scorer;
- deterministic rerun / content hash equality;
- `strict-v1` byte identity before and after evaluation;
- no network/model/provider construction in the focused command path;
- checked-in schema parity.

Where the new test expresses a defect/gap that exists on the pre-7-A main
baseline, record the fail-on-main result before implementing the fix. Do not
force meaningless fail-on-main claims for tests that only exercise a brand-new
contract.

## 7. Required automatic verification

Before closure, run and record exact results for the focused 7-A suite and the
complete repository gate. At minimum the implementation must automatically run
the current `.github/workflows/ci.yml` equivalents:

```bash
python -m pip install ".[api,dev]"
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
pnpm --dir apps/dashboard install --frozen-lockfile
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
export CLOUDFLARE_API_TOKEN=ci-client-bundle-api-token-sentinel
export SURFACE_API_ACCESS_CLIENT_ID=ci-client-bundle-origin-id-sentinel
export SURFACE_API_ACCESS_CLIENT_SECRET=ci-client-bundle-origin-secret-sentinel
export TVE_DASHBOARD_ACCESS_CLIENT_ID=ci-client-bundle-dashboard-id-sentinel
export TVE_DASHBOARD_ACCESS_CLIENT_SECRET=ci-client-bundle-dashboard-secret-sentinel
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
```

If repository scripts/package names have changed by implementation time, use
the then-current CI workflow's exact equivalent command and record the
substitution explicitly.

After push, query GitHub Actions automatically. Phase 7-A may be marked
`CLOSED` only when a required run is `success` and its `head_sha` exactly
matches the implementation commit. Record focused test count, full Python
pass/skip count, Dashboard test count, exact SHA, run id and conclusion.

## 8. Manual-intervention policy

No manual owner action is planned or required for Phase 7-A.

If an unexpected authority/environment limit genuinely prevents an automatic
step, do not turn that into a vague evidence gap. Record:

1. exact command/action attempted;
2. exact blocker/authority boundary;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Do not ask the owner to approve a candidate rule merely to close 7-A.

## 9. Stop boundary

Stop after the immutable evaluation/admission dossier is implemented, tested,
schema-covered and closed on exact-head CI.

Do not:

- materialize or write `strict-v2` or another candidate rule profile;
- modify `strict-v1`;
- open, update, approve or merge a profile PR;
- add automatic approval/application;
- add performance thresholds whose policy has not been explicitly selected;
- expand providers/sources or Bridge/FQGate;
- add notification vendors;
- add brokerage/trading/funds mutation;
- mix Windows-host bootstrap work into this package.

A later separately selected Phase 7 package may define candidate-profile
materialization and the explicit human-approval/PR boundary after 7-A is closed.
