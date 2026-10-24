# Phase 7-C4-A-R3 — Conditional Execution Input Freshness and Lock Hardlink Containment

Status: **SELECTED / NOT IMPLEMENTED / TESTS-FIRST ONLY**. Selected by `docs/status/phase-7-c4-a-r2-post-closure-review-2026-10-24.md` after independent GitHub source/CI review of C4-A-R2. **R2 remains CLOSED**.

## 0. Mandatory sync and inspect before action

Run `git status --short`, `git fetch origin --prune`, `git log -5 --oneline origin/main`; protect uncommitted changes and construct a clean feature branch/worktree from verified latest `origin/main`, **never `git reset --hard`**. Inspect the current open PR list, relevant exact-head CI and any more recent R3 fixes; do not duplicate work if this review/goal PR merged after your starting checkout. Read `AGENTS.md`, this goal, its selection review, the R2 status, `docs/operations/profile-activation-executor.md` and the actual executor/CLI/test code before editing. Treat this specification as a hypothesis-testing gate, not a mandate to create an R3 fix.

## 1. Bounded outcome

Determine whether two source-backed residuals can be reproduced as material errors in the **actual current TVE CLI**, using exclusively disposable local Ed25519 fixtures. If reproduced, implement the smallest compatible repairs and close with full automation. If not reproduced, record falsification evidence and **do not** change executor code or invent additional vulnerabilities. No R4 by default.

- **F1 preloaded inputs:** after `_prepare_activation_inputs` but before apply, change one named file used by an in-memory plan (policy exception, decision record, signed lifecycle file, or boundary input) while trust-root and evidence bundle stay byte-identical. Source: `cli.py` preparation at roughly lines 2211–2275, narrow R2 recheck at 2291–2333, and executor in-lock derivation from prepared objects at 1688–1707. Confirm the separately launched fresh invocation fails first; report the actual same-invocation result. Use a deterministic monkeypatch barrier, not sleeps or probabilistic timing.
- **F2 hardlink lock:** on Linux POSIX, create a hard link from an *outside-store regular temporary file* to the exact computed `locks/<digest>.lock`; note `O_NOFOLLOW` plus `fstat(S_ISREG)` currently does not distinguish an external hardlink. Drive actual apply and rollback with a disposable valid receipt. Hold an external `flock` and check whether exit 3 (intended only for legitimate in-store lock contention) can be induced through that inode. Prove link count/inode identity, unchanged external bytes and zero unexpected config mutation.

These are **not yet reproduced TVE execution failures**. A standalone `os.link` primitive demonstration is not sufficient for a baseline-red claim.

## 2. Strict baseline-red/falsification protocol

1. Pin initial immutable `origin/main` SHA and HEAD CI. Add only new test file(s) to a pristine worktree of that SHA. Use the real `tests/test_activation_execution.py::_Env` fixture, runtime-generated real Ed25519 keys, on-disk trust-root/evidence, real CLI preview→apply/rollback. Never manipulate protected project files or reuse real user keys.
2. Assert exact return code, named status and blockers, before/after SHA-256 of private config, external trap hash/inode, receipt/journal/before-image/outcome existence, actual mutated input hash and (for F1) fresh-invocation truth. Run the same candidate test set at least twice; preserve commands and observed output. A green baseline must be reported as NOT_REPRODUCED and excluded from a defect-fix justification.
3. For F1 choose an input mutation that *would change authorization or plan readiness* when loaded fresh, rather than a cosmetic edit. Ensure successful valid baseline controls remain green. If the input is excluded by a documented caller contract, explain why no fix is required. For F2 create hardlinks only within temporary storage on the same filesystem; if unsupported on a local platform, automatically execute under Linux CI and explicitly report the skipped OS/FS instead of substituting manual claims.
4. Only when baseline-red proves an erroneous outcome, make the minimal change. Possible F1 approach: compare stable byte/content identities for the actually supplied preloaded authority-relevant file set at the existing pre-write and pre-replace anchors, return fail-closed named code; avoid rereading or reclassifying unrelated external files and preserve deliberate library injection behavior. Possible F2 approach: reject `st_nlink != 1` for the final lock FD before `flock` (after checking platform semantics), without unlinking any hostile inode. Do not silently change the meaning of `ACTIVATION_BUSY`.
5. Pin success cases: ordinary opt-in apply, preview byte-for-byte read-only, no inadvertent new authority from in-memory forgery, trust-root revocation/rotation, evidence tampering, legitimate single-link lock reuse, legitimate two-process one-success/one-busy, rollback and interrupted recovery, immutable store contents, no staging temp residue on blocked mutation. Preserve all R2 F1/F2 regression assertions and every historical C4-A/R1 failure-code contract.
6. No new persisted contract/schema or default-profile mutation unless an independently reproduced issue truly forces it. No broad redesign, daemon, broker integration, real strict-v2 activation, live provider/network access, or arbitrary security-gate expansion.

## 3. Automatic verification and exact evidence

Run focused tests (including `tests/test_activation_execution.py`, `tests/test_activation_execution_r1_regressions.py`, `tests/test_activation_execution_r2_regressions.py` and any new file), **then every step of the current `.github/workflows/ci.yml`**:
- `python -m ruff check .`; `python -m turtle_value_engine config validate --input config/project.example.toml`; `python -m pytest -q`;
- `systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer`;
- `pnpm --dir apps/dashboard install --frozen-lockfile`; `python scripts/export_surface_openapi.py --check`;
- `pnpm --dir apps/dashboard api:check`; `pnpm --dir apps/dashboard types:check`; `pnpm --dir apps/dashboard lint`; `pnpm --dir apps/dashboard typecheck`; `pnpm --dir apps/dashboard test --run`; `pnpm --dir apps/dashboard build`; `pnpm --dir apps/dashboard security:client-bundle`; `pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict`; `python scripts/dashboard_cross_stack_smoke.py`.
- Use the current CI workflow's documented sentinel environment when building/scanning the Dashboard, not real secrets. Compare Git blob SHA and content SHA of `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml` before/after; all must match; default stays `strict-v1`. Document actual counts and every warning/skip.
- Open a scoped PR only after baseline evidence and tests (or a clear no-fix investigation report). Verify exact-head GitHub Actions matches the PR head and passes; merge only when permission/workflow allows; verify merge-head CI; record final SHA/URL/test outcomes. Do not report an unrun check as green. Never alter historical CLOSED phase records to relabel an unreproduced issue as a proven exploit.

## 4. Human involvement, explicitly bounded

**No human action for engineering acceptance.** All reproduction, source checks, CLI operations and verification use disposable temporary files and cryptographic fixtures. If Linux hardlink/fcntl behavior cannot be tested on a developer's OS, run automatically in Ubuntu CI. If remote CI is unavailable, document exactly which job, URL/commit, reason and command are missing; do not invent a human requirement.

A subsequent *real* strict-v2 choice remains completely separate: owner reads C1 audit and decision dossier (14% CDC eligibility gate above S band's 12%), independently ACCEPT/REJECTs, manages real owner keys outside the repo, verifies a read-only preview of the private config and exact diff/id/SHA, then explicitly authorizes any real `--apply`; only then inspect receipt and optionally invoke explicit rollback. **Coding agent must not generate an owner acceptance/signature, request private keys, change checked-in defaults, or run that real step.**

## Definition of done

Truthful baseline-red **or** clearly falsified candidate matrix; smallest proven fix only; tests automated; full CI matrix and four protected blobs verified; accurate post-closure status without spurious R4; owner-policy decision deliberately left untouched.
