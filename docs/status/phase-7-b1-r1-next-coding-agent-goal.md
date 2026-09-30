# Coding-agent handoff — Phase 7-B1-R1 Materialization Publication Hardening

Status: **READY FOR HANDOFF**
Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-b1-r1-materialization-publication-hardening.md`

Selection audit:
`docs/status/phase-7-b1-post-closure-review-2026-09-30.md`

Reviewed baseline:
`76066f620c9f10b8375818ec4811c2624f0f9d1f`

## Handoff

goal

Implement Phase 7-B1-R1 — Immutable Materialization Publication and Active-Rule Path Hardening in blooddrunk/turtle-value-engine.

Read and follow, in order:
1. AGENTS.md
2. docs/status/phase-7-b1-post-closure-review-2026-09-30.md
3. docs/goals/phase-7-b1-r1-materialization-publication-hardening.md
4. docs/status/phase-7-b1-2026-09-30.md
5. docs/goals/phase-7-b1-materializable-candidate-profile-foundation.md
6. docs/architecture/candidate-profile-materialization.md
7. src/turtle_value_engine/cli.py
8. src/turtle_value_engine/backtest/workspace.py
9. tests/test_evolution_materialize.py

The exact reviewed baseline is 76066f620c9f10b8375818ec4811c2624f0f9d1f. Preserve the Phase 7-B1 semantic closure. Do not start B2.

Mission:
- eliminate the check-then-os.replace TOCTOU from immutable B1 outputs; a concurrent different writer must never be overwritten;
- use the repository's established no-overwrite immutable publication pattern (temp + fsync + hardlink/exclusive-create or a rigorously equivalent boundary);
- keep concurrent identical writers idempotent and classify concurrent different content as a conflict while preserving the existing winner;
- make candidate publication a prerequisite and the materialization record the final authority marker for a complete pair;
- add one canonical complete-pair resolver/validator that requires both regular non-symlink files and proves the exact candidate bytes match CandidateProfileMaterializationV1.candidate_content_sha256 (and candidate id/profile validation as appropriate);
- on a normal second-stage failure, roll back only prerequisite artifacts provably created by this invocation; never delete pre-existing/concurrent files;
- document crash truthfully: an orphan candidate may remain after process death, but without a final valid materialization record it is not a committed materialization and B2 must reject it;
- bind active-rules refusal to the actual --base-profile/rule root, not only package-root/CWD heuristics, and publish only to the canonical destinations that were validated;
- fail closed on final symlinks/non-regular files and path redirection into supplied inputs, authoritative workspace or active rules;
- preserve all B1 authoritative re-admission, semantics, projection, replay, hashes, no-network behavior and strict-v1 byte identity.

Before production changes, create deterministic fail-on-baseline regressions against 76066f620c9f10b8375818ec4811c2624f0f9d1f:
1. Inject a competing different file after the current final exists-check and immediately before os.replace; prove baseline overwrites it.
2. Inject a failure/conflict only on the materialization publish after candidate publish succeeds; prove baseline leaves a partial candidate.
3. Run from a different CWD with the base profile copied under <tmp>/active/rules/strict-v1.yaml and candidate output under the same external active rules root; prove baseline accepts it.
Do not fabricate missing-symbol failures.

Post-fix automatic verification must prove:
1. concurrent different bytes never overwrite;
2. concurrent identical writers converge;
3. second-stage failure produces no completed pair and safely rolls back current-invocation prerequisite;
4. incomplete/orphan pair is rejected by the resolver;
5. candidate tampering/hash mismatch is rejected;
6. final symlink/non-regular and forbidden-root redirections fail closed;
7. external active rules root is refused independent of CWD/package layout;
8. byte-identical rerun stays idempotent;
9. every existing B1 focused semantic/replay test remains green;
10. socket guards still prove no network construction;
11. rules/strict-v1.yaml remains byte-identical;
12. any new persisted contract/schema has drift parity;
13. the complete CI-equivalent gate is green: Ruff, config validation, full Python suite, systemd verify, generated OpenAPI/API/Wrangler type checks, Dashboard lint/typecheck/tests/build/client secret scan, Wrangler strict dry-run, cross-stack smoke.

After push, query GitHub Actions yourself. Do not close R1 unless the required run is success and head_sha exactly equals the implementation commit. Record implementation SHA, run id/conclusion, focused regression counts, full Python pass/skip count, Dashboard count, concurrent-create proof, second-stage rollback/incomplete-pair proof, active-rules path proof, no-network result and strict-v1 byte identity.

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
Do not create/name/install strict-v2, write an approved profile into active rules/, open or merge a rule-profile PR, record human/GitHub approval or rejection, mutate strict-v1, automatically apply a candidate, add provider/Bridge/FQGate or notification-vendor/Windows-bootstrap scope, or add brokerage/trading. Stop after B1-R1 publication/path hardening is proven and exact-head CI closure is recorded. B2 remains next only after that.
