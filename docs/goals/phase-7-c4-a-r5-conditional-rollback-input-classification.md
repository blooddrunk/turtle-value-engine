# Goal: Phase 7-C4-A-R5 (conditional) — Rollback input classification parity

**Selection:** a conditional, tests-first source hypothesis from [C4-B-R1 independent review](../status/phase-7-c4-b-r1-post-closure-review-2026-10-24.md), NOT permission to reopen accepted C4-B/R1 or to redesign activation. Baseline at review: `8ba65c5ef72a067dc770509f0c64c202a7943ef7`. Carry out implementation only if a probe fails on the actual clean latest-main baseline.

## 0. Mandatory synchronization before any action

```bash
git status --short
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

Do not discard an existing dirty worktree: stop and preserve those changes separately. Check this goal against current `origin/main` and any newer accepted implementation before adding tests; if already fixed, prove it and close with no production change. Use a new scoped branch. Do not blindly reset or force-push; do not edit protected historical release bytes.

## 1. Exact conditional hypothesis

The read-only C4-B inspector already reports malformed `[profiles]` values as controlled facts, but the C4-A rollback executor may fail to classify malformed **hash-consistent** caller-supplied before-images and current config bytes:

- `activation_execution.py::_load_verified_before_image`: after byte hash checks, raw TOML parse and `image_parsed.get("profiles", {}).get("default")` may escape as an unclassified parser/attribute exception.
- `activation_execution.py::rollback_profile_activation`: prior-bytes idempotence branch repeats the unguarded nested `.get`.

The threat model is *forged or adversarial receipt-bound local inputs*, not forged owner authority successfully accepted by normal apply. Build all negative fixtures in disposable temp directories; do not use actual user activation state.

## 2. Reproduce first, before touching production source

Add `tests/test_activation_execution_r5_probes.py`, borrowing public helpers and throwaway runtime signing fixtures as appropriate. Minimum cases:

1. A **well-formed receipt** whose identity, hashes, path and `content_sha256` are internally consistent, with a syntactically valid but scalar `profiles = "unexpected"` before-image at its claimed SHA-256 path; arrange current config bytes to match `activated_config_sha256` and take the real `rollback_profile_activation` and literal CLI paths. Pre-fix hypothesis: an `AttributeError` escapes. Expected post-fix: deterministic named `BEFORE_IMAGE_CONTENT_MISMATCH` refusal, CLI exit class 2, no traceback, no config restore or rollback-intent/outcome write.
2. The same hash-consistent before-image with malformed TOML / invalid UTF-8. Require the same controlled named before-image error; do not hide the fault with a blanket `except Exception`.
3. A self-consistent receipt with `current_config_sha256 == prior_config_sha256`, but current TOML's `profiles` is a scalar rather than a table. Require a controlled refusal rather than `AttributeError` and no clobber. Match existing error semantics where possible; if adding a named code is unavoidable, document exact exit and why.
4. Controls: genuine signed apply -> rollback -> idempotent rollback, before-image missing, before-image hash mismatch, and interrupted-restore finalization must retain **exact** preexisting statuses and durable effects.

Use real project functions / CLI subprocess, not a duplicate mocked parser. Generate receipt identities using the actual deterministic ID/content-hash helpers, so probes reach the intended code path. Verify the fixture is not trivially rejected earlier (that would be a green test but not evidence for this hypothesis). Snapshot config and relevant `journal/`, `receipts/`, `before-images/`, `rollbacks/` before/after; account explicitly for the executor's legitimate per-config `locks/` behavior rather than falsely requiring zero writes. Assert no writes outside intended private root. Assert precise stderr/stdout and exit codes, no stack trace. No sleeps, live traffic, real signatures, external keys or manual fixture assembly.

Commit the probe tests before the fix. On **pristine baseline production code**, run:

```bash
python -m pytest tests/test_activation_execution_r5_probes.py -q
```

Record the exact SHA, complete failure summary, matching asserted line and two unchanged green controls. If no reproducible red exists, STOP implementation, explain the faulty hypothesis, leave executor unchanged, and preserve the test evidence.

## 3. Minimal repair, only if demonstrably red

Guard `profiles` types in both rollback paths; normalize parse/decode errors only at this narrow input boundary to an existing specific `ActivationExecutionError` code or the already established blocked-precondition class. Keep hashes, receipts, identity derivation, locking, journal/outcome order, idempotence, authorizer, activation-status model, schemas, strict-v1 default, economic math and all existing normal apply/rollback outcomes untouched. Do not silently "repair" forged inputs or treat an external receipt as current owner consent.

Re-run the exact unchanged probes until green twice, then focused suites:

```bash
python -m ruff check .
python -m pytest tests/test_activation_execution.py tests/test_activation_execution_r1_regressions.py tests/test_activation_execution_r2_regressions.py tests/test_activation_execution_r3_probes.py tests/test_activation_execution_r4_probes.py tests/test_activation_status.py tests/test_activation_status_r1_regressions.py tests/test_activation_execution_r5_probes.py -q
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest -q
```

Run the remainder of **.github/workflows/ci.yml** unchanged: systemd verification, OpenAPI check, dashboard frozen install/api:check/types:check/lint/typecheck/55-test/build/client-bundle secret scan, Wrangler strict dry-run, cross-stack smoke. On Windows without systemd or other CI tools, do not request a manual workaround: use the Linux GitHub Actions run on the exact PR SHA as the authoritative substitute and record the locally unavailable step/error.

Compare Git blob IDs of `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml` against the pinned review SHAs; all must be byte-identical. Default stays `strict-v1`.

## 4. Closure and reporting

Write `docs/status/phase-7-c4-a-r5-YYYY-MM-DD.md` with the actual baseline head, tests-first red/green evidence or falsification, exact commands/results, before/after state proof, scoped code diff, protected-byte SHA checks and remaining limitations. If reproduced, open one scoped PR, confirm **exact head SHA** Actions success, and after authorized merge verify merge-head and latest-main CI. Don't report CI as passed before it has completed. If remote access/permission fails, state exact attempted command/API, returned error, permission owner, resume command, automated alternative, machine-checkable pass criterion and exactly what remains unverified.

**Human intervention boundary:** none for implementation, code review, fixture generation or tests. Do NOT request owner keys, policy exception signatures or a real strict-v2 activation for this phase. A future optional live owner decision (14% CDC pass threshold versus 12% S band), independently signed decision, fresh preview and explicit application require deliberate **separate human authorization**; they are not verification substitutes.

## 5. Stop conditions

Stop rather than expand scope if the hypothesis is false, changes affect published bytes or calculation semantics, tests require real owner credentials, or a proposed fix alters receipt/rollback persistence protocols. Report why and propose a separately reviewed goal instead.
