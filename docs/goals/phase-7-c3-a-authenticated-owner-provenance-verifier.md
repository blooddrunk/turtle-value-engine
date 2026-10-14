# Phase 7-C3-A — Authenticated Owner Provenance Verifier: Contracts, Threat Model and Offline Verification

Status: **IMPLEMENTED / CLOSED**
Closed at implementation: `ee05e21e56caf6271469d16efd518c2c285143b2`
(exact-head Actions run `38507640664` `success`; closure record
`docs/status/phase-7-c3-a-2026-10-14.md`)
Selected by: the Phase 7-C2-R2 closure record
(`docs/status/phase-7-c2-r2-2026-10-14.md` §9) following the C2-R1/C2-R2
post-closure chain (`docs/status/phase-7-c2-r1-2026-10-14.md` §8,
`docs/status/phase-7-c2-r2-2026-10-14.md`)
Reviewed baseline: `6133df5c7ced9f976747ffb70d21149f49696585` (main, 2026-10-14)
Objective: provide the first real implementation of the C2
`OwnerDecisionVerifier` trust-model interface — an offline, standard,
digitally signed owner-provenance verifier — as contracts, threat model,
pure verification function, a library-only verifier class and deterministic
test fixtures. **C3-A implements no activation executor, no CLI trust wiring,
no key provisioning and no evidence-capture tooling** (C3-B owns trusted
identity registration lifecycle, capture, revocation workflow and end-to-end
record integration).

## 1. Signature technology choice (recorded rationale)

**Ed25519 (RFC 8032) detached signatures**, verified through the open-source
audited `cryptography` library (OpenSSL backend; Apache-2.0 OR BSD-3-Clause):

- fully offline verification, no network, no vendor, no account, no service;
- deterministic signatures (no nonce-misuse failure class as in ECDSA);
- fixed 32-byte keys and 64-byte signatures — no parameter variants to
  misconfigure; widely standardized (RFC 8032, FIPS 186-5, SSH, Git, minisign);
- the `cryptography` implementation is maintained and audited; the project
  deliberately avoids transcribing pure-Python crypto into the repository.

Rejected alternatives (recorded for audit): GnuPG (heavy tooling, opaque
packets, awkward canonical byte binding), ECDSA P-256 (nonce fragility, DER
encoding variance), RSA (large keys, padding-mode choices), Sigstore/managed
identity (requires network/infrastructure, conflicts with the offline
boundary), allowlists/usernames/Git authors/CI success (already established
in C2 as proving neither authorship nor permission).

## 2. Contracts (`evolution/owner_provenance.py`)

