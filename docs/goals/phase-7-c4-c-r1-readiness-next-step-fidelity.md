# Goal: Phase 7-C4-C-R1 — Readiness Next-Step Command Safety and Context Fidelity

**Selected by:** `docs/status/phase-7-c4-c-post-closure-review-2026-10-25.md` after an independent connector-based review of merged C4-C PR #32. The current source commands themselves remain informational; this phase repairs misleading or unsafe **operator-facing hints**, not the existing policy/authority/executor logic.

## 0. Mandatory first action: synchronize latest repository state

Execute before any edits, without discarding uncommitted changes:

```bash
git status --short
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git log -5 --oneline
```

If dirty, preserve changes in a separate branch/worktree; do not `reset --hard` or stash blindly. The reviewer saw main at `3357b81a70228d129938402f681ba6e519f5b2e3`, **but this is an observation, not a hardcoded development base**: resolve and pin the new actual `origin/main`. Read `AGENTS.md`, `docs/spec/`, `docs/roadmap.md`, the C4-C goal/closure and post-closure review, `src/turtle_value_engine/evolution/owner_readiness.py`, its CLI parser/handler, C4-C tests, and `docs/operations/owner-readiness-handoff.md`. Check whether this exact repair is already present on main or an active PR before changing code.

## 1. The bounded demonstrated defects

**F1 (P1, independently shell-reproduced):** shell command-like hints contain bare `<决策记录>`/`<策略例外>`/`<信任根>`/`<证据束>`/`<执行存储>`/`<你的路径>.md`. POSIX shells treat these as I/O redirects, and a no-op stub in a temporary directory demonstrated unintended creation of `--policy-exception` and `--project-config` files plus mangled argv. Neither a shell-valid token nor a clear human input is guaranteed. **Do not copy any present hint into a real private host.**

**F2 (P2, source-confirmed):** retry `readiness-summary` hints re-emit only base/target/manifest/config/optional store, dropping the decision/exception/revocation/trust/evidence/lifecycle/boundary inputs. The displayed command can incorrectly reset an authenticated observed journey to `OWNER_DECISION_REQUIRED`.

**F3 (P2, parser-confirmed):** `plan-activation` and `decision-dossier` require an `--output` and persist files; some hints mislabel these file-creating steps as read-only inspection. Any persisted step must be separated, explicitly described as an opt-in write, and never silently executed.

## 2. Desired minimal behavior and invariants

