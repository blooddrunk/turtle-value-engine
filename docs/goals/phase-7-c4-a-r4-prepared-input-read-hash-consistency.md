# Phase 7-C4-A-R4 — Conditional Prepared Input Read/Hash Consistency

Status: **SELECTED FOR TESTS-FIRST REPRODUCTION; NOT IMPLEMENTED**. Selection: `docs/status/phase-7-c4-a-r3-post-closure-review-2026-10-24.md`. R3 remains CLOSED. No automatically selected R5.

## Step 0 — synchronize before any work

Run `git status --short`, `git fetch origin --prune`, `git log -5 --oneline origin/main`; protect local modifications; use a clean feature branch/worktree created from verified latest `origin/main`, **never** `git reset --hard`. Inspect latest open PRs/CI and avoid duplicate goals after this review PR merges. Read `AGENTS.md`, this goal, the selection review, `docs/status/phase-7-c4-a-r3-2026-10-24.md`, `docs/operations/profile-activation-executor.md`, and current CLI/executor/probe tests.

## Objective — prove or falsify ONE bounded source hypothesis

The CLI parses the named decision records, policy exceptions, revocations, boundary input and signed lifecycle statements into prepared objects, then **independently re-reads their paths** to compute `prepared_input_file_sha256s`. An external mutation *between the read used for parsing and the new digest read* may bind the new bytes' hash to an old prepared object, so the two R3 anchors can approve stale in-memory authority. This is **not yet reproduced**; a theoretical interleaving is not proof.

### First: pristine-baseline deterministic proof, tests only

1. Pin the current exact `origin/main` SHA and its CI. Work in a pristine tree with only new tests; no runtime edit before baseline. Use existing `tests/test_activation_execution.py::_Env`, generated throwaway real Ed25519 keys, real trust-root and authority-evidence bundle, temp private config and activation root.
2. Drive the actual `record-decision` / READY preview / `activate-profile --apply` CLI path. Inject a deterministic monkeypatch barrier immediately after the exact file read/parser consumption but **before** `_prepared_input_file_sha256s` re-reads that file. Replace a policy exception with different *valid canonical* bytes preserving `exception_id` but changing `content_sha256` (or a forged-annotation record); keep trust-root and bundle bytes strictly unchanged. Do not rely on sleeps.
3. Establish the truth-control: a separate fresh invocation on the mutated bytes must return exit 1 `ACTIVATION_BLOCKED` with the appropriate `DECISION_EXCEPTION_BINDING_STALE` / `EVIDENCE_RECORD_CONTENT_MISMATCH` blocker and unchanged config. Demonstrate the actual same-invocation exit/status, plan/config digests, prepared-vs-disk file identity, journal, receipt and before-image. A simple mock return value or function call with no real CLI path is insufficient.
4. Repeat the baseline twice with identical observed results, record commands and output (including an ordinary no-mutation success control). Distinguish failures in test setup from real behavioral failures. The old R3 post-preparation replacement tests must remain green.
5. If no incorrect same-invocation behavior is reproduced: mark **NOT_REPRODUCED**, do not change runtime code, close this conditional probe with evidence and propose C4-B operator-readiness as the next separately scoped goal. **Do not write hypothetical-failure assertions as if verified.**

### Only if a real incorrect result is reproduced — smallest repair

- Carry the digest of the *exact byte buffer consumed by the parser* into `prepared_input_file_sha256s`; parse and hash the same bytes (or use a bounded shared loader/parse-bytes helper preserving existing validation and errors). Cover all **actually supplied** named preloaded inputs, including repeated paths, boundary input and signed lifecycle inputs; avoid silently using a second read as the authority for the original object.
- Keep the two R3 in-lock file freshness anchors. Maintain exact status/exit behavior and read-only planner/preview semantics; do not alter explicit library-verifier contracts, receipts, rollback, lock acquisition, fsync or unrelated file handling. For an input replaced during initial reading, fail closed rather than inventing a valid prepared identity.
- Assert old R3 tests, new deterministic barrier tests, recovery/idempotence and genuinely busy 0/3 lock contention remain green.

## Automated verification and exact evidence

- Focused: `python -m pytest tests/test_activation_execution_r3_probes.py tests/test_activation_execution_r2_regressions.py tests/test_activation_execution_r1_regressions.py tests/test_activation_execution.py -q`; run any new R4 tests twice; add owner/provenance suites if touched.
- Full: `python -m ruff check .`; `python -m turtle_value_engine config validate --input config/project.example.toml`; `python -m pytest -q`; `systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer`; `python scripts/export_surface_openapi.py --check`; `pnpm --dir apps/dashboard install --frozen-lockfile`; `pnpm --dir apps/dashboard api:check`; `pnpm --dir apps/dashboard types:check`; `pnpm --dir apps/dashboard lint`; `pnpm --dir apps/dashboard typecheck`; `pnpm --dir apps/dashboard test --run`; `pnpm --dir apps/dashboard build` (CI sentinel environment as defined in workflow); `pnpm --dir apps/dashboard security:client-bundle`; `pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict`; `python scripts/dashboard_cross_stack_smoke.py`. Follow actual updated `.github/workflows/ci.yml` if changed.
- Compare blobs/SHA-256 with pinned base: `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml`; must be unchanged. Project default stays `strict-v1`; no real key, decision, policy exception, private config, brokerage credential, live provider or trading.
- Open one bounded PR with exact baseline SHA, observed red/green evidence, resulting fix OR falsification, focused/full gate and protected-blob proof. Verify Actions `head_sha` equals exact PR commit SHA before merging. If merged, check merge-head CI exact SHA and add closure record. Do not claim green while jobs are pending.
- For any genuinely unavailable automation: write *exact command*, failure output, why missing, a supported CI/Linux automatic fallback, what remains unverified, and a human procedure **only if unavoidable** with precise input, steps, expected status/hash, pass/fail and scope. No catch-all "manual evidence incomplete".

## Next package if falsified / after narrow R4 closure

Prefer **Phase 7-C4-B — Local Operator Rehearsal and Activation State Verification** in a new separately reviewed goal: an entirely offline, human-readable Chinese-first dry-run/rehearsal with disposable credentials/config; read-only state inspection of receipt, journal, before-image and rollback result; simple explicit recovery/rollback guidance, zero real activation; all verifiable with generated fixtures. Do not add a security-hardening R5 without independently reproduced new evidence.

## Human boundary

**Engineering acceptance requires zero human steps**. Only a future *real* strict-v2 economic-policy decision and optional private config activation require the owner's deliberate action: review 14% CDC gate vs 12% S valuation band, use owner-controlled key outside Git to sign the actual decision, inspect real READY plan/diff and separately invoke apply. Automated tests never simulate that they are the owner's actual authorization.
