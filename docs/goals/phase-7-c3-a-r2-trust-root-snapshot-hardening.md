# Phase 7-C3-A-R2 — Trust Root Snapshot Hardening (independent review closure)

Status: **SELECTED / IN PROGRESS**
Selected by: independent post-C3-A-R1 review of main
`ce9726d2445f578215159722d85ac8027d8d20ac` (branch
`phase-7-c3-a-r2-trust-root-snapshot-hardening`)
Objective: make the trust root content-addressed through every artifact that
depends on it, with fail-on-baseline reproductions, adversarial regressions
and the full automatic gate.  No manual owner action.

## 1. Reviewed defects (all reproduced fail-on-baseline `ce9726d`)

The standalone six-check reproduction builds one throwaway Ed25519 key, two
valid registries with the **same key set** (therefore the same derived
`registry_id`) but different trust content (validity windows that both cover
`decided_at`; revocation flags, scopes and identity edits are the same class),
and executes the real record-time capture and plan-time re-attestation flows.
All six checks show the defect on the pristine baseline:

1. **`registry_id` is not a content identity.**  Two registries with identical
   key sets but different trust semantics share one `registry_id`, because the
   id is derived from key ids only.
2. **`verification_id` collides across different trust roots.**  The same
   signed statement verifies byte-identically (same `verification_id`) under
   both registries; only un-hashed check *prose* (the validity-window text)
   differs, and the dossier carries no registry content hash anywhere — the
   persisted VERIFIED dossier cannot name or be replayed against the exact
   trust-root bytes that produced it.  This contradicts
   `docs/architecture/owner-provenance-verification.md` §4, which promises
   "registry id and content hash are bound into every verification dossier".
3. **The persisted VERIFIED record captures no structured trust-root
   identity.**  The record's `authority` assessment names the verifying key
   only inside the free-text `detail`; no structured key/registry identity
   field exists (violates the repository rule that evidence identity is
   first-class data, never prose-only citation).
4. **Two different trust roots reach byte-identical READY plans.**  The same
   captured record planned with re-attestation verifier A (registry content
   C1) and verifier B (registry content C2, same key set) produces the same
   `plan_id` and the same plan bytes; the READY plan names no attesting
   registry anywhere, so the owner-facing artifact cannot state which trust
   root re-attested the authority it relies on.

No privilege escalation exists through these gaps today (forged VERIFIED
claims still cannot reach READY — C2-R1 re-attestation is unaffected); the
defect class is audit integrity: the one input whose content decides trust
(the registry) is the one input whose content no persisted artifact pins.
C3-B evidence capture cannot be built on top of dossiers/plans that cannot
name their trust root.

## 2. Hardening rules (the corrected invariants)

1. `OwnerProvenanceVerificationV1` gains the required
   `registry_content_sha256` field, set from the supplied registry's own
   validated content hash and included in the `verification_id` derivation —
   one verification identity per (trust-root content, key, decision content,
   outcome).  The canonical nine-check sequence is unchanged (the registry's
   internal consistency is already enforced at model construction; the new
   binding is recording, not checking).
2. `OwnerAuthorityAssessmentV1` gains three additive optional structured
   fields — `attested_key_id`, `attested_registry_id`,
   `attested_registry_content_sha256` — populated by
   `SignedOwnerProvenanceVerifier` on every assessment (VERIFIED and
   rejected) from its own registry and the verification dossier.  They are
   captured bookkeeping of what the verifier actually used, never authority:
   a forged record claiming foreign attested fields changes nothing, because
   plan-time authority always comes from the fresh injected-verifier
   assessment.
3. `ProfileActivationPlanV1` gains `authority_reverification_registry_id` /
   `authority_reverification_registry_content_sha256`, sourced exclusively
   from the **fresh** re-attestation assessment (never the persisted record
   claim), included in the `plan_id` derivation, and required to be supplied
   together (both-or-neither coherence).  Plans derived under different
   attesting trust roots therefore differ in identity and bytes.
4. Deliberate non-goal: a verifier that attests no trust root (the generic
   C2 fake fixtures, and any future non-registry trust model) still follows
   the unchanged C2/C2-R1 rules — the fields stay visibly `None` rather than
   fabricating a binding, and no new READY-blocking requirement is imposed on
   the verifier interface in this package.  Nothing about the
   fail-closed re-attestation semantics changes.

## 3. Acceptance

- Fail-on-baseline reproductions for defects 1–4 executed on pristine
  `ce9726d`; identical adversarial cases pass on the hardened tree.
- Adversarial regressions live in `tests/test_owner_provenance.py`
  (`test_r2_*`): dossier content binding and identity divergence, record
  structured attestation, plan trust-root binding and divergence, fresh-
  verifier-over-persisted-claim precedence, forged-attestation inertness,
  and preservation of every C3-A/C3-A-R1 negative class.
- Schema drift parity regenerated for `owner-provenance-verification`,
  `owner-policy-decision-record` and `profile-activation-plan`; the pinned
  per-position check sequences are unchanged.
- Full local gate green (ruff, focused suites, full pytest, config validate,
  systemd verify, OpenAPI/Dashboard/Wrangler/cross-stack checks) and
  exact-head GitHub Actions success on the implementation commit.
- `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, the strict-v2 release
  manifest, the default profile and all configuration remain byte-identical;
  no owner key, signature, decision, approval or activation is synthesized;
  `execution_performed=false` / `automatic_activation_allowed=false` stand.
- C3-B (trusted registry lifecycle/persistence, evidence capture, signed
  revocation, CLI integration) remains a separately selected package; this
  package changes no CLI surface.
