# Phase 7-A-R2 post-closure review — materialization readiness

Status: **R2 CLOSURE PRESERVED / PHASE 7-B1 SELECTED BEFORE PROFILE MATERIALIZATION**
Date: 2026-09-30

Reviewed implementation:
`3ac7684e6be483cc1a411478826797696c7951cf`

R2 closure:
`docs/status/phase-7-a-r2-2026-09-30.md`

Current reviewed `main`:
`adfb843b3f1c1c6f0aa1ed29d2d7c86aa899bb42`

Selected follow-up:
`docs/goals/phase-7-b1-materializable-candidate-profile-foundation.md`

Coding-agent handoff:
`docs/status/phase-7-b1-next-coding-agent-goal.md`

## 1. Verdict

Phase 7-A-R2 is accepted at the boundary it actually implements. The authoritative
experiment-keyed freeze slot, workspace resolution path, exact-sequence schema
hardening, non-destructive CLI behavior and exact-head CI closure are coherent.
No implementation defect found in this review requires reopening R2.

R2 is nevertheless **not the point at which a `CandidateProfileProposal` can be
turned directly into `strict-v2`**. The next boundary is semantic rather than
provenance-related: the current calibration proposal does not define how its
`parameter_overrides` map to concrete `RuleProfile` fields, and the default
calibration scorer does not execute a candidate `RuleProfile` through the
deterministic investment engine.

Therefore the next package is Phase 7-B1, not an immediate profile PR/approval
workflow.

## 2. Evidence independently re-checked

The implementation commit is
`3ac7684e6be483cc1a411478826797696c7951cf`. GitHub Actions run
`36679050588` is `success` and its `head_sha` is exactly the implementation
SHA. The CI job executed the current repository gate, including Ruff, config
validation, Python tests, systemd verification, generated contract checks,
Dashboard lint/typecheck/tests/build/security scan, Wrangler strict dry-run and
the cross-stack smoke.

The CI log independently records:

- `6966 passed, 2 skipped` for Python;
- `55 passed` for Dashboard tests;
- the committed R2 regression files executing in the full suite.

The R2 workspace implementation was also inspected directly:

- `CalibrationFreezeRecordV1` recomputes its deterministic freeze/content
  identities;
- `BacktestWorkspace` stores freeze records by `experiment_id`, rejects
  conflicting existing bytes and publishes new artifacts through an atomic
  create-only link boundary;
- `commit_calibration_freeze()` commits prerequisites first and the anchor last;
- `resolve_anchored_calibration_evidence()` fail-closes across missing/corrupt/
  foreign anchors and binding/experiment mismatches;
- `tve evolution evaluate --calibration-workspace` resolves the authoritative
  chain before evaluation, while sidecar-only binding input cannot become READY;
- the pure evaluator adds the three `FREEZE_ANCHOR_*` checks and includes the
  anchor identity in the deterministic dossier identity;
- the checked-in Draft 2020-12 schema derives an exact `prefixItems` sequence
  from the canonical check list.

## 3. Boundary A — a persisted READY dossier is evidence, not an authorization token

`evaluate_controlled_evolution()` is intentionally pure. A library caller can
construct internally valid typed inputs and call that pure function without
performing workspace I/O. R2 explicitly places *authority* in the workspace
resolution boundary rather than in the freeze-record bytes by themselves.

That design is acceptable for R2, but it has a direct consequence for the next
phase: **B1 must never accept a previously persisted
`READY_FOR_HUMAN_REVIEW` JSON dossier as sufficient authorization to materialize
a candidate profile.**

Before any materialization output is produced, B1 must resolve the authoritative
calibration workspace and re-run/revalidate the R2 admission chain against the
exact frozen manifest, experiment, holdout, observations and base-profile
bytes. A dossier may be retained as an audit artifact, not as a bearer
credential.

## 4. Boundary B — current proposal parameters have no rule-profile materialization semantics

The current `CalibrationSearchSpace` stores:

`parameters: dict[str, list[float | int | str | bool]]`

with no target `RuleProfile` path or versioned parameter-semantics contract.
`CandidateProfileProposal.parameter_overrides` simply copies the selected trial
parameter dictionary.

The built-in scorer interprets parameter *names* only as generic feature filters:

- `min_<feature>` -> keep observations whose free-form `feature_values[feature]`
  is greater than or equal to the candidate value;
- `max_<feature>` -> analogous upper bound;
- `equals_<feature>` -> equality filter.

The repository's canonical fixtures use `min_quality`; `rules/strict-v1.yaml`
contains no field named `min_quality`, and `RuleProfile` is a nested typed
configuration whose loader rejects unknown fields.

Consequently there is no deterministic, auditable answer today to the question
"which exact YAML leaf should `min_quality=4.0` modify?". Inventing that
mapping during B1 materialization would be a post-hoc semantic reinterpretation
of an already-scored experiment.

Existing R2-era proposals without a calibration-time materialization contract
must therefore remain readable/evaluable but **non-materializable**.

## 5. Boundary C — generic feature filtering is not candidate-profile replay

The default calibration scorer documents that it scores deterministic feature
filters "without interpreting strict-v1". It operates on
`CalibrationObservation.feature_values`, whose keys are free-form. The normal
calibration path therefore does not prove that applying an override to a real
`RuleProfile` and rerunning the deterministic engine would reproduce the same
candidate behavior.

