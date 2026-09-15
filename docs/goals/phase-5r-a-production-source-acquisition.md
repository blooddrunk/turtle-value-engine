# Phase 5R-A — Personal-First Production Source Acquisition and Compiler Ingestion

Status: **ACTIVE / PARTIAL**

## Objective

Make the repository acquire a bounded, real A/H historical corpus itself and
compile it deterministically into the existing `HistoricalDatasetManifest` and
content-addressed JSONL shards. The default path is for a personal research
project: it must not require an institutional market-data contract, manual CSV
assembly, a live model, or a network dependency during replay and ordinary CI.

The word "production" in this goal means repeatable, auditable, fail-closed use
by the project owner. It does not mean that private source bytes may be
redistributed, published, or used to provide a public data service.

This goal is additive. It must not change `strict-v1`, deterministic investment
math, Phase 5 signal/portfolio semantics, or point-in-time rules.

## Implementation status — 2026-09-15

A0–A5 and A7 are implemented. The repository now has category-union production
coverage evaluation, additive coverage evidence bases, typed acquisition plans
and receipts, a private immutable raw-byte CAS, explicit network/retry and
credential boundaries, per-source aggregate artifacts for multi-response
batches, the documented Hithink A-share dump adapter, an injected bridge to the
existing official filing downloader, and an offline raw-to-shard compiler.
Deterministic fake-transport tests cover the new boundaries.

The goal remains `ACTIVE / PARTIAL`: no credential was read from chat or the
local environment and no live probe was run, so A6's minimum real private A/H
acceptance is not claimed. The precise unresolved source, membership, terminal
economics and authorization blockers are recorded in
`docs/operations/phase-5r-a-acquisition.md` and in readiness reports.

The repository now also exposes `tve historical accept`, a pure offline A6
audit over a persisted batch, probe report, raw CAS, compiled manifest and
shard store. It records exact blockers and exits fail closed; this audit tool
does not itself make the real private acceptance claim pass.

For the project-owner live policy, the built-in CLI transport additionally
requires every required request credential to be declared as an `ENVIRONMENT`
reference and to resolve to a non-empty value before it can touch the network.
Keyring/injected resolution remains an explicit library boundary for controlled
runners and deterministic fake-transport tests; it is not a default CLI live
authorization.

## Decisions frozen for this task package

1. **Personal-first access**: official public sources and documented
   personal-account APIs are the default. Institutional sources may have
   adapters later, but no institutional contract may be a prerequisite for the
   default acceptance path.
2. **The project acquires data**: the owner may configure credentials and choose
   a source policy, but must not be required to prepare bars, actions, membership
   tables, filings, or research rows by hand.
3. **Local is authoritative first**: exact raw bytes, receipts, compiler inputs,
   shards, and manifests are stored outside Git in a local content-addressed
   store. Git contains code, schemas, plans, small legal fixtures, and redacted
   reports only.
4. **Remote storage is optional**: a private remote object store may mirror
   eligible artifacts after local acceptance. Losing network access must not
   prevent replay of an already materialized local corpus.
5. **Access and redistribution are separate**: a source usable under a personal
   account is recorded as private/internal unless its terms explicitly allow
   redistribution. A private corpus can be useful without being publishable.
6. **No source laundering**: an aggregator cannot become authoritative merely
   because it is free. Provider identity, upstream identity where known, terms,
   retrieval method, historical capability, coverage, and unresolved gaps stay
   explicit.
7. **No hidden substitution**: current constituents are never used as historical
   constituents; adjusted prices never silently replace unadjusted prices plus
   actions; missing rows never imply suspension; live quotes never stand in for
   historical bars.
8. **No cloud prerequisite**: neither Cloudflare, Supabase, nor a VPS is required
   to close the first local vertical slice.

## Milestone ladder

Phase 5R-A is deliberately split into claims that can be earned independently:

