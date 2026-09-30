# Controlled Evolution Evaluation Architecture

Phase 7-A implements the first executable stage of the roadmap's controlled
evolution chain — `proposal -> evaluation -> tests -> point-in-time
validation/backtest -> PR -> human approval` — and owns **evaluation only**.

The boundary turns one existing `PROPOSAL_ONLY` calibration result plus its
frozen evidence into an immutable, deterministic, schema-covered
evaluation/admission dossier.  It creates no rule profile, edits no profile,
opens no pull request and records no approval.

Phase 7-A-R1 adds the frozen-evidence binding boundary: admission is possible
only against a prior calibration-time evidence binding, and the persisted
dossier contract itself enforces the canonical check set and a deterministic
`evaluation_id`.

## Runtime boundary

```text
calibration/freeze boundary (Phase 5 calibration path)
frozen BacktestDatasetManifest + frozen CalibrationObservation rows
+ resulting CalibrationExperiment (embedded PROPOSAL_ONLY proposal)
        -> build_calibration_evidence_binding(...)          # pure, offline
        -> CalibrationEvidenceBindingV1                     # persisted prior artifact

frozen BacktestDatasetManifest
frozen CalibrationExperiment (embedded proposal + selected trial)
frozen CalibrationHoldoutResult
frozen CalibrationObservation rows
prior CalibrationEvidenceBindingV1
raw base-profile bytes (e.g. rules/strict-v1.yaml)
        -> evaluate_controlled_evolution(...)   # pure, offline, non-mutating
        -> ControlledEvolutionEvaluationV1
```

Both library functions are pure: they receive already-validated typed models
and byte inputs, perform no I/O of their own, construct no provider, model,
transport or network client, and never write to the supplied artifacts.  The
binding is produced only at the calibration/freeze boundary, where the exact
manifest, the exact observation rows and the resulting experiment are
simultaneously available; the evaluator never synthesizes the expected
evidence identity from its own supplied inputs.

The CLI wrappers are offline.  `tve calibrate --evidence-binding-output`
persists the binding produced by a normal calibration without manual JSON
assembly, `BacktestWorkspace.save_calibration_evidence_binding` persists it
in the immutable backtest artifact store, and `tve evolution evaluate`
requires the prior binding (`--evidence-binding`), refuses any `--output`
path that would overwrite a supplied input, writes the dossier atomically
and prints it.  Repeated execution from byte-identical inputs produces a
byte-identical dossier; neither contract carries wall-clock fields.

## The calibration evidence binding

`CalibrationEvidenceBindingV1` (`calibration_evidence_binding_v1`, schema
`schemas/calibration-evidence-binding.schema.json`) binds, in one immutable
artifact with a deterministic `binding_id` and `content_sha256`:

- `manifest_id` and the exact `manifest_content_sha256`;
- `experiment_id` and the exact `experiment_content_sha256`;
- the exact canonical `observations_content_sha256` and the observation count;
- `base_profile_id` and the exact `base_profile_sha256`;
- the `proposal_id` and the canonical proposal payload SHA-256.

The model recomputes `binding_id` from the bound identities and
`content_sha256` from the persisted payload, so a tampered binding cannot
validate.  `build_calibration_evidence_binding` fail-closes on a manifest
whose identity disagrees with the experiment and on an experiment without a
selected proposal.  The canonical observation-set and proposal-payload hashes
are shared with the evaluator (`canonical_observations_sha256`,
`canonical_proposal_payload_sha256`), so a substitution that changes any
row content — including non-scoring provenance such as
`CalibrationObservation.source_hash` — changes the observation identity even
when every derived calibration and holdout score stays identical.

## The dossier contract

`ControlledEvolutionEvaluationV1` (`controlled_evolution_evaluation_v1`,
schema `schemas/controlled-evolution-evaluation.schema.json`) binds:

- a deterministic `evaluation_id` derived from every bound identity below,
  including the prior evidence binding identity (and `null` components when
  no binding was supplied — a dossier that can never be READY);
- base `profile_id` and exact `base_profile_sha256` recomputed from the
  supplied profile bytes;
- frozen dataset identity (`dataset_id`, `manifest_content_sha256`);
- `experiment_id` and the experiment's content hash;
- `proposal_id` plus a SHA-256 over the canonical serialized proposal payload
  (the proposal contract itself carries no content-hash field and is not
  retroactively mutated);
- `candidate_profile_id` and the exact `parameter_overrides`;
- separate holdout-result and frozen-observation content hashes;
- `evidence_binding_id` / `evidence_binding_sha256` — the identity of the
  prior binding the evaluation ran against (both required for
  `READY_FOR_HUMAN_REVIEW`);
- machine-readable checks with stable names and explicit `PASS`/`BLOCKED`
  states plus non-secret detail;
- `admission_state` — only `READY_FOR_HUMAN_REVIEW` or `BLOCKED`;
- `requires_human_approval = true` and `automatic_application_allowed = false`;
- a deterministic `content_sha256`.

