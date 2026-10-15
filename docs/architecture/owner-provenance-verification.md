# Owner Provenance Verification — Architecture (Phase 7-C3-A + 7-C3-B)

Status: C3-A implemented at its offline verification boundary (contracts,
threat model, pure offline verification, the real library verifier class,
deterministic test fixtures) with the R1 binding hardening and R2
trust-root snapshot hardening. C3-B implemented at its trusted operations
boundary: the versioned registry-snapshot store (trust-root lifecycle:
init/enroll/revoke/rotate), the immutable create-only evidence bundles
with offline byte-identical re-verification, the signed
revocation/supersession protocols, and the fail-closed CLI integration of
the real verifier (`tve provenance …` plus the `record-decision` /
`plan-activation` provenance extensions). No activation executor exists.

Related documents:

- Goals: `docs/goals/phase-7-c3-a-authenticated-owner-provenance-verifier.md`,
  `docs/goals/phase-7-c3-b-trusted-owner-provenance-operations.md`
- Trust-model interface and record/plan contracts:
  `docs/architecture/owner-policy-decision-and-activation-plan.md`
- Modules: `src/turtle_value_engine/evolution/owner_provenance.py`,
  `src/turtle_value_engine/evolution/owner_lifecycle.py`,
  `src/turtle_value_engine/evolution/owner_trust_store.py`
- Tests: `tests/test_owner_provenance.py`,
  `tests/test_owner_trust_operations.py`
- Owner procedure: `docs/operations/owner-provenance-walkthrough.md`

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

### 3.1 C3-A-R1 binding hardening (independent review)

An independent post-C3-A review found and closed five binding gaps; the
corrected invariants are:

- **Unsigned supersession fails closed.** Plan-time re-attestation rejects
  any record carrying `supersedes_decision_record_id`
  (`OWNER_PROVENANCE_UNSIGNED_SUPERSESSION`): the signature covers the
  decision input only, so it can never authenticate replacement metadata.
  No signed supersession protocol exists yet — fail closed until one is
  versioned (a later phase); a forged supersession chain cannot help
  either, because every superseder remains active itself and the resolver
  fails closed as AMBIGUOUS/CONFLICTING.
- **The record's `source_revision` must equal the signed input's.** The
  legitimate record-time flow copies the input's `source_revision` into
  the record provenance, so any drift at plan time is tampering
  (`OWNER_PROVENANCE_RECORD_INPUT_BINDING_MISMATCH`).
- **One key material, one identity.** Every accepted Base64 value must be
  the canonical RFC 4648 encoding of its decoded bytes; pad-bit aliases
  are rejected before any `key_id` is derived, and a registry can never
  hold one key under two identities. Legitimate encoder output is always
  canonical, so no valid key or signature is rejected.
- **Impossible calendar dates classify, never crash.** A syntactically
  ISO-shaped but calendar-invalid `decided_at` (e.g. `2026-02-30`) leaves
  `key_validity=UNKNOWN` and yields a deterministic `REJECTED` dossier;
  registry validity dates fail as `ValidationError` at model construction.
- **Revocations cannot shape a plan.** A revocation is unauthenticated
  bookkeeping; until a versioned signed revocation protocol exists, any
  revocation that withdraws a record of the planned target blocks the
  activation plan with `OWNER_REVOCATION_AUTHORITY_UNVERIFIED`. Without
  this, a forged revocation of a dissenting REJECT collapsed a CONFLICTING
  set onto the single signed ACCEPT and reached READY — withdrawing a
  decision must never *increase* what the remaining set authorizes.
  Revoking a stale/other-target record stays inert bookkeeping.

### 3.2 C3-A-R2 trust-root snapshot hardening (independent review)

A second independent review found that no persisted artifact could name the
exact trust-root *content* that produced a VERIFIED result: `registry_id` is
derived from key ids only, so the same key set re-windowed, re-scoped,
revoked or un-revoked keeps the id while changing the content — and only the
id was bound. The corrected invariants:

- **The verification dossier binds the registry content.**
  `OwnerProvenanceVerificationV1` carries the required
  `registry_content_sha256` and derives `verification_id` from it, so one
  verification identity names one exact trust-root content; the canonical
  nine-check sequence is unchanged (the registry's internal consistency is
  enforced at model construction — the new binding is recording, not
  checking).
