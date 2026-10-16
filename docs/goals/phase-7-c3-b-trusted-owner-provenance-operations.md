# Phase 7-C3-B — Trusted Owner Provenance Operations

Status: **IMPLEMENTED / CLOSED** (PR #10; implementation
`c7943b5903d74588d0eeffaec94cc80bcdc279fc`, exact-head Actions run
`38708419906` `success`; merge `6d2da2edd23fe7b0a9fea45f9778e31923c1de03`,
merge-head run `38834048273` `success`; closure record
`docs/status/phase-7-c3-b-2026-10-16.md`)

## 1. Problem

C3-A (+R1/R2) delivered the offline Ed25519 verification core, binding
hardening and trust-root content snapshots, but the boundary is not yet a
usable or persistently auditable personal-research workflow:

- the trusted key registry exists only as an in-memory object — there is no
  versioned, content-identified snapshot store, and no enrollment, rotation
  or revocation lifecycle for trust itself;
- verification dossiers, signed statements, trust-root snapshots and the
  resulting decision records are never captured as one immutable evidence
  unit, and nothing can re-verify such evidence offline later;
- the production CLI constructs no verifier, so even a genuinely signed
  owner decision can neither record as `OWNER_AUTHORITY_VERIFIED` nor reach
  a `REVERIFIED` (and therefore READY) activation plan — fail-closed, but
  unusable;
- revocation and supersession of decisions remain unsigned bookkeeping that
  can only *block* (C3-A-R1 rules); no authenticated protocol exists to
  express them.

## 2. Scope

### Work package A — trusted registry and evidence operations

1. An explicitly supplied trust-root store holding **versioned registry
   snapshots** (`OwnerProvenanceRegistrySnapshotV1`): each snapshot wraps
   one `OwnerProvenanceKeyRegistryV1`, carries a sequence number, binds its
   parent snapshot by content hash (append-only chain from sequence 1), and
   is identified by a deterministic id plus full-content SHA-256. Loading
   validates the whole chain fail-closed (gaps, duplicates, tampered
   parents, foreign files).
2. Snapshot lifecycle operations (pure, then persisted create-only):
   `init` (first snapshot), `enroll` (new public key), `revoke` (key
   revoked with a mandatory reference), `rotate` (old key revoked and new
   key enrolled in one atomic snapshot). Old snapshots are never rewritten.
3. An immutable, create-only **evidence store**: one bundle directory per
   deterministic `bundle_id` holding the exact canonical decision-input
   bytes, the signed statement, the registry snapshot used, the
   verification dossier and the resulting decision record (or `null` when
   validation failed), plus the bundle manifest binding them all.
4. Deterministic capture through the real
   `SignedOwnerProvenanceVerifier` at record time, and offline
   re-verification from persisted evidence requiring byte-identical replay
   of the dossier plus the record bindings.
5. Fail-closed CLI integration that constructs the **real** verifier only:
   - `tve provenance registry init|enroll|revoke|rotate|status`;
   - `tve provenance verify-evidence`;
   - `tve evolution record-decision --signed-statement --trust-root
     [--evidence-root]`;
   - `tve evolution plan-activation --trust-root --authority-evidence
     [--signed-revocation ...] [--signed-supersession ...]`.
6. Trust-root ownership rules: the trust root is supplied by the operator
   as an explicit path; no decision artifact field designates it (no such
   field exists and none may be added); the CLI refuses a trust root that
   is located inside a submitted decision bundle directory and refuses
   decision artifacts stored inside the trust root; plan-time
   re-attestation always uses the trust root's **latest** validated
   snapshot, so registry revocation/rotation takes effect immediately.

### Work package B — authenticated revocation and supersession

Narrowly versioned signed protocols, parallel to the C3-A decision
statement:

- `turtle-value-engine:owner-decision-revocation:v1` —
  `OwnerRevocationPayloadV1` (exact revoked record id **and** content
  SHA-256, target profile id + SHA-256, revoked-by identity, revoked-at,
  rationale, source revision) + detached Ed25519 statement +
  deterministic verification dossier with its own pinned canonical check
  sequence (ALGORITHM_SUPPORTED, KEY_RESOLUTION, KEY_IDENTITY_BINDING,
  KEY_VALIDITY_WINDOW, KEY_NOT_REVOKED, PAYLOAD_CONTENT_BINDING,
  PURPOSE_BINDING, SIGNATURE_VERIFIED).
