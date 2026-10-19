# Phase 7-C3-B-R2 — Capture Attestation Consistency and Safe Owner-Key Provisioning

Status: **SELECTED / NOT IMPLEMENTED**. Source-level candidates from `docs/status/phase-7-c3-b-r1-post-closure-review-2026-10-19.md`; first reproduce before repairing. This goal is **not** permission to execute an activation.

## 0. Mandatory first action: synchronize

`git status --short`, `git fetch origin --prune`; inspect latest `origin/main`, recent PRs and head-matched Actions. Do not overwrite dirty worktrees or run `git reset --hard`; create a clean worktree/feature branch from verified current `origin/main`. Read `AGENTS.md`, R1 closure, the independent post-R1 review, and the actual implementation. Rebase this plan if upstream advanced.

## 1. Scope

Harden the distinction between (a) byte-consistent historic proof, (b) a genuinely attested captured authority assessment, and (c) fresh authority at plan time. R1 binds signed decision fields and physical components, but its replay and strict loader do not explicitly check `record.authority` against the recomputed verification dossier or the compatibility of `VALID` / `REJECTED` / blockers. Separately harden the *optional* runbook's real owner encrypted-key creation, never creating any owner's key or signing any owner's decision.

## 2. Must-fail-on-baseline reproductions before implementation

Use real Ed25519, actual capture/persistence/replay/strict load/CLI; no mocked verifier. Work in temp directories and use ephemeral throwaway private keys. Start from a genuinely valid signed capture; for a forged bundle recalculate **every** deterministic record ID, record content hash, bundle ID, manifest content hash and physical component so every JSON document remains model-valid and the directory name matches the new bundle ID.

1. Tamper only **unsigned authority metadata** in the record (one case each for `attested_key_id`, `attested_registry_id`, `attested_registry_content_sha256`, and `evidence_content_sha256`), keeping owner-signed fields and source revision unchanged. Test the exact fresh-dossier/actual-byte coherence expectation; record whether baseline replay returns `REPLAYS_BYTE_IDENTICAL`, the strict loader accepts, and the CLI returns exit 0.
2. Build a model-valid `VALID` bundle with a record falsely claiming `OWNER_AUTHORITY_VERIFIED`, but whose real signed-capture input, statement and registry recompute as `REJECTED`. Avoid the simple malformed-bundle case: consistent IDs, hashes, six-file shape and matching directory required. Observe baseline audit, strict load, and separate plan behavior. A rejected signature must **never** establish historic VERIFIED authority.
3. Create `VALID` with nonempty `validation_blockers` while preserving all self-hashes; compare with real `validate_owner_decision` behavior and document any unavoidable backward-compatibility boundary.
4. Preserve positive examples: actual verified/valid capture, honest rejected/invalid no-record capture (still `REPLAYS_BYTE_IDENTICAL` as historic integrity only), offline socket-denied replay, deterministic repeated replay, and fresh plan READY→BLOCKED after key revocation.
5. For the owner walkthrough, prove initial PEM file mode under a deliberately permissive `umask`, preexisting destination, symlink destination, and repeated invocation. No real owner key/passphrase in tests. Record actual baseline outcomes even when a hypothesis is not reproduced.

If any suspected defect is not reproduced, write the counter-evidence and narrow the implementation accordingly. Red/green results must have exact SHA, command, failing assertion/output, and named test cases in committed status; do not present a code-reading hypothesis as an executed exploit.

## 3. Smallest safe repair

- Centralize **one** capture-attestation consistency contract shared by strict load and audit replay; compare recorded claims with the recomputed dossier, signed bytes, trust-root content, and defensible historic capture semantics. For malformed artifacts fail closed; for parseable divergences replay should report stable machine-readable mismatches. Never infer current authority from historical replay; current plan verifier is untouched.
- Invariants should explicitly cover verifiable `authority_status`, `verification_method`, attested key/registry identity/content hash, evidence hash and coherent `VALID` / `REJECTED` / blockers. Check exact real capture behavior first; an honest rejection may be INVALID but still replay identically. Do not invent an economic audit replay from missing external evidence.
- Keep persisted V1 shapes, deterministic IDs and pre-existing legitimate bundle bytes stable wherever possible. If any schema change becomes indispensable, version explicitly and test schema generation/parity and historical compatibility.
- Owner runbook: set the private directory to mode 0700; store an encrypted PKCS#8 Ed25519 private key through a one-time exclusive no-follow create with initial mode 0600, validate directory/path assumptions, refuse overwrite/symlink/racing writer, securely close handles; interactively prompt for passphrase without argv/logs/environment on the real owner path. A throwaway-key automated subprocess smoke may use a test-only secret. Ensure a second process reloads the key and signs valid canonical bytes. No actual key is placed in repo, CI or review output.

## 4. Completion gates (automated before manual)

- First add regression tests and run them on pristine **current main**, recording each actual baseline result. Then run identical tests on the repair branch. Full deterministic fixture and CLI assertions with expected exit 0/1/2, strict-loader fail-close and preserved positive replay.
- `python -m ruff check .`; focused tests, `python -m pytest -q` with exact passes/skips; run actual `.github/workflows/ci.yml` equivalents: config validation, systemd-analyze verify, OpenAPI parity, Dashboard generated API/Wrangler types, lint, typecheck, tests, build, client-bundle security scan with documented CI sentinels, Wrangler strict dry-run, cross-stack smoke. Use actual project commands from workflow rather than guessed substitutions; document skipped/unavailable checks with concrete blocker.
- Protected SHA-256 compare against pristine baseline for `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml`. Default `strict-v1` must remain; no live providers, models, owner approval, activation executor, secret exposure, or changes to `execution_performed=false` / `automatic_activation_allowed=false`.
- Open focused PR; audit entire diff and reviews; require GitHub Actions success on **exact PR head SHA**; merge only after green and no serious unresolved findings, then check exact merge-head CI. If unable to run CI, leave PR unmerged and give exact commands/blocker. Commit status with reproducible red→green traces, code limitations, hashes and CI URLs.

## 5. Human validation and boundaries

**No human input is required to close this engineering task.** A genuine owner's *optional* follow-on is separate: examine the exact strict-v2 audit/dossier and exception implications, consciously choose REJECT versus ACCEPT_WITH_EXCEPTION, choose and secure a private-key location/password manager, verify public-key identity and validity/scope, independently sign the accepted canonical payload, inspect `record-decision`/replay/plan output, and explicitly decide whether any future activation should happen. These steps are **not** replaceable by throwaway test keys or automatically inferred from passing CI. Never execute a profile switch or fabricate this evidence.
