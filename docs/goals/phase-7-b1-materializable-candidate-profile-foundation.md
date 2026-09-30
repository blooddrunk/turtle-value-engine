# Phase 7-B1 — Materializable Candidate Profile Semantics and Offline Projection Foundation

Status: **CLOSED / AUTOMATIC CI CLOSURE** — implementation
`ad4f3580894d65e2c15b40723f9faf6583710d11`, Actions run `36685558492`
(`success`, exact `head_sha`); closure record
`docs/status/phase-7-b1-2026-09-30.md`
Date: 2026-09-30
Post-closure review: `docs/status/phase-7-b1-post-closure-review-2026-09-30.md` preserves this closure and selects Phase 7-B1-R1 publication/path hardening before B2.
Selected after: Phase 7-A-R2 post-closure review

Selection audit:
`docs/status/phase-7-a-r2-post-closure-review-2026-09-30.md`

Pre-B1 reviewed baseline:
`adfb843b3f1c1c6f0aa1ed29d2d7c86aa899bb42`

Coding-agent handoff:
`docs/status/phase-7-b1-next-coding-agent-goal.md` (consumed by this
implementation)

Architecture:
`docs/architecture/candidate-profile-materialization.md`

## 1. Objective

Create the first safe bridge from an admitted `CandidateProfileProposal` to a
deterministic **candidate-only** `RuleProfile` artifact without changing or
installing any live rule profile.

B1 must solve two separate problems before profile PR/approval work can begin:

1. candidate parameters need explicit, versioned rule-profile semantics frozen
   before calibration selection; and
2. the resulting candidate profile needs deterministic frozen point-in-time
   semantic replay, not merely the existing generic feature-filter score.

B1 ends with an immutable offline candidate/materialization artifact that is
ready for a later B2 review/PR boundary. It does not create `strict-v2`, does
not install a rule file, and does not record approval.

## 2. Source of truth

Read and follow, in order:

1. `AGENTS.md`
2. `docs/status/phase-7-a-r2-post-closure-review-2026-09-30.md`
3. `docs/status/phase-7-a-r2-2026-09-30.md`
4. `docs/architecture/controlled-evolution-evaluation.md`
5. `docs/architecture/backtesting-and-calibration.md`
6. `docs/goals/phase-5-backtesting-calibration.md`
7. `rules/strict-v1.yaml`
8. `src/turtle_value_engine/config/models.py` and `config/loader.py`

Frozen investment semantics remain authoritative. Do not alter a rule simply
to make calibration or holdout performance look better.

## 3. Current gap that B1 must close

`CalibrationSearchSpace.parameters` is currently an untyped mapping from
parameter names to finite candidate values. The built-in calibration scorer
interprets only the `min_`, `max_` and `equals_` name prefixes as filters over
free-form `CalibrationObservation.feature_values`; it explicitly does not
interpret `strict-v1`.

`CandidateProfileProposal.parameter_overrides` therefore identifies the selected
filter values but does **not** tell the system which exact nested `RuleProfile`
field should change. The canonical test proposal `min_quality` has no direct
field of that name in `strict-v1`.

No B1 implementation may infer a materialization path after seeing the winning
candidate. That would make the meaning of the experiment mutable after the
fact.

## 4. Materializable parameter semantics

Add the smallest coherent versioned contract/registry that makes a parameter
materializable. Exact class names are implementation choices, but the following
invariants are mandatory.

### 4.1 Frozen before selection

For every materializable parameter, the calibration input must freeze at least:

- stable parameter key;
- concrete target scalar leaf in `RuleProfile` (or an equivalent canonical
  registry key that resolves uniquely to that leaf);
- scalar value type/range contract;
- calibration/replay operator semantics;
- observation/metric semantic identity needed to prove the candidate effect;
- registry/spec version and deterministic content identity.

This semantics identity must be covered by the calibration experiment identity
and therefore by the R2 experiment-keyed authoritative freeze. An equivalent
design is acceptable only if the freeze record explicitly binds the semantics
artifact id/content hash. A semantics mapping attached only at B1
materialization time is not acceptable.

### 4.2 Legacy compatibility is read-only

Existing v1/R2 search spaces and proposals without materialization semantics
remain valid historical calibration/evaluation artifacts, but they must be
classified as non-materializable. Do not infer a target from a parameter name,
feature name, candidate id, rationale text, or score.

### 4.3 No arbitrary mutation surface

Materialization must not accept a caller-provided arbitrary YAML/JSON path that
is absent from the frozen parameter semantics. It may modify only explicitly
supported scalar rule leaves. Structural replacement, list injection, metadata
rewriting and unknown fields must fail closed.

## 5. Deterministic candidate profile projection

Build a pure or narrowly I/O-wrapped materializer that:

1. reads the exact base-profile bytes and verifies
   `CandidateProfileProposal.base_profile_sha256`;
2. parses them through the existing YAML loader/`RuleProfile` model;
3. verifies the base profile id and every frozen parameter target/type;
4. applies only the selected registered overrides to an in-memory copy;
5. assigns deterministic candidate-only metadata without reusing the human
   release name `strict-v2`;
6. validates the complete resulting `RuleProfile` after mutation;
7. derives canonical candidate bytes/content hash deterministically;
8. emits an immutable materialization record that binds at least:
   - R2 evaluation identity/content hash;
   - freeze-anchor id/content hash;
   - evidence-binding id/content hash;
   - experiment/proposal identities;
   - exact base-profile id/hash;
   - parameter-semantics id/hash/version;
   - exact changed rule paths with before/after values;
   - candidate profile id/content hash;
   - profile-aware replay identity/result;
   - `requires_human_approval=true`;
   - `automatic_application_allowed=false`.

The candidate artifact is review input only. It is never automatically made an
active rule profile.

