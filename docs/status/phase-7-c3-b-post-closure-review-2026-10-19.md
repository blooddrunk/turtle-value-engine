# Phase 7-C3-B — Independent Post-Closure Review (2026-10-19)

Status: **REVIEW COMPLETE AT SOURCE/REMOTE-CI LEVEL; FOLLOW-UP HARDENING SELECTED; NOT A REOPENING OF PR #10**

## 1. Reviewed immutable baseline and verified delivery

- Repository: `blooddrunk/turtle-value-engine`; reviewed `main` at `2cebd91341553edbbbaf8f07cb307d6949b7e223`.
- C3-B implementation: PR [#10](https://github.com/blooddrunk/turtle-value-engine/pull/10), implementation head `c7943b5903d74588d0eeffaec94cc80bcdc279fc`, merged as `6d2da2edd23fe7b0a9fea45f9778e31923c1de03`.
- GitHub Actions at exact implementation head: run [38708419906](https://github.com/blooddrunk/turtle-value-engine/actions/runs/38708419906) **success**. Merge-head run [38834048273](https://github.com/blooddrunk/turtle-value-engine/actions/runs/38834048273) **success**. Current reviewed `main` run [38835217538](https://github.com/blooddrunk/turtle-value-engine/actions/runs/38835217538) **success**, 24/24 reported workflow steps green (including checkout/setup/teardown).
- Closure record `docs/status/phase-7-c3-b-2026-10-16.md` reports local `ruff`, full `pytest` **7,260 passed / 2 skipped**, config/systemd/OpenAPI/Dashboard/cross-stack gates green. The two skips are pre-existing opt-in live AKShare tests. These local numbers are **closure-record evidence, not a new local test run by this review**.
- C3-B feature boundaries are materially present: trust-snapshot lifecycle, signed decision capture, immutable evidence, offline verifier, signed lifecycle statements, real-verifier CLI plan-time re-attestation. No activation executor and no real owner acceptance were found or asserted.
- This review inspected source via the connected GitHub repository and actual remote CI/PR metadata. An independent fresh checkout/test execution was **not available in the reviewing environment**. All newly described failure classes below are **source-demonstrated candidates for mandatory executable fail-on-baseline reproduction**; do not claim reproduced test results until the coding agent runs them.

## 2. Finding F1 — Offline evidence replay does not reconcile all persisted components (priority P1, audit-integrity)

**Location:** `src/turtle_value_engine/evolution/owner_trust_store.py`, `reverify_owner_decision_evidence` (~905–1009); `load_owner_decision_evidence` (~773–847); CLI `_run_provenance_verify_evidence_command` (~2352–2368).

- At ~954 the audit replay **loads but discards** the on-disk `verification.json`. At ~968–975 it compares the freshly recomputed verification only with **the verification embedded in `bundle.json`**, not with that separate file.
- At ~976–984 it takes `record = bundle.record` and **never reads** the physical `record.json`. A missing `record.json` can therefore be missed by `tve provenance verify-evidence` even when `bundle.record` is present. A different-but-self-consistent valid record file can likewise remain unchecked.
- The strict consumer loader *does* read and compare these files; the CLI's standalone audit path calls the **other**, incomplete `reverify_owner_decision_evidence` implementation.
- The audit path also checks `snapshot_id` and snapshot hash but does **not** reconcile the manifest's separate `registry_id` / `registry_content_sha256` against the registry in the loaded snapshot (~962–966).

**Impact:** `REPLAYS_BYTE_IDENTICAL` and CLI exit 0 can overstate persisted-component integrity. This is **not evidence of an activation authorization bypass**: plan-time authority still uses `load_owner_decision_evidence` and fresh signature verification. Nonetheless it breaks C3-B's explicit audit replay requirement and warrants correction before expanding execution/activation.

**Required red-on-baseline tests:** capture real signed evidence with runtime-generated Ed25519 test keys; delete `record.json`; replace `record.json` with a *different structurally/hash-valid* record; replace `verification.json` with a *different structurally/hash-valid* dossier (not merely malformed JSON); substitute an internally valid snapshot/manifest identity mismatch. Assert that audit replay no longer returns a clean `REPLAYS_BYTE_IDENTICAL` / exit 0. Also test valid unchanged evidence stays deterministic, plus the strict loader still fails closed. Test against clean `2cebd91` first, and record exact observed red results.

## 3. Finding F2 — Self-consistent forged manifest/record requires semantic binding tests (priority P1, audit-integrity)

**Location:** same `reverify_owner_decision_evidence` (~977–984), `OwnerProvenanceEvidenceBundleV1.validate_bundle` (~543–576), and `SignedOwnerProvenanceVerifier.verify_decision_authority` (~867–943).

The offline replay currently checks a record's provenance hash against the manifest and a record hash against its own embedded expected hash, but does **not** independently compare each decision field of that record to the parsed signed decision-input bytes. A deliberately regenerated, self-consistent manifest/record can therefore be a source-level candidate for a false successful *audit* replay even though a fresh activation-plan verifier would reject it. Unlike a single corrupt file, this adversarial case must re-derive all self-hashes and deterministic IDs in the fixture to avoid a trivial parse failure.

**Required test:** capture genuine signed ACCEPT or REJECT, construct a fully model-valid alternative record with a changed decision/rationale/owner identity or source revision while preserving the originally signed bytes, and regenerate matching bundle content hash and ID in a separate bundle directory. Require offline replay to flag signed-record-content divergence. Do **not** claim complete recreation of record-time economic/profile audits: those require external profile, audit, exception and allowlist inputs not present in the evidence bundle. Define exactly what offline replay can prove, and keep the activation authority check separate.

## 4. Finding F3 — Real-owner walkthrough's key provisioning instructions are not executable end-to-end (priority P2, operations)

**Location:** `docs/operations/owner-provenance-walkthrough.md`, §0–§3.

- §0 selects `~/tve-trust/bundle/` outside Git, but §1 writes to relative `Path("bundle/owner.pub")` after `cd ~/research/turtle-value-engine`, which can fail if that relative directory does not exist or creates an unexpected file inside the repository.
- §1 generates an ephemeral private key and tells the operator to store it, but provides no secure export: after the process exits, that key is gone and §3's `private = ...` cannot sign with it.
- Repair with a genuinely followable private-key provisioning/secure encrypted storage/restore/signing procedure entirely outside the repository; avoid command-line passphrase arguments, logs, Git, CI and chat. Keep the workflow optional; test keys are enough for engineering closure.

## 5. Boundaries and selection

- **Selected next engineering package:** `docs/goals/phase-7-c3-b-r1-evidence-replay-integrity-hardening.md`. Do this **before** an activation executor or a new C3 feature.
- C3-B remains merged and closed on its recorded implementation/CI evidence; these are *post-closure audit-integrity defects and documentation gaps*, not proof that existing cryptographic verification can authorize a forged plan.
- The real owner has **not** supplied actual strict-v2 economic acceptance. Do not generate owner keys, signatures, rationales, approval, policy exceptions or activate/switch any profile on the owner's behalf.
- Protected bytes: `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml`. Default must stay `strict-v1`; `automatic_activation_allowed=false`, `execution_performed=false`. No network/model/provider in provenance replay.
- No real-owner manual activity is needed to reproduce, implement or close R1. Manual acceptance belongs to a separate explicit business decision, not a placeholder engineering validation step.