| Milestone | Claim | Required evidence |
| --- | --- | --- |
| `ACQUISITION_READY` | The project can fetch and replay exact raw source bytes. | Explicit network opt-in, credential isolation, immutable raw blobs, receipts, retry/rate-limit behavior, offline replay tests. |
| `PERSONAL_RESEARCH_READY` | A named private A/H corpus is usable for its declared categories and dates. | Automatic acquisition, source terms/access evidence, category-specific coverage, deterministic compilation, real private acceptance, explicit limitations. |
| `PRODUCTION_ELIGIBLE` | The existing full Phase 5R production claim passes. | All existing `--require-production` obligations, historical membership, all required categories, terminal economics, PIT research, and independent reconciliation. |

The first implementation cycle must close `ACQUISITION_READY` and a bounded
`PERSONAL_RESEARCH_READY` market-data slice. It must not weaken
`PRODUCTION_ELIGIBLE` to make an incomplete corpus appear complete.

## Source policy and first candidates

Every candidate remains unqualified until an adapter probe records actual
response shape, date span, listing coverage, account entitlement, throttling
behavior, and a terms/access evidence hash. A failed candidate narrows the
claim or activates a documented fallback; it never causes fabricated data.

| Category | Default candidate path | Authority/reconciliation path | Required probe or unresolved fact |
| --- | --- | --- | --- |
| A-share prices and actions | Hithink Financial-API full-market Parquet dumps using a personal key | SSE/SZSE/BSE public records where lawful and technically available; a second documented provider for sampled values | Confirm actual account access, retained history, inclusion of terminal/delisted listings, revisions, throttling, and private caching rights. |
| A-share universe/lifecycle/delistings | A documented personal API if it returns effective-dated history; otherwise an automatic exchange-source adapter | SSE/SZSE/BSE listed/delisted records | A current security master is not historical membership. Confirm code changes, listing/terminal dates, and historical constituent/change data separately. |
| H-share prices/lifecycle/actions | A documented personal-account historical API selected after probing; existing AKShare/Eastmoney adapters may be used only as private candidate or reconciliation inputs | HKEX/HKEXnews issuer and listing records where automated use is permitted | No free authoritative H-share source is assumed. Exact delisted retention, action completeness, automation rights, and history span are open blockers until probed. |
| Benchmarks | Documented personal historical index-level API | CSI and Hang Seng Indexes source metadata and change notices | Index levels and historical membership are different datasets. Historical constituents require effective-dated files or change reconstruction. |
| FX | SAFE and/or HKMA official historical series | Independent sampled cross-check where available | Confirm exact currency orientation, publication/availability timestamp, date span, and permitted private caching. |
| A-share filings | Existing CNINFO/SSE/SZSE discovery and document-cache boundary | Issuer/exchange filing identity and document hash | Confirm automation terms, pagination, revisions, and publication timestamps for the bounded target. |
| H-share filings | Existing HKEXnews discovery/document boundary only when the access method is permitted | Issuer/HKEX filing identity and document hash | HKEX website restrictions must be respected; no scraping workaround is allowed. An authorized or otherwise permitted route is still to be selected. |
| Historical research | Deterministic extraction and frozen Phase 4 artifacts from locally cached filings | Filing hash, locator, `available_at`, review state | No online-model reconstruction. Missing validated Business Quality remains `NOT_EVALUATED`/review-required. |

Commercial institutional providers such as Wind or iFinD are optional adapter
extensions only. They are not part of the default dependency graph or the
minimum acceptance criteria.

## Work packages

### A0. Correct the claim and coverage boundary

- Preserve the current strict `production_eligible` and
  `--require-production` behavior for backward compatibility.
- Add a separate typed acquisition/readiness report for
  `ACQUISITION_READY` and `PERSONAL_RESEARCH_READY`; do not overload a prose
  warning or reinterpret `production_eligible`.
- Fix production coverage evaluation so legitimate multi-source composition is
  evaluated as a union by source category, listing, and period. One SSE source
  must not be required to cover H listings and one HK source must not be
  required to cover A listings.
- Define category-specific coverage evidence. Trading sessions are meaningful
  for prices; zero corporate-action rows, zero delistings, or zero filings do
  not prove completeness by themselves.
