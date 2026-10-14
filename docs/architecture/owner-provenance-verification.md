# Owner Provenance Verification — Architecture (Phase 7-C3-A)

Status: implemented at the C3-A boundary (contracts, threat model, pure
offline verification, the real library verifier class, deterministic test
fixtures). C3-B (trusted identity registration lifecycle, evidence-capture
tooling, revocation workflow, end-to-end record integration and any CLI
wiring) remains a separately selected package. No activation executor exists.

Related documents:

- Goal: `docs/goals/phase-7-c3-a-authenticated-owner-provenance-verifier.md`
- Trust-model interface and record/plan contracts:
  `docs/architecture/owner-policy-decision-and-activation-plan.md`
- Module: `src/turtle_value_engine/evolution/owner_provenance.py`
- Tests: `tests/test_owner_provenance.py`

## 1. Why digital signatures, and why Ed25519

Phase 7-C2 established that an unsigned local JSON file, an EnvironmentFile
username, Git author text, a green CI run, a publication manifest and an
identity allowlist prove neither authorship nor permission, and that every
CLI-recorded decision stays visibly `OWNER_AUTHORITY_UNVERIFIED` until a
real authenticated source exists. C2-R1 additionally made plan-time
authority re-attestation mandatory through an injected verifier. C3-A
supplies that verifier.

The choice is **Ed25519 detached signatures (RFC 8032)** verified through
the open-source audited `cryptography` library:

- verification is fully offline — no network, vendor, account or service;
- signatures are deterministic (no ECDSA-style nonce failure class);
- 32-byte keys and 64-byte signatures with no parameter variants;
- standardized widely (RFC 8032, FIPS 186-5, SSH, Git, minisign);
- the repository deliberately avoids transcribing pure-Python crypto — the
  maintained, audited implementation is a dependency instead.

Rejected alternatives are recorded in the goal document (GnuPG, ECDSA
P-256, RSA, Sigstore/managed identity, and every non-cryptographic
"proof" already rejected by C2).

`cryptography` is a new **optional** `[provenance]` dependency group; the
core package never imports it at module scope. CI installs
`.[api,dev,provenance]`; without the extra, verification fails closed with a
classified `OwnerProvenanceError` instead of degrading.

## 2. Contracts

All contracts are immutable, `extra="forbid"`, content-hashed and exported
with checked-in Draft 2020-12 schemas (exact drift parity; the verification
schema pins the canonical nine-check sequence per position via
`prefixItems` with `items: false`).

```text
OwnerProvenanceKeyRegistryV1            the independent trust root
  └─ OwnerProvenanceKeyRecordV1[]       one registered Ed25519 public key
OwnerSignedDecisionStatementV1          the immutable signature evidence
OwnerProvenanceVerificationV1           the deterministic result dossier
  └─ OwnerProvenanceVerificationCheckV1[]  canonical nine-check sequence
```

### 2.1 The trust root is independent of the decisions it verifies

A registry is an explicitly supplied file/object; its `registry_id` is
derived from the registered key ids, and each `key_id` is derived from the
algorithm + public-key material **only**. Nothing in the registry references
any decision artifact, and no decision artifact can influence a key
identity. Supplying a different registry is a visible operator action —
there is no path by which a decision file selects or mutates its own trust
root.

Each key record states the bound `owner_identity`, an explicit
`authorized_decisions` scope (`ACCEPT_WITH_EXCEPTION` and/or `REJECT`),
owner-declared `valid_from`/`valid_until` ISO dates, and an explicit
`revoked` flag with a mandatory revocation reference.

### 2.2 What is signed

The signed message is the fixed domain prefix
`turtle-value-engine:owner-policy-decision:v1` + a NUL byte + the exact
canonical JSON bytes of one `OwnerPolicyDecisionInputV1`:

```python
from turtle_value_engine.evolution.owner_provenance import (
    owner_decision_input_signature_message,
)
message = owner_decision_input_signature_message(decision_input)
# sign `message` with the owner's Ed25519 private key outside this
# repository, then assemble the evidence statement with
# build_owner_signed_decision_statement(signature=..., key_id=...,
# decision_input=...)
```

The decision input itself already binds the base and target profile ids +
byte SHA-256, the release-manifest id + content SHA-256, the fresh-audit id
+ content SHA-256, the exception id + full content SHA-256, the rationale,
the owner identity and `decided_at`. Combined with the domain prefix this
yields replay protection along every axis:

| replay attempt | blocked by |
| --- | --- |
| same signature, different profile bytes/hash | `DECISION_CONTENT_BINDING` + `SIGNATURE_VERIFIED` |
| same signature, different decision value (ACCEPT↔REJECT) | `DECISION_CONTENT_BINDING` + `SIGNATURE_VERIFIED` |
| same signature, different rationale/binding/date | `DECISION_CONTENT_BINDING` + `SIGNATURE_VERIFIED` |
| signature from another purpose/contract reused here | domain prefix breaks `SIGNATURE_VERIFIED` |
| signature by an unregistered key | `KEY_RESOLUTION` |
| key valid for another identity | `KEY_IDENTITY_BINDING` |
| key scoped to REJECT used for ACCEPT | `KEY_SCOPE_AUTHORIZED` |
| decision dated outside the key's window | `KEY_VALIDITY_WINDOW` |
| revoked key | `KEY_NOT_REVOKED` |
| semantically identical but non-canonical bytes | `DECISION_CONTENT_BINDING` (anti-malleability: only the canonical byte form may be signed) |
| an ACCEPT record whose provenance points at signed REJECT bytes | verifier record-binding check (`OWNER_PROVENANCE_RECORD_INPUT_BINDING_MISMATCH`) |