1. `OwnerProvenanceKeyRecordV1` — one registered trusted public key:
   content-derived `key_id` (deterministic from algorithm + key bytes only,
   never from decision files), `algorithm="ED25519"`, base64 32-byte public
   key, bound `owner_identity`, explicit `authorized_decisions` scope,
   owner-declared `valid_from`/`valid_until` ISO dates (compared against the
   signed decision's `decided_at` — deterministic, no wall-clock), explicit
   `revoked` + `revocation_reference`.
2. `OwnerProvenanceKeyRegistryV1` — the independent trust root: an explicitly
   supplied immutable registry with unique key ids and unique key material.
   Nothing in the registry is derived from, or referenced by, the decision
   files it verifies.
3. `OwnerSignedDecisionStatementV1` — the immutable signature evidence:
   fixed `purpose` domain literal, `algorithm="ED25519"`, `key_id`,
   64-byte `signature_base64`, `decision_input_content_sha256` (the exact
   canonical decision-input bytes) and `signed_content_sha256` (the exact
   domain-separated message), plus the declared owner identity.
4. `OwnerProvenanceVerificationV1` + `OwnerProvenanceVerificationCheckV1` —
   the deterministic result dossier with the canonical nine-check sequence
   (`ALGORITHM_SUPPORTED`, `KEY_RESOLUTION`, `KEY_IDENTITY_BINDING`,
   `KEY_SCOPE_AUTHORIZED`, `KEY_VALIDITY_WINDOW`, `KEY_NOT_REVOKED`,
   `DECISION_CONTENT_BINDING`, `PURPOSE_BINDING`, `SIGNATURE_VERIFIED`),
   a deterministic `verification_id`/`content_sha256`, and VERIFIED only when
   every check passes.

The signed message is the fixed domain prefix
`turtle-value-engine:owner-policy-decision:v1` + NUL + the exact canonical
`OwnerPolicyDecisionInputV1` bytes. The input itself already binds base and
target profile ids + byte SHA-256, release-manifest id + content SHA-256,
fresh-audit id + content SHA-256, exception id + full content SHA-256,
rationale, owner identity and `decided_at`, so a signature cannot be replayed
across profiles, versions or decisions without breaking verification, and the
domain prefix prevents replay of the same key's signature for any other
purpose.

## 3. Verification boundary

- `verify_owner_provenance(decision_input_bytes=..., statement=...,
  registry=..., declared_owner_identity=...)` — a pure offline function;
  every check is evaluated and recorded; VERIFIED requires all nine.
- `SignedOwnerProvenanceVerifier(OwnerDecisionVerifier)` — the real
  library-only verifier class (`kind="ed25519-signed-owner-provenance"`)
  constructed with the registry, the statement and the exact signed
  decision-input bytes. At plan time it additionally proves the presented
  record and the signed submission are the same content:
  `provenance.source_content_sha256` must equal the signed bytes' hash, and
  the record's embedded decision fields must equal the signed input's fields
  (an ACCEPT record pointing at a signed REJECT submission is REJECTED). The
  returned `OwnerAuthorityAssessmentV1` sets `allowlist_matched=True` only on
  a positive registry identity binding and binds
  `evidence_content_sha256` to the exact record bytes (the C2-R1 contract).
- The production CLI constructs no verifier and gains no flag; no
  `trust=true`, environment override or fake-verifier selector exists
  (asserted by source scan).

## 4. Threat model (summary; full text in
`docs/architecture/owner-provenance-verification.md`)

In scope: forged/self-consistent VERIFIED records, signature replay across
profiles/versions/purposes, unsigned-substitution (record claims provenance
hash of a signed submission it does not embed), tampered decision bytes,
wrong/revoked/expired/scope-exceeding keys, identity mismatch, malformed
keys/signatures, algorithm confusion. Out of scope (documented, fail-closed
or deferred): key theft (mitigated by owner key custody + revocation in
C3-B), registry substitution (the registry is an explicit independent input —
a caller supplying a different registry changes the trust root visibly),
side-channel/timing attacks on the offline verifier.

## 5. Acceptance criteria

1. Deterministic tests generate real Ed25519 test keypairs (fixtures only;
   no real owner key enters the repository) and prove: VERIFIED happy path;
   every negative class above fails closed with the exact failing checks;
   cross-profile, cross-decision-value and cross-purpose signature reuse is
   rejected; a forged record pointing at a signed REJECT cannot verify as
   ACCEPT.
2. End-to-end: `plan_profile_activation(authority_verifier=
   SignedOwnerProvenanceVerifier(...))` reaches `REVERIFIED`/READY only with
   a genuinely signed, registry-valid decision; without a signature or with
   any tampering it stays BLOCKED, `execution_performed=false`,
   `automatic_activation_allowed=false`.
3. Three checked-in Draft 2020-12 schemas with exact drift parity and the
   pinned nine-check sequence; determinism (no wall-clock fields); socket
   guard proving no network during verification; published-byte and
   default-profile invariance; no CLI verifier selector (source assertion).
4. `cryptography` is a new optional `[provenance]` dependency group; CI
   installs it; the module fails closed with a classified error when the
   library is absent; core imports stay dependency-free (lazy import).
5. Full automatic gate (ruff, focused, full pytest, config validate, every
   CI workflow command incl. Dashboard/OpenAPI/Wrangler/cross-stack smoke)
   and exact-head Actions success. No manual owner action is required for
   C3-A closure; no real owner signature is claimed or synthesized —
   synthetic test keys prove the boundary, and real owner acceptance of
   strict-v2 remains explicitly absent.

## 6. Exclusions

No activation executor, no rule/default/config mutation, no CLI authority
wiring, no key provisioning or revocation workflow tooling (C3-B), no
provider/Bridge/notification expansion, no investment-math changes, no
H-share scope change.
