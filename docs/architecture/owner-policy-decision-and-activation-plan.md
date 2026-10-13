# Owner Policy Decision and Activation Plan Architecture

Phase 7-C2 implements the additive, offline boundary between a C1 semantic
audit (`POLICY_DECISION_REQUIRED` / `READY_FOR_POLICY_DECISION`) and any
future *actual activation* of a published versioned profile. It records an
explicitly supplied owner decision with complete artifact bindings, resolves
sets of records/revocations into one fail-closed authority state, derives a
read-only activation/rollback plan with a config inventory, and generates the
Chinese owner decision dossier that must exist before any real owner
acceptance is requested.

```text
owner-authored decision input (unsigned local JSON)
  + published profile/manifest bytes + policy-exception file
        -> validate_owner_decision(...)          # offline, re-runs C1 fresh
        -> 6 canonical checks (shape / bindings / fresh audit /
           exact exception binding / full coverage / provenance)
        -> OwnerPolicyDecisionValidationV1
             VALID   -> immutable OwnerPolicyDecisionRecordV1 (create-only)
             INVALID -> blockers, no record

decision records (+ revocations, + supersession links)
        -> resolve_owner_decision_authority(...)  # fail-closed
        -> DecisionAuthorityResolutionV1
             ACCEPT_VERIFIED | ACCEPT_UNVERIFIED | ACCEPT_AUTHORITY_REJECTED
             | REJECTED | NO_DECISION | AMBIGUOUS | CONFLICTING

resolved authority + fresh C1 audit + explicit config paths
        -> plan_profile_activation(...)          # read-only
        -> ProfileActivationPlanV1
             READY_FOR_EXPLICIT_OWNER_EXECUTION | BLOCKED
             (execution_performed=false, automatic_activation_allowed=false)
```

Nothing in this phase switches a default profile, writes `rules/`, replays
monitoring effects or sends notifications.

## Artifact validity versus real authority

The central separation is that a *shape-valid, correctly bound* decision
record is not yet an *authorized* one:

- an unsigned local JSON file, an EnvironmentFile username, Git author text,
  a green CI run and a publication manifest prove neither human authorship
  nor permission;
- `declared_owner_identity` is matched against an explicit optional
  allowlist, and the allowlist is **not authentication** — an unknown
  identity is rejected outright, a known identity is still unverified;
- actual authority is assessed only through the injected
  `OwnerDecisionVerifier` interface (an explicit trust-model ABC). No
  implementation ships with the production CLI and there is deliberately no
  CLI flag that could select one, so fake verifiers stay test fixtures
  injected through the library boundary;
- with no authenticated source available, every CLI-recorded decision
  carries `authority_status=OWNER_AUTHORITY_UNVERIFIED` visibly, and the
  activation plan reports the `OWNER_AUTHORITY_UNVERIFIED` blocker instead
  of inventing a verified acceptance.

## Complete content-hash binding (expiry is binding-relative)

A decision record binds, by deterministic id and content hash: the exact
base and target profile bytes, the release manifest, the **fresh** C1 audit,
and — for `ACCEPT_WITH_EXCEPTION` — the policy exception by **both** its
deterministic id and its **full content hash**. C1 exception ids omit
rationale/declarer, so an unchanged id with altered content is exactly the
`EXCEPTION_BINDING_MISMATCH` blocker. Expiry needs no wall clock: any byte
change in any bound artifact makes the declared bindings stale
(`DECLARED_BINDINGS_STALE` / `DECLARED_AUDIT_STALE`), and the resolver
reports stale records instead of silently preferring a newer file.

Validation always re-runs the C1 audit from the supplied
profile/manifest/template bytes and the supplied exceptions; a previous
dossier's self-reported readiness is never trusted or even read.

## Record-set semantics (duplicates, conflicts, revocation, supersession)

`resolve_owner_decision_authority` loads every supplied record fail-closed
(a tampered record fails to parse/hash and aborts the operation), groups by
the exact target identity, and:

- collapses exact duplicates (same id, byte-equal content); two records
  sharing an id with different content fail closed;
- removes revoked records (any structurally valid revocation that binds the
  revoked record's target; a forged revocation can only make authority
  ambiguous, never redirect it) and superseded records (explicit
  `supersedes_decision_record_id`, same-target only, no self/cycles/double
  supersession);