- Keep all current wire contracts readable. Any schema revision must be
  additive/versioned and must not touch `strict-v1`.

Acceptance:

- tests reproduce the current cross-market false blocker and prove the
  aggregate fix;
- a partial personal corpus cannot pass `--require-production`;
- existing Phase 5R fixtures remain byte-equivalent and valid under their
  original claims.

### A1. Acquisition contracts and local raw store

Add a dedicated `turtle_value_engine.historical.acquisition` boundary with
typed equivalents of:

```text
HistoricalAcquisitionPlanV1
HistoricalAcquisitionRequestV1
CredentialReferenceV1
RawArtifactReceiptV1
RawAcquisitionBatchManifestV1
SourceProbeReportV1
AcquisitionReadinessReportV1
HistoricalSourceAdapter
CredentialResolver
NetworkTransport
RawBlobStore
HistoricalRawDecoder
HistoricalIngestionCompiler
```

The exact names may change if existing repository naming requires it, but the
responsibilities must remain separate.

Raw blobs use exact response bytes and this layout:

```text
<raw-store>/sha256/<first-two-hash-bytes>/<sha256>.blob
```

Each immutable receipt records at least:

- adapter/provider identity and version;
- stable request identity and canonical parameters;
- a redacted stable source URI, excluding credentials and expiring signatures;
- retrieval start/end time, HTTP status, content type and length;
- safe response headers such as `ETag`, `Last-Modified`, request ID, and
  `Retry-After` when present;
- SHA-256 of exact bytes;
- parent/batch identity for paginated or presigned downloads;
- source terms/license evidence URI and content hash;
- a non-secret access-grant reference for personal/restricted access;
- declared storage policy: `LOCAL_ONLY`, `PRIVATE_REMOTE_ALLOWED`, or
  `REDISTRIBUTABLE`.

Secrets may be resolved only from environment variables, OS keyring, or an
explicit injected resolver. Secret values must never enter request hashes,
logs, receipts, manifests, fixtures, error messages, or CLI output.

Writes are atomic. A partial download stays quarantined; a completed path is
created only after size and SHA-256 validation. An existing content hash is
idempotent only when bytes are identical.

### A2. Explicit network, retry, and rate-limit boundary

Add a thin networked CLI separate from all existing replay commands:

```text
tve historical source probe --plan <plan.json> --network=allow
tve historical acquire --plan <plan.json> --network=allow \
  --raw-store <private-path> --batch-output <batch.json>
tve historical compile --batch <batch.json> --raw-store <private-path> \
  --store <artifact-store> --output <historical-manifest.json>
```

CLI spelling may be adjusted to the existing parser style, but these semantics
are required:

- network is denied unless the user passes an explicit opt-in;
- compile, validate, freeze, snapshot, backtest, and calibrate remain offline;
- 401/403, incompatible schema, permission, checksum, and semantic errors fail
  immediately;
- retry only connection failures, 408, 429, and bounded transient 5xx results;
- honor `Retry-After`, then use bounded exponential backoff with jitter;
- enforce per-host concurrency and token-bucket limits;
- when a provider publishes no fixed limit, begin conservatively and record
  observed throttling instead of inventing a quota;
- pagination, resume, and presigned-URL refresh are adapter-owned and auditable.

Ordinary tests use an injected fake transport and a fake clock. No ordinary CI
test may contact a provider, Cloudflare, Supabase, a VPS, or a model.

### A3. First A-share vertical slice

- Implement the Hithink Financial-API adapter only for capabilities confirmed
  by its official repository documentation and the owner's live probe.
- Start with full-market unadjusted daily bars and corporate-action/adjustment
  events if the probe verifies their exact shapes and private-use terms.
- Decode Parquet only behind an optional dependency. Preserve raw bytes first;
  decoding may not replace the source artifact.
- Treat any adjusted factor or adjusted price as reconciliation input until its
  basis is proven. Canonical returns remain unadjusted prices plus explicit
  actions.
- Add the smallest qualified lifecycle/calendar source needed to make the
  bounded A-share rows interpretable. If terminal/delisted retention is not
  proven, report it as a blocker rather than selecting only survivors.