1. Preserve `tve evolution readiness-summary` as a deterministic, Chinese-first **zero-write** informational JSON command. No new authority or automatic execution. All source facts, 11 `journey_state` values, exit classes 0/2, no `--output`, schema drift parity, stable names and fixed boundary literals remain intact.
2. For executable **read-only** next-step commands, compose from argument vectors with safe POSIX quoting (`shlex.join` or equivalent). Never interpolate raw unquoted placeholders or shell operators, and never synthesize `--apply`, rollback, signing, registration or `--output` commands as if they were read-only. The only executable next-step text is an explicitly validated safe read-only operation with all **required** inputs actually known; otherwise emit ordinary prose requesting missing parameters and/or point to the existing runbook (not a fake paste-ready command).
3. Keep context fidelity. When a retry/preview command is advertised as a replay of the observed state, carry the exact effective file-path inputs in their original repeatable order: `--decision-record`, `--policy-exception`, `--revocation`, `--trust-root`, `--authority-evidence`, `--signed-revocation`, `--signed-supersession`, `--boundary-input`, `--activation-root`, plus pair/manifest/config. If the library boundary lacks CLI path provenance, pass a **small bounded read-only hint input** from the CLI handler, or refrain from generating a replay command. Do not reinterpret parsed owner records into new files, invent trust-root paths, or serialize signing secrets. If no activation root is supplied, do not emit a purportedly runnable `activate-profile` preview (the parser requires `--activation-root`).
4. Clearly distinguish `readiness-summary` and `activation-status` (read only), `activate-profile` without `--apply` (read-only preview; mandatory arguments), and `decision-dossier`/`plan-activation` (`--output` creates a file). If mentioning file-creating commands, describe the write destination and require explicit operator choice; ensure they cannot be mistaken for zero-write.
5. Maintain full path secrecy boundary: never print private keys or secret contents; only operator-supplied path references already needed for the particular hint. Check injection through whitespace, apostrophes, semicolon, `$`, backticks and shell redirection characters. A quoted placeholder still isn't real input: label it non-executable and do not claim it is copy-ready.
6. Do **not** alter `activation_execution.py`, `activation_status.py`, owner-authentication semantics, `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, release manifest, config template or deterministic investment math. Do not introduce a daemon, live broker integration, LLM policy approver or automatic strict-v2 enablement. Minimize output/schema changes; when changing any public contract, explicitly justify and add parity tests instead of silent drift.

## 3. Tests-first (entirely automatic)

Before production fixes, add `tests/test_owner_readiness_summary_r1_probes.py` (or another clearly named focused suite) reproducing F1–F3 **on pristine synchronized main**, alongside at least one unchanged green C4-C control. Record actual red assertion failures and the exact base SHA. No manual fixture assembly and no real credentials.

Minimum matrix:

- Baseline bare hints: demonstrate shell redirection side effects in a **temporary** directory with a stub/no-op command, never executing the real activation CLI; assert resulting argv is corrupted and unexpected files can be created. After repair, shell command-like suggestions must tokenize as intended and a safe stub execution must produce neither redirection artifacts nor a hidden write. Test both ordinary placeholder cases and user-supplied paths with spaces/metacharacters.
- Verified throwaway ACCEPT journey: generate hints and compare the parsed replay argv to the actual supplied decision, policy exception, trust root, authority evidence, custom boundary input, and activation root. `readiness-summary` replay must retain the same verified decision/authority and projected state when all inputs are unchanged. Use real CLI temporary fixtures for parsing and authority checks, not hand-built fake status strings.
- Repeatable `--decision-record`/`--revocation`/`--policy-exception`/`--signed-revocation`/`--signed-supersession` preserve order, multiplicity, and quoting, or omit the shortcut with **explicit** explanation when exact replay is not feasible.
- `activation-root` omitted: do not emit an executable incomplete preview. Inspect `OWNER_DECISION_REQUIRED`, `OWNER_AUTHORITY_NOT_PROVEN`, `DECISION_CONFLICT`, `ACTIVATION_BLOCKED`, `PREVIEW_READY`, `RECOVERY_PENDING`, `ALREADY_APPLIED` and `ROLLED_BACK` cases for honest and safe guidance.
- Check file-writing commands are never labeled read-only/copy-ready. The summary itself never creates files, directories, locks or receipts: take whole-tree before/after snapshots for successful and refused paths, including any safe-command-output tests. No network sockets; no private-key contents; fixed `summary_is_informational_not_authorization=true`, `automatic_activation_allowed=false`, `execution_performed=false`.
- Real test-fixture executor preview/apply/rollback/idempotence controls remain green, with unchanged activation and receipt semantics. `strict-v1` remains default.
- **Diagnostic only, not R1 scope:** evaluate the review's `summary_id` partial store-binding hypothesis in an isolated regression if inexpensive. Log whether actually reproduced; if true and independently material, propose a separate, version-aware task rather than silently broadening R1.

After minimal repair run the focused suite twice and all adjacent C4-C, C4-B/R1, C4-A/R1–R5, owner C2/C3 suites. Then `python -m ruff check .`, `python -m turtle_value_engine config validate --input config/project.example.toml`, `python -m pytest -q`; run the unchanged `.github/workflows/ci.yml` matrix: systemd, OpenAPI, Dashboard frozen install/types/lint/typecheck/test/build/client-bundle scan, Wrangler strict dry-run and cross-stack smoke. Compare the four protected Git blob SHAs with the previous review (`e34f4ca0` / `0e75b02e` / `ded56064` / `a9cff0de` prefixes).

## 4. Deliverables and evidence

One scoped implementation PR, focused baseline-red/after-green tests, minimal production hint fix, and any necessary Chinese manual correction. Create `docs/status/phase-7-c4-c-r1-YYYY-MM-DD.md` with actual baseline SHA, exact repro commands/output, green test totals, before/after tree proof, protected blob parity, limitations and execution exclusions. Review exact PR-head workflow run SHA and `success` before merger; inspect merged-main SHA and CI afterward. Do not claim full CI before it finishes. Clearly distinguish implementer-local proof from reviewer remote CI log verification.

**Engineering acceptance requires zero human interaction.** If optional real owner strict-v2 policy selection is contemplated separately, explicitly stop at a decision boundary: owner reads current 14% vs 12% audit and 13% replay, personally decides ACCEPT-with-exception or REJECT, signs locally using private trust material outside repo/chat/CI, runs a fresh read-only preview, checks exact config diff + expected hashes, and executes apply/rollback **only under separate explicit instruction**. Never request private keys, forge approvals, assume CI grants authorization, or perform a live activation in this task.