- `turtle-value-engine:owner-decision-supersession:v1` — same shape, binding
  **both** the superseded and the superseding record by id and content
  SHA-256 plus the shared target binding.

Resolver/plan integration (all additive):

- `resolve_owner_decision_authority` accepts authenticated revocation and
  supersession bindings (plain content-bound carriers produced only by
  fresh cryptographic verification in the hosting boundary); each binding
  must match an actually supplied record byte-exactly (id, content hash,
  target binding) or the resolution fails closed; authenticated removals
  are reported in the resolution; double supersession across unsigned and
  authenticated links stays fail-closed; unsigned revocation/supersession
  semantics and the C3-A-R1 plan blockers are unchanged.
- `plan_profile_activation` verifies signed lifecycle statements freshly
  against a supplied trust root (`lifecycle_trust_root`); without a trust
  root, any signed statement blocks the plan
  (`LIFECYCLE_TRUST_ROOT_REQUIRED`); a statement that fails verification
  blocks the plan (`SIGNED_REVOCATION_REJECTED:*` /
  `SIGNED_SUPERSESSION_REJECTED:*`). Only VERIFIED statements may remove
  records; withdrawing a decision may never increase authorization except
  through this authenticated path (an authenticated revocation of a
  dissenting REJECT legitimately resolves a conflict — it is the owner's
  own signed statement).

## 3. Non-goals / frozen boundaries

- `rules/strict-v1.yaml`, `rules/strict-v2.yaml`,
  `docs/releases/strict-v2/release-candidate.json`,
  `config/project.example.toml` stay byte-identical; strict-v1 stays the
  default.
- No activation executor; `execution_performed=false` and
  `automatic_activation_allowed=false` stay fixed literals.
- No owner decision, signature, approval or activation is synthesized; no
  real owner key exists in the repository; test keys are throwaway
  fixtures.
- No provider/model/network construction anywhere in the new boundary; no
  private-key material is read, held or signed by production code.
- No environment variable, Git history, username, CI status or
  allowlist-only path can establish trust; the CLI offers no verifier
  *selector*, only the real verifier constructed from explicit inputs.

## 4. Acceptance criteria (automatic)

Focused deterministic tests must prove, with ephemeral runtime-generated
Ed25519 keys and the real library/CLI entrypoints:

1. registry snapshot lifecycle: init/enroll/revoke/rotate produce a valid
   append-only chain; tamper, gap, duplicate-sequence and foreign-file
   corruptions fail closed; the same key set under different trust content
   yields distinct snapshot content identities;
2. capture: a genuine signature under a matching trust root yields a
   VERIFIED record and a complete evidence bundle; invalid signatures
   yield no record and an honest REJECTED bundle;
3. evidence re-verification replays byte-identically offline (socket
   guard) and detects any tampered component as a classified mismatch;
4. create-only publication: collisions are classified failures, never
   overwrites; byte-identical recaptures are idempotent; a racing foreign
   writer is never clobbered;
5. CLI: the full walkthrough (init → sign → capture → plan READY) works
   end-to-end through `python -m turtle_value_engine`; revoking the key in
   the trust root flips the plan back to blocked; the trust-root
   co-location guards fire; orphan flags and missing stores exit 2 with
   classified errors;
6. signed lifecycle: verified revocation/supersession produce exactly
   their scoped effect; wrong-record, wrong-content, cross-target,
   cross-purpose, unknown-key, revoked-key and unsigned variants fail
   closed; unsigned revocation still cannot upgrade authorization;
7. schema drift parity for every new and regenerated schema, including
   the pinned per-position check sequences;
8. published bytes and the strict-v1 default are preserved.

The full automatic gate (ruff, full pytest, config validate,
systemd-analyze verify, surface OpenAPI check, Dashboard
api/types/lint/typecheck/test/build, security scan, Wrangler dry-run,
cross-stack smoke) plus exact-head GitHub Actions success closes the
package. No manual owner action is required for closure; the real-owner
walkthrough is documentation, and real economic acceptance of strict-v2
remains a separate explicit human decision.