- **The captured record names its trust root structurally.**
  `OwnerAuthorityAssessmentV1` carries the additive optional
  `attested_key_id` / `attested_registry_id` /
  `attested_registry_content_sha256`, populated by the real verifier on
  every assessment (VERIFIED and rejected). They are captured bookkeeping,
  never authority: a forged record claiming foreign attested fields is
  inert, because plan-time authority always comes from the fresh
  injected-verifier assessment.
- **The activation plan binds the fresh re-attestation trust root.**
  `ProfileActivationPlanV1` carries
  `authority_reverification_registry_id` /
  `authority_reverification_registry_content_sha256` sourced exclusively
  from the fresh re-attestation assessment (never the persisted record
  claim), supplied together or not at all, and participates in the `plan_id`
  derivation — two different trust roots can never produce the same READY
  plan identity.
- **Deliberate non-goal.** A verifier that attests no trust root (the
  generic C2 fake fixtures, any future non-registry trust model) follows the
  unchanged C2/C2-R1 rules; the fields stay visibly `None` rather than
  fabricating a binding, and no new READY-blocking rule is imposed on the
  verifier interface in this package.

### 3.3 C3-B trusted operations (store, evidence, lifecycle, CLI)

**Trust-root store** (`owner_trust_store.OwnerProvenanceTrustStore`). The
trust root is an operator-owned directory of append-only versioned
snapshots (`snapshots/snapshot-<seq>.json`). One
`OwnerProvenanceRegistrySnapshotV1` wraps a full
`OwnerProvenanceKeyRegistryV1` with its sequence number, a content-hash
link to its parent (sequence 1 has none) and its own deterministic id plus
full-content SHA-256 — so the same key set under different trust content
re-windowed, re-scoped or re-revoked is a *distinct* snapshot identity
(the R2 content-snapshot rule applied to the store itself). Every load
validates the complete chain fail-closed (contiguity from 1, parent links,
model-level tamper detection, foreign files); publication is a single
exclusive `O_CREAT|O_EXCL` open (byte-identical appends idempotent, any
foreign content a classified immutable error, symlinks refused). Trust
lifecycle operations are pure snapshot transitions — `enroll` (new public
key), `revoke` (mandatory reference), `rotate` (old revoked + new enrolled
in ONE atomic snapshot) — persisted only as the next snapshot; committed
snapshots are never rewritten.

**Evidence bundles.** One capture = one immutable directory per
deterministic `bundle_id` holding the exact canonical decision-input
bytes, the signed statement, the registry snapshot trusted at capture
time, the verification dossier, the resulting decision record (or `null`
when validation failed) and the manifest binding them
(`OwnerProvenanceEvidenceBundleV1`; `capture_is_evidence_not_authority`
fixed). Capture runs the real record-time boundary
(`validate_owner_decision` with the real verifier injected over the exact
submitted bytes) plus the pure dossier; a signature that does not verify
yields an honest INVALID/REJECTED bundle, never a fabricated VERIFIED
capture. `load_owner_decision_evidence` is the strict fail-closed loader
(every component hash must match the manifest) used by consumers;
`reverify_owner_decision_evidence` is the audit replay: it *compares* —
recomputing the dossier from the actual persisted bytes and naming every
divergence — so even a fully self-consistent forged bundle whose embedded
dossier claims a verification the bytes cannot reproduce surfaces as a
`MISMATCH`.

**Signed revocation/supersession** (`owner_lifecycle`). Two narrowly
versioned domain-separated protocols parallel to the decision statement:
`turtle-value-engine:owner-decision-revocation:v1` over
`OwnerRevocationPayloadV1` (exact revoked record id AND content SHA-256,
target binding, identity, date, rationale) and
`turtle-value-engine:owner-decision-supersession:v1` over
`OwnerSupersessionPayloadV1` (both records bound by id and content
SHA-256, shared target). Verification is pure/offline against the same
trust root with its own pinned eight-check sequence (ALGORITHM_SUPPORTED,
KEY_RESOLUTION, KEY_IDENTITY_BINDING, KEY_VALIDITY_WINDOW,
KEY_NOT_REVOKED, PAYLOAD_CONTENT_BINDING, PURPOSE_BINDING,
SIGNATURE_VERIFIED). A key may sign lifecycle statements when enrolled,
identity-bound, in-window and not revoked — the key's decision-value scope
governs which decisions it may make, not withdrawals, which can only
reduce or restate authorization. Verified payloads feed the resolver only
through the plain content-bound carriers
(`AuthenticatedRevocationBindingV1` /
`AuthenticatedSupersessionBindingV1` in `owner_decision`), which must
match actually supplied records byte-exactly or the resolution fails
closed; cycles and double supersession stay fail-closed across unsigned
and authenticated links, exact duplicate bindings collapse idempotently.

