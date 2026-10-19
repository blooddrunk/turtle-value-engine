# Phase 7-C3-B-R1 — Evidence Replay Integrity and Executable Owner Walkthrough

Status: **IMPLEMENTED / CI CLOSURE PENDING** (selected by `docs/status/phase-7-c3-b-post-closure-review-2026-10-19.md`; reviewed baseline `main` `462159cc5e2571e779048bb188b852a35b96ae59` — merge of PR #11, code equal to `2cebd91`)

## 0. First action: synchronize and review the actual upstream

Before writing any code: `git status --short`; `git fetch origin --prune`; inspect `origin/main` / recent PRs and workflow status; preserve local changes; switch to a clean branch/worktree at current `origin/main` (do **not** hard-reset or overwrite a dirty tree). Review `AGENTS.md` and this goal. If main moved beyond `2cebd91`, rebase the finding and tests on the newest actual HEAD, not stale snapshots. PR #10 and three exact-head remote CI runs are already closed/successful; do not re-implement C3-B.

## 1. Purpose

Close the **audit replay consistency** holes described in the review: the standalone `tve provenance verify-evidence` must not report `REPLAYS_BYTE_IDENTICAL` when an actual on-disk evidence component is missing/different or a self-consistent record claims decision fields not signed by the owner. Repair the real-owner walkthrough so its *optional* key-generation and signing instructions can actually be followed without exposing any private key.

This package **does not** implement an activation executor, select a new default, make economic judgments, issue any real owner approvals, fetch real-world feeds, or change deterministic investment rules.

## 2. Required tests-first reproduction (automatic, clean baseline)

Use ephemeral `Ed25519PrivateKey.generate()` test fixtures, the real `capture_owner_decision_evidence` / persistence / offline replay and the real CLI, not mock verifier results. Add narrow regressions to the existing test module or a clearly named new test module. **Run the regressions on pristine pre-fix main**, preserving their exact failing assertions/logs under a short review report (no binary dumps and no test secrets committed), then run identical tests after the fix.

Cases:
1. Confirm clean signed bundle replays byte-identically; honest invalid signed capture still replays honestly as rejected evidence, not as authorization.
2. Remove `record.json` from a `VALID` bundle. On baseline, `reverify_owner_decision_evidence` does not read it. After fix, reverify must fail closed with a classified error or explicit mismatch, and CLI must **not exit 0**.
3. Replace a valid on-disk `record.json` with another **Pydantic-valid, internally hashed** record while preserving `bundle.json`. After fix, return a named component divergence or classified failure (no clean replay).
4. Replace on-disk `verification.json` with a different **internally valid** signature dossier (e.g. computed against a different test registry), preserving the original `bundle.json`. After fix, classify dossier-file divergence. Merely corrupting a `detail` string without recomputing the dossier hash is **not** sufficient to prove this case.
5. Create a model-valid `bundle.json` whose `registry_id` or `registry_content_sha256` is inconsistent with the persisted snapshot's internal registry (recompute manifest content hash). Offline replay must classify it; the strict consumer loader should also fail closed when this discrepancy is relevant.
6. Construct a **fully self-consistent forged record + manifest** (recomputed deterministic record ID, record content hash, bundle ID and bundle content hash, stored under its matching directory name), while keeping the originally signed `decision-input.json` and statement. Change at least one signed field (decision or rationale; additionally test provenance source revision), keeping the fixture otherwise model-valid. Offline replay must reject that record-to-signed-bytes discrepancy. Prove the pre-fix replay outcome; no mock or already-invalid JSON.
7. Ensure no unrecognized or unexpected `record.json` can silently masquerade as an `INVALID` no-record bundle. Define the allowed six-file/five-file bundle shapes; fail closed on missing/extra/duplicate/symlinked components without destroying immutable existing evidence. Keep error categories deterministic and meaningful.
8. Socket-denied offline replay and byte-identical repeated replay remain successful. Verify genuine `plan-activation` still freshly re-attests current trust roots; key revocation still flips READY to BLOCKED. No implicit authority transfer from a historical bundle.

## 3. Implementation constraints

- Centralize **one precise evidence component manifest integrity contract** for strict loading and audit re-verification: actually read `verification.json` and, when a record exists, `record.json`; reconcile each with the embedded manifest and the actual signed payload. Validate the nested snapshot registry identity/hash against both manifest fields and the fresh dossier. Prefer classified mismatch reports for valid-but-divergent artifacts and classified fail-closed errors for unreadable/invalid artifacts; never reinterpret missing/invalid as success.
- Bind all owner-signed decision-input fields and `source_revision` to the actual persisted record. Do **not** mistake a self-consistent SHA-256 or deterministic ID for authentication. Clearly distinguish **historical replay integrity** from **fresh owner authority** and from complete re-execution of profile/economic audits.
- Avoid changing persisted V1 schemas/IDs unless unavoidable; if versioning is necessary, supply deterministic schema drift-parity and compatibility tests. Preserve exact-success bytes for previously valid evidence.
- Avoid destructive cleanup, force pushes, unsafe filesystem path assumptions and real secrets. Honor create-only evidence publication, idempotence, symlink/race fail-closed boundaries, and the operator-owned trust root. If path security limitations require a narrower guarantee, document it exactly rather than claiming universal tamper proof.

## 4. Repair the operator walkthrough (automatic documentation validation)

Fix `docs/operations/owner-provenance-walkthrough.md` §0–§3, not just prose:
- Use explicit outside-repository absolute locations and create required directories. Explain how to inspect and confirm the selected paths before invoking provenance CLI commands.
- Provide a concrete encrypted Ed25519 private-key storage-and-reload procedure (e.g. `cryptography` encrypted PKCS#8 or an established hardware keystore) and a signer snippet deriving the public key and signing the canonical message. Obtain encryption passphrases interactively, never on CLI argv; no private key, password, raw PEM, or signature of a real owner belongs in Git, CI or chat.
- Ensure the same persisted key can sign after a fresh process restart; add an **automated temporary-directory round-trip smoke test** of documented operations using throwaway keys and a test passphrase (only ephemeral runtime fixture). If an essential real-owner judgment remains manual, spell out the exact supplied inputs, inspected outputs, success/failure criteria and boundary; do not call that a missing engineering verification.
- Verify the real CLI command names, paths and exit codes (0/1/2), including `REPLAYS_BYTE_IDENTICAL` for captured `REJECTED` evidence meaning *integrity only*, not decision authorization.

## 5. Verification and completion gates

1. Baseline fail-on-regression evidence **with exact SHA and failing assertion/output**; after fix each same case passes.
2. `python -m ruff check .`; focused provenance/trust/decision tests; `python -m pytest -q` with actual pass/skip counts. Live AKShare tests are optional network-dependent and **not** a required phase gate.
3. Run all established `.github/workflows/ci.yml` equivalents: config validate, systemd-analyze verification, checked-in OpenAPI parity, Dashboard generated API/Wrangler types, lint, typecheck, tests, build, client-bundle security scan, Wrangler dry-run, cross-stack smoke. Capture each exact command, result and any limitations; prefer executing the script/CI itself, not reciting checks.
4. Compare SHA-256 of protected published files and project default to pristine baseline; keep `strict-v1` default, `execution_performed=false`, `automatic_activation_allowed=false`, no activation executor and no owner acceptance.
5. Open a focused PR, inspect the complete diff and review comments, verify GitHub Actions `success` on the **exact PR head SHA**. Merge only after successful checks and no unresolved serious findings; then confirm an exact merge-head `main` Actions success. Do not represent a pending or mismatched SHA run as passing.
6. Write closure status with test red/green evidence, actual CI URLs/SHAs, code limitations, protected hashes, and why no human is required for engineering closure. If CI cannot run, deliver the unmerged PR and exact blocker instead of false closure.

## 6. Next selection after R1

Only **after** R1 is accepted, independently re-review provenance-to-plan integrity and decide whether another narrow security repair or a separately authorized controlled activation design is warranted. Real strict-v2 economic acceptance, operator-owned key enrollment/signing and any actual profile switch are distinct **manual owner decisions**, not test fixtures and not part of R1. Never turn a passing replay check into permission to activate.
