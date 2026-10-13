# Phase 7-C1 — Versioned Profile Semantic Audit & Activation Readiness

Status: **IMPLEMENTED / CLOSED**
Date: 2026-10-13
Closed at: implementation `37dda800e42cc401de3c85cf05065fd70dc3d3be`
(Actions run `38334476461`, `success`, exact `head_sha` match; closure
record `docs/status/phase-7-c1-2026-10-13.md`)
Selected from: Issue #5 (`https://github.com/blooddrunk/turtle-value-engine/issues/5`)
Reviewed baseline: `0e149504b9f0faa7c82fba67e8fdcc932578a8b2` (merged main after PR #4)

## 1. Objective

Build a deterministic, offline, read-only semantic-audit and
activation-readiness capability for published versioned rule profiles, and
resolve the presentation defect where strict-v2 analyses emit misleading
hardcoded `strict-v1` decision labels.

The capability must answer three separable questions for a published
profile pair such as `strict-v1 -> strict-v2`, each with its own outcome:

1. **Well-formed/reproducible** — do the exact published bytes, identities,
   version lineage, release-manifest integrity and registered rule changes
   hold together?
2. **Semantically coherent for activation** — are the profile's internal
   band orderings and the relationships between eligibility gates and
   valuation tiers coherent, or are there anomalies that require an
   explicit policy resolution?
3. **Policy accepted by owner** — has a human made the economic-policy
   decision? (Never answerable by this phase; detection-only.)

The published `strict-v2` CDC anomaly (`cdc.yield_bands.pass = 0.14` above
the retained `s = 0.12` band and the `extreme_safety` 12% tier hurdle) must
be classified as exactly what the Issue says it may be: a well-formed,
reproducible, deliberately stricter eligibility gate whose cross-field
policy consistency has no explicit machine-checked activation decision.
C1 must not silently normalize thresholds, must not mutate published bytes,
and must not approve anything.

No manual owner action is planned for C1. Human approval is reserved for
the later economic-policy decision and activation.

## 2. Source of truth

Read and follow, in order:

1. `AGENTS.md`
2. Issue #5 (canonical problem statement and required scope)
3. `docs/spec/01-cdc.md` section 11 (ordered CDC yield bands)
4. `docs/status/phase-7-b2-post-merge-2026-10-12.md`
5. `docs/goals/phase-7-b2-b1-pr-construction-exact-head-ci.md`
6. `docs/goals/phase-7-b1-materializable-candidate-profile-foundation.md`
7. `rules/strict-v1.yaml`, `rules/strict-v2.yaml`
8. `docs/releases/strict-v2/release-candidate.json`
9. `src/turtle_value_engine/gates/cdc.py`
10. `src/turtle_value_engine/calculations/valuation.py`
11. `src/turtle_value_engine/pipeline.py`
12. `src/turtle_value_engine/config/models.py`
13. `src/turtle_value_engine/evolution/profile_release.py` and
    `evolution/release_pair.py`

The exact reviewed baseline is
`0e149504b9f0faa7c82fba67e8fdcc932578a8b2`.

Preserve every Phase 7-A/R1/R2, B1/R1, B2-A/B2-B1 authority, no-network,
fail-closed and strict-v1 default invariant.

## 3. Recorded baseline behavior (pre-implementation, main `0e14950`)

Captured on the reviewed baseline with the existing implementations; these
are the facts C1 must preserve as evidence:

- Gate level (actual `evaluate_cdc_gate`, synthetic CDC results): the
  CDC.YIELD status diverges exactly on the window `[0.08, 0.14)` —
  `PASS` under strict-v1, `WATCH` under strict-v2. At `0.14 - 1e-9`
  strict-v2 is still `WATCH`; at `0.14` and above both are `PASS`; below
  `0.06` both are `FAIL`; on `[0.06, 0.08)` both are `WATCH`.
- End-to-end (`run_analyze` over a `fixtures/healthy_cash_cow.json`
  derived input with market caps chosen to hit each band): inside the
  divergence window the strict-v2 CDC gate is `WATCH`, which propagates
  through `_non_price_gate_argument` as `None`, so valuation is withheld
  to `SPECIAL_REVIEW` (`NON_PRICE_GATES_UNRESOLVED`) and the final
  decision is `WATCH` rather than a valuation-classified state.
- `CDCYieldBands` (`config/models.py`) enforces only `> 0` per field; no
  cross-field ordering exists anywhere in the repository.
- `src/turtle_value_engine/pipeline.py` emits three hardcoded
  `strict-v1` decision labels (`"The strict-v1 inputs do not support a
  normal valuation."`, `"No normal strict-v1 valuation is available..."`,
  `"Deterministic strict-v1 state: ..."`) regardless of the active
  profile, so strict-v2 analyses carry misleading provenance text.
- Published identities on main: `rules/strict-v1.yaml` =
  `e3618f78…333`, `rules/strict-v2.yaml` =
  `adba44b7…dd7`, release manifest content =
  `c0d6cb5b…1e8`; manifest `rule_changes` is exactly one leaf:
  `cdc.yield_bands.pass` `0.08 -> 0.14`.

## 4. Contract design

### 4.1 `ProfileSemanticAuditV1` (`profile_semantic_audit_v1`)

Immutable, no wall-clock fields, checked-in Draft 2020-12 schema
`schemas/profile-semantic-audit.schema.json` with drift parity. Binds:

- base/target profile ids and exact byte SHA-256 hashes;
- release manifest id and content SHA-256;
- boundary-input identity (template analysis id + input content hash) and
  the deterministic boundary row evidence;
- an exact canonical ordered check list (like Phase 7-A-R2), each check
  with `PASS | FINDING | BLOCKED`, a scope
  (`base | target | pair`) and a stable machine-readable reason code;
- derived `semantic_findings` (stable codes, per profile, each marked
  covered or not covered by a declared policy exception);
- `policy_approval_status` (detection-only, see 4.3);
- `activation_readiness`:
  `BLOCKED_FOR_ACTIVATION | POLICY_DECISION_REQUIRED |
  READY_FOR_POLICY_DECISION`;
- fixed literals `requires_human_policy_approval=true`,
  `automatic_activation_allowed=false`,
  `publication_is_not_activation_approval=true`;
- deterministic `audit_id` and `content_sha256`.

Classification rule (deterministic):

- any `BLOCKED` check (invalid profile, manifest/identity/lineage tamper,
  unregistered rule change, non-reproducible replay) →
  `BLOCKED_FOR_ACTIVATION`;
- otherwise any uncovered semantic finding → `POLICY_DECISION_REQUIRED`
  with the finding reason codes;
- otherwise → `READY_FOR_POLICY_DECISION`.

`READY_FOR_POLICY_DECISION` still means the human economic-policy decision
is outstanding; it is never an approval.

### 4.2 Canonical checks

Exact ordered sequence, enforced by a model validator and by per-position
`prefixItems` schema constraints (inline, no external `$ref`):

1. `BASE_PROFILE_VALID`
2. `TARGET_PROFILE_VALID`
3. `VERSION_LINEAGE_NEXT`
4. `RELEASE_MANIFEST_VALID` (parses; fixed literals intact)
5. `BASE_PROFILE_BYTES_HASH`
6. `TARGET_PROFILE_BYTES_HASH`
7. `TARGET_PROFILE_IDENTITY` (id, filename, rule-payload digest)
8. `RULE_CHANGES_REGISTERED` (re-derived base->target leaf diff equals the
   manifest's registered changes exactly)
9. `CDC_BAND_ORDER` (base)
10. `CDC_BAND_ORDER` (target)
11. `CDC_GATE_TIER_COHERENCE` (base)
12. `CDC_GATE_TIER_COHERENCE` (target)
13. `THROUGH_RETURN_BAND_ORDER` (base)
14. `THROUGH_RETURN_BAND_ORDER` (target)
15. `VALUATION_TIER_ORDER` (base)
16. `VALUATION_TIER_ORDER` (target)
17. `BOUNDARY_REPLAY_REPRODUCIBLE`
18. `POLICY_EXCEPTIONS_VALID`

Band-order invariants (from `docs/spec/01-cdc.md` section 11 and the
through-return band structure): `s >= a >= pass >= watch >= fail_below`.
Gate/tier coherence: `cdc.yield_bands.pass <=
valuation.tiers.extreme_safety.cdc_yield`. Valuation tier order:
`observation <= acceptable <= turtle_entry <= extreme_safety` on both
tier fields. A violation of a *band/tier ordering* invariant or the
gate/tier relationship is a `FINDING` (semantic coherence), not a
`BLOCKED` structural invalidity: the profile remains executable and
interpretable as a stricter eligibility policy, which is exactly the
distinction Issue #5 requires.

### 4.3 Policy-exception and approval semantics

`VersionedPolicyExceptionV1` (`versioned_policy_exception_v1`, checked-in
schema): explicit, versioned, human-authored declaration binding the exact
profile id + byte hash, one rule path, one narrow exception code
(initially only `CDC_GATE_ABOVE_S_BAND_PERMITTED`), a non-empty rationale
and a declaring owner identity. C1 defines the contract and coverage
machinery only; **no exception is checked in for strict-v2** (that is the
owner's policy decision), and the audit never invents one.

`PolicyApprovalClaimV1` (detection-only input): a claim file binding
target id + hash, decision `ACCEPTED | REJECTED`, deciding human and date.
The audit validates only its shape and binding and reports
`policy_approval_status`:

- `ABSENT` — no claim supplied (the expected state for C1);
- `UNVERIFIED_ACCEPTANCE_CLAIM` / `UNVERIFIED_REJECTION_CLAIM` —
  well-formed and binding, but explicitly not verified: verifying a human
  approval is outside the offline audit boundary;
- `MISMATCHED_CLAIM` — binds different bytes/id (stale or ambiguous).

No status ever becomes a verified approval, and no status changes the
fixed literals or allows automatic activation.

### 4.4 Boundary replay evidence

Two deterministic row sets derived from one explicitly supplied normalized
input (default `fixtures/healthy_cash_cow.json`):

- **Gate rows** — exact boundary values through the actual
  `evaluate_cdc_gate` (synthetic `CDCResult` with exact yields): for every
  distinct CDC threshold in the union of both profiles' `cdc.yield_bands`
  and valuation-tier CDC hurdles, the values `t-1e-9`, `t`, `t+1e-9`,
  plus midpoints between adjacent thresholds (this covers
  `0.06/0.08/0.10/0.12/0.13/0.14` plus epsilon as required by Issue #5).
- **Pipeline rows** — the actual `run_analyze` end-to-end on
  boundary-derived inputs (market-cap facts rescaled so the CDC yield
  lands at `t±1e-6`, midpoints, and below/above probes), with a
  deterministically synthesized maximal business-quality assessment so the
  full green path is observable. Each row records both profiles' CDC
  gate status, valuation state, final decision, per-rule divergence
  reasons and withheld-valuation reason codes.

The replay proves actual decision divergence: strict-v1 classifies a
normal valuation state inside the window where strict-v2 withholds to
`WATCH`/`SPECIAL_REVIEW`.

### 4.5 CLI boundary

```text
tve evolution audit-profile \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  [--boundary-input fixtures/healthy_cash_cow.json] \
  [--policy-exceptions <file>] \
  [--approval-claim <file>] \
  [--output <audit.json>]
```

Read-only with respect to every supplied artifact; the only write is the
optional output. Output paths under active `rules/`, over any supplied
input, or that are symlinks are refused. Exit codes: `0` audit produced
and `READY_FOR_POLICY_DECISION`; `1` audit produced and
`BLOCKED_FOR_ACTIVATION` or `POLICY_DECISION_REQUIRED` (payload still
printed/persisted); `2` invalid input/path. No provider, model, transport
or network client is constructed anywhere in the path.

## 5. Misleading strict-v1 output labels

Fix `pipeline._build_decision` to derive the three decision texts from the
active profile id (`normalized_input.profile_id`, already verified equal
to the active profile at `run_analyze` entry). strict-v1 outputs remain
byte-identical; strict-v2 outputs stop claiming to be strict-v1.
Investment calculations, states, enums and schemas are unchanged.

## 6. Baseline evidence

C1 is a new capability with a presentation fix. Structural baseline
recorded in section 3. Additionally required before implementation:
fail-on-baseline proof that a strict-v2 analysis currently emits
`strict-v1`-labeled decision text (the defect being fixed), captured from
the reviewed baseline.

## 7. Required automatic verification

Focused C1 tests must prove at minimum:

1. published `strict-v1`/`strict-v2`/manifest audit: structural checks
   PASS, both coherence findings reported for strict-v2 only,
   classification `POLICY_DECISION_REQUIRED`, approval `ABSENT`;
2. exact CDC boundary/epsilon gate rows (the `[0.08, 0.14)` window,
   `0.14-1e-9` WATCH, `0.14` PASS) through the real gate;
3. end-to-end decision divergence rows through the real pipeline,
   including valuation withholding reasons;
4. valid monotonic configurations (synthetic compliant profile) reach
   `READY_FOR_POLICY_DECISION` with zero findings;
5. tampered manifest / wrong profile hashes / wrong lineage /
   unregistered extra rule change → `BLOCKED_FOR_ACTIVATION` with stable
   reason codes and zero rule-file mutation;
6. a well-formed, hash-bound policy exception covers the findings
   (classification stays policy-gated but the finding is marked covered);
   a mismatched/foreign exception is rejected and never covers;
7. approval-claim detection: absent / stale (wrong hash →
   `MISMATCHED_CLAIM`) / acceptance claim stays `UNVERIFIED_*` and never
   enables activation;
8. deterministic reproducibility: two audits byte-identical (no
   wall-clock), stable `audit_id`/`content_sha256`;
9. socket-guarded execution proves zero network sockets;
10. zero implicit activation: default profile, `rules/strict-v1.yaml`,
    `rules/strict-v2.yaml` and the release manifest byte-identical before
    and after every audit path;
11. schema drift parity for both new schemas; the audit validates against
    the checked-in schema;
12. decision-label fix: strict-v1 strings unchanged, strict-v2 strings
    carry `strict-v2`, and all existing suites stay green.

Then run the complete CI-equivalent gate (Ruff, config validation, full
Python suite, systemd verify, OpenAPI/API/Wrangler checks, Dashboard
lint/typecheck/tests/build/secret-scan, Wrangler strict dry-run,
cross-stack smoke). After push, require GitHub Actions `success` with
`head_sha` exactly equal to the implementation commit.

## 8. Manual-intervention policy

No manual owner action is planned. If an external authority blocks a
check, record all seven items (exact attempted command, exact blocker,
required human action, credential/data boundary, resume command,
machine-checkable success criterion, remaining unverified scope).

## 9. Stop boundary

Stop after the audit capability, tests, label fix, documentation, exact
CI closure, Issue #5 evidence update and handoff are complete.

Do not:

- change any published profile/release-manifest byte;
- change the default profile or apply/activate strict-v2;
- synthesize, infer or record a policy approval or a policy exception for
  the published strict-v2;
- normalize or "fix" the 0.14 threshold (recommend a separately reviewed
  strict-v3 instead if the owner rejects it);
- expand provider/Bridge/FQGate, notification, brokerage or trading scope.

C1 ends with a verified semantic-audit and activation-readiness mechanism,
not an activated investment policy.
