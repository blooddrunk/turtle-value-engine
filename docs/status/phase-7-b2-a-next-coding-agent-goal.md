# Coding-agent handoff — Phase 7-B2-A Versioned Profile Release Bundle

Status: **READY FOR HANDOFF**
Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-b2-a-versioned-profile-release-bundle.md`

Selection audit:
`docs/status/phase-7-b1-r1-post-closure-review-2026-09-30.md`

Reviewed baseline:
`d296fde91ab0ff2e65ae6306281e8a3407f95a20`

## Handoff

goal

Implement Phase 7-B2-A — Versioned Profile Release Bundle and PR-Ready Provenance in blooddrunk/turtle-value-engine.

Read and follow, in order:
1. AGENTS.md
2. docs/status/phase-7-b1-r1-post-closure-review-2026-09-30.md
3. docs/goals/phase-7-b2-a-versioned-profile-release-bundle.md
4. docs/status/phase-7-b1-r1-2026-09-30.md
5. docs/status/phase-7-b1-2026-09-30.md
6. docs/architecture/candidate-profile-materialization.md
7. docs/goals/phase-5-backtesting-calibration.md
8. src/turtle_value_engine/evolution/materialization_pair.py
9. src/turtle_value_engine/evolution/materialize.py
10. src/turtle_value_engine/backtest/calibration_freeze.py
11. src/turtle_value_engine/config/loader.py and config/models.py
12. rules/strict-v1.yaml

The exact reviewed baseline is d296fde91ab0ff2e65ae6306281e8a3407f95a20. Preserve Phase 7-A/R1/R2 and B1/R1 closures. Do not start B2-B.

Mission:
- create a fully offline, deterministic, immutable PR-ready versioned-profile release bundle from a complete B1-R1 candidate/materialization pair;
- do not trust the pair as bearer authority: require the authoritative calibration workspace plus exact frozen manifest/experiment/holdout/observations/base profile, freshly rerun controlled-evolution admission and B1 materialization, then require exact candidate bytes + materialization id/content-hash equality with the supplied pair;
- accept an explicit target profile id for the strict lineage and require strict-vN -> strict-v(N+1); for the current baseline this means strict-v1 -> strict-v2 only;
- derive release bytes from the freshly reproduced candidate and permit only deterministic top-level profile metadata changes: id -> strict-v2, deterministic name, base status preserved, base description preserved;
- prove every rule-bearing field outside profile metadata is exactly equal candidate -> release;
- prove base -> release rule changes equal the source materialization's exact registered rule changes and contain no hidden semantic changes;
- introduce a versioned immutable release manifest (suggested VersionedProfileReleaseCandidateV1) with checked-in Draft 2020-12 schema, deterministic ids/hashes, source authority identities, target path rules/strict-v2.yaml, candidate/release rule-payload hashes required equal, metadata changes, and fixed requires_human_approval=true / automatic_merge_allowed=false / automatic_application_allowed=false;
- add an offline CLI such as tve evolution prepare-profile-release that writes release profile prerequisite first and release manifest authority-last outside active rules;
- reuse/extract the B1-R1 immutable no-overwrite publication pattern rather than cloning weaker check-then-write code;
- add a read-only complete-release resolver that rejects missing/orphan/tampered/symlinked/hash/id-mismatched bundles;
- keep rules/strict-v1.yaml byte-identical and rules/strict-v2.yaml absent for the entire B2-A implementation and verification;
- construct no socket and instantiate no GitHub/provider/model/transport client.

Baseline discipline:
B2-A is a new capability. Do not invent fail-on-baseline tests that fail merely because new symbols are absent. Record structural baseline evidence instead: B1-R1 ends at the candidate/materialization pair; there is no release-bundle contract/CLI, no strict-v2 file, and no path that emits exact PR-ready versioned-profile bytes.

Automatic verification is mandatory:
1. honest authoritative B1 chain -> deterministic strict-v2 release bundle;
2. self-consistent foreign/forged pair -> rejected by fresh authoritative re-materialization;
3. wrong workspace/manifest/experiment/holdout/observations/base bytes -> zero release output;
4. same/skipped/backward/arbitrary target version -> fail closed;
5. candidate -> release diff is profile-metadata-only;
6. candidate/release rule payload identities are equal;
7. base -> release rule diff exactly matches materialization.rule_changes;
8. release RuleProfile validates and round-trips deterministically;
9. identical rerun is byte-identical/idempotent;
10. concurrent identical publisher converges and concurrent different publisher never overwrites;
11. injected second-stage failure leaves no committed release and rolls back only provably owned prerequisite;
12. orphan/tampered/symlinked release pair fails resolver;
13. input/workspace/active-rules collisions and parent/symlink redirection fail closed;
14. full B2-A library and CLI socket guards prove no network construction;
15. strict-v1 bytes remain identical and rules/strict-v2.yaml remains absent;
16. every new persisted schema has model/generated drift parity;
17. all B1/R1 focused tests remain green;
18. run the full current CI-equivalent gate: Ruff, config validation, full Python suite, systemd verify, generated OpenAPI/API/Wrangler checks, Dashboard lint/typecheck/tests/build/client-bundle secret scan, Wrangler strict dry-run, cross-stack smoke.

After push, query GitHub Actions yourself. Do not close B2-A unless the required run is success and head_sha exactly equals the implementation commit. Record exact implementation SHA, run id/conclusion, focused test counts, full Python pass/skip count, Dashboard count, authoritative re-materialization proof, metadata-only/rule-equality proof, immutable publication/resolver proof, no-network result, strict-v1 byte identity and strict-v2 absence.

No manual owner action is planned for B2-A.

If and only if a genuinely external authority/environment prevents one automatic check, document ALL seven items:
1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.
Continue every other automatic check. Never use a vague "evidence not fully recorded" placeholder.

Stop boundary:
Do not create/write rules/strict-v2.yaml, open or merge a GitHub PR, record or synthesize human approval, change the default profile, automatically apply the candidate, mutate strict-v1, add provider/Bridge/FQGate or notification-vendor/Windows-bootstrap scope, or add brokerage/trading behavior.

Stop after B2-A exact release bytes + immutable release manifest are fully proven and exact-head CI closure is recorded. Phase 7-B2-B is the later GitHub PR + real human approval + versioned-profile publication boundary.
