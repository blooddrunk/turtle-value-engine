# Phase 7-C3-B-R2 — Independent Post-Closure Review (2026-10-20)

Status: **R2 closure ACCEPTED; next R3 tests-first candidate SELECTED (not implemented)**.

This is a GitHub-source/CI **independent static review**, not an independently executed local test run. Attempts to clone the public repository in the review runtime failed because GitHub DNS was unavailable (`Could not resolve host: github.com`). All new gaps below are **code-path hypotheses requiring fail-on-pristine-main executable reproduction**; no exploit, regression result or local test success is claimed for R3.

## 1. Exact baseline and verified closure

- Repository: `blooddrunk/turtle-value-engine`; default branch `main`; inspected main head `90f8754af1a2bb2e8f09b8edcbc05be4982fa90d`, before this documentation-only review branch.
- Phase 7-C3-B-R2 goal: `docs/goals/phase-7-c3-b-r2-capture-attestation-consistency-hardening.md`; implementation PR [#14](https://github.com/blooddrunk/turtle-value-engine/pull/14) **merged**, implementation head `814779019846278ea5490d61298b8cd8c7a17bc9`, merge head `12f1d68b12f347e8a9bb99e00c63dd51cf62b303`. The later `90f8754` commit only closed R2 documentation.
- Actions exact implementation-head [39221642102](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39221642102), merge-head [39222367923](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39222367923), and latest main-head [39223078950](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39223078950): **completed / success**, each with the corresponding `head_sha` and successful named job steps (Ruff, config, pytest, systemd, OpenAPI, Dashboard API/types/lint/typecheck/test/build/secret scan, Wrangler strict dry-run, cross-stack smoke).
- The main-head CI job's actual log reports **7291 passed, 2 skipped, 9 warnings** and Dashboard **55 passed**. The two skipped tests are opt-in live AKShare checks, not a hidden owner acceptance gate. No separate test was run in the review runtime.
- Compare pristine selection baseline `c40dc7a` to `90f8754`: three commits, changed paths only `AGENTS.md`, the R2 goal/walkthrough/closure, `owner_trust_store.py` and the new R2 test file. Protected `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml` were not changed in the compare. Recorded SHA-256 values are in `docs/status/phase-7-c3-b-r2-2026-10-19.md`.
- PR #14 has no submitted reviews or unresolved inline review threads. This fact is not a substitute for the source review below.
- R2's source uses one shared `capture_attestation_divergences` contract for historical status, method, attested registry/key and evidence hash; replay recomputes the dossier and strict loading also recomputes it. R2's 16 committed tests preserve genuine VERIFIED, honest REJECTED/INVALID, and the safe private-key creation cases. No reason to reopen the **closed R2 scope**.

## 2. Residual source-level hypotheses: do not present as reproduced defects

### F1 — strict-loader/replay asymmetry over record provenance content hash (high-confidence source-path observation)

`reverify_owner_decision_evidence` in `src/turtle_value_engine/evolution/owner_trust_store.py` explicitly emits `RECORD_PROVENANCE_NOT_BOUND_TO_INPUT_BYTES` when `record.provenance.source_content_sha256 != bundle.decision_input_content_sha256`. However `load_owner_decision_evidence` checks the decision-input file hash, physical/embedded record equality, `_record_signed_payload_divergences` (signed content fields and `source_revision`), fresh dossier equality, and `capture_attestation_divergences`, **without an equivalent provenance source-content-hash check**. The shared attestation helper compares `authority.evidence_content_sha256`, which is a *different field*. `DecisionProvenanceV1` only requires a non-null hash for one source kind, not equality with the signed bytes.

Candidate reproduction: start with a genuinely VERIFIED capture, change **only** `record.provenance.source_content_sha256` to another valid hash, rebuild a model-valid record with fresh deterministic id/content hash, regenerate the manifest/bundle hashes and matched component directory. Expected on reviewed source: replay names `RECORD_PROVENANCE_NOT_BOUND_TO_INPUT_BYTES`, but strict loading may accept. Prove with the actual model/store APIs and CLI, not via a mock. This is historic evidence-consumer consistency, **not** evidence of a READY-plan bypass: plan-time `SignedOwnerProvenanceVerifier` explicitly compares record provenance against signed bytes.

### F2 — residual forged recorded authority annotations (candidate)

`capture_attestation_divergences` checks authority method/status/key/registry/evidence hash, but does not inspect `authority.verifier_kind`, `authority.allowlist_matched`, or `authority.reason_code`. In the real verified record-time `SignedOwnerProvenanceVerifier` path these are deterministic: kind `ed25519-signed-owner-provenance`, affirmative `allowlist_matched=True`, reason `ED25519_OWNER_PROVENANCE_VERIFIED`. Record content can be re-hashed without a new owner signature because these fields are not part of the signed decision input. Such edits might be silently accepted as genuine capture metadata even after the R2 fix.

Reproduce *separately* for a forged verifier kind, false or null allowlist outcome, and false reason code, with complete self-consistent rehashing and real persisted components. Test replay, strict load and plan independently; do not claim an authorization bypass when fresh plan-time re-attestation is the effective guard. Free-text `detail` should be studied as an audit annotation separately; do not overfit to formatting prose or retroactively invalidate legitimate historical evidence without an explicit compatibility analysis.

### F3 — unsigned supersession carried by a forged capture (candidate)

`capture_owner_decision_evidence` calls `validate_owner_decision` without a `supersedes_decision_record_id` argument. The signed input does **not** bind this optional record metadata. `_record_signed_payload_divergences` compares the signed decision fields plus revision, and `capture_attestation_divergences` does not reject a newly added `record.supersedes_decision_record_id`. A fully self-consistent forged bundle with only that optional record field changed therefore warrants replay and strict-load testing. The plan-time verifier already checks `unsigned_supersession` and rejects it, and authenticated supersession uses its separate signed lifecycle protocol; no claim of a plan bypass.

### Deferred, not selected

The manifest contains a deterministic `bundle_id`, and publication places it under that directory name, but loading from a renamed/moved folder has no explicit basename check. Treat this as a **locator/portability contract question**, not a known authority defect; imposing a basename restriction may break legitimate offline copies. Also do **not** conflate historic evidence integrity with independent trust-root ownership, replay of the economic C1 audit from absent inputs, whole-directory replacement by an actor controlling the evidence root, or real owner acceptance. They belong to different boundaries.

## 3. Decision

**Select Phase 7-C3-B-R3 — Capture-Origin and Authority-Annotation Consistency (tests first)**, narrowly scoped to F1, F2 and F3. Goal: `docs/goals/phase-7-c3-b-r3-capture-origin-consistency-hardening.md`.

Why R3 precedes any executor: it is inexpensive to resolve a demonstrable mismatch between offline audit replay and its strict consumer before adding a new mutating phase. This is not a request to keep polishing indefinitely: **after red-on-current-main/green-after-fix evidence, full CI and an independent post-R3 closure review, select the next boundary on actual results**. If none of F1/F2/F3 reproduce, record counter-evidence and close the R3 candidate without unjustified source modifications.

## 4. Mandatory engineering/verification gates

1. First synchronize upstream and protect dirty worktrees. Use the **actual** latest `origin/main` at the time of implementation, not this review's pinned SHA.
2. Execute real Ed25519 tests against a clean **pristine baseline** before implementing; include complete recomputation of the deterministic record/bundle identities and physical components. Record exact failing assertions, passing controls and the baseline SHA in committed evidence. Source-reading hypotheses must not be reported as executable findings.
3. Implement the smallest shared, fail-closed contract. A parseable incoherence should give named `MISMATCH` on replay (CLI exit 1) and a classified strict-loader error (CLI exit 2), preserving genuine evidence and the distinct plan-time verifier.
4. Execute focused and complete tests plus all current `.github/workflows/ci.yml` equivalents; check protected SHA-256, strict-v1 default, no activation code and no owner key/signature/acceptance synthesis. PR-head CI must match its exact SHA and be green before merge; verify the merge-head main CI after.
5. R3 engineering requires **no real human owner action**. Optional future owner key custody, strict-v2 economic judgment, and a real profile switch require separate explicit owner decisions and documented observable steps; no placeholder `manual gate incomplete` is accepted as an R3 closure explanation.

## 5. Honest limitations

- Independent local checkout/test execution in this review environment: **BLOCKED by GitHub DNS**, exact attempted operation: `git ls-remote https://github.com/blooddrunk/turtle-value-engine.git HEAD`. GitHub Actions logs and connector-accessible source were inspected instead.
- Current main CI passing does **not** exercise the new R3 adversarial candidates until the tests are written. R3's red/green counts remain **UNKNOWN**.
- This review and the associated goal are **documentation-only**; the R2 implementation, runtime behavior, profile rules, actual owner trust material and activation state remain unchanged.
