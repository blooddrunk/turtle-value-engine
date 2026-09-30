# Phase 7-B1-R1 post-closure review — release-boundary readiness

Status: **B1-R1 CLOSURE PRESERVED / PHASE 7-B2-A SELECTED**
Date: 2026-09-30

Reviewed closure:
`docs/status/phase-7-b1-r1-2026-09-30.md`

Reviewed implementation:
`b7d889a86f0a56e49cfb639f5605de61a02bfd17`

Closure commit:
`d296fde91ab0ff2e65ae6306281e8a3407f95a20`

Selected next package:
`docs/goals/phase-7-b2-a-versioned-profile-release-bundle.md`

## 1. Verdict

Phase 7-B1-R1 remains correctly CLOSED. The three defects selected by the
post-B1 review were proven behaviorally on the unchanged B1 implementation,
then closed by the implementation:

- immutable finals use no-overwrite publication rather than check-then-replace;
- candidate publication is prerequisite-first and the materialization record
  is the authority-last marker, with safe rollback on normal second-stage
  failure and explicit orphan semantics after process death;
- active-rules refusal is bound to the supplied base-profile root rather than
  only package/CWD conventions.

The new `resolve_complete_materialization_pair` read boundary rejects orphan,
tampered, symlinked and candidate-hash/id-mismatched pairs. No further B1-R2
hardening blocker was found in this review.

## 2. Independent closure evidence re-checked

GitHub Actions run `36691452309` was independently queried:

- workflow: `CI`;
- event: `push`;
- `head_sha`: `b7d889a86f0a56e49cfb639f5605de61a02bfd17`, exactly the R1 implementation;
- conclusion: `success`;
- CI log: `7021 passed, 2 skipped` for Python;
- Dashboard: `55 passed`;
- Ruff, systemd verification, generated API/Wrangler checks, Dashboard build,
  client-bundle secret scan, Wrangler strict dry-run and cross-stack smoke all
  completed successfully.

The R1 closure record also captures the three fail-on-B1-baseline behavioral
proofs: concurrent overwrite, second-publish partial candidate and external
active-rules acceptance. The proofs assert real file/CLI behavior rather than
absence of new R1 symbols.

## 3. Why B2 should be split into B2-A and B2-B

The Phase 5 sequence is:

```text
proposal
-> frozen PIT evaluation
-> robustness/sensitivity review
-> tests
-> PR
-> human approval
-> new versioned profile
```

B1/R1 now provides a trustworthy local review artifact. The remaining boundary
contains two fundamentally different authority classes:

1. deterministic transformation/verification that can and should be automated;
2. a genuine human approval decision represented by a GitHub review.

Combining both into one coding-agent task would force an otherwise automatic
implementation to stop mid-phase waiting for a human click, or tempt the agent
to invent an approval surrogate. Neither is desirable.

Therefore Phase 7-B2 is split:

- **Phase 7-B2-A — Versioned Profile Release Bundle and PR-Ready Provenance**:
  fully offline and automatically closable. Produce the exact versioned-profile
  bytes and immutable release manifest that a later PR must use, but do not
  write active `rules/`, open a PR or record approval.
- **Phase 7-B2-B — GitHub PR, Human Approval and Versioned-Profile Publication**:
  later remote-authority package. It may automate branch/commit/PR creation,
  CI/status polling, approval verification and post-merge verification, but
  the actual approving review must be performed by a human.

This split minimizes manual work while preserving the explicit human gate.

## 4. B2-A must not treat the materialization pair as bearer authority

`CandidateProfileMaterializationV1` is deterministic and hash-validated, but
its hashes are not signatures. A caller with typed-model access can construct a
different internally self-consistent record. The R1 pair resolver proves that
candidate bytes and the supplied record form a coherent pair; it is not a
replacement for the authoritative calibration workspace.

B2-A must therefore require the same authoritative frozen evidence needed by
B1 and freshly re-establish the source materialization before producing release
bytes:

1. resolve the R2 experiment-keyed freeze/binding from the authoritative
   calibration workspace;
2. re-run the controlled-evolution admission over the exact frozen inputs;
3. re-run B1 materialization in memory;
4. require exact equality of the re-materialized candidate bytes,
   materialization id and materialization content hash with the supplied
   complete pair.

A stale, foreign or merely self-consistent pair must fail closed. No persisted
READY/materialization JSON is a bearer authorization token.

## 5. B2-A output contract

B2-A should introduce the smallest versioned immutable release-candidate
contract, for example `VersionedProfileReleaseCandidateV1`, plus a checked-in
Draft 2020-12 schema.

The release contract must bind at least:

