# Phase 7-C3-A-R1 Post-Closure Review (2026-10-15)

Review baseline: main `ce9726d2445f578215159722d85ac8027d8d20ac`
(clean tree; local full gate re-run green: ruff clean,
**7219 passed / 2 skipped** — identical to the R1 closure record).

## 1. Prior closures re-verified on this baseline

- PR #7 (C2-R2) MERGED: head `50fa2e3`, merge `3a5d0d9`; exact-head run
  `38503935467` and merge-head run `38505331190` both `success`
  (`head_sha` match confirmed through the GitHub API).
- PR #8 (C3-A-R1) MERGED: head `79560e3`, merge `cac83f4`; exact-head run
  `38531123746` `success` (every CI step green, verified job-by-job),
  merge-head run `38531561420` `success`; main-head closure run `38532198863`
  `success`.
- Protected bytes byte-identical to every closure record:
  `rules/strict-v1.yaml` `e3618f78…`, `rules/strict-v2.yaml` `adba44b7…`,
  `docs/releases/strict-v2/release-candidate.json` `604226f4…`,
  `config/project.example.toml` `9c621217…`.
- The five C3-A-R1 hardening rules were re-read in source and remain
  intact (unsigned supersession/revocation fail closed, `source_revision`
  binding, canonical Base64 identity, classified calendar dates,
  target-scoped revocation blocking).

The C2-R2/C3-A/C3-A-R1 closures are **preserved**. No C3-A-R1 defect
reopened.

## 2. New findings: the trust root is not snapshotted anywhere

The review then audited the *auditability* of the C3-A chain itself: which
persisted artifact can name the exact trust-root content that produced a
VERIFIED result?  A standalone six-check adversarial reproduction (one
throwaway Ed25519 key; two valid registries with the same key set — same
derived `registry_id` — but different trust content, both verifying the same
signed statement; the real record-time capture and plan-time re-attestation
flows) was executed on the pristine baseline.  **All six checks show the
defect on `ce9726d`:**

| Check | Result on baseline |
|---|---|
| same key set under different trust content shares one `registry_id` | **DEFECT** |
| different trust roots share one `verification_id` (identity collision) | **DEFECT** |
| dossier value set carries no registry content hash | **DEFECT** |
| persisted VERIFIED record has no structured trust-root/key identity (prose-only `detail`) | **DEFECT** |
| two different trust roots reach byte-identical READY plans (same `plan_id`) | **DEFECT** |
| READY plan names no attesting registry anywhere | **DEFECT** |

Why this is a defect class and not a cosmetic gap:

- `docs/architecture/owner-provenance-verification.md` §4 explicitly
  promises "registry id and content hash are bound into every verification
  dossier" — the implementation binds only the content-insensitive
  `registry_id`.  A registry whose key is revoked, re-windowed or re-scoped
  is the *same registry identity* under this scheme.
- The repository's own evidence rule (`AGENTS.md` §6: evidence identity is
  first-class data, never prose-only citation) is violated by the VERIFIED
  record, which names its key only inside the free-text `detail`.
- The READY plan is the owner-facing artifact for a future explicit
  execution decision; two different trust roots producing byte-identical
  READY plans means the plan cannot state which trust root re-attested the
  authority it relies on, and C3-B evidence capture cannot be layered on
  artifacts that cannot name their trust root.
- No privilege escalation exists through these gaps today (forged VERIFIED
  claims still cannot reach READY); the class is audit integrity of the one
  input whose content decides trust.

## 3. Selection

**Phase 7-C3-A-R2 — Trust Root Snapshot Hardening** is selected before any
C3-B work (goal:
`docs/goals/phase-7-c3-a-r2-trust-root-snapshot-hardening.md`).  Scope: bind
the registry content hash into the verification dossier identity, capture
structured attested identity in the authority assessment, bind the fresh
re-attestation trust root into the activation plan identity, regenerate the
three affected schemas, and pin everything with fail-on-baseline
adversarial regressions.  No CLI surface, no new READY-blocking rule for the
generic verifier interface, no signed supersession/revocation protocol
(still C3-B), no activation executor.
