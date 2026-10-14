# Phase 7-C2 independent post-closure review — 2026-10-14

Status: **IMPLEMENTATION CI VERIFIED; SECURITY/INTEGRITY HARDENING SELECTED**
Reviewed main: `acc76508ee4aec6f312126538b93d04b572433fa`
Implementation: `26cd2b47ba5f9bc8989698742c9bc78721d99d9c`
Goal: `docs/goals/phase-7-c2-owner-policy-decision-and-activation-plan.md`
Closure: `docs/status/phase-7-c2-2026-10-13.md`
Selected follow-up: `docs/goals/phase-7-c2-r1-activation-plan-trust-boundary-hardening.md`

## Verified evidence and important limits

- Compared `51df04d0227661bd9d0eceef3469b5f61f4b58f9` through `acc76508ee4aec6f312126538b93d04b572433fa`: two commits, 17 changed files. Phase 7-C2 implementation plus documentation closure are both on main.
- Implementation Actions run `38360550883` completed success on *exact* implementation SHA `26cd2b47ba5f9bc8989698742c9bc78721d99d9c`. Its test job `115173454998` shows every CI step successful: Ruff, default strict-v1 config, pytest (7145 passed / 2 skipped), systemd, OpenAPI/types, Dashboard lint/typecheck/55 tests/build/client-secret scan, Wrangler dry-run, and cross-stack smoke.
- Documentation-head Actions run `38361400705` completed success on exact SHA `acc76508ee4aec6f312126538b93d04b572433fa`; its single job `115176200950` also completed all steps successfully.
- Existing focused C2 regressions cover 55 scenarios; the currently published strict-v1/strict-v2/release bytes and strict-v1 default remain unchanged per the existing checked-in invariants. No owner decision or exception exists on main. There is no execution capability in C2.
- This is an independent **static code-path review** using the connected GitHub source and Actions metadata, *not* an independently executed local clone or newly passing regression. A local clone attempt was blocked by DNS/network resolution; the findings below require executable proof in C2-R1, not retrospective claims of a reproduced exploit.

## Findings

### C2-R1-F1 — P1: Persisted authority assertions are not independent authorization evidence

`OwnerPolicyDecisionRecordV1.validate_record` (evolution/owner_decision.py, around lines 254-293) verifies a recomputable deterministic ID and SHA-256 content hash. It does not verify an owner signature or authenticated evidence. `load_decision_record` accepts any self-consistent such object. `resolve_owner_decision_authority` maps the embedded `authority.authority_status` to `ACCEPT_VERIFIED` (around lines 1210-1245). `plan_profile_activation` consumes that resolved state directly (activation_plan.py, around lines 532-602), and the CLI accepts externally supplied `--decision-record` paths.

A crafted, internally self-consistent record asserting VERIFIED may therefore make the *read-only* CLI return `READY_FOR_EXPLICIT_OWNER_EXECUTION` without a production owner verifier. Tests construct VERIFIED records via injected scripted verifiers, but do not yet assert that loading such a record into the production CLI must remain unverified. This is an integrity/authorization confusion at the planning boundary, **not actual activation**.

Required fix: replay or re-attest authenticated authority from a trusted source at plan time, never from a record's self-assertion. Until a real verifier exists, the ordinary production CLI must always refuse READY from an externally loaded VERIFIED claim. No CLI-selectable fake verifier or trust-me switch.

### C2-R1-F2 — P1: Plan omits full decision-to-current-evidence binding checks

`resolve_owner_decision_authority` selects the current set by target profile id + SHA-256. After this, `plan_profile_activation` re-runs the C1 audit but does not compare the selected decision record's **base id/hash, release manifest id/content hash, fresh audit id/content hash** against the plan's actual artifacts. The exception-supply check (activation_plan.py, around lines 547-556) compares only exception IDs, not their complete `content_sha256`, and does not require the exact bound exception set.

A stale/wrong-context decision or rationale-altered exception with the same C1 exception ID could be attached to an otherwise machine-clean fresh audit and produce an incorrect READY result if the authority assertion is trusted.

Required fix: compare every bound field and both exception identity and complete content hash, fail closed with stable reason codes, and test mismatched base/manifest/audit/exception independently. A record valid *when created* is not thereby valid for a different planning context.

### C2-R1-F3 — P2: Create-only CLI output has an overwrite race

`_write_create_or_identical` in cli.py (around lines 1647-1660) does an `exists/read` check then invokes `_atomic_write`; the latter uses `os.replace` (around lines 986-996). A conflicting file created between those operations can be overwritten, contrary to advertised create-only guarantees. By contrast, `record_owner_decision_file` already uses `O_CREAT|O_EXCL`.

Required fix: true atomic no-overwrite creation with byte-identical existing-file idempotence, bounded failure cleanup and a deterministic interleaving test. Do not introduce a new path that can replace rules, release files, inputs or symlinks.

### C2-R1-F4 — P2: Library plan permits absent project-default inventory

`plan_profile_activation(project_config_path=None)` makes no required-default blocker, while the production CLI does require `--project-config`. A directly called library planner can thus report READY without inspecting the configuration whose default would change. The runner-config inventory also currently labels the associated watchlist path without requiring it to be inventoried explicitly; clarify and enforce inventory completeness for claimed READY rather than silently assuming the set is complete.

Required fix: either require the config and dependent live references for READY, or explicitly mark inventory incomplete and BLOCKED. Frozen historical artifacts remain preserved, not rewritten.

## Review decision and ordered roadmap

**C2 implementation closure remains historically valid as an offline implementation/CI result. C2 is not accepted as a secure input to any future activation executor until C2-R1 is complete.**

Select **Phase 7-C2-R1 — Activation Plan Trust-Boundary Hardening** as the next coding-agent package, with no real owner interaction or production credentials. It must include fail-on-baseline negative regression demonstrations, focused fixes, all automatic checks and exact-head CI before claiming closure. Do not create an Issue solely to track this personal research package.

Only after C2-R1 should the next review consider **C3: a real authenticated owner provenance verifier with immutable captured evidence and offline replay**. A controlled activation executor is later still; neither C2-R1 nor C3 is authority to switch defaults. Owner economic acceptance must remain an explicit separate real action, never synthesized by CI or an agent.
