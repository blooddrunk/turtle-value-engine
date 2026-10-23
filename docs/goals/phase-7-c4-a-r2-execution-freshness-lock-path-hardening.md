# Phase 7-C4-A-R2 — Activation Authority Freshness and Lock-Inode Containment

Status: **IMPLEMENTED / CLOSED** (see `docs/status/phase-7-c4-a-r2-2026-10-23.md`). Selected by `docs/status/phase-7-c4-a-r1-post-closure-review-2026-10-23.md`. R1 and C4-A remain **CLOSED**.

## 0. Mandatory sync, evidence and branch discipline

Before changing code: `git status --short`, `git fetch origin --prune`, `git log -5 --oneline origin/main`, examine current open PRs and exact-head GitHub Actions. Never discard unrelated work or use a destructive `git reset --hard`. If the selection-doc PR is open, inspect it first; merge it only after its exact-head CI success, or incorporate its authoritative content without duplicate divergent goals. Start a clean implementation branch/worktree from **latest** `origin/main` after this inspection, not the historic `fca90d6` review snapshot.

Read `AGENTS.md`, the R1 goal/closure/post-closure review, `docs/operations/profile-activation-executor.md`, full `evolution/activation_execution.py`, activation input preparation/CLI handling in `cli.py`, actual fixture/test helpers, and current `.github/workflows/ci.yml`.

## Outcome and strictly bounded scope

Tests-first evaluate and, **only when reproduced**, repair two specific local activation-executor candidates:

- **F1: authority-read-to-mutation freshness**. The CLI currently constructs `_prepare_activation_inputs(args)` (including `_load_trust_root_snapshot`, the evidence verifier, decision/revocation/exception material) **before** `apply_profile_activation` enters `_ConfigLock`. The latter re-derives a plan under the lock, but with those previously loaded authority objects. Determine whether an owner key revocation or authoritative trust-root revision occurring **inside the same apply invocation after input load and before protected execution** is missed. The existing "revoke after an earlier preview, before a later apply command" test is not this case. New mutation must require authority/evidence actually current at the execution boundary, and a recorded explicit expected-plan/config binding. This is a source-backed hypothesis, **not a demonstrated bypass** until failing baseline tests establish it.
- **F2: existing lock-file symlink**. `_guard_activation_store` verifies directories, but `_ConfigLock.__enter__` currently calls `os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)` without `O_NOFOLLOW` or post-open inode/type verification. A pre-existing final-component symlink may bind the lock to a foreign temporary file, even though the `locks/` directory is legitimate. Show the actual behavior in an isolated `tmp_path` trap and require no outside-store lock acquisition or protected config mutation on the hostile layout.

Avoid an open-ended security audit, new signing protocol, owner approval requirements, provider calls, daemon restarts, Dashboard work, policy changes, or claims of perfect transactional consistency across independent files/actors.

## 1. Mandatory baseline-red / falsification first

In a **pristine current-main worktree** without modifying production code, add deterministic regression tests. Run them at least twice and record exact SHA, invocation, expected vs actual status/exit code, config SHA-256 before/after, trust-root latest-snapshot identity before/after, directory/file side effects, and stdout/errors; put test case names, observed evidence, and the baseline-to-fixed mapping in the implementation PR.

**F1 baseline tests**, all with disposable runtime Ed25519 owner signing keys, real trust-root registry/evidence files, READY preview, temporary private TOML and no network:
1. Establish a fully authorized ordinary apply control case.
2. Install a deterministic barrier at the transition from CLI input preparation to executor lock entry; rotate/revoke the signing key in the real temporary trust-root store after preparation but before fresh plan derivation. Assert whether the old prepared registry still enables `ACTIVATED` (candidate failure), and inspect exact bytes after.
3. Distinguish an unauthorized older preview from this **within-one-invocation** race; retain the existing after-preview rejection test.
4. If necessary, inject another barrier before actual config `os.replace` to determine whether a changed authoritative snapshot can escape a purported final freshness check. Do not assume an ability to make independent storage changes globally atomic; state the tested observation window precisely.
5. Include normal revocation/rotation blocking, stale evidence/decision material as applicable and unchanged owner-authorized success/recovery.

**F2 baseline tests**, all paths disposable:
1. Derive the exact lock filename for a private test config; make `activation_root/locks/<digest>.lock` a symlink to an **unrelated temporary regular file**.
2. Exercise apply and explicit receipt-bound rollback separately and capture external file open/flock behavior, exit classification, config hash and store contents.
3. Verify a normal existing regular lock file and real two-process contention still work. Include non-regular lock targets and permission/open failures; `ACTIVATION_BUSY` exit 3 must mean only genuine flock contention.

