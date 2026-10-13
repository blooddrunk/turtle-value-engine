# Phase 7-C2 — Owner Policy Decision Records and Read-only Activation Plans

Status: **IMPLEMENTED / CLOSED**
Date: 2026-10-13
Closed at: implementation `26cd2b47ba5f9bc8989698742c9bc78721d99d9c`
(Actions run `38360550883`, `success`, exact `head_sha` match; full suite
7145 passed / 2 skipped; closure record
`docs/status/phase-7-c2-2026-10-13.md`)
Offline implementation boundary only: no real owner acceptance occurred or
was required, and nothing was activated — implemented ≠ owner-accepted ≠
activated.
Selected by the post-C1 review on 2026-10-13. This is an implementation
package, not an instruction to accept or activate strict-v2.

## Outcome and scope

Build an additive, typed, offline boundary that records an explicitly supplied
owner decision, verifies its artifact bindings, and derives a read-only
activation/rollback plan. Implementation and automated acceptance must finish
without a real owner acceptance. Actual configuration changes belong to a later,
separately selected package. Existing C1 claims remain detection-only.

## Contracts

1. Define an immutable owner-decision record with canonical id/content hash,
   exact base/target profile byte hashes, release manifest id/hash, fresh audit
   id/content hash, decision, rationale, declared owner identity, timestamp,
   exception id/content hash where relevant, and provenance/verification state.
   Use ACCEPT_WITH_EXCEPTION or REJECT for the current strict-v2 policy question.
   Do not silently map a C1 approval claim to verified owner authority.
2. Separate artifact validity from authority. An unsigned local JSON, an
   EnvironmentFile username, Git author text, CI success or publication proves
   neither human authorship nor permission. An owner identity setting is an
   allowlist, not authentication. Unverified records remain visibly unverified.
   Define a verifier interface and an explicit trust model; fake verifiers are
   test fixtures only and must not be selectable by the production CLI.
   If no usable authenticated source is available, finish the offline boundary
   and report OWNER_AUTHORITY_UNVERIFIED; do not invent a verified acceptance.
3. Bind all policy exceptions by BOTH deterministic id and full content hash
   (C1 exception ids omit rationale/declarer), bind provenance/source revision,
   and define conflict, duplicate, revocation and supersession semantics. Reject
   stale or ambiguous authority rather than selecting the newest file silently.
4. Define a deterministic activation-plan contract with explicit blockers,
   current/proposed profile references, affected configurations/artifacts,
   preconditions and rollback references. Every plan fixes
   automatic_activation_allowed=false and execution_performed=false.
   A verified decision is necessary but is not itself an execution request.
5. Add checked-in schemas with drift parity. Preserve frozen C1 schema and
   status meanings; no broad mutation of RuleProfile or investment math.

## Commands and effects

Design additive CLI commands for decision validation/recording and activation
planning. Require explicit input/output paths; guard symlinks, input collisions
and published directories. Emit machine-readable outcomes with documented exit
codes. Do not overwrite existing decision records with different content.

Re-run C1 from the supplied profile/manifest/template bytes, never trust a
previous dossier's self-reported readiness. ACCEPT_WITH_EXCEPTION must bind the
exact exception and leave no uncovered finding or structural blocker. REJECT
must remain a terminal non-activation outcome; correction is a new version via
the existing evolution/release chain, never editing strict-v2 in place.

Default planning is entirely offline with no provider/model/network construction.
If a real provenance verifier needs network, isolate it in an explicit opt-in
operation with captured immutable evidence and offline replay; ordinary CI uses
injected scripted evidence. No credential provisioning is required for closure
of the offline implementation boundary.

Inventory affected config through explicit supplied paths, including project
default profile, monitoring/watchlist references, normalized-input profile ids,
backtest/dataset/frozen historical references and Dashboard surface projections.
Preserve historical artifacts and label incompatible/missing references with
specific blockers. Never silently rewrite their profile ids. A rollback plan
must identify the prior config bytes/hash and expected current state; exclude
automatic replay of already committed monitoring effects or notifications.

## Automatic acceptance

- Actual published strict-v2 with no owner record stays policy-gated; no files
  under rules/, release manifests or runtime configuration change.
- Fixture accept/reject/unverified, wrong owner, forged claim, revoked/conflicting
  records, stale audit/profile/manifest/source revision, altered rationale with
  unchanged exception id, duplicate/idempotent records and output guards.
- Covered gate-above-S anomaly can proceed only with exact verified test authority;
  unrelated a/watch disorder stays uncovered (C1-R1 regression).
- Dry-run plans for compatible/incompatible/missing config and deterministic
  rollback; repeat runs produce identical artifacts and no side effects.
- Schema drift/parity, socket-guarded offline CLI, byte preservation, default
  strict-v1 preservation and no fake-verifier production escape hatch.
- Run python -m ruff check ., python -m pytest and every command currently in
  .github/workflows/ci.yml. Record the implementation commit, CI run URL, exact
  head SHA and each job conclusion. Distinguish implementation acceptance from
  real owner-policy acceptance; missing real authority cannot invalidate passing
  fixture-based implementation tests or be reported as a real acceptance.

## The only human step, when real acceptance is requested later

Before asking, automation must generate a Chinese decision dossier containing:
exact profile/manifest/audit/exception hashes, the two uncovered findings, the
13% replay (strict-v1 EXTREME_SAFETY vs strict-v2 WATCH), the observed divergence
interval [8%,14%), and accept/reject effects. State that this is synthetic boundary
evidence, not proof that 14% improves investment performance.

The owner must choose ACCEPT_WITH_EXCEPTION (retain 14% despite 12% S/tier
thresholds) or REJECT (retain strict-v1; corrected policy needs a new release),
provide a rationale, and submit through the documented authenticated source.
Give exact fields, submission command/location, expected verification result,
and troubleshooting steps for identity/hash/staleness failures. Automation then
captures source evidence and verifies bindings. Without that decision, return
the precise blocker and a completed dry-run plan; do not claim activation.
No owner action is needed to implement or automatically test this package.

## Non-goals

No actual default switch, exception/approval authored for the owner, provider or
Bridge/FQGate expansion, H-share scope expansion, notifications, trading or
Windows deployment. Preserve strict-v1, strict-v2 and their release bytes.