### A4. First H-share and official-document vertical slice

- Run source probes before selecting an H-share primary. No adapter may claim
  authority, delisted coverage, action completeness, or historical membership
  from a current snapshot.
- Implement the smallest documented personal-use H source that passes the
  probe. If none passes, close the acquisition foundation and retain a precise
  `H_SOURCE_UNQUALIFIED` blocker; do not introduce a mandatory institutional
  source.
- Reuse the existing official filing discovery/download/cache architecture.
  Extend it only where the selected lawful access method requires raw-byte
  receipts and batch identity.
- Compile filing locators, document hashes, publication/availability timestamps,
  and revisions. A later revision remains a distinct artifact.

### A5. Deterministic raw-to-shard compiler

For every selected adapter, implement an offline decoder that:

1. verifies the raw blob against its receipt and batch manifest;
2. validates provider schema/version and rejects unrecognized changes;
3. emits canonical typed rows with deterministic IDs and source lineage;
4. sorts rows by a documented canonical key;
5. deduplicates byte/semantic-identical rows and fails on conflicting natural
   keys;
6. freezes canonical JSONL through `HistoricalArtifactStore`;
7. creates `HistoricalSourceDescriptor`, `HistoricalShardReference`, coverage,
   missingness and reconciliation artifacts;
8. builds the existing `HistoricalDatasetManifest` without a network or model
   call.

The provenance chain must remain traversable:

```text
raw response bytes SHA-256
  -> raw receipt and batch hash
  -> decoder/mapping version
  -> canonical row source identity
  -> canonical JSONL SHA-256
  -> shard reference
  -> HistoricalDatasetManifest SHA-256
```

For a batch or paginated source, create a stable aggregate source artifact that
lists child blob hashes. Do not assign one arbitrary page hash to rows compiled
from multiple responses.

### A6. Minimal real private A/H acceptance

The live acceptance is opt-in, local/private, and never runs in ordinary CI. It
must use an automatically acquired target, not user-prepared data.

After A0 probes qualify the sources, commit a redacted target definition with:

- at least one real A listing and one real H listing over a shared period of at
  least two complete calendar years;
- at least one source-proven terminal, delisted, code-change, or prolonged-
  suspension case in either market;
- one benchmark and the FX path required to express A/H returns in the declared
  reporting currency;
- at least one real official filing per market with source document hash and
  point-in-time availability;
- explicit market calendars, missing/suspended sessions, corporate actions,
  source limitations, and reconciliation samples.

If a single bounded target cannot prove historical membership, label it
`FIXED_RESEARCH_UNIVERSE`; do not call it survivorship-bias-free. The target may
graduate to `HISTORICAL` only after effective-dated membership and lifecycle
coverage are proven.

The acceptance must prove:

- live acquisition followed by network-disabled re-compilation produces the
  same manifest and shard hashes;
- corrupt/missing blobs, schema drift, conflicting duplicates, incomplete
  calendars, unknown terminal economics, and future filings fail closed;
- no secret or restricted raw content is committed;
- no online model is invoked; absent frozen Business Quality remains explicit;
- the existing compact adversarial fixture and all earlier tests still pass.

The exact real listing IDs and dates are intentionally not invented in this
task package. They must be selected from verified probe results and recorded in
the redacted acceptance plan before implementation claims completion.

### A7. Documentation and operator runbook

- Add a Chinese-first runbook covering source selection, environment-variable
  credential references, local directories, acquire/compile/replay, source
  terms evidence, key rotation, backups, and deletion.
- Add `.gitignore` entries for default private stores, receipts, live reports,
  credentials, and downloaded documents without ignoring committed fixtures.
- Record actual probe outcomes and unknowns. Do not copy secrets or restricted
  response samples into documentation.
- Update `AGENTS.md`, the Phase 5R parent goal, architecture, roadmap, and README
  only after the corresponding command is executable.

## Remote storage decision and later plan

Remote storage is a follow-on work package after the local content-addressed
path passes acceptance.

