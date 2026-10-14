# Phase 7-C2-R1 — Activation Plan Trust-Boundary Hardening

Status: **IMPLEMENTED / CI CLOSURE PENDING**
Selected by: `docs/status/phase-7-c2-post-closure-review-2026-10-14.md`
Reviewed baseline: `acc76508ee4aec6f312126538b93d04b572433fa` (main, 2026-10-14)
Objective: repair the read-only C2 planning trust boundary before authenticating any real owner decision or developing a profile-activation executor.

## 1. Scope and source of truth

Read `AGENTS.md`; the C2 goal/architecture/closure; the 2026-10-14 post-closure review; the C1/C1-R1 semantic-audit code and tests; `evolution/owner_decision.py`, `evolution/activation_plan.py`, `cli.py`; current `tests/test_owner_decision_activation.py`; schemas; and `.github/workflows/ci.yml`. Verify main/head and known exact CI results before changes.

Preserve every published byte (`rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`), the `strict-v1` default, all deterministic investment math and existing real monitoring outputs. C2-R1 is an **offline/read-only correctness and safety repair**, not activation, owner economic-policy acceptance, signing-key provisioning, broker integration or H-share expansion. No issue or unrelated platform work.

## 2. Mandatory defects to fix

### R1-A: persisted claims must never become trusted authority by themselves

- Demonstrate on the *baseline* with a test: an internally hash-consistent `OwnerPolicyDecisionRecordV1` with `authority_status=OWNER_AUTHORITY_VERIFIED`, supplied as an external JSON file to ordinary `tve evolution plan-activation`, can currently cause a false READY when a matching exception and compatible project config are supplied. Use a scripted fixture, **not** a real owner identity or fabricated real approval; retain failing-baseline proof.
- Distinguish immutable-record integrity from authenticated source provenance at the plan entry point. Plan-time authority must be independently checked against a trusted injected verifier/immutable captured source *and* the original source bytes/hash/revision, rather than trusting serialized `authority` text or a self-recomputed content hash.
- No real authenticated source exists yet: production CLI must fail closed with a machine-readable BLOCKED cause (for example `OWNER_AUTHORITY_REVERIFICATION_REQUIRED`); do not emit READY even when handed an internally hash-consistent forged VERIFIED record. A diagnostic blocker/exit 1 is preferable to swallowing or silently upgrading the claim.
- Preserve fixture-only VERIFIED/READY scenarios by passing verified evidence through an explicit **library-only** test injection mechanism. There must be no CLI verifier selector, local JSON trust override, permissive boolean `trust_verified=true`, environment bypass or special-case real owner acceptance. The future real-source adapter belongs to a later phase.
- Test synthetic fake-verified, synthetically validated unsigned, edited verifier method/evidence, absent original source, altered original bytes, allowlist mismatch, stale/cross-target source and intentional negative/rejected verification. Assert source may not be self-certified by a record field.

### R1-B: bind the exact active decision to the exact fresh plan context

- At plan time bind selected active record against **base ID+actual byte SHA, target ID+actual byte SHA, release-manifest ID+content SHA, fresh C1 audit ID+content SHA, exception ID+full content SHA**; include source revision/identity/provenance whenever authority is assessed. Require exact exception-set membership, not matching ID somewhere in a list.
- Return stable, granular blockers (e.g. `DECISION_BASE_BINDING_STALE`, `DECISION_MANIFEST_BINDING_STALE`, `DECISION_AUDIT_BINDING_STALE`, `DECISION_EXCEPTION_BINDING_STALE`, `DECISION_EXCEPTION_SET_MISMATCH`). Codes may differ if justified and tested; do not silently pick a newer record or silently drop stale evidence.
- Add executable negative tests for each binding independently, especially an exception with **unchanged deterministic C1 ID but different rationale/content hash**; C1 exception coverage alone is not approval.
- Keep `REJECT` terminal, revocations/supersession fail-closed, and no application side effect. No mutation of frozen C1 contract/schema.

### R1-C: true atomic create-only outputs

- Replace the C2 `_write_create_or_identical` check-then-`os.replace` race with no-overwrite open/publication. Preserve exact-byte idempotence for already present outputs. Never overwrite a different-content file, a symlink, a supplied input or a published-directory path.
- Add an orchestrated concurrency/interleaving test: make a second writer create conflicting content *after the first existence check but before its publication*, prove the conflicting file is not replaced. Confirm no orphan temporary output or unauthorized deletion.
- Test across `record-decision`, `plan-activation` and `decision-dossier`, including invalid-decision exit 1 and blocked-plan output publication; no sockets, no provider/model/client initialization.

### R1-D: complete config inventory before READY

- A library call omitting project config must be explicitly BLOCKED, consistent with CLI `--project-config` required.
- If a runner config points to a watchlist, ensure that live reference is inventoried and validated, or emit a clear missing-inventory blocker; no silent READY on a partial live-runtime inventory. Define explicit path-resolution/alias and missing/unreadable behavior; do not recurse arbitrarily.
- Historical normalized inputs, frozen backtests and Dashboard snapshots remain pinned/preserved with explicit labels and rollback no-replay exclusions. No background replay or live mutations.

## 3. Required automatic verification (close only on evidence)

1. Capture a concise baseline matrix identifying which **new negative tests fail** on original main (and which existing 55 C2 tests pass). Do not call unexecuted scenarios reproduced.
2. Implement the smallest compatible production changes; add focused fixture tests and optional schema drift updates only where the contract actually changes. Avoid new human/credential dependencies.
3. Run `python -m ruff check .`, `python -m pytest tests/test_owner_decision_activation.py -q`, `python -m pytest`, `python -m turtle_value_engine config validate --input config/project.example.toml`, and *every command* in `.github/workflows/ci.yml`. No hidden skips; explain the two opt-in AKShare live skips, and record any new ones.
4. Exercise the published strict-v1 → strict-v2 C1 audit on actual checked-in bytes (its expected policy-gated status is not test failure); generate dossier and a no-record blocked plan; run forged VERIFIED record and stale/hash-mismatch regression through the **CLI** and assert exit/blockers/output immutability. Use controlled temporary directories.
5. Compare before/after exact SHA-256 of both published profiles, release manifest, `config/project.example.toml`, and relevant strict-v1 decision fixture outputs. Confirm no new owner record or exception in repository and no default change.
6. Push the implementation on a focused branch; require successful GitHub Actions run whose `head_sha` equals the reviewed implementation SHA; check **every job and step**. If a PR is necessary, do not merge a failing or unverified head. Produce an exact-head closure record with run/job URLs, all conclusions and test counts.
7. For an unavoidable external blocker, report the exact blocking command, expected versus observed output, attempted automatic retries, how to resume, and a precise bounded human validation procedure. **No human input is necessary for expected C2-R1 closure**; do not ask the owner to decide strict-v2, generate signatures, configure credentials, or click approval.

## 4. Exit criteria and exclusions

- **Hard safety gate:** ordinary production CLI with a fabricated/self-consistent VERIFIED decision must never output READY; invalid/mismatched audit/manifest/exception must always BLOCK; compatible fixture provenance can be READY only under independently injected trusted test evidence in the library.
- All current C2 invariants and fixed `execution_performed=false` / `automatic_activation_allowed=false` remain enforced and schema-consistent.
- No source creates an actual rule activation, mutable decision approval, real signature verifier or PR reviewer approval. A future authentication source must be separately selected after this safety repair. No automated trading, actual owner economic decision, Windows bootstrap or unrelated refactor.
- Close only after baseline-failing regressions pass, full CI is green at the exact final SHA and a precise written closure record exists.