- source materialization id/content hash;
- source evaluation/freeze/binding/experiment/proposal identities already
  carried by the materialization;
- exact base-profile id/hash;
- exact candidate id/hash;
- explicit target versioned profile id;
- intended repository target path;
- exact release-profile bytes hash;
- exact rule-semantic payload identity proving candidate -> release changes
  only metadata;
- deterministic candidate -> release metadata changes;
- `requires_human_approval=true`;
- `automatic_merge_allowed=false`;
- `automatic_application_allowed=false`;
- deterministic release-candidate id and content hash.

For the current strict lineage, the target id must be explicit and version
safe: `strict-vN -> strict-v(N+1)`. B2-A must not silently skip versions,
overwrite an existing target or accept arbitrary path traversal.

## 6. Exact release bytes

Release bytes must be derived from the freshly revalidated B1 candidate.
Rule-bearing payload outside the top-level `profile` metadata block must be
byte/model-semantically identical to the B1 candidate.

For the versioned profile metadata, use one deterministic policy. The preferred
current policy is:

- `profile.id` -> explicit target id (for this lineage, `strict-v2`);
- `profile.name` -> deterministic name derived from the target version;
- `profile.status` -> preserve the base profile status;
- `profile.description` -> preserve the base profile description unless a
  separately frozen deterministic metadata policy is introduced.

The generated profile must validate through the existing `RuleProfile`
model and round-trip deterministically.

B2-A output remains outside active `rules/`. The intended later target path
is recorded as `rules/<target-id>.yaml`; the actual repository write belongs
to B2-B.

## 7. Automatic verification policy

B2-A is a new capability, not a newly discovered unsafe B1 behavior. Do not
fabricate fail-on-baseline tests whose only failure is that B2-A symbols do not
exist. Record the structural baseline instead: there is no release-bundle
contract/CLI, no `strict-v2`, and no current path that converts a complete B1
pair into PR-ready exact release bytes.

Post-implementation tests must prove at minimum:

1. honest authoritative B1 chain -> deterministic release bundle;
2. a self-consistent but foreign/forged materialization pair is rejected by
   fresh authoritative re-materialization;
3. wrong workspace/manifest/experiment/holdout/observations/base bytes fail
   closed before any release output;
4. target version must be exactly the next strict version and path-safe;
5. candidate -> release changes only the deterministic `profile` metadata;
6. release rule payload is exactly equal to the candidate rule payload;
7. release vs base rule diff matches the authoritative materialization rule
   changes and no hidden rule change exists;
8. release profile validates/round-trips and exact bytes/hash are deterministic;
9. repeated identical execution is byte-identical/idempotent;
10. release outputs are immutable/create-only and an authority-last manifest
    rejects incomplete/tampered pairs;
11. output under active `rules/`, authoritative workspace or supplied inputs
    is refused;
12. socket-guarded B2-A paths construct no network socket;
13. `rules/strict-v1.yaml` remains byte-identical and
    `rules/strict-v2.yaml` remains absent throughout B2-A;
14. every new persisted contract has schema drift parity;
15. the complete current CI-equivalent gate is green.

After push, query GitHub Actions automatically. B2-A closes only when the
required run is `success` and `head_sha` exactly equals the implementation
commit.

## 8. Manual-intervention policy

No manual owner action is planned for B2-A.

If and only if a genuinely external authority/environment makes one automatic
check impossible, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue every other automatic check. Never use a vague evidence-not-recorded
placeholder.

## 9. Future B2-B human boundary

B2-B is intentionally not part of the current handoff. Its unavoidable manual
step must be explicit when selected:

1. the agent creates a branch/commit/PR using the exact B2-A release bytes and
   recorded target path;
2. all PR CI/checks are polled automatically and must be green for the exact PR
   head SHA;
3. **human action:** an authorized reviewer inspects the PR and submits an
   actual GitHub `APPROVED` review for that exact head SHA;
4. the agent re-queries GitHub and verifies reviewer identity, approval state,
   PR head SHA and B2-A release hash before any merge;
5. only then may the authorized workflow merge/publish the new versioned
   profile;
6. post-merge automation verifies the exact published profile hash,
   `strict-v1` byte identity and that the default profile was not silently
   changed.

No approval may be synthesized from a CLI flag, local JSON file, commit
message, bot self-review or coding-agent assertion.

## 10. Stop boundary

Stop B2-A after offline versioned-profile release bytes + immutable release
manifest are implemented and exact-head CI closure is recorded.

Do not write `rules/strict-v2.yaml`, open or merge a PR, record human approval,
change the default profile, automatically apply the candidate, add
provider/Bridge/FQGate or notification/Windows scope, or add brokerage/trading
behavior.