## 6. Authoritative re-admission before materialization

Do not trust a serialized `ControlledEvolutionEvaluationV1` dossier alone.

The B1 application/CLI boundary must require the authoritative calibration
workspace plus the exact frozen evidence needed by R2, resolve the
`CalibrationFreezeRecordV1`/binding through the workspace loader and
re-run/revalidate the controlled-evolution admission immediately before
candidate generation.

Materialization is allowed only if that fresh evaluation is
`READY_FOR_HUMAN_REVIEW`. A supplied dossier may be compared for identity as
an audit convenience, but it must not be the authority.

## 7. Profile-aware frozen PIT replay

The existing default scorer is a generic feature filter and is not proof that
a real candidate `RuleProfile` produces the same decisions.

B1 must add a canonical candidate semantic verification path. Prefer rerunning
the existing deterministic engine under the projected candidate profile over
the frozen point-in-time normalized inputs already represented by historical
decision artifacts. Preserve the chronological train/validation/holdout
boundary and never use holdout outcomes to choose or alter the candidate.

If a bounded optimized adapter is used for a supported parameter instead of
full engine replay, it must be registered explicitly and have automated
equivalence tests against the canonical engine for that parameter's supported
domain. Generic `feature_values` filtering by itself is not sufficient.

If the required frozen normalized/research input is absent or cannot support
the candidate semantics, classify materialization/replay as blocked. Do not
silently reuse the baseline decision, baseline analysis or generic filter
score.

Keep ordinary B1 execution fully offline. No provider, model, transport,
GitHub or brokerage client belongs in the semantic replay path.

## 8. CLI/application boundary

A thin command such as the following is appropriate (exact spelling may differ
if a clearer repository convention exists):

```text
tve evolution materialize-candidate \
  --calibration-workspace <authoritative-root> \
  --manifest <frozen-manifest> \
  --experiment <frozen-experiment> \
  --holdout <frozen-holdout> \
  --observations <frozen-observations> \
  --base-profile rules/strict-v1.yaml \
  --candidate-output <review-workspace>/candidate.yaml \
  --materialization-output <review-workspace>/materialization.json
```

Required behavior:

- all supplied evidence is validated/re-admitted through the R2 workspace
  authority before projection;
- candidate and materialization outputs are create-only/non-destructive and
  must not overwrite inputs, workspace authority artifacts or existing
  different bytes;
- refuse output under the active `rules/` directory in B1;
- repeated byte-identical output is idempotent;
- blocked inputs produce no partial candidate file;
- no network socket may be created.

## 9. Required automatic verification

### 9.1 Baseline audit

Record the reviewed pre-B1 facts without fabricating a missing-symbol
regression:

- default calibration scorer says it does not interpret `strict-v1`;
- only `min_`/`max_`/`equals_` generic feature filters define built-in parameter
  behavior;
- no current production path materializes `parameter_overrides` into a
  `RuleProfile`;
- current `min_quality` fixture is not a `RuleProfile` field.

### 9.2 Focused B1 tests

At minimum prove:

1. R2 legacy/unbound `min_quality` proposal -> explicit non-materializable
   failure, zero candidate output;
2. one or more real registered `RuleProfile` scalar parameters -> deterministic
   end-to-end calibration/freeze/admission/projection/replay;
3. semantics mapping is frozen before selection and changing it changes the
   experiment/freeze identity or conflicts with the authoritative slot;
4. wrong base-profile bytes/hash/id -> fail closed;
5. unknown parameter, unregistered path, structural target, type mismatch,
   out-of-contract value -> fail closed;
6. candidate diff contains exactly the registered rule leaves and deterministic
   candidate metadata, nothing else;
7. identical rerun -> byte-identical candidate/materialization identity;
8. fake/sidecar-only anchor or dossier-only materialization attempt -> fail
   closed;
9. canonical candidate PIT replay is deterministic and chronological/holdout
   isolation remains intact;
10. missing frozen replay input -> explicit blocker with no fallback;
11. candidate/output path collisions and attempts to write under `rules/` ->
    fail closed before mutation;
12. schema drift parity for every new persisted contract;
13. socket-guarded B1 paths -> no network socket;
14. `rules/strict-v1.yaml` -> byte-identical before/after all tests.

### 9.3 Full gate and CI closure

Run the repository's complete current CI-equivalent gate, including at least:

- Ruff;
- config validation;
- full Python suite;
- systemd unit verification;
- generated OpenAPI/API/Wrangler type checks;
- Dashboard lint/typecheck/tests/build and client-bundle secret scan;
- Wrangler strict dry-run;
- cross-stack smoke.

After push, query GitHub Actions automatically. Do not close B1 unless the
required run is `success` and `head_sha` exactly equals the implementation
commit. Record exact implementation SHA, run id/conclusion, focused counts,
full Python pass/skip count, Dashboard count, replay proof, no-network proof
and `strict-v1` byte identity.

## 10. Manual-intervention policy

No manual owner action is planned for B1.

If and only if a genuinely external authority/environment makes one check
impossible, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue every other automatic verification. Never use a generic
"evidence not fully recorded" statement.

## 11. Stop boundary

Stop after materializable parameter semantics, authoritative re-admission,
deterministic candidate-only profile projection and profile-aware frozen PIT
replay are implemented and exact-head CI closure is recorded.

Do not:

- create/name/install `strict-v2`;
- write candidate bytes into active `rules/`;
- open or merge a rule-profile PR;
- record GitHub/human approval or rejection;
- mutate `strict-v1`;
- automatically apply any candidate;
- add provider/Bridge/FQGate scope;
- add notification vendors or Windows bootstrap;
- add brokerage/trading behavior.

Those belong to Phase 7-B2 or separately selected later work.
