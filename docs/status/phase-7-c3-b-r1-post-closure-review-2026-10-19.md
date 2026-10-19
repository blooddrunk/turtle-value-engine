# Phase 7-C3-B-R1 — Independent Post-Closure Review (2026-10-19)

Status: **SOURCE/REMOTE-CI REVIEW COMPLETE; TWO FOLLOW-UP CANDIDATES SELECTED FOR TESTS-FIRST R2. R1 REMAINS CLOSED.** This report is a source-level review; it does **not** claim fresh local red/green reproduction.

## 1. Immutable reviewed baseline and verified delivery

- Reviewed repository `blooddrunk/turtle-value-engine`, default `main` at `cf01f11991af6284cc263a55b9d2c5d500a413c4`.
- R1 PR [#12](https://github.com/blooddrunk/turtle-value-engine/pull/12) **merged**, implementation head `c38af8c1228d03de2a110d2bf8b9d2e74797ccbc`, merge commit `80d386cb1ee6384cb620573be01d55c125e4b4e0`; closure documentation commit `cf01f11`.
- Exact-head PR Actions [39189313847](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39189313847), exact merge-head [39189735260](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39189735260) and latest main [39190197319](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39190197319): all **success**, head SHAs independently matched. Each reported workflow job and all 25 reported setup/check/test/build/teardown steps succeeded. Latest main CI logs independently show **7275 passed, 2 skipped, 9 warnings** in the deterministic Python test suite.
- Changed paths from prior reviewed baseline `462159c` to `cf01f11`: `AGENTS.md`, one existing goal, the owner walkthrough, one new closure report, `src/turtle_value_engine/evolution/owner_trust_store.py`, and one new regression test module. None of the four protected published/config files changed in that compare. Recorded exact protected SHA-256 values remain in `docs/status/phase-7-c3-b-r1-2026-10-19.md`.
- The R1 closure’s nine baseline-red regressions and fixed-green evidence, real component-file replay checks, signed decision/source-revision binding, registry identity binding, strict consumer checks, key round-trip smoke and fresh plan-time trust-root re-attestation remain accepted. No reason found to reopen PR #12. No real owner acceptance or activation occurred.
- Independent checkout/test execution was **not possible in this review environment** (GitHub DNS/network unavailable to the local test container). No new test was executed for the findings below; each remains a **mandatory executable candidate** for the coding agent, not a claimed exploit reproduction.

## 2. Candidate F1 (P1 audit-integrity) — captured authority claims are not replay-bound to cryptographic attestation

Code trace: `owner_trust_store.py` `_record_signed_payload_divergences` (~646–672) checks `_DECISION_CONTENT_FIELDS` and `source_revision`; `load_owner_decision_evidence` (~860–951) checks components, registry and signed record fields; `reverify_owner_decision_evidence` (~1013–1137) compares a recomputed `verification` but does not explicitly reconcile **record.authority** against that verification result or the original signed-capture semantics. The bundle validator (~546–578) ties VALID to record presence, not to cryptographic status or empty blockers.

Source-predicted, **not yet independently reproduced** cases to test against pristine `cf01f11`:

1. Start with a genuinely captured VALID, signed and verified bundle. Rebuild a fully model-valid record with only `authority.attested_key_id`, `attested_registry_id`, `attested_registry_content_sha256` and/or `authority.evidence_content_sha256` forged. Preserve *all actually signed decision fields and source revision*. Recompute deterministic record id/content hash and manifest bundle id/content hash; persist all matching component files under the matching bundle id. The current audit/loader lacks an explicit cross-check between those claims and the recomputed dossier/registry/signed input.
2. Start with a genuine INVALID/REJECTED signed capture (no record). Construct a Pydantic-valid record about the same signed decision input but falsely claiming `OWNER_AUTHORITY_VERIFIED`, set manifest `validation_state=VALID` with that record, rebuild identifiers and all physical components. The current audit/loader does not explicitly reject `VALID` with a recomputed `verification_status=REJECTED`. Demonstrate its actual behavior by executing the test before any fix.
3. A forged VALID bundle can list nonempty `validation_blockers` even though record-time `validate_owner_decision` derives INVALID whenever blockers exist. Test this invariant separately, with all IDs/hashes recomputed.

**Impact/boundary:** A misleading `REPLAYS_BYTE_IDENTICAL` may overstate the authenticity of captured authority metadata or the VALID/REJECTED relationship. This is **not** a demonstrated authorization bypass: the activation planner's verifier separately re-attests a record against the operator-supplied current trust root; the independent replay never grants permission. Recomputing the full record-time C1 economic audit from an evidence bundle is not feasible because all required input bytes are not present; do **not** require it or redefine offline replay as economic approval. Scope R2 only to externally checkable cryptographic/capture invariants.

## 3. Candidate F2 (P2 operational key custody) — private key is not created atomically with owner-only permissions

`docs/operations/owner-provenance-walkthrough.md` §1 creates `~/tve-trust/private/owner.pem` using `Path.write_bytes`, then suggests `chmod 600` **after** creation. Under a typical `umask 022`, this does not itself establish private-file mode 0600 at the initial write, and the default create operation also lacks create-only refusal of pre-existing files/symlinks. Key generation is optional, operator-owned and outside the repo; there is no evidence a real key was created or exposed.

Repair the runbook with private directory creation mode 0700; an atomic exclusive no-follow create of the encrypted PKCS#8 key with mode 0600 **from the first open**; explicit safe refusal if the path already exists; no passphrase on argv, in Git, logs or chat. Round-trip and refusal/permissions tests must run with **throwaway keys only** and forced permissive process umask to prove the file-creation boundary.

## 4. Selected next task and engineering gates

**Phase 7-C3-B-R2 — Capture Attestation Consistency and Safe Owner-Key Provisioning**. Exact tests-first contract: `docs/goals/phase-7-c3-b-r2-capture-attestation-consistency-hardening.md`.

- First synchronize latest upstream, preserve dirty local changes, re-check PR/main/CI and use actual current main; do not copy stale SHA assumptions into a worktree.
- Prove the F1/F2 outcomes with real signed/invalid fixtures and fully self-consistent forged bundles on **pristine current main**. Record exact passing/failing assertions; if a hypothesis is false, report why and remove/re-scope rather than force a fix.
- Write the smallest shared fail-closed replay/strict-loader check plus safe owner-key documentation/test fix; preserve V1 schema/IDs if feasible, legitimate VERIFIED/REJECTED history, and no network/synthetic owner approvals.
- Run focused tests, Ruff, full pytest, every actual `.github/workflows/ci.yml` equivalent (OpenAPI, project-config, systemd, Dashboard generated types/lint/typecheck/tests/build/security/Wrangler/cross-stack smoke), exact SHA protected-byte audit, and remote exact-head PR CI. Merge only when green; check merge-head CI and record it honestly.
- No real key provisioning, real strict-v2 economic acceptance, private key disclosure or actual profile switching is required for engineering closure. The real owner's separate decisions are: inspect the C1 economics/exception and approve/reject policy; take custody of and register the owner key; sign the final exact payload if approving; and separately authorize any future activation implementation/execution. None is implied by automated test success.

Do not start a controlled activation executor or change the strict-v1 default in R2. After R2, independently decide whether further security repair or a separately authorized controlled-activation design is warranted.
