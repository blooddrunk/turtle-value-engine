# Phase 7-C4-A-R4 — Independent Post-Closure Review (2026-10-24)

Status: **R4 ENGINEERING ACCEPTED / CLOSED. Phase 7-C4-B selected for a separate implementation.** No real owner authorization, strict-v2 activation, or R5 security-hardening task is implied.

## 1. Reviewed source and exact CI identities

- Repository: blooddrunk/turtle-value-engine; verified latest main at **518cd73f99b0f3b0dbe51dbc59d377c36cf4f028** immediately before opening this selection change.
- R4 implementation PR [#26](https://github.com/blooddrunk/turtle-value-engine/pull/26): implementation head **25cc7ca6412aa1367e7ab5fb80481146ef7a568d**; merged into main at **a7b3950b69673894fe427bf12ce19620d2761c1f**. The R4 closure-status and AGENTS documentation-only commit is **518cd73f99b0f3b0dbe51dbc59d377c36cf4f028**.
- PR exact-head CI [40079218012](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40079218012) is success at the PR head; merge-head CI [40079798576](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40079798576) is success at the merge commit; latest-main CI [40080180093](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40080180093) is success at the exact latest main SHA.
- Independently fetched and read raw latest-main job log (run 40080180093, job **120831927702**) and the associated job-step results. Full Python suite: **7412 passed, 2 skipped, 9 warnings**. The two skips are the explicitly opt-in live AKShare tests. Dashboard: **55 passed**. Ruff, example-config validation, systemd verification, generated OpenAPI/types checks, Dashboard lint/typecheck/build, client-bundle secret scan, Wrangler strict dry-run and cross-stack smoke completed successfully. The non-failing Pydantic and Node/Actions deprecation warnings do not constitute a failure of this R4 contract.
- At review time GitHub REST reported **0 open pull requests and 0 open issues**.

## 2. Independent source-level inspection and result

Inspected PR #26 changed files, current src/turtle_value_engine/cli.py (input preparation, named file digest derivation, authority recheck and command dispatch), src/turtle_value_engine/evolution/owner_decision.py (decision and revocation loaders), the original C4-A execution path, tests/test_activation_execution_r4_probes.py, the R3 selection review, the R4 goal/status and the operator guide.

- The CLI now associates each named consumed input buffer with its label: decision-record[i], revocation[i], policy-exception[i], boundary-input, signed-revocation[i], signed-supersession[i]. The prepared object and the expected hash derive from the **same consumed bytes**, not a second path read.
- The additive decision/revocation loader APIs return parsed models plus the bytes actually consumed, preserving existing path-loader entrypoints. Policy exception parsing receives an additive bytes mode. The two R3 in-lock authority freshness anchors remain in place, re-reading on-disk sources for comparison at execution boundaries.
- The five R4 committed probes are inspectable and exercise the real disposable-fixture CLI, not merely a mocked helper return: an authorization-relevant file replacement after parsing, replacement at the former digest-read boundary (exception and decision-record cases), a freshly reloaded blocking truth control, and a no-mutation apply control. Their fixed-tree passing execution was independently observed in the latest-main CI log. No contradictory code-level finding was identified in this bounded review.
- The phase author's pristine-baseline record reports three repeatable red cases and two green controls on baseline **96d89e65ead14b6d2946e5e07af0e657cccdddac**, before fixing production code. **That baseline-red reproduction was reviewed as recorded implementation evidence, not independently re-executed in this review.** The current environment could not clone the public repo (git: Could not resolve host: github.com). We do not claim a local full-suite run or locally reproduced baseline failure.

## 3. Protected artifact identity independently rechecked

Queried the Git tree recursively at both pristine selection baseline **96d89e6** and reviewed latest-main **518cd73**; both trees are non-truncated. Exact blob SHA equality:

| Protected file | Both trees: Git blob SHA |
| --- | --- |
| rules/strict-v1.yaml | e34f4ca00ba822766e05e6ccd48d3398b0245e4a |
| rules/strict-v2.yaml | 0e75b02e9305415018bb57c9b9fb8418440eb090 |
| docs/releases/strict-v2/release-candidate.json | ded5606454d3ef0afc1a0fdc0fea937d3c6cc786 |
| config/project.example.toml | a9cff0de8fbc4e6f510f3ee5e8551f4b89aeaa03 |

The checked-in example default remains **strict-v1**. Engineering fixture activations are not an actual owner-approved strict-v2 switch.

## 4. Explicit limits and non-claims

- The two in-lock anchors observe source identity only at their two sampling points. No cross-file/global transaction, guarantee for the final-anchor-to-config-replace race, or multi-host atomicity is claimed.
- Individual adversarial byte-replacement probes for revocation, boundary-input and the two signed lifecycle input categories were not added by R4. Their parsing and digest derivation use the same code path, but this is **shared-code coverage**, not a claim that separate adversarial demonstrations were executed for each category.
- Local self-hash consistency, receipt validation and crash-injection/fsync ordering are not physical power-loss certification, authentic owner consent, or a live-provider acceptance test.
- No independent locally executed verification is claimed because network name resolution prevented cloning. The exact remote CI and inspectable source/diff are the basis for engineering acceptance.
- Do not create an automatic R5 from an unproven residual. A further security repair requires independently reproducible source-backed faulty behavior and a separate scoped goal.

## 5. Next selection: Phase 7-C4-B

Proceed to **Phase 7-C4-B — Read-Only Activation State Inspection and Disposable Operator Rehearsal**, specified in [the dedicated goal](../goals/phase-7-c4-b-operator-rehearsal-activation-state-verification.md).

Reason: C4-A through R4 already provide the mutation, journal, receipt, before-image and rollback implementation, with many automated tests. Their remaining practical gap is **operator observability**: before retrying an interrupted apply or rollback, an operator currently has to interpret multiple JSON files and hashes manually. A minimal offline, read-only status/verification surface with deterministic disposable rehearsal tests is more valuable than speculative R5 hardening.

Boundary: status must classify only what persisted local artifacts and the observed config bytes actually prove; it must not re-authorize the policy, silently finalize/repair state, invoke apply/rollback, touch real keys or trade, or claim that a local receipt proves current owner authority. Do not expand the implementation into an account-deployment workflow, security research program, or live strict-v2 rollout.

## 6. Automation-first acceptance and human boundary

Engineering acceptance of C4-B should be entirely automatic: temporary private configs and runtime-created disposable Ed25519 keys; no live provider, cloud account, private market corpus, human signatures or real owner intervention. Commit exact commands, tests, file-hash before/after proofs and exact-head CI links in the future C4-B status record. If an environmental check cannot run, record the attempted command, actual error, impact, automated alternative and the remaining unverified assertion; do not write a vague evidence-incomplete statement.

A future **optional real-owner** strict-v2 decision is a separate, explicit authorization: the owner must independently review the CDC 14% versus S-band 12% policy exception, decide ACCEPT/REJECT, control their own private key, sign and record the real decision, inspect a fresh private-config preview, and deliberately run the expected-identity bound apply. Neither this review nor C4-B authorizes or requires that action.