**Plan-boundary freshness.** `plan_profile_activation` verifies every
signed lifecycle statement freshly against the supplied
`lifecycle_trust_root`: without one, any statement blocks
(`LIFECYCLE_TRUST_ROOT_REQUIRED`); a failing statement blocks
(`SIGNED_REVOCATION_REJECTED:*` / `SIGNED_SUPERSESSION_REJECTED:*`). Only
a fully verified statement becomes a resolver binding. Unsigned
revocations keep their unchanged C3-A-R1 semantics (any unsigned
revocation that withdraws a record of the planned target still blocks with
`OWNER_REVOCATION_AUTHORITY_UNVERIFIED`); an *authenticated* revocation of
a dissenting REJECT legitimately resolves a conflicting set — it is the
owner's own signed statement, verified fresh. The resolution and plan
contracts carry the additive `authenticated_revoked_record_ids` /
`authenticated_superseded_record_ids`, which participate in their identity
derivations.

**CLI integration (the real verifier only).** `tve provenance registry
init|enroll|revoke|rotate|status` manage the trust root;
`tve provenance verify-evidence` replays one bundle (exit 0/1);
`tve evolution record-decision --signed-statement … --trust-root …
[--evidence-root …]` captures VERIFIED records with evidence (the default
unsigned flow is byte-compatible); `tve evolution plan-activation
--trust-root … --authority-evidence … [--signed-revocation …]
[--signed-supersession …]` re-attests authority freshly against the trust
root's **latest** snapshot — registry revocation/rotation takes effect
immediately — and verifies lifecycle statements the same way. There is no
verifier selector, no environment-derived trust and no fake-verifier
escape hatch; the CLI constructs `SignedOwnerProvenanceVerifier` at
exactly two authorized sites (source-scanned by tests).

**Trust-root ownership.** The trust root is supplied by the operator as
its own path; no decision artifact field designates it (none exists and
none may be added). The CLI additionally refuses a trust root located
inside the directory of any submitted decision artifact (and decision
artifacts stored inside the trust root), so a submitted bundle can never
smuggle the trust root it is asked to be verified under — supplying the
trust root stays a visible, structurally independent operator action.

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
  registry revocation record: `tve provenance registry revoke` appends the
   revoking snapshot and every future verification under that trust root
   fails closed (proven end-to-end by the C3-B CLI walkthrough test).
- **Registry substitution** — the registry is an explicit independent
   input; the operator's choice of `--trust-root` is the visible trust
   decision, structurally separated from every submitted bundle (§3.3),
   with registry id and content hash bound into every verification
   dossier, every evidence bundle and every activation plan (§3.2).
- **Side-channel/timing attacks** on the offline verifier — the attacker
   model (local decision files, no secrets at verification time) does not
   expose a secret-dependent computation.

## 5. Determinism and auditability

- Verification dossiers carry no wall-clock fields; identical inputs always
  produce byte-identical dossiers (asserted by tests), so evidence is
  replayable offline at any later time.
- The dossier binds the registry id **and** registry content hash (§3.2),
  the key id, decision-content hash, every check outcome, and its own
  `verification_id`/`content_sha256`.
- Keys never enter this repository: production code never signs and never
  holds private key material (source-scanned); all test keys are throwaway
  fixtures generated at runtime. No real owner acceptance of strict-v2 is
  claimed — C3-A proves the boundary, it does not exercise real owner
  authority.

## 6. Owner signing operations (outside this repository)

The complete practical procedure — generating the owner key outside the
repository, registering only its public key through the trust-root store,
signing exact canonical payloads, capturing with the real verifier,
replaying evidence offline, exercising signed revocation/supersession and
revoking trust — is documented step by step in
`docs/operations/owner-provenance-walkthrough.md`. The private key is
never committed, never passed through chat, and never read by this
repository; compromise handling is key revocation in the trust root (one
new immutable snapshot), after which every future verification of that
key fails closed while already-captured evidence stays auditable.