The evidence statement (`OwnerSignedDecisionStatementV1`) records the
purpose, algorithm, key id, base64 signature, the decision-input content
hash, the signed-message hash, the declared identity and its own content
hash — evidence, never authority on its own.

## 3. The verification boundary

`verify_owner_provenance(...)` is a pure offline function: no clock (the
validity window compares the key's owner-declared dates against the signed
decision's own `decided_at`), no network, no filesystem. Every canonical
check is evaluated and recorded; `VERIFIED` requires all nine.

`SignedOwnerProvenanceVerifier` implements the C2 `OwnerDecisionVerifier`
interface and serves the two deterministic C2 call points, distinguished by
the **contract** of the presented bytes (never a heuristic):

1. **Record time** (`validate_owner_decision` with the verifier injected):
   the presented bytes are the submitted decision-input bytes. They must be
   byte-identical to the signed submission; the signature is verified and a
   genuine `OWNER_AUTHORITY_VERIFIED` assessment (with
   `allowlist_matched=True` only on a positive registry identity binding) is
   captured into the record. C2's own record flow then persists the
   provenance hash of those exact bytes.
2. **Plan time** (C2-R1 reverification): the presented bytes are the
   canonical record bytes. The verifier re-verifies the signature and
   additionally proves the record is *about* the signed submission:
   `provenance.source_content_sha256` must equal the signed bytes' hash, and
   the record's embedded decision fields (decision, all profile/manifest/
   audit/exception bindings, rationale, identity, date) must equal the
   signed input's fields. The returned assessment binds
   `evidence_content_sha256` to the exact record bytes, as C2-R1 requires.
   Provenance *kind* is bookkeeping (C2: "provenance is bookkeeping, never
   authentication") — the content hash is the binding.

The class is constructed only with three explicit inputs (registry,
statement, signed bytes) by a hosting process. The production CLI
constructs none of them and exposes no flag, file convention or environment
variable that could select a verifier; no `trust=true`-style override
exists anywhere in the module (source-scanned by tests). A persisted
`OWNER_AUTHORITY_VERIFIED` claim on a record still proves nothing by itself
— only the cryptographic re-attestation at plan time can produce a READY
plan, exactly as hardened in C2-R1 and C2-R2 (where
`allowlist_matched=True` is the only allowlist state that may pass).

## 4. Threat model

In scope and cryptographically blocked (each with a deterministic negative
test): forged/self-consistent VERIFIED claims; signature replay across
profiles, versions, decisions or purposes; unsigned substitution (an ACCEPT
record pointing at signed REJECT bytes, or a record about different bytes
than were signed); tampered decision content; unknown, revoked,
out-of-window, scope-exceeding or foreign-identity keys; malformed key
material and signatures; non-canonical (malleable) input encodings; missing
crypto dependency.

Out of scope, documented honestly:

- **Private-key compromise** — mitigation is owner key custody plus the
  explicit registry revocation record; verification fail-closes on revoked
  keys. Revocation *workflow* tooling is C3-B.
- **Registry substitution** — the registry is an explicit independent
  input; a hosting process that supplies a different registry has visibly
  changed the trust root (registry id and content hash are bound into every
  verification dossier). Nothing in a decision file can influence it.
- **Side-channel/timing attacks** on the offline verifier — the attacker
  model (local decision files, no secrets at verification time) does not
  expose a secret-dependent computation.

## 5. Determinism and auditability

- Verification dossiers carry no wall-clock fields; identical inputs always
  produce byte-identical dossiers (asserted by tests), so evidence is
  replayable offline at any later time.
- The dossier binds the registry id, key id, decision-content hash, every
  check outcome, and its own `verification_id`/`content_sha256`.
- Keys never enter this repository: production code never signs and never
  holds private key material (source-scanned); all test keys are throwaway
  fixtures generated at runtime. No real owner acceptance of strict-v2 is
  claimed — C3-A proves the boundary, it does not exercise real owner
  authority.

## 6. Owner signing operations (outside this repository, for C3-B)

1. Generate an offline Ed25519 keypair and register the **public** key in
   the trusted registry file (identity, scope, validity window) kept
   outside Git or in an owner-controlled trust location.
2. Prepare the decision input; serialize it with the provided canonical
   helper; sign the domain-prefixed message with the private key
   (`openssl pkeyutl -sign -rawin` or a short `cryptography` script).
3. Assemble the statement with
   `build_owner_signed_decision_statement(signature=..., key_id=...,
   decision_input=...)` and submit it alongside the decision input to the
   hosting process that injects `SignedOwnerProvenanceVerifier`.
4. The private key is never committed, never passed through chat, and never
   read by this repository; compromise handling is key revocation in the
   registry (a new explicit registry revision), after which every
   verification of that key fails closed.
