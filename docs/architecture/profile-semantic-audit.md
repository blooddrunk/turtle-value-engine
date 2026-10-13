# Profile Semantic Audit and Activation Readiness Architecture

Phase 7-C1 implements the deterministic, offline, read-only audit boundary
between *publishing* a versioned rule profile (Phase 7-B2: bytes + release
manifest on `main`) and *activating* it as policy (a later explicit owner
decision). It was selected from
[Issue #5](https://github.com/blooddrunk/turtle-value-engine/issues/5): the
published `strict-v2` raises `cdc.yield_bands.pass` from `0.08` to `0.14`
while retaining `s = 0.12` and the 12% `extreme_safety` tier hurdle, and the
repository had no machine-checked way to distinguish a structural defect
from a deliberate stricter-eligibility policy awaiting an explicit decision.

```text
published profile pair + release manifest (+ optional boundary template,
policy exceptions, approval claim)
        -> audit_profile_semantics(...)            # offline, read-only
        -> 18 canonical checks (identity / lineage / manifest / rules)
        -> semantic coherence findings (band order, gate vs. tier)
        -> boundary replay through the REAL engine (gate + run_analyze)
        -> ProfileSemanticAuditV1
             BLOCKED_FOR_ACTIVATION | POLICY_DECISION_REQUIRED
             | READY_FOR_POLICY_DECISION
```

No audit outcome approves, applies or activates anything. The contract
carries the fixed literals `requires_human_policy_approval=true`,
`automatic_activation_allowed=false` and
`publication_is_not_activation_approval=true`; a green CI run and a valid
release manifest are inputs to the audit, never authority to activate.

## Three separable questions

1. **Well-formed/reproducible** — `BASE/TARGET_PROFILE_VALID`,
   `VERSION_LINEAGE_NEXT`, `RELEASE_MANIFEST_VALID`, byte-hash checks,
   `TARGET_PROFILE_IDENTITY` (id + canonical filename + rule-payload
   digest) and `RULE_CHANGES_REGISTERED` (the re-derived base-to-target
   leaf diff must equal the manifest's registered changes exactly).
   Failure is `BLOCKED` and the dossier classifies
   `BLOCKED_FOR_ACTIVATION`.
2. **Semantically coherent** — `CDC_BAND_ORDER`,
   `CDC_GATE_TIER_COHERENCE`, `THROUGH_RETURN_BAND_ORDER` and
   `VALUATION_TIER_ORDER`, each evaluated per profile. A violation is a
   `FINDING` with a stable code, not a structural `BLOCKED`: the profile
   stays executable and interpretable as a (possibly nonstandard)
   economic policy — exactly the distinction Issue #5 requires.
   Uncovered findings classify `POLICY_DECISION_REQUIRED`.
3. **Policy accepted by owner** — detection only
   (`policy_approval_status`: `ABSENT` / `UNVERIFIED_*` /
   `MISMATCHED_CLAIM`). Verifying a human decision is outside the offline
   boundary; no status is ever a verified approval.

The canonical check sequence (18 entries, each with a fixed
`name`+`scope`) is enforced twice: by a Pydantic model validator and by
per-position `prefixItems`/`const` constraints in the checked-in Draft
2020-12 schema `schemas/profile-semantic-audit.schema.json`, following the
Phase 7-A-R2 pattern.

## Semantic invariants

- **CDC band order** (`docs/spec/01-cdc.md` section 11):
  `s >= a >= pass >= watch >= fail_below`.
- **Gate/tier coherence**: `cdc.yield_bands.pass <=
  valuation.tiers.extreme_safety.cdc_yield` — the eligibility gate must not
  be stricter than the top valuation tier's CDC hurdle. The published
  strict-v2 violates this (`0.14 > 0.12`): yields in `[0.12, 0.14)`
  satisfy the `extreme_safety` hurdle yet are held at `WATCH` by the gate.
- **Through-return band order**: the same graded-band invariant on
  `through_return.yield_bands`.
- **Valuation tier order**: `observation <= acceptable <= turtle_entry <=
  extreme_safety` on both tier fields (redundant with the calculation-time
  guard, but audited explicitly at publication time).

## Boundary replay through the real engine

The audit never restates thresholds; it replays them:

- **Gate rows** — every distinct CDC threshold in the union of both
  profiles' `cdc.yield_bands` and valuation-tier CDC hurdles is probed at
  `t-1e-9`, `t`, `t+1e-9` (plus midpoints) through the actual
  `evaluate_cdc_gate` with synthetic `CDCResult` objects. For
  strict-v1/v2 the divergence window is exactly `[0.08, 0.14)`:
  `PASS` under strict-v1, `WATCH` under strict-v2.
- **Pipeline rows** — the actual `run_analyze` runs end-to-end on
  boundary-derived inputs (market-cap facts rescaled so the CDC yield
  lands at `t±1e-6`, midpoints and outer probes) under both profiles,
  with a deterministic synthetic maximal business-quality assessment so
  the full green path is observable. Each row records both profiles' CDC
  gate status, valuation state, final decision, `auto_decision_allowed`,
  rule-level divergence reasons (`CDC.YIELD:PASS->WATCH`) and
  valuation-withholding reasons (`NON_PRICE_GATES_UNRESOLVED`).

For the published pair this proves the Issue #5 scenario end-to-end: at a
13% CDC yield strict-v1 reaches `EXTREME_SAFETY` with
`auto_decision_allowed=true`, while strict-v2 withholds valuation
(`SPECIAL_REVIEW`) and decides `WATCH`. The replay is computed twice per
audit and must be byte-identical (`BOUNDARY_REPLAY_REPRODUCIBLE`).

The boundary template is an explicitly supplied normalized input (default:
the checked-in synthetic `fixtures/healthy_cash_cow.json`); its analysis id
and content hash are bound into `audit_id`. Fail-closed template blockers
(`BOUNDARY_TEMPLATE_PROFILE_MISMATCH`, `BOUNDARY_TEMPLATE_CDC_UNAVAILABLE`,
`BOUNDARY_TEMPLATE_EVIDENCE_COLLISION`) become `BLOCKED` checks, never
silent fallbacks.

## Versioned policy exceptions

`VersionedPolicyExceptionV1` (`versioned_policy_exception_v1`) is an
explicit, human-authored declaration binding one exact profile id + byte
hash, one rule path and one narrow registered code — initially only
`CDC_GATE_ABOVE_S_BAND_PERMITTED` for `cdc.yield_bands.pass`. A binding
exception marks the matching findings `covered_by_policy_exception=true`
and moves the classification to `READY_FOR_POLICY_DECISION`; the exception
never changes engine behavior, never covers arbitrary band disorder (the
coverage predicate requires the exact gate-above-band pattern:
`pass > s`, `s >= a`, `watch >= fail_below`), and **no exception is
checked in for strict-v2** — declaring one is the owner's policy decision.

## Approval-claim detection

`PolicyApprovalClaimV1` (`policy_approval_claim_v1`) models a *claim* of a
human ACCEPTED/REJECTED decision bound to exact target bytes. The audit
validates only shape and binding and reports
`UNVERIFIED_ACCEPTANCE_CLAIM` / `UNVERIFIED_REJECTION_CLAIM` /
`MISMATCHED_CLAIM`. There is deliberately no `VERIFIED` status: no offline
artifact can prove who typed a JSON file, and no claim changes the fixed
no-activation literals.

## CLI boundary

```text
tve evolution audit-profile \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  [--boundary-input ...] [--policy-exceptions ...] [--approval-claim ...] \
  [--output audit.json]
```

Read-only over every supplied artifact; the only write is the optional
output. Output paths that are symlinks, equal to a supplied input, or
under published artifact directories (active `rules/`, the supplied
profiles' directory, the manifest's directory) are refused. Exit codes:
`0` READY_FOR_POLICY_DECISION, `1` BLOCKED_FOR_ACTIVATION or
POLICY_DECISION_REQUIRED (the dossier is still printed and persisted),
`2` invalid input/path. No provider, model, transport or network socket is
constructed anywhere in the path.

## Profile-aware decision labels

`pipeline._build_decision` previously emitted hardcoded `strict-v1` text
(`"Deterministic strict-v1 state: …"`, `"No normal strict-v1 valuation…"`,
`"The strict-v1 inputs do not support…"`) regardless of the active
profile. Phase 7-C1 derives all three from `normalized_input.profile_id`
(verified equal to the active profile at `run_analyze` entry), so
strict-v1 output is byte-identical and strict-v2 analyses stop carrying
misleading provenance text. Investment calculations, states, enums and
schemas are unchanged.

## Relationship to neighbors

- The audit consumes the **published** Phase 7-B2 artifacts exactly as
  they exist on `main`; it never rewrites them and never consults the
  private calibration workspace (that is B1/B2-A authority, a different
  question than publication integrity).
- `strict-v1` remains the default profile; auditing `strict-v2` neither
  applies nor activates it. Activation remains a separate explicit owner
  decision (later Phase 7-C2 scope), to be taken only after the owner
  resolves the recorded findings — by declaring the policy exception or by
  publishing a corrected `strict-v3` through the unchanged 7-A/B1/B2
  chain.
