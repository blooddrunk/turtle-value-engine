# Phase 7-C3-A-R1 — Provenance Binding Hardening (independent review closure)

Status: **IMPLEMENTED / CLOSED**
Closed at implementation `79560e3412ce031c283e8d0c0a7ed2ae868dd750`
(exact-head Actions run `38531123746` `success`; closure record
`docs/status/phase-7-c3-a-r1-2026-10-14.md`)
Selected by: independent post-C3-A review of main `7d681f94780af20d00a6b793ec539030081c2220`
(PR #8, branch `phase-7-c3-a-r1-provenance-binding-hardening`)
Objective: close every trust-boundary defect an independent review finds in the
C3-A authenticated provenance boundary, with fail-on-baseline reproductions,
adversarial regressions and the full automatic gate.  No manual owner action.

## 1. Reviewed defects (all reproduced fail-on-baseline `7d681f9`)

1. **Unsigned supersession changes record-set resolution.**  A genuinely
   signed ACCEPT record carrying unsigned `supersedes_decision_record_id`
   metadata pointing at a conflicting REJECT collapsed a CONFLICTING set into
   a single active record and reached `READY_FOR_EXPLICIT_OWNER_EXECUTION`.
2. **Signed `source_revision` not compared at plan time.**  A record whose
   persisted `provenance.source_revision` differed from the signed decision
   input's own `source_revision` still verified — the legitimate record-time
   flow always copies the input's revision, so drift is tampering.
3. **Noncanonical Base64 aliases.**  Changing only unused RFC 4648 pad bits
   produced a different string that decodes to the same Ed25519 key material,
   derived a distinct `key_id`, and entered a registry alongside the
   canonical entry (two identities, one key).
4. **Calendar-invalid ISO-shaped dates.**  `decided_at = "2026-02-30"`
   escaped `verify_owner_provenance` as a raw unclassified `ValueError`
   instead of a deterministic `REJECTED` dossier.
5. **Unsigned revocation changes record-set resolution (found by the R1
   review itself, same class as 1).**  A forged revocation of a dissenting
   REJECT removed it from the active set and reached
   `READY_FOR_EXPLICIT_OWNER_EXECUTION`; the resolver applies every
   structurally valid revocation at face value and nothing authenticated it.

## 2. Hardening rules (the corrected invariants)

1. `SignedOwnerProvenanceVerifier` rejects any record presented at plan-time
   re-attestation that carries `supersedes_decision_record_id` with the
   classified `OWNER_PROVENANCE_UNSIGNED_SUPERSESSION` reason — a signature
   over the decision input never authenticates supersession metadata.  No
   signed supersession protocol is invented here; fail closed until a
   versioned protocol exists (C3-B or later).  A forged supersession chain
   cannot help either: every superseder stays active itself, so the
   resolution fails closed as AMBIGUOUS/CONFLICTING (pinned by test).
2. Plan-time re-attestation additionally requires the record's
   `provenance.source_revision` to equal the signed input's
   `source_revision` (both the presented provenance and the embedded record
   provenance); drift is `OWNER_PROVENANCE_RECORD_INPUT_BINDING_MISMATCH`.
3. Every accepted Base64 value (public key, signature) must be the canonical
   RFC 4648 encoding of its decoded bytes — `_decode_base64` re-encodes and
   compares, and `owner_provenance_key_id` validates before deriving an id,
   so one key material has exactly one representable identity.  Legitimate
   encoder output is always canonical, so no valid artifact is rejected.
4. `verify_owner_provenance` classifies impossible calendar dates
   deterministically: the validity-window check catches `ValueError` and
   leaves `key_validity=UNKNOWN` → `REJECTED` dossier.  Registry validity
   dates were and remain classified `ValidationError` at model construction
   (pinned by test).
5. `plan_profile_activation` blocks with
   `OWNER_REVOCATION_AUTHORITY_UNVERIFIED` whenever a supplied revocation
   withdraws a record of this plan's exact target — withdrawing a decision
   can never increase what the remaining set authorizes until a versioned
   signed revocation protocol exists.  A revocation of a stale/other-target
   record stays inert bookkeeping and does not block.

## 3. Acceptance

- Fail-on-baseline reproductions for defects 1–5 executed on pristine
  `7d681f9` worktrees; identical adversarial cases pass on the hardened tree.
- Adversarial regressions live in `tests/test_owner_provenance.py`
  (`test_r1_*`); the two pre-R1 fixtures whose `source_revision` drifted from
  the signed submission were updated to the legitimate value (their records
  were exactly the tampering class the fix now rejects; test purposes are
  unchanged).
- Full local gate green (ruff, focused suites, full pytest, config validate,
  systemd verify, OpenAPI/Dashboard/Wrangler/cross-stack checks) and
  exact-head GitHub Actions success on the implementation commit.
- `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, the strict-v2 release
  manifest, the default profile and all configuration remain byte-identical;
  no owner key, signature, decision, approval or activation is synthesized;
  `execution_performed=false` / `automatic_activation_allowed=false` stand.
