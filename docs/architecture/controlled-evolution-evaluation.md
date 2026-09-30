# Controlled Evolution Evaluation Architecture

Phase 7-A implements the first executable stage of the roadmap's controlled
evolution chain — `proposal -> evaluation -> tests -> point-in-time
validation/backtest -> PR -> human approval` — and owns **evaluation only**.

The boundary turns one existing `PROPOSAL_ONLY` calibration result plus its
frozen evidence into an immutable, deterministic, schema-covered
evaluation/admission dossier. It creates no rule profile, edits no profile,
opens no pull request and records no approval.

## Runtime boundary

```text
frozen BacktestDatasetManifest
frozen CalibrationExperiment (embedded proposal + selected trial)
frozen CalibrationHoldoutResult
frozen CalibrationObservation rows
raw base-profile bytes (e.g. rules/strict-v1.yaml)
        -> evaluate_controlled_evolution(...)   # pure, offline, non-mutating
        -> ControlledEvolutionEvaluationV1
```

The library function is pure: it receives already-validated typed models and
byte inputs, performs no I/O of its own, constructs no provider, model,
transport or network client, and never writes to the supplied artifacts. The
CLI wrapper (`tve evolution evaluate`) reads the files, refuses any
`--output` path that would overwrite a supplied input, writes the dossier
atomically and prints it. Repeated execution from byte-identical inputs
produces a byte-identical dossier; the contract carries no wall-clock fields.

## The dossier contract

`ControlledEvolutionEvaluationV1` (`controlled_evolution_evaluation_v1`,
schema `schemas/controlled-evolution-evaluation.schema.json`) binds:

- a deterministic `evaluation_id` derived from every bound identity below;
- base `profile_id` and exact `base_profile_sha256` recomputed from the
  supplied profile bytes;
- frozen dataset identity (`dataset_id`, `manifest_content_sha256`);
- `experiment_id` and the experiment's content hash;
- `proposal_id` plus a SHA-256 over the canonical serialized proposal payload
  (the proposal contract itself carries no content-hash field and is not
  retroactively mutated);
- `candidate_profile_id` and the exact `parameter_overrides`;
- separate holdout-result and frozen-observation content hashes;
- machine-readable checks with stable names and explicit `PASS`/`BLOCKED`
  states plus non-secret detail;
- `admission_state` — only `READY_FOR_HUMAN_REVIEW` or `BLOCKED`;
- `requires_human_approval = true` and `automatic_application_allowed = false`;
- a deterministic `content_sha256`.

The dossier reports evidence admission only. It contains no economic
performance threshold, no candidate ranking and no investment decision.

## Admission checks

Every check is recomputed independently from the supplied evidence:

| Check | Meaning |
| --- | --- |
| `BASE_PROFILE_BYTES_HASH` | supplied profile bytes hash to `base_profile_sha256` |
| `BASE_PROFILE_IDENTITY_AGREEMENT` | experiment, proposal and search space agree on the base profile |
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
Structurally unusable inputs (for example an experiment without a selected
proposal) fail closed before any dossier is produced.

## Reproducibility policy

The reproduction check re-runs `CalibrationRunner` with the repository's
canonical built-in scorer over the frozen observations and the recorded
search space/split, then compares everything the canonical path determines
(all experiment fields except the recomputed `content_sha256` and the free
text `rationale`). Because the experiment contract does not record a custom
scorer, an experiment produced with an unrecorded custom scorer cannot be
proven reproducible: it is `BLOCKED` rather than guessed compatible.

## Verification posture

The focused suite covers substitution of profile, manifest, proposal,
experiment, holdout and observations; selected-trial mismatch; holdout
leakage; corrupt chronology; non-`PROPOSAL_ONLY` input; custom-scorer
non-reproducibility; deterministic rerun/hash equality; schema drift parity;
socket-guarded no-network execution; and byte identity of `strict-v1.yaml`
and every supplied artifact across evaluation.
