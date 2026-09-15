# Production historical data and research archive boundary

Status: ACTIVE with a bounded replay implementation. The checked-in compact
corpus is an acceptance fixture, not an authoritative or redistributable A/H
market-history claim.

## Boundary

Phase 5R adds a source-aware layer beside the completed Phase 5 contracts:

```text
acquired source/cache artifacts
  -> HistoricalSourceDescriptor + declared target scope
  -> content-addressed JSONL shards
  -> HistoricalDatasetManifest
  -> offline compiler and validators
  -> BacktestDatasetManifest (Phase 5)
  -> DecisionSnapshot -> signal/portfolio replay/calibration proposal
```

The compiler is deliberately cache-only. It has no provider client, no model
client and no fallback acquisition path. A missing shard, changed byte,
dangling ID, unrelated availability record or invalid point-in-time reference
is an error.

## Source and coverage contract

`HistoricalSourceDescriptor` records one source artifact's category, provider
identity, authority, query parameters, retrieval time, version, source content
hash, coverage dates/listing scope and licensing constraints. The categories
cover universe membership, listing lifecycle/delistings, prices, corporate
actions, benchmarks, FX, filings and research archives. A production source
must additionally retain a license-evidence URI and hash; a
`RESTRICTED_INTERNAL` source must carry an access-grant reference. A prose
license label alone cannot make a production claim eligible.

`HistoricalTargetScope` names the universe, A/H listing IDs, inclusive date
range, membership claim, required source categories and licensing scope. A
historical/survivorship-free claim is eligible only when source descriptors are
historical-capable, coverage is complete, authority/licensing is established,
membership intervals exist, coverage reports are complete and an independent
reconciliation report passes. The validator never infers completeness from a
non-empty row count. Current-constituent snapshots are rejected as historical
membership.

Coverage is recorded per listing and period. Expected sessions must be
supplied by a declared calendar source; without them the report is `UNKNOWN`.
Missing sessions, suspended rows and unresolved terminal outcomes remain
visible in reports and manifest missingness instead of being filled.
`HistoricalValidationSummary.production_blockers` explains why a bounded
fixture is not eligible for a production claim even when ordinary replay
validation is otherwise successful; `--require-production` turns that state
into a command failure.

## Shard storage decision

The Phase 5 manifest remains supported for compact fixtures and backward
compatibility. Phase 5R stores large collections in immutable content-addressed
JSONL shards:

```text
<store>/sha256/<first-two-hash-bytes>/<sha256>.jsonl
```

`HistoricalShardReference` carries format, schema version, content hash, row
count, date range, listing scope and source artifact identity. JSONL was chosen
for the first boundary because it is streamable, diffable and available in the
standard library. A future Parquet/columnar adapter may be added only as an
explicit format contract; it must retain the same hash and provenance fields.
Git contains only compact fixtures. Large, private or licensed artifacts are
external inputs and are never silently fetched during replay.

## Listing lifecycle and replay semantics

The source-aware lifecycle keeps A and H listings distinct while linking them
to an economic company. It retains listing date, terminal date/outcome,
currency, calendar, timezone, historical codes and code changes. Delisting,
acquisition/cancellation, transfer, prolonged suspension and unresolved
terminal outcomes are distinct. An unresolved terminal outcome maps to an
explicit unknown terminal state in the Phase 5 manifest; the compiler never
creates a zero terminal value.

Market rows retain listing market/currency, unadjusted versus adjusted basis,
suspension/missing state and source hash. The canonical return path remains
unadjusted prices plus explicit actions. Adjusted prices that already include
the same dividend/split scope are rejected when explicit actions are present.
Benchmark identity and price-return/total-return semantics are explicit, and
FX observations remain listing/currency-specific.

`reconcile_observations` persists canonical-versus-independent comparisons,
tolerances, missing rows and pass/fail status. A report cannot use the same
source on both sides and cannot combine adjusted prices with explicit actions.

## Historical research archive

`HistoricalResearchArchiveManifest` references immutable Phase 4 evidence
packets, research tasks, analyst runs, Business Quality results, reports,
filings and document/extraction/evidence artifacts. Each reference carries
availability, content/source-document hashes, filing identity, page/section
locator and review status. `validate_research_archive` checks every binding at
the decision timestamp; date-only availability on the same day is not
intraday evidence, and unknown availability is unusable.

An archived Business Quality result must be `FROZEN_VALIDATED`. Backtest
compilation consumes the reference only; it never invokes an analyst or live
model to reconstruct the result. Without a valid archive, the existing Phase 4
`NOT_EVALUATED`, WATCH or manual-review result remains the only valid outcome.

## Offline commands

```bash
tve dataset validate --manifest <historical-manifest.json> --store <store>
tve dataset freeze --manifest <historical-manifest.json> --store <store> \
  --output <backtest-manifest.json>
tve dataset snapshot --manifest <historical-manifest.json> --store <store> \
  --output <snapshots.json>
tve backtest --manifest <historical-manifest.json> --store <store> \
  --run-spec <run-spec.json> --snapshots <snapshots.json>
tve calibrate --manifest <historical-manifest.json> --store <store> \
  --search-space <search-space.json> --split <split.json> \
  --observations <observations.json> --base-profile-sha256 <hash>
```

Networked acquisition is intentionally outside these commands. The compact
fixture's `--require-production` check fails until a user supplies an
authoritative, licensed source corpus and complete coverage evidence.
