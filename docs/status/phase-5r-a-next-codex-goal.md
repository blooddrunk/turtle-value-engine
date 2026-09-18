# Codex Goal — Phase 5R-A M6-A Read-only Research Surface

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

Status: **M6-A COMPLETE; M5-A/B COMPLETE; A6 PENDING**

## Current audited state — 2026-09-18

Read and follow `AGENTS.md` and its source-of-truth order before editing. Read at least:

- `docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-a-m5-b-s3-compatible-artifact-backend.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/architecture/production-historical-data-and-research-archive.md`
- `docs/status/phase-5r-a-2026-09-18.md`
- `docs/roadmap.md`

M5-A and M5-B are complete. Current audited M5-B head was `1580670`; the
repository records:

- `python3 -m ruff check .`: PASS
- `python3 -m pytest tests/test_historical_artifact_mirror.py -q`: 10 passed
- `python3 -m pytest tests/test_historical_artifact_s3_mirror.py -q`: 11 passed
- `python3 -m pytest tests/test_m4_reconciliation.py -q`: 19 passed
- `python3 -m pytest`: 6276 passed, 2 skipped

GitHub had no attached CI status/workflow run for that head. A separate ChatGPT
audit confirmed the implementation/contract boundary but could not independently
clone/run because the audit container could not resolve github.com. Therefore
run a fresh baseline before editing and record exact results.

M4-D/M4-E remain optional claim-specific extensions, not current blockers.
M2-D remains gated and `H_PRICE_SOURCE_SELECTED_FUTU` remains unchanged.
Full Phase 5R/A6 production eligibility remains pending but is not a prerequisite
for useful personal research or M6-A.

## Preflight

Before editing:

```bash
python -m ruff check .
python -m pytest
```

If only `python3` exists, use the equivalent `python3 -m ...` commands.
Do not build M6-A on a red baseline.

## Objective

Implement **M6-A — Read-only Research Surface Contract** exactly as specified in:

`docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`

Create the first stable, versioned, schema-backed, deterministic **read-only
projection** of already validated/frozen Turtle artifacts for later consumption
by Hermes, Skills, APIs and a personal Web Dashboard.

This is **not** a second analysis engine and **not** an HTTP/UI milestone.

## Required implementation

1. Add a typed/versioned persisted contract, approximately
   `ResearchSurfaceSnapshotV1`.
2. Add a JSON Schema for the snapshot.
3. Build the snapshot only from existing validated/frozen artifacts.
4. Project deterministic analysis values from `CompanyAnalysis`; do not
   recompute CDC, Net Cash, Through Return, hard gates, valuation or final state.
5. When matching trace/report/research artifacts are supplied, keep stable
   references/identities and fail closed on incompatible identities or `as_of`.
6. When historical/readiness/acceptance artifacts are supplied, expose a compact
   status projection including exact blockers/warnings/limitations and the
   existing production/claim state.
7. Missing optional historical/acceptance artifacts must be explicit
   `NOT_AVAILABLE`/equivalent, never fabricated as healthy.
8. Preserve not-evaluated Business Quality and all partial/blocked states.
9. Define deterministic canonical serialization and snapshot identity/content
   hash. Identical semantic inputs must produce identical output identity.
10. Add a reusable Python projection/facade before adding CLI wiring.
11. Add a thin offline CLI, preferably:
    - `tve surface build ... --output ...`
    - `tve surface validate --input ...`
12. Do not recursively discover workspace/store files. Only consume explicit
    provided artifacts.
13. Do not copy credentials, signed URLs, raw provider response bodies or
    restricted filing/source bytes into the surface.
14. Ordinary CI must remain network-free and model-free.

## Deterministic tests

At minimum cover:

- minimal `CompanyAnalysis` -> valid snapshot;
- full matching analysis + trace/report -> valid snapshot;
- mismatched identities/as_of -> fail closed;
- optional historical/acceptance input absent -> explicit unavailable state;
- A6/production blocked state preserved exactly;
- not-evaluated Business Quality remains not evaluated;
- deterministic metrics/valuation copied from source artifact, not recomputed;
- no secret/raw-provider payload leakage through generic dict copying;
- same inputs -> same canonical bytes/content hash;
- changed source identity/value -> changed surface identity;
- generated output validates against checked-in schema;
- malformed snapshot fails validation;
- CLI build/validate remain fully offline;
- full existing test suite remains green.

## Preferred scope

Keep changes close to:

```text
src/turtle_value_engine/surface/__init__.py
src/turtle_value_engine/surface/contracts.py
src/turtle_value_engine/surface/projection.py
src/turtle_value_engine/__init__.py
src/turtle_value_engine/cli.py
schemas/research-surface-snapshot.schema.json
tests/test_research_surface.py
docs/architecture/agent-api-web-surface.md
docs/goals/phase-5r-a-m6-a-read-only-research-surface.md
docs/status/phase-5r-a-2026-09-18.md
docs/status/phase-5r-a-next-codex-goal.md
docs/roadmap.md
```

Reuse current typed models/schema helpers. Avoid broad refactors of deterministic
analysis, Phase 4 research orchestration, historical acquisition, M4 or M5.

## Explicitly not current work

Do **not** implement in M6-A:

- FastAPI/Flask/HTTP server;
- Cloudflare Worker application code;
- Cloudflare D1 schema/indexes;
- React/TanStack/UI components;
- authentication/authorization;
- remote publishing of the new snapshot;
- M5-C broader artifact-class mirroring;
- raw `RawBlobStore` remote mirroring;
- Phase 6 watchlist/event monitoring;
- scheduler/cron/GitHub Actions automation;
- live provider acquisition;
- live analyst/model calls;
- M4-D;
- M4-E;
- M2-D;
- trading/orders/transfers;
- changes to `strict-v1`, PIT/A6 semantics or deterministic investment math.

## Verification

After implementation run at minimum:

```bash
python -m ruff check .
python -m pytest tests/test_research_surface.py -q
python -m pytest
```

Add focused CLI/schema tests as required. Record the exact commands/results in
the dated status document.

## Acceptance

M6-A is complete when one versioned schema-backed read-only surface snapshot can
be deterministically produced and validated from existing frozen Turtle
artifacts; all projected investment values remain owned by their original
validated artifacts; identity/`as_of` conflicts fail closed; partial/missing/A6
blocked states remain visible; secrets/raw restricted payloads cannot leak; a
thin offline CLI exists; and the full suite remains green.

Stop after M6-A closure. Do not automatically start M6-B, M5-C, Worker/UI or
Phase 6 monitoring in the same goal. Update the roadmap/status docs with the
actual next decision point.

## M6-A closure

M6-A is now closed. The versioned ResearchSurfaceSnapshotV1 contract,
checked-in JSON Schema, explicit allowlisted projection API and offline
surface build/validate CLI are implemented. The surface copies validated
deterministic values, keeps trace/report and historical identity conflicts
fail-closed, and exposes missing/partial/blocked/not-evaluated states without
promoting them. It does not copy credentials, signed URLs, raw provider
payloads or restricted filing/source bytes.

The next Codex goal must be selected from a concrete deployment requirement:
M6-B read-only API, M5-C remote artifact policy, or M6-C Worker/Dashboard.
Phase 6 monitoring remains out of scope until explicitly opened.
