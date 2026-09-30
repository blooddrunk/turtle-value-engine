# Coding-agent handoff — Phase 7-B1 Materializable Candidate Profile Semantics and Offline Projection Foundation

Status: **READY FOR HANDOFF**
Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-b1-materializable-candidate-profile-foundation.md`

Selection audit:
`docs/status/phase-7-a-r2-post-closure-review-2026-09-30.md`

Reviewed baseline:
`adfb843b3f1c1c6f0aa1ed29d2d7c86aa899bb42`

## Handoff

```text
goal

Implement Phase 7-B1 — Materializable Candidate Profile Semantics and Offline Projection Foundation in blooddrunk/turtle-value-engine.

Read and follow, in order:
1. AGENTS.md
2. docs/status/phase-7-a-r2-post-closure-review-2026-09-30.md
3. docs/goals/phase-7-b1-materializable-candidate-profile-foundation.md
4. docs/status/phase-7-a-r2-2026-09-30.md
5. docs/architecture/controlled-evolution-evaluation.md
6. docs/architecture/backtesting-and-calibration.md
7. docs/goals/phase-5-backtesting-calibration.md
8. rules/strict-v1.yaml
9. src/turtle_value_engine/backtest/calibration.py
10. src/turtle_value_engine/config/models.py and config/loader.py

The exact reviewed baseline is adfb843b3f1c1c6f0aa1ed29d2d7c86aa899bb42. Preserve Phase 7-A-R2 closure; do not reopen it unless you find a concrete implementation defect.

Mission:
- make candidate parameters materializable only when their concrete RuleProfile semantics are versioned and frozen before calibration selection;
- do not infer a YAML/profile target post hoc from names such as min_quality;
- keep existing R2 legacy/unbound proposals readable/evaluable but explicitly non-materializable;
- project an admitted proposal deterministically from the exact base-profile bytes into a candidate-only RuleProfile artifact using only frozen/registered scalar rule targets;
- create an immutable materialization record binding the authoritative R2 evidence, base profile, parameter-semantics identity, exact before/after diff, candidate bytes/hash and candidate semantic replay result;
- before materialization, resolve the authoritative calibration workspace and freshly re-run/revalidate the R2 admission chain; never treat a persisted READY_FOR_HUMAN_REVIEW dossier as a bearer authorization token;
- prove candidate semantics with canonical frozen point-in-time deterministic-engine replay wherever the necessary frozen normalized/research inputs exist; if you introduce a bounded optimized adapter, register it explicitly and prove equivalence to the canonical engine for its supported semantics;
- fail closed when replay inputs are missing; do not silently reuse baseline decisions or the generic feature-filter score;
- preserve holdout isolation, offline/no-network behavior, requires_human_approval=true, automatic_application_allowed=false and strict-v1 byte identity.

Critical current fact you must design around:
The built-in CalibrationRunner default scorer explicitly scores generic feature filters without interpreting strict-v1. CalibrationSearchSpace.parameters has no RuleProfile target binding, and CandidateProfileProposal.parameter_overrides simply copies the selected trial parameters. The canonical tests use min_quality, which is not a field in rules/strict-v1.yaml. A direct strict-v2 generator from the current proposal would therefore be semantically invented after the fact and is forbidden.

Implementation discipline:
A. Introduce the smallest coherent versioned materializable-parameter contract/registry. Every supported parameter must have a stable semantic identity, concrete scalar RuleProfile target (or canonical registry key resolving uniquely to it), type/range contract and replay/operator semantics.
B. Freeze that semantics identity before candidate selection and make it part of the experiment/freeze authority. Prefer an additive search-space contract if it preserves compatibility cleanly; if you use a separate semantics artifact, the authoritative freeze must bind its id/content hash. A materialization-time mapping supplied after calibration is not acceptable.
C. Keep legacy search spaces valid for historical replay, but classify proposals without the new binding as NON_MATERIALIZABLE/blocked. Do not guess.
D. Materialize from the exact base-profile bytes: verify SHA/id, parse with RuleProfile, apply only registered selected values to an in-memory copy, validate the entire profile, serialize deterministically, and emit an immutable materialization record. Do not write to rules/ and do not call the candidate strict-v2.
E. Add a B1 application/CLI boundary that requires --calibration-workspace and the exact frozen R2 evidence. It must resolve the authoritative anchor/binding and freshly re-evaluate before candidate output. Dossier-only and sidecar-only authority must fail closed.
F. Add profile-aware frozen PIT semantic replay. Prefer running the existing deterministic engine over frozen HistoricalDecisionArtifact.normalized_input under the projected candidate profile. Preserve train/validation/holdout chronology. If required input is absent, block. An optimization is allowed only with explicit registry scope plus automated equivalence to canonical engine behavior.
G. Candidate/materialization outputs must be create-only/non-destructive, must refuse collisions with inputs/workspace artifacts, and must refuse paths under active rules/. A blocked run leaves no partial candidate output.

Automatic verification is mandatory:
1. Record baseline structural facts; do not manufacture a fail-on-baseline test that only fails because B1 symbols do not exist.
2. Add a focused test proving the existing R2 min_quality proposal is rejected as non-materializable.
3. Add at least one real registered RuleProfile scalar end-to-end case: calibration/freeze -> authoritative admission -> candidate projection -> profile-aware PIT replay.
4. Prove semantics are frozen before selection: changed mapping/spec must change bound identity or conflict with the existing experiment freeze.
5. Prove wrong base bytes/hash/id, unknown parameters, structural/unregistered targets, type/range mismatches and post-hoc mapping substitution fail closed with zero candidate output.
6. Prove the candidate diff is exactly the registered rule leaves plus deterministic candidate metadata; no hidden semantic changes.
7. Prove identical reruns are byte-identical/idempotent.
8. Prove dossier-only, arbitrary sidecar anchor/binding and fake-workspace mismatches cannot authorize materialization.
9. Prove canonical candidate PIT replay is deterministic, chronological and holdout-isolated; missing required frozen replay input must block rather than fall back.
10. Socket-guard every B1 path and prove zero network socket construction.
11. Hash rules/strict-v1.yaml before/after and prove byte identity.
12. Add drift-parity tests for every new checked-in schema.
13. Run the complete current CI-equivalent gate: Ruff, config validation, full Python suite, systemd verify, generated OpenAPI/API/Wrangler types, Dashboard lint/typecheck/tests/build/client secret scan, Wrangler strict dry-run, cross-stack smoke.

After push, query GitHub Actions yourself. Do not close B1 unless the required run is success and head_sha exactly equals the implementation commit. Record exact implementation SHA, Actions run id/conclusion, focused test counts, full Python pass/skip count, Dashboard count, candidate replay proof, schema proof, no-network result and strict-v1 byte identity.

No manual owner action is planned. If and only if a genuinely external authority/environment prevents one automatic check, document ALL seven items:
1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.
Continue every other automatic check. Never use a vague 'evidence not fully recorded' placeholder.

Stop boundary:
Do not create/name/install strict-v2, write candidate bytes into active rules/, open or merge a rule-profile PR, record human/GitHub approval or rejection, mutate strict-v1, automatically apply a candidate, add provider/Bridge/FQGate or notification-vendor/Windows-bootstrap scope, or add brokerage/trading. Stop after B1 candidate semantics/projection/replay is fully proven and exact-head CI closure is recorded. B2 will own the later PR/human-approval boundary.
```
