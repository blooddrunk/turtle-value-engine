# Phase 5R-A M6-A — Read-only Research Surface Contract

Status: **ACTIVE / NEXT**
Date: 2026-09-18
Audited baseline: `1580670` (M5-B complete on `main`)

Parent context:
- `AGENTS.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-a-m5-b-s3-compatible-artifact-backend.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/architecture/production-historical-data-and-research-archive.md`

## 1. Objective

Create the first stable **read-only product/agent surface** over already-frozen
Turtle artifacts.

M6-A must define one small, versioned, schema-validated, machine-readable
research snapshot that can later be consumed by:

- Hermes or another tool-using agent;
- a thin Skill/runtime adapter;
- a local or remote read-only API;
- a personal Web Dashboard, including a later Cloudflare Worker UI.

The surface is a **projection**, not a second engine. It must not recompute CDC,
Net Cash, Through Return, hard gates, valuation, Business Quality validation or
historical replay semantics. Those values remain owned by the existing typed
artifacts and deterministic engine.

M6-A is deliberately local/offline first. It freezes the data contract before
choosing an HTTP framework, authentication scheme or UI stack.

## 2. Why this is the next package

M5-A and M5-B now provide a deployment-neutral immutable artifact transport and
one real S3-compatible implementation. M5-C remains optional and should only be
opened when a concrete additional artifact class needs remote mirroring.

The concrete missing boundary is now the **derived read model** that agents,
APIs and a Dashboard can safely consume without understanding every internal
workspace/storage contract.

Full Phase 5R/A6 production eligibility is not a prerequisite for this work.
A partial dataset must remain visibly partial; M6-A must surface blockers rather
than converting them into a green state.

Phase 6 watchlist/event monitoring is also separate. M6-A does not schedule,
poll, acquire or re-run anything.

## 3. Frozen boundaries

Preserve all of the following:

1. `strict-v1`, deterministic calculations, gates and valuation are unchanged.
2. `tve analyze` remains offline and is still the owner of deterministic
   investment state.
3. Existing `CompanyAnalysis`, decision-trace, report, historical manifest,
   acceptance/readiness and research-workspace contracts remain authoritative.
4. The new surface copies/projects already-computed values; it must not recreate
   formulas or infer a more favorable state.
5. Missing, blocked, partial and not-evaluated states remain explicit.
6. No source credential, API key, signed URL, raw provider payload or restricted
   filing bytes may enter the surface artifact.
7. Ordinary CI remains network-free and model-free.
8. A6 remains an optional strict corpus-claim boundary, not a prerequisite for
   personal research or M6-A.
9. M4-D/M4-E remain optional claim-specific reconciliation extensions.
10. M2-D remains gated and `H_PRICE_SOURCE_SELECTED_FUTU` remains unchanged.
11. M5-C raw/research-sidecar remote mirroring is not pulled into M6-A.
12. No trading, order, cancellation, transfer or brokerage state change is in
    scope.

## 4. Contract: ResearchSurfaceSnapshotV1

Introduce a typed/versioned read model, named approximately
`ResearchSurfaceSnapshotV1`.

The exact Python naming may follow repository conventions, but the persisted
contract must be explicit and schema-backed.

At minimum the snapshot should contain these sections.

### 4.1 Identity

- contract/schema version;
- deterministic surface/snapshot ID or content hash;
- company/listing identity already present in the source artifacts;
- `as_of`;
- rule/profile identity;
- source artifact identities/hashes needed to reproduce the projection.

Do not add a wall-clock timestamp that makes otherwise identical inputs produce
different bytes. If operational timestamps are useful later, keep them outside
the deterministic snapshot identity.

### 4.2 Deterministic analysis view

Project, without recalculation:

- final deterministic state;
- hard-gate statuses and reasons;
- key deterministic metrics already present in `CompanyAnalysis`;
- valuation state/ranges already present in `CompanyAnalysis`;
- Business Quality state/score/confidence only when already validated;
- unresolved or not-evaluated states.

The projection must not turn a missing field into zero, a failed gate into a
pass, or an indicative valuation into an actionable one.

### 4.3 Evidence / trace / report references

When supplied, retain stable references to:

- decision trace;
- research/report artifact;
- accepted-adjustment provenance;
- relevant evidence/workspace artifact identities.

M6-A should prefer identities/references over embedding large evidence bodies.
If a supplied trace/report does not match the analysis identity, fail closed.

### 4.4 Data/corpus status

When historical/readiness/acceptance artifacts are supplied, expose a compact
read-only status view suitable for an agent or Dashboard:

- manifest/dataset identity;
- declared scope/date range when available;
- source freshness/coverage summary already computed by existing contracts;
- `production_eligible` or equivalent claim state when present;
- exact blockers/warnings/limitations;
- mirror/package identity when explicitly provided.

Absence of those optional artifacts is a declared `NOT_AVAILABLE`/equivalent
state, not an exception and not a fabricated green status.

## 5. Builder / projection boundary

Add a reusable Python builder/facade that accepts existing validated models (or
loads their persisted JSON through existing model validators) and returns the
surface snapshot.

A suitable shape is approximately:

```text
validated frozen artifacts
  -> identity compatibility checks
  -> read-only projection
  -> ResearchSurfaceSnapshotV1
  -> schema validation / canonical serialization
```

Rules:

