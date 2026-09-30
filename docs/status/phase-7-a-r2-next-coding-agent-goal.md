# Coding-agent handoff — Phase 7-A-R2 Authoritative Calibration Freeze Anchor and Schema Semantic Parity Hardening

Status: **CONSUMED** (implementation delivered; see
`docs/status/phase-7-a-r2-2026-09-30.md`)
Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-a-r2-authoritative-freeze-anchor-hardening.md`

Selection audit:
`docs/status/phase-7-a-r1-post-closure-review-2026-09-30.md`

Pre-R2 baseline:
`cbcf4cab5f361eb45d5be83a846e74c3b7f085cd`

## Original handoff

The original coding-agent handoff text is preserved verbatim below.

Use this as the implementation handoff for the selected R2 package.

```text
goal

Implement Phase 7-A-R2 — Authoritative Calibration Freeze Anchor and Schema Semantic Parity Hardening in blooddrunk/turtle-value-engine.

Read and follow, in order:
1. AGENTS.md
2. docs/status/phase-7-a-r1-post-closure-review-2026-09-30.md
3. docs/goals/phase-7-a-r2-authoritative-freeze-anchor-hardening.md
4. docs/status/phase-7-a-r1-2026-09-30.md
5. docs/architecture/controlled-evolution-evaluation.md

The exact reviewed R1 baseline is cbcf4cab5f361eb45d5be83a846e74c3b7f085cd; R1 implementation is aea01cb8e8aee17b4d7fcbaddbed31d6db3ec776. Do not treat the later planning/documentation commit as proof that the code defect is fixed.

Mission:
- close the remaining provenance hole where a caller can substitute same-id manifest content and/or non-scoring observation provenance, rebuild a fresh matching CalibrationEvidenceBindingV1, and thereby remove the mismatch that R1 detects only against an already-trusted binding;
- add one authoritative immutable calibration-freeze slot per CalibrationExperiment.experiment_id, persisted by the normal calibration/freeze workflow, so conflicting evidence/binding for the same experiment fails closed without replacing original bytes;
- make READY_FOR_HUMAN_REVIEW depend on the binding resolved and verified through that authoritative calibration workspace/anchor, not an arbitrary sidecar --evidence-binding path;
- preserve existing R1 binding artifacts as readable/exportable compatibility artifacts;
- make the checked-in Draft 2020-12 controlled-evolution evaluation schema reject reordered canonical checks and count-preserving duplicate/omission, not merely unknown names or wrong total count;
- preserve strict-v1 bytes, proposal-only semantics, canonical scorer/holdout replay, offline/no-network behavior, requires_human_approval=true, automatic_application_allowed=false, and every Phase 7-A/R1 substitution/leakage/chronology/reproduction check.

Verification discipline is mandatory:
A. Before implementation, write focused regressions using only R1 surfaces and run the exact same test file against cbcf4cab5f361eb45d5be83a846e74c3b7f085cd. The proof must show the actual unsafe R1 behavior, not fail because an R2 class/flag does not exist:
   1) same-dataset-id changed manifest + freshly rebuilt matching binding reaches READY on R1;
   2) source_hash-only observation substitution + freshly rebuilt matching binding reaches READY on R1 while canonical reproduction remains unchanged;
   3) schema-only validation accepts a 19-check reordered dossier on R1;
   4) schema-only validation accepts a 19-check count-preserving duplicate/omission dossier on R1.
Record the exact command and exact failing assertions/output.

B. Implement the smallest coherent fix. Prefer an additive immutable CalibrationFreezeRecordV1 (or equivalently explicit contract) keyed by experiment_id in BacktestWorkspace. Commit the authoritative anchor last. Byte-identical repeat is idempotent; different content for the same experiment_id is a hard conflict. Add a normal calibrate -> workspace persistence path. The evaluation CLI must resolve/verify the authoritative freeze and binding from that workspace before READY is possible. An arbitrary exported binding file alone must never be enough for READY.

C. Keep the core evaluator pure if possible: put filesystem resolution in an explicit workspace/loader boundary and pass already validated anchored evidence into the pure evaluator. Do not hide I/O in a function documented as pure.

D. Harden the generated checked-in JSON Schema using a real Draft 2020-12 exact-sequence representation (for example prefixItems with per-position consts plus the appropriate items policy), and keep deterministic model/schema generation from one canonical source. Add model+schema tests for canonical, reordered, duplicate/omission, truncated and unknown-name cases. Do not claim that JSON Schema can recompute cryptographic hashes; keep those semantic checks in model/runtime validation and document the boundary accurately.

E. Automatically verify at least:
- focused R2 regression suite;
- authoritative freeze round-trip, idempotency and conflicting-second-freeze byte preservation;
- missing/corrupt/foreign anchor and missing/mismatched referenced binding fail-closed;
- sidecar-only binding cannot become READY;
- real calibrate -> authoritative workspace freeze -> evolution evaluate chain becomes READY;
- socket-guarded no-network behavior;
- rules/strict-v1.yaml byte identity;
- full Python suite;
- complete current CI-equivalent repository gate (Ruff, config validation, systemd verify, generated OpenAPI/API/Wrangler types, Dashboard lint/typecheck/tests/build/client-bundle scan, Wrangler strict dry-run, cross-stack smoke).

After push, query GitHub Actions yourself. Do not close R2 unless the required CI run is success and its head_sha exactly equals the implementation commit. Record exact SHA, run id/conclusion, focused counts, full Python pass/skip count, Dashboard test count, schema adversarial results, no-network result and strict-v1 byte identity.

No manual owner action is planned. If and only if an external authority/environment makes one automatic step impossible, document ALL seven items:
1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.
Continue every other automatic verification. Never write a vague "evidence not fully recorded" placeholder.

Stop boundary:
Do not implement Phase 7-B, candidate-profile materialization, strict-v2, rule-profile PR creation/merge, human approval recording, provider/Bridge/FQGate expansion, notification-vendor work, Windows bootstrap, brokerage/trading, or any strict-v1 semantic change. Stop after R2 is fully proven and exact-head CI closure is recorded.
```
