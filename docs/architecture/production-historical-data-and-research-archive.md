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

## Phase 5R-A acquisition boundary

Phase 5R-A adds a separate, opt-in path before the cache-only compiler:

```text
HistoricalAcquisitionPlanV1
  -> explicit source probe / adapter request
  -> exact response bytes in private RawBlobStore
  -> immutable RawArtifactReceiptV1 + batch manifest
  -> offline HistoricalIngestionCompiler
  -> HistoricalDatasetManifest and verified JSONL shards
```

`tve historical source probe` and `tve historical acquire` require
`--network=allow`; their default is deny. The built-in CLI transport additionally
requires every required request credential to be declared as an `ENVIRONMENT`
reference and resolved to a non-empty value before any request is sent.
Keyring/injected resolution is reserved for explicitly controlled library
runners and fake transports. Credential values are never included in request
parameters, hashes, receipts, manifests, logs or chat. Raw
bytes use the local layout
`<raw-store>/sha256/<first-two>/<sha256>.blob`; partial streams remain in a
quarantine directory until length and SHA-256 checks pass. Remote mirroring is
not part of the authoritative path.

`tve historical compile` reads only a batch and local raw CAS. It does not
construct a provider, model client or network fallback. Full-market responses
are validated against their adapter schema and filtered to the declared
listing/date request scope before canonical rows are frozen. Unknown schemas,
conflicting natural keys, duplicate semantic rows with different values,
invalid provenance and out-of-scope rows fail closed. Source hashes for a
multi-response batch are aggregate hashes over all child blobs. New batch
manifests also persist one `RawSourceAggregateV1` per source; each aggregate
lists the child receipt IDs and blob SHA-256 values used to derive that source
hash. Older v1 batch files without this additive field remain readable through
the legacy batch hash path.

The first documented A-share candidate is the Hithink Financial-API market-dump
adapter: its official endpoint reference documents unadjusted daily-k and
adjustment-factor Parquet shapes, but documentation alone does not establish an
owner account's entitlement, retention of terminal listings, caching terms or
coverage. The source probe inspects the downloaded Parquet schema and actual
observed date/listing span before setting historical capability; a successful
signing response alone is insufficient. Adjustment factors remain
reconciliation-only unless an operator explicitly enables their decoder after
those facts are evidenced. H-share sources are never inferred from current
snapshots; absent a successful source-specific probe the readiness report keeps the exact
`H_SOURCE_UNQUALIFIED` blocker. Official filing downloads are bridged through
the existing injected filing downloader and do not add an unauthorised scraping
route. Filing receipts retain the non-sensitive filing ID, publication date,
document hash/size, retrieval timestamp, final URL and revision identity; later
bytes remain distinct immutable artifacts. The offline compiler projects those
receipt fields into a `FILING_DOCUMENT` shard without parsing document content;
the local retrieval-finished timestamp is the conservative availability bound,
not an inferred source-publication timestamp. See the Chinese-first operator
[runbook](../operations/phase-5r-a-acquisition.md).

`tve historical accept` is the offline A6 audit boundary. It reads only a
persisted batch, readiness/probe report, raw CAS, artifact store and manifest;
it repeats compilation and checks manifest/shard identities, target scope,
calendars/lifecycle, category coverage, terminal or suspension evidence,
benchmark/FX, official filings, actions, limitations and reconciliation. It
persists exact blockers and exits non-zero when the minimum private A/H claim
is not proven. It never resolves credentials or invokes a provider, network or
model.

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
non-empty row count. For a production Phase 5R claim, the validator evaluates
all nine source categories in the contract even if a compact fixture declares a
smaller `required_source_kinds` list. Current-constituent snapshots are
rejected as historical membership.

Coverage is recorded per listing and period. Expected sessions must be
supplied by a declared calendar source; without them the report is `UNKNOWN`.
Missing sessions, suspended rows and unresolved terminal outcomes remain
visible in reports and manifest missingness instead of being filled.
Benchmark observations are global series by contract, so the offline compiler
projects their observed dates onto the listing scope explicitly declared by
each benchmark request; it does not require a synthetic `listing_id` on the
benchmark row.
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
The local artifact store creates its root and shard directories as private
`0700` directories and rejects symlinked roots or directory components; a
missing or redirected artifact is an error rather than a network fallback.

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