| Option | Recommended role | Decision |
| --- | --- | --- |
| Local filesystem | Authoritative raw store and compiler input for Phase 5R-A | **Required first**. Simplest offline and legal boundary. |
| Cloudflare R2 | Private mirror for blobs/shards eligible for remote storage; later Dashboard artifact origin | **Preferred first remote backend** because it is object storage with an S3-compatible API and a useful hobby-scale free tier. Never mirror `LOCAL_ONLY` artifacts. |
| Cloudflare D1 | Later Dashboard metadata/index, run status, small query projections | **Later only**. It is a serverless SQL database, not the raw historical blob store. |
| Supabase | Alternative later Postgres/Auth layer for the Dashboard | **Optional alternative**, not the canonical blob store. The current free file-storage quota and idle pausing make it a weak sole archive. |
| Owner VPS | Scheduled acquisition runner, encrypted backup, or private API host | **Good optional operations host** if already available. It has more maintenance, security, and backup responsibility than managed object storage. |
| Direct source only | Live acquisition without retained raw snapshots | **Rejected**. Upstream revisions, outages, and entitlement changes would destroy reproducibility. |

The future storage abstraction should expose immutable `put-if-absent`, verified
`get`, `head`, and explicit sync operations. Remote reads must verify SHA-256.
Remote storage must never be an implicit network fallback inside offline replay.
Artifact storage policy and source terms must be checked before upload.

## Web Dashboard follow-on

After the private corpus and offline compiler are stable, Phase 6 may add a
read-only personal Dashboard using Cloudflare Workers, with R2 for permitted
artifacts and D1 for derived indexes/status. Its first version should display
coverage, source freshness, manifest identity, replay results, decisions,
missing data, and blockers.

The Dashboard must not:

- run deterministic investment calculations in a second implementation;
- expose personal API keys, raw restricted data, or filing bytes that may not be
  redistributed;
- silently acquire data during a page request;
- turn a failed/partial source state into a green result;
- make Phase 5R-A depend on Cloudflare availability.

Acquisition should normally run from the local machine or owner VPS. Workers
may read derived artifacts and enqueue future Phase 6 jobs, but real-time/event
monitoring remains Phase 6 and is not a Phase 5R-A exit condition.

## Planning evidence for named services

These links justify only the infrastructure choices above; prices, quotas, and
service limits must be rechecked when the corresponding optional backend is
implemented.

- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/) lists
  the current Standard free tier and states that direct R2 egress is free.
- [Cloudflare R2 S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)
  documents the interface suitable for an optional object-store backend.
- [Cloudflare D1 overview](https://developers.cloudflare.com/d1/) describes D1
  as a serverless database with SQLite semantics for Workers/HTTP access, not
  as blob storage.
- [Cloudflare Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
  and [platform limits](https://developers.cloudflare.com/workers/platform/limits/)
  are the authoritative references for a later Dashboard deployment.
- [Supabase pricing](https://supabase.com/pricing) currently lists the Free
  plan's database, file-storage, egress, and idle-pausing limits.
- [Hithink Financial-API repository](https://github.com/HiThink-Tech/Financial-API)
  and its
  [market-dump endpoint reference](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-market-dumps.md)
  are implementation leads, not proof of the owner's data entitlement or
  redistribution rights; A0 must capture those separately.

## Verification commands

Before marking an implementation work package complete:

```bash
python -m ruff check .
python -m pytest
```

Also run a network-denial test for every existing offline CLI, a secret-leak
scan over generated redacted outputs, and an opt-in private live acceptance when
the corresponding credentials are configured.

## Completion rule

Mark this goal `COMPLETE` only when A0–A7 are implemented and the minimum real
private A/H acceptance passes for its honest declared claim. If an H source,
historical membership source, terms grant, terminal treatment, or official
filing route remains unresolved, retain `ACTIVE / PARTIAL` and name the exact
blocker. Do not solve a blocker by requiring an institutional subscription,
manual dataset construction, scraping against published restrictions, or
weakening an existing validation rule.