The persisted contract itself enforces semantic integrity for its version:
the checks must be exactly the canonical required-check set
(`REQUIRED_EVALUATION_CHECK_NAMES`, nineteen checks) in canonical order — no
omission, duplicate, unknown substitution or reordering — expressed both in
the model validator and in the checked-in schema (per-check name enum plus
exact item count); `evaluation_id` is recomputed from the bound identities
rather than accepted as arbitrary text; `content_sha256` is recomputed over
the final persisted payload.

The dossier reports evidence admission only.  It contains no economic
performance threshold, no candidate ranking and no investment decision.

## Admission checks

Every check is recomputed independently from the supplied evidence.  The
evaluator emits exactly this canonical sequence:

| Check | Meaning |
| --- | --- |
| `BASE_PROFILE_BYTES_HASH` | supplied profile bytes hash to `base_profile_sha256` |
| `BASE_PROFILE_IDENTITY_AGREEMENT` | experiment, proposal and search space agree on the base profile |
| `EVIDENCE_BINDING_PRESENT` | a prior calibration evidence binding is supplied |
| `EVIDENCE_BINDING_MANIFEST_IDENTITY` | supplied manifest id/content hash equal the binding |
| `EVIDENCE_BINDING_EXPERIMENT_IDENTITY` | supplied experiment id/content hash equal the binding |
| `EVIDENCE_BINDING_OBSERVATIONS_IDENTITY` | supplied observation-set hash and count equal the binding |
| `EVIDENCE_BINDING_BASE_PROFILE_IDENTITY` | supplied base-profile id/hash equal the binding |
| `EVIDENCE_BINDING_PROPOSAL_IDENTITY` | supplied proposal id/payload hash equal the binding |
| `MANIFEST_IDENTITY` | manifest identity and content hash match the experiment |
| `EXPERIMENT_CONTENT_HASH` | experiment content hash recomputes exactly |
| `PROPOSAL_EMBEDDING` | the proposal is the deterministic proposal of this experiment's selected trial |
| `SELECTED_TRIAL_AGREEMENT` | selected trial, candidate id and parameter overrides agree |
| `SEARCH_HOLDOUT_ISOLATION` | no search trial touches holdout rows or scores |
| `CHRONOLOGY_DISJOINT_ORDERED` | train/validation/holdout ranges stay ordered and disjoint |
| `PROPOSAL_STATUS_PROPOSAL_ONLY` | `PROPOSAL_ONLY` without automatic application |
| `HOLDOUT_BINDING` | holdout belongs to this experiment, proposal and date range |
| `HOLDOUT_CONTENT_HASH` | holdout content hash recomputes exactly |
| `CANONICAL_REPRODUCTION` | the canonical built-in scorer reproduces the experiment/proposal |
| `HOLDOUT_REPRODUCTION` | canonical holdout recomputation reproduces the artifact |

All checks `PASS` yields `READY_FOR_HUMAN_REVIEW`; any `BLOCKED` check yields
`BLOCKED` with the failing names and detail recorded in the dossier itself.
A missing evidence binding fail-closes: the dossier is `BLOCKED` (all six
binding checks), never `READY_FOR_HUMAN_REVIEW`.  Structurally unusable
inputs (for example an experiment without a selected proposal) fail closed
before any dossier is produced.

A same-`dataset_id` manifest with different valid content is `BLOCKED` on
`EVIDENCE_BINDING_MANIFEST_IDENTITY`.  A `source_hash`-only observation
substitution is `BLOCKED` on `EVIDENCE_BINDING_OBSERVATIONS_IDENTITY` even
when every derived calibration and holdout result is unchanged.

## Reproducibility policy

The reproduction check re-runs `CalibrationRunner` with the repository's
canonical built-in scorer over the frozen observations and the recorded
search space/split, then compares everything the canonical path determines
(all experiment fields except the recomputed `content_sha256` and the free
text `rationale`).  Because the experiment contract does not record a custom
scorer, an experiment produced with an unrecorded custom scorer cannot be
proven reproducible: it is `BLOCKED` rather than guessed compatible.
Reproduction is necessary but not sufficient: exact input identity is proven
separately against the calibration-time evidence binding.

## Verification posture

The focused suites cover the four documented pre-R1 unsafe behaviors
(same-id manifest substitution, `source_hash`-only observation substitution,
truncated READY dossier, wrong `evaluation_id` — each proven failing on the
pristine pre-R1 baseline before implementation), substitution of profile,
manifest, proposal, experiment, holdout, observations, binding, observation
count, base-profile and proposal identities inside the binding; selected-trial
mismatch; holdout leakage; corrupt chronology; non-`PROPOSAL_ONLY` input;
custom-scorer non-reproducibility; deterministic rerun/hash equality; schema
drift parity for both contracts; socket-guarded no-network execution; and
byte identity of `strict-v1.yaml` and every supplied artifact across
evaluation.