This matters because the Phase 5 design already states that a proposed new
profile must pass frozen point-in-time evaluation, robustness/sensitivity
review and tests before PR/human approval. B1 must bridge this semantic gap
instead of treating the generic feature-filter score as proof of candidate rule
behavior.

The repository already carries frozen historical decision artifacts and may
carry their `normalized_input`. B1 should use canonical deterministic replay
under the projected candidate profile where the necessary frozen inputs exist.
If an optimized parameter adapter is introduced instead, it must be bounded to
explicitly registered parameters and automatically proven equivalent to the
canonical engine path for the supported semantics. Missing replay inputs must
fail closed; do not silently fall back to generic feature filtering.

## 6. Why this is Phase 7-B1 rather than Phase 7-A-R3

R2's contract is provenance/admission integrity, and that contract is satisfied.
The new finding is the first missing capability of the *materialization* phase:
a proposal has to acquire explicit rule-profile semantics before any profile
can be projected. Reopening 7-A would blur the boundary between evidence
admission and candidate generation.

Select **Phase 7-B1 — Materializable Candidate Profile Semantics and Offline
Projection Foundation**. Keep the eventual remote PR/human-approval boundary
for B2 after B1 proves that the candidate bytes themselves are deterministic,
semantically bound and replayable.

## 7. Required B1 invariants

B1 must, at minimum:

1. introduce one versioned materializable-parameter contract/registry (exact
   class name may differ) that binds every supported candidate parameter to
   concrete `RuleProfile` semantics, including target scalar leaf/type and the
   scorer/replay meaning;
2. freeze those semantics **before calibration selection** and include their
   identity/content in the experiment/freeze authority. A target mapping added
   after seeing calibration results is never admissible;
3. classify legacy/unbound R2 proposals as non-materializable rather than infer
   a mapping from names;
4. load the exact base-profile bytes, verify the recorded SHA-256, validate the
   typed `RuleProfile`, and apply only frozen/registered overrides to a copy;
5. produce deterministic candidate-profile bytes plus an immutable
   materialization record binding the authoritative R2 evidence, base-profile
   identity, parameter-semantics identity, exact before/after diff and candidate
   content hash;
6. keep candidate output separate from `rules/strict-v1.yaml` and do not assign
   the human version name `strict-v2` automatically;
7. re-resolve the authoritative workspace and re-run/revalidate R2 admission
   immediately before materialization; dossier-only input is insufficient;
8. prove candidate semantics through canonical frozen PIT replay (or a narrowly
   registered adapter with machine-proven equivalence), preserving holdout
   isolation and fail-closed behavior when required frozen inputs are absent;
9. preserve `requires_human_approval=true` and
   `automatic_application_allowed=false`; materialization is not approval;
10. remain fully offline/no-network and non-destructive.

## 8. Verification policy

B1 should be closed primarily by automation. No manual owner action is planned.

Do not manufacture a fake "fail-on-R2" regression whose only failure is that
B1 symbols do not exist. The baseline evidence for this new capability gap is
structural: no profile materializer consumes `parameter_overrides`, the default
scorer explicitly does not interpret `strict-v1`, and the canonical R2 fixtures
use an unbound `min_quality` parameter.

After implementation, focused tests must prove at least:

- an R2 legacy `min_quality` proposal fails closed as non-materializable;
- a supported registered real `RuleProfile` scalar can be calibrated/projected
  end-to-end with its semantics frozen before selection;
- unknown/unbound parameters, type mismatches, illegal target paths and
  post-hoc mapping substitutions fail closed with zero candidate output;
- wrong base-profile bytes/hash fail closed;
- candidate output changes only the exact registered rule leaves plus
  deterministic candidate metadata; no extra semantic diff is allowed;
- repeated identical inputs produce byte-identical candidate and
  materialization identities;
- a dossier file alone cannot authorize materialization; the authoritative
  workspace path is required and revalidation is performed;
- candidate-profile PIT replay is deterministic and remains isolated from the
  holdout search boundary;
- missing required frozen replay input is an explicit blocker, not a fallback;
- all B1 paths construct no network socket;
- `rules/strict-v1.yaml` remains byte-identical;
- checked-in schemas have drift-parity tests;
- non-destructive output/path collision behavior is proven;
- the complete current CI-equivalent repository gate is green.

After push, query GitHub Actions automatically. Close B1 only when the required
run is `success` and its `head_sha` exactly equals the implementation commit.

If a genuinely external authority or environment limitation makes one check
impossible, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue all other automatic checks. Do not replace this with a vague statement
that evidence is incomplete.

## 9. Stop boundary

Stop after offline candidate semantics/projection and profile-aware replay are
implemented and exact-head CI closure is recorded.

Do **not** create or modify `rules/strict-v2.yaml`, write candidate bytes into
the active `rules/` directory, open/merge a rule-profile PR, record human
approval/rejection, mutate `strict-v1`, add provider/Bridge/FQGate scope, add
notification vendors, Windows bootstrap, brokerage/trading, or any automatic
rule application. Those remain B2 or separately selected future work.
