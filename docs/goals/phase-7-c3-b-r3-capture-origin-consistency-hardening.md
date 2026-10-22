# Phase 7-C3-B-R3 — Capture-Origin and Authority-Annotation Consistency (tests first)

Status: **IMPLEMENTED / CLOSED** (implementation `cbf88a4673aa233e852a4879cbb090579871516b`, PR #16 merged as `720720edf90f608f05b19730d58ca13d2d98f1fc`; exact-head Actions run `39752585126` `success`, merge-head run `39753385499` `success`; closure record `docs/status/phase-7-c3-b-r3-2026-10-22.md`). Selected by `docs/status/phase-7-c3-b-r2-post-closure-review-2026-10-20.md`; R2 remains **CLOSED**. This document does not authorize switching any profile or implementing an activation executor.

## Mandatory first step: synchronize the latest code

Inspect `git status --short`, `git fetch origin --prune`, `git log -5 --oneline origin/main`, the current PR list and exact-head Actions. Preserve dirty changes (separate worktree, never `reset --hard`). Create a fresh worktree/feature branch from **verified current origin/main**. Read `AGENTS.md`, this goal, the R2 closure and post-closure review, the real store/provenance/planner code, and CI. Do not assume the selection review's SHA is still current.

## Phase goal and exact candidate findings

Strengthen the distinction between faithfully replaying a historical evidence capture, *reading* it for a downstream consumer, and **fresh plan-time authority**. Verify three hypotheses from static code review before any repairs:

1. **F1 provenance source bytes**: replay checks `record.provenance.source_content_sha256` against actual decision bytes, strict loader apparently does not. Modify this field only on a genuine VERIFIED capture, and recompute all deterministic record and bundle IDs/hashes, physical component contents, and matching bundle directory. Confirm replay mismatch, loader outcome, real CLI exit behavior and plan-time fail-close.
2. **F2 remaining authority claims**: separately forge `record.authority.verifier_kind`, `allowlist_matched` (false/null), and `reason_code` on a genuinely VERIFIED capture, recomputing every deterministic binding as above. Compare with the actual `SignedOwnerProvenanceVerifier` record-time values. Determine whether replay/loader incorrectly treat the false capture annotations as genuine, while keeping plan-time fresh verification separate. Study `detail` only as an optional compatible audit-text concern; never anchor security on free-form wording.
3. **F3 unsigned supersession**: change only a captured record's `supersedes_decision_record_id`, rebinding all deterministic identities. Signed input has no supersession field; normal capture does not generate this metadata. Verify offline replay/strict load and demonstrate the existing plan-time unsigned-supersession rejection. Preserve separately signed lifecycle revocation/supersession support.

Required controls: genuine VERIFIED capture, honest REJECTED/INVALID capture, honest INVALID with VERIFIED crypto, repeatable socket-denied offline replay, current trust-root revocation READY→BLOCKED, no duplicate/foreign bundle effects. All signatures and keys must be throwaway runtime Ed25519 fixtures. No mocked verifier in candidate reproductions.

**Baseline gate**: commit exact pre-fix failing/passing assertions and pristine baseline SHA. If a hypothesis does *not* reproduce, report the counter-evidence and eliminate its proposed change rather than manufacturing a red test or widening scope. A source-observed absence of a check is NOT an executed exploit.

## Minimal implementation only after a red baseline

- Prefer shared explicit coherence checks consumed by replay **and** strict loader. Correct only reproduced inconsistencies, keeping stable named machine-readable mismatch codes. Replay of parseable diverging evidence must produce `MISMATCH` and CLI exit **1**; strict downstream consumption must fail closed with classified error/CLI exit **2**. Malformed/missing/symlink components must still fail closed.
- Do not equate historical byte integrity with fresh authorization. The activation plan must continue to re-attest against the operator's **current** trust root. An honest historically REJECTED capture still replays as historical evidence, without becoming an authorized decision.
- Keep existing valid persisted V1 contracts, schema fields, default profile, published bytes and IDs unchanged where possible; explicitly assess historical bundle compatibility before changing behavior. Do not invent missing C1 audit inputs or claim to re-run the economic audit from a bundle. No activation executor, profile switching, owner decision, real key generation, network provider, or LLM-based deterministic math.
- Do not enforce the bundle directory basename without an independently demonstrated security/contract requirement; archived/relocated evidence may be valid.

## Full automatic acceptance

1. Run identical new real-fixture adversarial tests on clean pristine current main and on the implementation branch; preserve concise terminal evidence with exact commands and assertion excerpts. Tests must exercise model-valid fully rehashed artifacts, physical files, loader, offline replay, CLI exit 0/1/2, and read-only plan behavior.
2. Run `python -m ruff check .`, relevant focused pytest suites, `python -m pytest -q`, and all actual current `.github/workflows/ci.yml` equivalents: config validate, `systemd-analyze verify`, checked OpenAPI, dashboard `api:check`, `types:check`, lint, typecheck, tests, build, client-bundle secret scan using **only test sentinel values** from CI, Wrangler strict dry-run, cross-stack smoke. Run contention-prone smoke sequentially if parallel full-suite pressure causes timeout; report first failure and successful rerun distinctly, never hide the failure.
3. Compare SHA-256 of `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml` against the pristine baseline and ensure the default remains `strict-v1`. Check no `execution_performed=true`, no `automatic_activation_allowed=true`, no real owner key or owner approval, and no executable mutation path.
4. Commit source/test/docs, a concise status record with baseline red→green evidence, exact SHA/hashes and CI URL; update `AGENTS.md` only with verified, completed facts. Open a focused PR. Require success on the **exact PR head SHA** and no serious unresolved review before merge. Confirm merge-head CI on main; if not green, do not claim closure.
5. If execution environment lacks dependencies or GitHub access, use the closest safe automated runner/CI; document precise blocked command/environment, do not declare unexecuted tests passing, and leave implementation unmerged until its required gates are satisfied.

## Manual action boundaries (not needed to close R3)

**No owner participation is required for R3.** The tests use disposable Ed25519 keys only, exercise no real personal investment decision and change no active profile.

A future real-owner strict-v2 decision, **outside R3**, requires independently: (a) inspect the exact strict-v2 economic audit findings and exception coverage, compare to current strict-v1 and affirm ACCEPT_WITH_EXCEPTION or REJECT; (b) choose and protect a private-key location/passphrase and backup outside the repo, and verify its 0600/0700 permissions; (c) register the public key with identity/scope/window, inspect returned key id; (d) sign exactly the canonical decision input in the owner's own environment, with no key/passphrase in chat, CLI argv, Git, or logs; (e) run `record-decision`, `verify-evidence` and read-only `plan-activation`, inspect the actual binding hashes, replay code and READY/BLOCKED reasons; (f) separately authorize **any** subsequent profile change and its rollback. None of these real-owner steps may be fabricated, assumed from CI, or replaced by test fixtures. If the next chosen work is executor design, it must remain non-activating until an explicit owner authorization gate is defined and genuinely exercised.

## Completion output

Provide: actual upstream HEAD, reproduced defects and eliminated hypotheses, exact automated gate results, unchanged protected hashes, PR/commit links with exact-head CI, limitations, owner-manual scope (if any), and a small prioritized next goal. Do not skip over failed/unavailable checks with "evidence not fully recorded."