- no provider call;
- no model call;
- no network call;
- no file discovery by recursive root scan;
- no hidden fallback;
- no recomputation of investment math;
- fail closed on conflicting identities or incompatible `as_of` boundaries.

## 6. Thin CLI

Add a thin additive CLI only after the reusable Python projection API exists.

Preferred namespace:

```bash
tve surface build \
  --analysis <company-analysis.json> \
  [--trace <decision-trace.json>] \
  [--report <research-report.json>] \
  [--historical-manifest <historical-manifest.json>] \
  [--acceptance <historical-acceptance.json>] \
  --output <research-surface.json>

tve surface validate --input <research-surface.json>
```

Exact optional flags may be adjusted to existing artifact/model names. Keep the
command local/offline. Do not add HTTP serving to this milestone.

## 7. Schema and deterministic identity

Add a JSON Schema for the persisted snapshot.

The same semantic inputs must produce the same canonical snapshot bytes/content
hash. Tests must prove:

- field ordering/serialization does not create identity drift;
- optional unavailable sections are represented deterministically;
- source identities participate in snapshot identity;
- changing a projected source artifact changes snapshot identity;
- a regenerated snapshot validates against the checked-in schema.

## 8. Security / publication policy

The M6-A snapshot is a derived result artifact, but that does not make every
source byte publishable.

At minimum:

- never embed credentials or credential references that resolve to secrets;
- never copy raw provider response bodies;
- never copy signed URLs;
- do not embed restricted filing/source bytes merely because the local
  workspace contains them;
- preserve source/provenance IDs needed for audit without exposing secrets;
- make partial/missing evidence visible.

A later M5-C/M6 publish package may decide which snapshot classes are eligible
for R2/remote mirroring. That decision is not part of M6-A.

## 9. Deterministic tests

Ordinary tests must remain offline and model-free.

At minimum cover:

1. minimal `CompanyAnalysis` -> valid surface snapshot;
2. full analysis + matching trace/report -> valid surface snapshot;
3. mismatched analysis/trace/report identity -> fail closed;
4. missing optional historical/acceptance inputs remain explicit;
5. blocked/partial A6 state is preserved exactly, never promoted;
6. not-evaluated Business Quality stays not evaluated;
7. deterministic metrics/valuation are copied from source artifacts, not
   recomputed;
8. forbidden secret/raw-payload fields cannot leak through generic dict copying;
9. same inputs -> byte/content-hash stable output;
10. one source identity/value change -> surface identity changes;
11. JSON Schema validates generated snapshots and rejects malformed snapshots;
12. CLI build/validate are offline;
13. existing Phase 1-5R/M5 tests remain green.

## 10. Preferred implementation scope

Keep M6-A narrow, approximately within:

```text
src/turtle_value_engine/surface/__init__.py
src/turtle_value_engine/surface/contracts.py
src/turtle_value_engine/surface/projection.py
src/turtle_value_engine/__init__.py
src/turtle_value_engine/cli.py
schemas/research-surface-snapshot.schema.json
tests/test_research_surface.py
tests/test_cli.py                         # only if existing CLI tests live here
docs/architecture/agent-api-web-surface.md
docs/goals/phase-5r-a-m6-a-read-only-research-surface.md
docs/status/phase-5r-a-2026-09-18.md or dated successor
docs/status/phase-5r-a-next-codex-goal.md
docs/roadmap.md
```

Reuse existing models and schema helpers. Do not broadly refactor analysis,
research, historical acquisition or mirror code just to build the projection.

## 11. Explicitly out of scope

Do not implement in M6-A:

- FastAPI/Flask/HTTP server;
- Cloudflare Worker application code;
- D1 schema/indexing;
- UI components;
- authentication/authorization;
- remote publish/sync of the new surface artifact;
- M5-C broader mirror policy;
- raw `RawBlobStore` remote mirroring;
- Phase 6 watchlist/event polling;
- scheduled jobs;
- live provider acquisition;
- live analyst/model calls;
- M4-D/M4-E;
- M2-D;
- trading or brokerage actions;
- any change to deterministic investment math.

## 12. Verification

Before editing, run:

```bash
python -m ruff check .
python -m pytest
```

Use `python3 -m ...` if that is the available interpreter.

After implementation run at minimum:

```bash
python -m ruff check .
python -m pytest tests/test_research_surface.py -q
python -m pytest
```

Add focused CLI/schema tests as required and record exact results.

## 13. Acceptance

M6-A is complete when:

- a versioned schema-backed read-only surface snapshot exists;
- it is built only from already-validated/frozen artifacts;
- deterministic investment values are projected, not recomputed;
- identity/as-of mismatches fail closed;
- partial/missing/A6-blocked states remain explicit;
- the artifact contains no secrets or raw restricted provider payloads;
- output identity is deterministic;
- a thin offline CLI can build and validate the snapshot;
- ordinary CI remains network/model independent;
- the full existing suite remains green.

After M6-A closes, choose the next package based on a concrete deployment need:

- **M6-B**: read-only application/API adapter over the frozen surface;
- **M5-C**: explicitly authorize/mirror the new concrete surface artifact class
  to R2/S3 when remote distribution is required;
- **M6-C**: personal Worker/Dashboard consuming prepared surface artifacts;
- **Phase 6 monitoring**: later watchlist/event-driven orchestration.

Do not implement those follow-ons inside M6-A.