- resolves the remaining current records: exactly one is required.
  `ACCEPT`+`REJECT` is `CONFLICTING`, two distinct active accepts are
  `AMBIGUOUS` (newest-file-wins is explicitly forbidden);
- reports stale, revoked and superseded ids instead of discarding them.

## Read-only activation plan and config inventory

`plan_profile_activation` re-runs the C1 audit fresh (with the resolved
decision's bound exception when supplied), resolves the authority state and
inventories every explicitly supplied affected configuration:

| kind | source of profile reference |
| --- | --- |
| `PROJECT_DEFAULT_PROFILE` | `[profiles] default` in the supplied project TOML |
| `WATCHLIST` | `WatchlistSpecV1.profile_id` |
| `NORMALIZED_INPUT` | `NormalizedCompanyInput.profile_id` |
| `BACKTEST_DATASET_MANIFEST` | decision artifacts' normalized input/analysis profile ids |
| `SURFACE_SNAPSHOT` | `ResearchSurfaceSnapshotV1.profile_id` |
| `MONITORING_RUNNER_CONFIG` | not profile-scoped; reports its bound watchlist path |

Historical artifacts pinned to the prior profile are
`BASE_PINNED_PRESERVED` — labelled, preserved byte-for-byte, never rewritten.
Foreign (`FOREIGN_PROFILE_REFERENCE`), missing (`MISSING_REFERENCE`) and
unreadable (`UNREADABLE_REFERENCE`) references, an incoherent project
default (`DEFAULT_NOT_BASE` / `DEFAULT_ALREADY_TARGET`) and every unresolved
decision/audit blocker make the plan `BLOCKED` with specific codes. The
plan is `READY_FOR_EXPLICIT_OWNER_EXECUTION` only when the resolved decision
is `ACCEPT_VERIFIED`, the fresh audit is `READY_FOR_POLICY_DECISION` and the
inventory is clean — and even then `execution_performed=false` and
`automatic_activation_allowed=false` are fixed literals: a verified decision
is necessary input, never an execution request.

The embedded rollback plan records the prior project-config bytes hash and
prior default profile, the expected current state, explicit restoration
steps, and fixed exclusions — no automatic monitoring replay, no
notification replay, no historical-artifact rewrite.

## CLI surface

- `tve evolution record-decision` — validate one supplied decision against
  freshly re-run evidence and persist the immutable record create-only
  (byte-identical reruns are idempotent no-ops; a different record at the
  same path is refused). Exit 0 recorded / 1 invalid decision (dossier
  printed and persisted) / 2 unusable inputs or guarded paths.
- `tve evolution plan-activation` — derive the read-only plan; exit 0 ready
  / 1 blocked (plan printed and persisted) / 2 unusable inputs.
- `tve evolution decision-dossier` — generate the deterministic Chinese
  decision dossier from a fresh audit (exact hashes, threshold
  relationship, 13% behavioural contrast, divergence interval, accept/reject
  effects, submission fields and failure handling), stating explicitly that
  it is synthetic boundary evidence rather than performance proof.

All three refuse symlink outputs, outputs over supplied inputs, and outputs
under published artifact directories (`rules/`, the supplied profiles and
release manifest). None constructs a provider, model, transport or network
socket; none exposes a verifier selection.

## Schemas (drift parity)

Six checked-in Draft 2020-12 schemas are generated from the models:
`owner-policy-decision-input`, `owner-policy-decision-record`,
`owner-policy-decision-revocation`, `owner-policy-decision-validation`
(with the per-position `prefixItems` pinning of the six-check canonical
sequence), `owner-decision-authority-resolution` and
`profile-activation-plan`. The frozen C1 schemas and status meanings are
unchanged.

## Relationship to earlier boundaries

- Phase 7-C1 remains the readiness authority; C2 re-runs it, never trusts a
  persisted dossier, and never maps a C1 `PolicyApprovalClaimV1` (a
  different contract) onto a decision record.
- A `REJECT` decision is terminal for this version: strict-v2 stays a
  published research artifact and corrections go through a new release from
  the unchanged 7-A → B1 → B2 chain.
- Actual default-profile switching is deferred to a separately selected,
  separately reviewed package; this phase's contracts are the audit trail
  and the plan such a package would consume.
