# Phase 7-C4-C-R1 — Independent post-closure review (2026-10-25)

**Disposition:** R1 is merged and its three scoped repairs have successful exact-head and merged-main CI. Preserve that acceptance, but do **not** describe its copy-ready operator hints as fully end-to-end verified: independent source inspection identifies one reproducible command-tail defect and one misleading write-step statement. Select one narrow **Phase 7-C4-C-R2 — Executable Hint Copy Boundary and Write-Step Accuracy**. Neither engineering acceptance nor this review authorizes a real owner decision, strict-v2 activation, rule revision or credential handling.

## 1. Evidence, provenance and limits

- Repository: `blooddrunk/turtle-value-engine`; reviewed `main` at **`3c282f92aa513fd77a87c0f727a3c7dbed1b89c3`**. This is a dated observation, not an instruction to reset or develop from this fixed SHA.
- R1 implementation [PR #34](https://github.com/blooddrunk/turtle-value-engine/pull/34), final PR head `1f46644566005a7a9abcc3e2ec7c3437439075fc`, merged as `9666566b9339951a2914d2ae2faf46f5da1e5c68`; closure documentation commit `3c282f9`.
- Verified GitHub Actions results against the **exact** heads: first implementation `d6265a4` [40188227158](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40188227158) = success; final PR head [40188948897](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40188948897) = success; merged main [40189862056](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40189862056) = success; current main [40190738713](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40190738713) = success. Independently inspected the latest run's job steps and raw log: **7,530 passed / 2 skipped / 9 warnings** in Python, **55 Dashboard tests** passed; other listed CI stages green.
- Inspected R1 PR file list, `owner_readiness.py` hint builders and summary identity composition, CLI handler and parser, `tests/test_owner_readiness_summary_r1_probes.py` including its hint extractor and collision diagnostic, owner handoff documentation, status and goal files, and current schema.
- The reviewer's local container could **not resolve github.com** for checkout; no independent local repo test execution is claimed. The separate standard-library `shlex.split` shell-tokenization proof below was run locally without any repository or private host. GitHub CI is remote independent execution evidence, not a claim of local replay.
- The implementation changes only the intended hint/CLI/tests/manual surfaces plus documentation; no evidence here of changed investment math, published profile bytes or activation executor. Protected file identities listed by the implementation status remain `e34f4ca0`, `0e75b02e`, `ded56064`, `a9cff0de`.

## 2. Independent findings

### F1 (P2): the advertised copyable command tail contains a Chinese full stop

In `src/turtle_value_engine/evolution/owner_readiness.py`, the new `_quoted()` correctly applies `shlex.join()`, **but** the command-bearing `_next_steps_zh` strings systematically append the literal Chinese punctuation `。` after the interpolated command (retry/status/preview and several journey branches). The manual says the command is the final segment after the final full-width colon and can be directly copied. `tests/test_owner_readiness_summary_r1_probes.py::_executable_hints` removes that terminal punctuation **before** parsing/executing; it therefore does not prove literal tail copy fidelity.

Independent source-free reproduction:

```python
import shlex
tail = "tve evolution readiness-summary --project-config '/tmp/config with spaces.toml'。"
assert shlex.split(tail)[-1] == "/tmp/config with spaces.toml。"
assert shlex.split(tail)[-1] != "/tmp/config with spaces.toml"
```

This is a **real shell-argument mismatch** if an operator copies the entire advertised tail, not a claim that any real `--apply` was invoked. Ordinary users may omit sentence punctuation by hand, but the documented machine-extractable and copy-ready contract should not rely on that. A command whose last argument is a quoted path may silently refer to a different path; a read-only command may fail or inspect the wrong input. No production shell command was executed in this review.

### F2 (P3): one write disclosure incorrectly claims exclusivity

`_next_steps_zh`'s `dossier_step` calls `decision-dossier --output` “旅程中唯一写文件步骤” while its `plan_activation_step` correctly says `plan-activation --output` also writes a plan file. This is an internal contradiction in the same informational response. R1 correctly moved both out of copy-ready/read-only commands; the remaining misleading “only writer” phrase merits a bounded text fix.

### Deferred, already reproduced: summary_id is not a full projection identity

The committed R1 diagnostic `test_diagnostic_summary_id_shared_across_distinct_store_problems` proves two outputs with the same corrupt activation-store status and same `summary_id`, but different `activation_store_problems` and different **`content_sha256`**. `summary_id` currently binds `store.status`, not every store problem/guidance. This is an **identity-contract** issue, not a command-copy fix. Preserve and explicitly track it for a separately scoped **version-aware** decision and tests; do not silently change `owner_readiness_summary_v1` identity semantics inside R2. `content_sha256` already distinguishes the complete content.

## 3. Selection and scope

Select [Phase 7-C4-C-R2 goal](../goals/phase-7-c4-c-r2-executable-hint-copy-boundary.md). **Tests first** on pristine synchronized main: capture the actual final segment after the final `：` without `rstrip` or punctuation removal; compare full-token argv and run only a no-op stub in a disposable sandbox, proving the baseline fails. Repair at the smallest hint-string boundary, correct the exclusivity phrase, and run the unchanged full CI matrix. Do not create a new state, schema, activation workflow or approval authority.

R1 remains **CLOSED with explicit follow-up**: F1–F3 addressed in its original remit, no need to revert the merged fix. R2 is additive operator-output correctness; it does not re-open real owner authorization or re-run actual activation. Leave the diagnostic summary-ID change for a separate contract-design stage.

## 4. Gate and manual boundary

**All engineering validation is automatic.** Use disposable files/keys and no-op shell stubs; no real owner signatures, external APIs, live market providers, `--apply`, rollback, private-host filesystem mutation, or real money movement. Verify tests-red-before-code, focused twice after repair, adjacent suites, full CI, exact final PR-head success, and merged-main success before recording closure. Record exact SHAs, command outputs, protected blobs and excluded optional live tests.

Only a separate, explicitly requested owner workflow could authorize strict-v2 policy selection: the owner must compare the CDC 14% pass threshold, 12% S band and 13% behavioural replay, personally decide ACCEPT-with-exception or REJECT, sign only outside repo/chat/CI using owner-controlled keys, verify a fresh read-only plan and exact config diff/hashes, and individually authorize apply or rollback. **None of those human actions are acceptance requirements for R2.**
