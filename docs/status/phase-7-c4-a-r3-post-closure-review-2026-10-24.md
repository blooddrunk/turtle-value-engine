# Phase 7-C4-A-R3 independent post-closure review / conditional R4 selection — 2026-10-24

Status: **R3 CLOSED / ENGINEERING ACCEPTED; conditional R4 tests-first probe SELECTED, NOT IMPLEMENTED.** No rule release, real owner decision, key or activation is authorized by this review.

## 1. Reviewed baseline and independently observed evidence

- Repository: `blooddrunk/turtle-value-engine`; inspected current `main` at `062890538d6430d36c7b94f72483620fe24c1576` (R3 closure-record commit).
- R3 implementation PR [#24](https://github.com/blooddrunk/turtle-value-engine/pull/24) has exact implementation head `69a3d58644dabb7407da4b4ed86081d18d202d9a`, merged as `b75d81b92651cd52681ce581f1e36473f7762440`. PR exact-head CI [40060493984](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40060493984), merge-head CI [40060984973](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40060984973), and current-main CI [40062547891](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40062547891) each report `success` and match the respective SHA.
- Independently fetched the **raw current-main job log** (run 40062547891, job 120778973326): `python -m pytest -q` **7407 passed / 2 skipped / 9 warnings**; Dashboard **55 passed**; Ruff, default `strict-v1` config validation, systemd verify, generated OpenAPI and Dashboard types, lint/typecheck/build, client-bundle secret scan, Wrangler strict dry-run and cross-stack smoke green. The skipped cases are opt-in live AKShare tests, not failures.
- Git compare `4247f20300464ada44019ecb2225527c9f407797...062890538d6430d36c7b94f72483620fe24c1576` touches only the R3 implementation/test/docs and closure; all four protected blobs remain: `rules/strict-v1.yaml` `e34f4ca00ba822766e05e6ccd48d3398b0245e4a`, `rules/strict-v2.yaml` `0e75b02e9305415018bb57c9b9fb8418440eb090`, `docs/releases/strict-v2/release-candidate.json` `ded5606454d3ef0afc1a0fdc0fea937d3c6cc786`, `config/project.example.toml` `a9cff0de8fbc4e6f510f3ee5e8551f4b89aeaa03`. Checked-in default is still `strict-v1`.
- At review time, GitHub search returned zero open PRs and zero open issues; historical issue #5 was confirmed `closed`. PR #24 had no unresolved review thread or PR discussion.
- Independently inspected the R3 changes in `src/turtle_value_engine/cli.py`, `evolution/activation_execution.py`, `tests/test_activation_execution_r3_probes.py`, the R3 goal/status and the operator guide. The implementation record reports pristine-base **8 failed / 3 passed** in three identical tests-first runs, and fixed-tree **11 passed**. **This reviewer did not rerun those baseline tests locally**: container `git clone` failed with `Could not resolve host: github.com`. The raw remote CI and source review, not an unexecuted local assertion, are the independent acceptance evidence.

## 2. R3 acceptance

**F1 prepared input freshness:** the R3 CLI now records input-file SHA-256s and injects two checks (before first durable write and just before config `os.replace`). Between preparation and either anchor, changed/removed named inputs produce `ACTIVATION_AUTHORITY_STALE`, with specific input labels and no config mutation. R3 tests cover policy-exception replacement/removal and forged decision-record replacement, plus fresh-invocation blocking controls. This closes the actually reproduced post-preparation drift from R3's stated baseline.

**F2 hardlink containment:** `_ConfigLock.__enter__` now checks `fstat(...).st_nlink == 1` before `flock` and refuses multi-link lock inodes with `ACTIVATION_LOCK_HARDLINK`. Existing symlink/non-regular refusal and genuine in-store contention behavior are preserved. The R3 hardlink probes are Linux/POSIX-specific and explicitly skip unsupported filesystems.

**Decision:** keep **C4-A, R1, R2 and R3 CLOSED**. The evidence supports engineering closure, not real owner economic approval or strict-v2 activation. Last-anchor-to-replace TOCTOU, non-atomic multi-file evidence and physical power-loss/multi-host certification remain documented non-claims; they are **not** selected as new defects by this review.

## 3. One newly source-backed *hypothesis*, not a reproduced vulnerability

`cli.py::_prepare_activation_inputs` first calls `load_decision_record`, `_load_policy_exceptions`, etc., building in-memory objects from the named files. **After** all these calls, it invokes `_prepared_input_file_sha256s(args)`, which calls `Path.read_bytes()` on those same paths *again*. The new digest is therefore not proven to be the identity of the bytes that actually produced the prepared object.

A same-user external writer replacing a file **after the parser consumed the original bytes but before the second hash read** could make the prepared plan use *old* authorization-relevant content while both in-lock rechecks compare a digest of the *new* on-disk content. This narrow load-to-hash race is distinct from R3's verified **post-hash** drift fixes. The existing R3 deterministic barriers start after preparation or after derivation and do not test the load-to-hash interval.

This is a **code-level hypothesis only**: no current-main TVE CLI success through this exact interleaving has been independently reproduced. No security bypass, failing test or R4 fix is claimed here. Do not replace the legitimate original R3 closure record or misrepresent its test evidence.

## 4. Selection: bounded conditional R4 probe, then practical C4-B

Select only the conditional, tests-first **Phase 7-C4-A-R4 — Prepared Input Read/Hash Consistency** at `docs/goals/phase-7-c4-a-r4-prepared-input-read-hash-consistency.md`.

Required first result: a deterministic actual-CLI test with disposable Ed25519 keys, unmodified trust root/evidence and a valid mutated canonical file, with an interleaving barrier exactly **between parsing and the new digest read**. Verify a separately started fresh CLI invocation would BLOCK, then record the real same-invocation result on a pristine pinned main **before changing production code**. Repeat and preserve command/output/hash/exit evidence. Include an ordinary no-mutation control.

- If and **only if** the pristine current main reproducibly accepts stale prepared objects (or otherwise materially violates the identity contract), make the smallest fix so every recorded digest is from the **same consumed byte buffer** as its prepared object. Recheck the original on-disk file at the two existing anchors. Keep compatible parser/error contracts and extend all named input classes; no third independent read mistaken for a fix. Rerun focused + full CI-equivalent automation and exact-head CI.
- If the interleaving does not demonstrate an incorrect result, record `NOT_REPRODUCED` with exact evidence, **make no executor/CLI security changes**, close the conditional probe, and select **Phase 7-C4-B operator-readiness** (clear read-only rehearsal/verification of receipt and rollback state using disposable fixtures) in a separate goal. Do **not** invent R5 or add unrelated lock/policy hardening.
- In either case protected profile/release/config bytes remain unchanged, default remains `strict-v1`, no real owner key/decision/config is used, and no real activation or auto-trading starts.

## 5. Human vs machine

**No human involvement is required for R4 engineering acceptance.** Use disposable fixtures, deterministic barriers and Linux CI, not an owner's cryptographic material. If a runner/platform or permission is genuinely unavailable, record attempted command, exact error, impact, automatic alternative and pass/fail evidence; do not use a vague "manual evidence incomplete" statement.

The **only separate owner-authority boundary** is a future *real* strict-v2 policy acceptance and optional private-config activation: the owner must judge the CDC 14% gate versus 12% S band, maintain their private key outside Git, sign the actual decision and explicitly approve the fresh preview/apply. Engineering or CI cannot substitute for this authorization.
