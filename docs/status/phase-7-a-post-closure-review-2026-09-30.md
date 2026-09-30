# Phase 7-A post-closure review / Phase 7-A-R1 selection — 2026-09-30

Status: **7-A ACCEPTED AT ITS ORIGINAL BOUNDARY; R1 REQUIRED BEFORE 7-B**

Reviewed repository head: `32f77c57a58f1b350d5871165958bd0de443bd4c`

Reviewed Phase 7-A implementation:
`04984bc764441a8d258b4c8c71fe31fec122275f`

Canonical Phase 7-A closure:
`docs/status/phase-7-a-2026-09-30.md`

Independent CI:
- implementation run `36658008383`: `success`, `head_sha=04984bc764441a8d258b4c8c71fe31fec122275f`;
- closure-doc run `36658382916`: `success`, `head_sha=32f77c57a58f1b350d5871165958bd0de443bd4c`.

Selected corrective goal:
`docs/goals/phase-7-a-r1-frozen-evidence-binding-hardening.md`

Coding-agent handoff:
`docs/status/phase-7-a-r1-next-coding-agent-goal.md`

## 1. What remains accepted

Phase 7-A is not a documentation-only closure. The implementation introduced a real offline
`ControlledEvolutionEvaluationV1` boundary, checked-in schema, thirteen explicit
admission checks, canonical calibration/holdout replay, a non-network CLI and focused
adversarial tests. The implementation exact-head CI is green and the repository-wide
automatic gate passed.

The review therefore preserves the historical 7-A closure. It does not rewrite the evidence
record and does not claim that the original implementation was absent.

## 2. Blocking finding F1 — same-ID manifest substitution is not bound to the calibration run

The current `MANIFEST_IDENTITY` predicate in
`src/turtle_value_engine/evolution/evaluate.py` proves only:

1. `manifest.dataset_id == experiment.manifest_id`; and
2. the supplied manifest's declared `content_sha256` is internally self-consistent.

`CalibrationExperiment` persists `manifest_id` but not the exact manifest content hash that
was present when calibration ran. Consequently a second valid
`BacktestDatasetManifest` can retain the same `dataset_id`, change other manifest content,
recompute its own valid `content_sha256`, and still satisfy the current
`MANIFEST_IDENTITY` check. The dossier then binds the substituted manifest rather than
proving that it is the manifest used by the calibration run.

The existing focused test changes the dataset id; it does not exercise this same-id/content-
substitution case.

## 3. Blocking finding F2 — non-scoring frozen-observation provenance can be substituted

The evaluator computes `observations_content_sha256` from whichever observation rows are
supplied at evaluation time, but the calibration experiment does not persist an expected
observation-set content identity.

Canonical replay compares derived calibration/holdout outputs. That catches many value
changes, but it is not an exact evidence-identity proof. In particular,
`CalibrationRunner` does not use `CalibrationObservation.source_hash` in scoring.
Changing only `source_hash` while preserving observation ids, dates, feature values,
eligibility and returns can therefore leave the reproduced experiment and holdout byte-
equivalent while the supplied frozen-observation provenance is different. The evaluator can
then still emit `READY_FOR_HUMAN_REVIEW`.

This is a direct mismatch with the intended "frozen evidence chain" boundary. Reproduction
is necessary, but it is not sufficient to prove exact input identity.

## 4. Blocking finding F3 — a truncated READY dossier can validate as a persisted contract

`ControlledEvolutionEvaluationV1.validate_evaluation()` currently verifies unique check
names, the relationship between BLOCKED checks and `admission_state`, and
`content_sha256`. It does not require the exact canonical required-check set.

Therefore a hand-built dossier containing only a subset of PASS checks can recompute a valid
`content_sha256` and still model/schema-validate as `READY_FOR_HUMAN_REVIEW`. The model
also does not recompute `evaluation_id` from its bound identities.

The current evaluator always emits all thirteen checks, so this does not invalidate the
implementation's own happy path. It is nevertheless a blocker before any later Phase 7
consumer is allowed to trust a persisted dossier as an admission artifact.

## 5. Selected correction — Phase 7-A-R1

R1 must close the identity gap before candidate-profile materialization, PR packaging or
human approval is implemented.

The selected design direction is additive:

- create a versioned immutable calibration evidence-binding artifact at the calibration/freeze
  boundary, where the exact manifest and exact observations are simultaneously available;
- bind at minimum exact manifest content hash, experiment content hash, observation-set
  content hash/count and base-profile identity/hash, with deterministic id/content hash;
- persist/emit that binding from the calibration path rather than synthesizing it from the
  evaluator's untrusted inputs;
- require the evaluation path to prove the supplied manifest, experiment and observations
  against that prior binding before `READY_FOR_HUMAN_REVIEW` is possible;
- harden `ControlledEvolutionEvaluationV1` so a READY dossier is valid only with the complete
  canonical check set and a deterministic `evaluation_id`.

Do not retroactively mutate `CandidateProfileProposal` or `strict-v1`. Prefer an additive
binding contract over silently redefining an existing persisted contract.

## 6. Mandatory fail-on-current-main proofs for R1

Before fixing the code, the coding agent must add deterministic tests against the reviewed
pre-R1 main that demonstrate at least:

1. same `dataset_id`, changed valid manifest content -> current evaluator can still report
   READY;
2. observation `source_hash` substitution with scoring inputs unchanged -> current evaluator
   can still report READY;
3. a manually constructed READY dossier missing one or more canonical checks can still
   model/schema-validate when its content hash is recomputed;
4. a dossier with a non-canonical `evaluation_id` can still validate when its content hash is
   recomputed.

Record the exact baseline SHA and test selection/output. These are real regression proofs,
not new-surface-absent demonstrations.

## 7. Automatic closure policy

R1 has no planned manual owner step. The coding agent must run the focused R1 regressions,
the full current repository CI-equivalent gate, push the exact implementation SHA, query
GitHub Actions automatically, and close only on a successful required run whose
`head_sha` exactly equals that implementation SHA.

If an unexpected authority/environment limit blocks one automatic step, record the exact
attempted command, exact blocker, exact human action, exact data/secret boundary, exact
resume command, machine-checkable success criterion and exact remaining unverified scope.
Continue every other automatic check that remains possible.

## 8. Stop boundary

Do not start Phase 7-B, candidate-profile materialization, `strict-v2`, PR creation/merge,
human approval recording, provider/Bridge/FQGate expansion, notification-vendor work,
Windows bootstrap, brokerage/trading or any `strict-v1` semantic change until R1 is closed.