**Gate**: fix a candidate only when it fails reproducibly on pristine main, or when a clear existing documented contract invariant independently demands it. A non-reproduced candidate becomes **UNPROVEN** with evidence, not invented failing tests or a gratuitous code change. Keep code diffs minimal.

## 2. Minimal fixes conditioned on reproduction

For F1, make execution-time authority and the active evidence/decision association genuinely current at the protected mutation boundary; do not silently treat old pre-lock `registry`/`verifier` objects as fresh after trust-root changes. Prefer a small shared refresh/revalidation function or injected loader that runs inside the lock for CLI apply, and a narrowly checked last-moment authoritative anchor where evidence warrants. Ensure the library entry point's explicit supplied verifier/trust-root contract remains documented; do not break preview's strictly read-only behavior, signed evidence verification or existing C2/C3 snapshot semantics. A changed trust root should result in a **named, fail-closed** status without replacing config. Never imply a cross-process/global atomic commit that is not provided.

For F2, avoid following a pre-existing final-component lock symlink (e.g. supported POSIX `O_NOFOLLOW` plus `fstat` type/inode consistency, with honest platform boundary). Reject other unsafe lock entries with stable error codes; do not unlink or alter foreign targets. Preserve non-blocking `flock` single-config mutual exclusion, deterministic lock naming and true contention semantics. Never introduce a "delete stale lock to recover" procedure.

Apply and rollback must still guard activation-root descendants before any mutation. Preserve immutable journals, before-images, receipts and rollback intents/outcomes including existing process-interruption recovery and `fsync` ordering. Rollback does **not** acquire or invent a new signed owner policy decision: it is an independent explicit receipt-bound restoration operation.

## 3. Mandatory fully automatic acceptance

1. Focused new baseline-red tests must pass on the fixed branch and demonstrate the originally observed failure on the *actual* prior main, preserving all existing focused tests. Include no-write/exit-code/hash evidence, replay idempotence, the real two-process 0/3 lock outcome, normal prior READY-preview/apply/rollback, rollback interruption finalization, and authority revocation/rotation.
2. Run exact commands in current `.github/workflows/ci.yml`: Python Ruff; config validate (default `strict-v1`); full Python pytest; systemd-analyze verify; checked OpenAPI export; frozen pnpm Dashboard dependency installation; API/types/Wrangler type parity, lint, typecheck, Dashboard 55+ tests, build, client-bundle secret scan, strict Wrangler dry-run, cross-stack smoke. Run CI-equivalent validation automatically; if any job is unavailable, explicitly name the command, reason and independent remote CI coverage rather than claim a pass.
3. Compare protected file SHA-256 and/or Git blob identity against current main: `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml`. Exact byte equality required; default stays `strict-v1`.
4. Attach human-readable and machine-readable test matrix with baseline SHA, fixed SHA, named outputs, reproducible command, CI URLs and exact head SHA. No real keys, credentials, actual owner signature, policy exception consent or production config copies in Git, logs or test artifacts.
5. Open an implementation PR, check all **exact implementation-head** Actions jobs `success` before requesting merge; after merge inspect the actual **merge-head** CI, then write a truthful closure record. Do not declare closure on `main` while CI is pending.

## 4. Human intervention — explicit boundary

**None for R2 engineering acceptance.** Temporary real-crypto fixtures, deterministic fault/barrier injection, automated subprocess contention and remote CI are sufficient. No human should be asked to manufacture a signature, approve a real strategy change, or run an undocumented manual smoke test for R2.

A real `strict-v2` switch is a **separate, optional owner decision**: first review the material CDC 14% PASS threshold versus S-tier 12% yield band (including 13% behavior), decide ACCEPT/REJECT and any matching signed exception, use the owner's private trust root, inspect the full READY diff and fresh hashes, then explicitly apply and verify receipt/rollback. This policy choice does **not** block R2 technical completion; never enable `strict-v2` in repository defaults.

## Definition of done

Reproduced F1/F2 violations either fixed with named fail-closed behavior, or honestly falsified and explicitly closed as unproven; no artificial test failures; complete automatic verification and exact-head CI links; historical R1/C4-A closure remains unchanged; no real policy/owner actions; no speculative R3 or broad C4-B implementation in this PR.
