# Phase 7-C4-A-R1 Independent Post-Closure Review / Phase 7-C4-A-R2 Selection — 2026-10-23

Status: **C4-A and C4-A-R1 CLOSED / R1 engineering evidence ACCEPTED; C4-A-R2 SELECTED, NOT IMPLEMENTED**.

## 1. Verified immutable baseline and acceptance

- Repository: `blooddrunk/turtle-value-engine`; reviewed the actual default-branch HEAD `fca90d68eabc00df747c931c67ba5672d9e7ddb1`. R1 implementation PR [#20](https://github.com/blooddrunk/turtle-value-engine/pull/20), exact implementation head `9f705bc2874bb3b5282dd2fcdc2967cb898b08aa`, merged as `cb765a15d4dd612e412d84b8dc735b3b52f53e5e`; documentation-only closing commit `fca90d6`.
- Independently checked [exact PR-head Actions 39894740310](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39894740310) (`success`, matching `9f705bc`), [merge-head Actions 39895218864](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39895218864) (`success`, matching `cb765a1`), and [current-main Actions 39895860150](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39895860150) (`success`, matching `fca90d6`).
- Independently inspected latest main CI job steps and raw job logs (job `120226039068`): Python **7381 passed / 2 skipped / 9 warnings**, Dashboard **55 passed**; Ruff, config validation, systemd, generated OpenAPI/types, lint/typecheck/build, client-bundle secret scan (4 files), strict Wrangler dry-run and cross-stack smoke all passed. The Node 20 runner deprecation warning is non-blocking and unrelated to R1.
- R1 closure documents baseline-red 21 failures / 3 controls green on pristine pre-fix `3e1520e`, and 24 green on fixed tree. Reviewed actual regression test definitions and implementation, including descendant store guard, `ProfileActivationRollbackIntentV1`, published rollback outcome revalidation, CLI original argv reconstruction/quoting, parent-directory fsync. The reported baseline-red runs are coding-agent evidence **not rerun independently in this review**.
- Compared Git blob SHA of the four protected artifacts at `3e1520e` versus `fca90d6`; exact matches for `rules/strict-v1.yaml` (`e34f4ca`), `rules/strict-v2.yaml` (`0e75b02`), `docs/releases/strict-v2/release-candidate.json` (`ded5606`), `config/project.example.toml` (`a9cff0d`). Checked-in default remains `strict-v1`; no real signed owner approval or strict-v2 activation performed.
- GitHub API showed zero open PRs and zero open issues at the review baseline. PR #20 had no review comments/threads. Local `git ls-remote` failed on DNS resolution of github.com, so this review cannot claim reviewer-local tests, independent baseline-red execution or real power-loss proof.

**Decision:** R1 **CLOSED**. Its four recorded defect repairs meet their stated automated acceptance; no retroactive rewrite of R1 or C4-A implementation/closure.

## 2. New source-backed hypotheses for narrow test-first R2

### F1 — stale latest-authority snapshot inside a single apply invocation (highest priority)

In `src/turtle_value_engine/cli.py`, `_run_evolution_activate_profile_command` calls `_prepare_activation_inputs(args)` before dispatching into `apply_profile_activation` (around lines 2447/2483). Preparation loads `_load_trust_root_snapshot` and constructs `SignedOwnerProvenanceVerifier`, `lifecycle_trust_root` and signed evidence objects (around 2211–2279). In `activation_execution.py`, `apply_profile_activation` then enters `_ConfigLock` and re-derives its plan from those **already prepared** objects (around 1516 and 1589–1608), not by reloading the latest on-disk trust root.

Existing test `test_revoked_key_after_preview_blocks_apply` (around 862) revokes *between separate CLI invocations*, so it does not prove a change *after preparation but before mutation inside one apply*. Whether such a change can actually permit a stale-authority apply is a **hypothesis requiring a deterministic real-crypto baseline-red test**. It would contradict the expressed C4-A requirement to verify current owner authority at the mutation boundary; do not label it a proven authorization bypass before testing.

Baseline gate: with only throwaway keys, revocation/rotation as a deterministic barrier between preparation and lock entry; assert config hash, artifact writes, exact exit/status, snapshot identities. If reproduced, refactor minimally to bind final execution to genuinely refreshed authority inside the lock (and test a last-moment drift checkpoint when justified), preserving owner opt-in. Document independent-writer TOCTOU limits honestly.

### F2 — final lock-file symlink follows a foreign inode (secondary)

R1's `_guard_activation_store(root, _APPLY_STORE_DIRS/_ROLLBACK_STORE_DIRS)` checks ancestor *directories*. `_ConfigLock.__enter__` uses `os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)` (around 740–744) and then `fcntl.flock`, without final-component `O_NOFOLLOW`/regular-inode validation. A pre-existing `locks/<digest>.lock` symlink to an unrelated **temporary** file may make apply/rollback lock a foreign inode, even though the parent `locks/` is safe. This is an untested source-level containment candidate, not an assertion that a malicious race has been reproduced.

Baseline gate: create the exact final-component symlink to a disposable trap file and run signed, private-fixture apply and rollback. Assert actual open/flock result and config bytes; compare ordinary regular lock behavior and real dual-process contention. If confirmed, refuse with a stable error and no external lock acquisition, preserving actual `ACTIVATION_BUSY` semantics. No need for a general `openat` framework or adversarial multi-actor guarantees in this limited personal/offline executor.

## 3. Selected next task and limits

Select **Phase 7-C4-A-R2 — Activation Authority Freshness and Lock-Inode Containment** with goal `docs/goals/phase-7-c4-a-r2-execution-freshness-lock-path-hardening.md`. This is an **engineering reliability follow-up**, not a new policy release. It must establish failing baseline evidence before changing production code; if a candidate does not reproduce, record UNPROVEN and skip its fix. Retain strict-v1 defaults and released artifacts byte-for-byte.

No real owner key, genuine consent, activated strict-v2 private config, network provider, Cloudflare deployment, scheduling or manual operational gate is needed to complete R2. No real owner decision should be simulated or silently requested. Only an explicitly separate real strict-v2 opt-in would require a human policy decision after reviewing the CDC 14% PASS versus S 12% band and 13% discrepancy.

Defer broader **C4-B** design until the two concrete local executor boundaries are reproduced and resolved or falsified. Do not automatically create an endless chain of further R-phases on purely theoretical risks.
