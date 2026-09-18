# Phase 5R-A M5 — Deployment-neutral Artifact Mirror

Status: **CLOSED / COMPLETE**
Date: 2026-09-18
Baseline: `58d3edc` (synchronized main)
Parent goals:
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-production-historical-corpus.md`

## 1. Objective

Make frozen historical datasets portable across storage locations **without
changing their bytes, SHA-256 identities, manifest semantics or offline
deterministic behavior**.

The first M5 merge is deliberately a mirror layer, not a rewrite of
`HistoricalArtifactStore`. The existing local filesystem CAS remains the
authoritative deterministic store. M5-A adds an explicit, backend-neutral
transport boundary that can copy and restore a declared frozen dataset package
byte-for-byte.

This prepares later private VPS / S3-compatible / Cloudflare R2 storage and the
M6 agent/API/Web surface without making any remote service a hidden dependency.

## 2. Audited baseline

At baseline `f17ce3c0`:

- `HistoricalArtifactStore` is an immutable local filesystem CAS;
- JSONL shard paths are derived from SHA-256 content identity;
- reads verify the persisted bytes against `HistoricalShardReference`;
- JSON sidecar artifacts can also be frozen by content hash;
- `RawBlobStore` is a separate private exact-byte acquisition CAS;
- M4-C can reconcile two frozen artifact stores completely offline;
- a real owner-authorized `SH600000` BaoStock/Hithink price sample has been
  acquired, replayed and reconciled with a 2/2 PASS.

The current M4 price evidence does not make the broader Phase 5R/A6 claim pass.

## 3. Frozen boundaries

M5 must preserve all of the following:

1. No change to `strict-v1`, CDC, Net Cash, Through Return, hard gates,
   valuation, PIT semantics or A6 semantics.
2. Existing `HistoricalDatasetManifest`, `HistoricalShardReference` and
   content hashes remain stable.
3. A mirror must copy exact persisted bytes. It must not parse and reserialize a
   shard merely to upload or restore it.
4. Deterministic analysis, validation, backtest and reconciliation must not
   acquire network fallback behavior.
5. Remote access, when added later, must be an explicit artifact operation, not
   an implicit `HistoricalArtifactStore.read_*` fallback.
6. Ordinary CI remains offline.
7. M5-A does **not** upload `RawBlobStore` provider bytes. Raw acquisition CAS,
   provider restrictions and `LOCAL_ONLY` data remain separate until an
   explicit later storage-policy package is approved.
8. Credentials, signed URLs and provider secrets must never enter mirror
   manifests, object keys, logs or Git.
9. M4-D/M4-E remain optional research-quality extensions and are not blockers
   for M5.
10. M2-D remains unimplemented and `H_PRICE_SOURCE_SELECTED_FUTU` remains
    unchanged.

## 4. M5-A — Mirror contract and offline reference backend

### 4.1 Backend-neutral object boundary

Add a small protocol/interface in the historical storage layer for immutable
object transport. Keep it narrower than a general cloud filesystem.

A suitable boundary should support equivalents of:

- put exact bytes at an explicit deterministic key if absent;
- read exact bytes by key;
- inspect byte length/hash metadata where available;
- fail on conflicting existing content;
- never list or discover arbitrary unrelated objects as part of a deterministic
  dataset operation.

Do not couple this interface to boto3, Cloudflare or one vendor.

### 4.2 Deterministic mirror manifest

Add a typed/versioned mirror manifest, for example
`historical_artifact_mirror_manifest_v1`, containing only explicit package
membership and non-secret integrity metadata.

At minimum it should retain:

- source dataset/manifest identity;
- each mirrored object's deterministic relative key;
- artifact role/type;
- SHA-256;
- byte length;
- a content hash for the mirror manifest itself.

Build the object inventory from an explicit `HistoricalDatasetManifest` and
its referenced frozen shards. **Do not recursively scan the artifact-store
directory**, because an unrelated/private artifact must not be uploaded merely
because it shares the same root.

The first M5-A package may cover:

- the canonical serialized historical dataset manifest;
- every shard explicitly referenced by that manifest.

Generic research sidecars, M4 reports and raw provider CAS can be added later
through explicit typed references; they are not required for the first merge.

### 4.3 Filesystem reference backend

Implement a second-filesystem backend as the executable reference adapter.

It exists to prove the deployment-neutral contract in ordinary offline CI:

```text
local authoritative HistoricalArtifactStore
        -> explicit mirror manifest
        -> filesystem mirror backend
        -> verified restore bundle
        -> HistoricalDatasetManifest + HistoricalArtifactStore
        -> existing validation/replay
```

This backend must use the same security posture as the current store:

- reject absolute/path-escape keys;
- reject symlink traversal;
- immutable/idempotent same-byte writes only;
- conflicting destination bytes fail closed;
- missing/corrupted objects fail closed.

### 4.4 Explicit push / verify / restore workflow

Add library functions and, if useful, a thin additive CLI surface.

The workflow must be explicit and separable:

1. build/freeze a mirror manifest from a known dataset + store;
2. push only listed objects;
3. verify destination objects against expected hash/length;
4. restore only listed objects into a new local bundle;
5. validate the restored `HistoricalDatasetManifest` with the existing
   `HistoricalArtifactStore` / compiler boundary.

A restored dataset must retain the same shard content hashes and deterministic
replay result as the source.

If a CLI is added, prefer a future-compatible namespace such as:

```text
tve artifacts mirror plan
tve artifacts mirror push
tve artifacts mirror verify
tve artifacts mirror pull
```

For M5-A, only the filesystem backend is required. Do not add a fake
`--backend=r2` option that has no real implementation.

## 5. M5-A expected implementation surface

Prefer the smallest coherent change, approximately:

```text
src/turtle_value_engine/historical/store.py
src/turtle_value_engine/historical/mirror.py          # preferred additive module
src/turtle_value_engine/historical/contracts.py       # mirror manifest models
src/turtle_value_engine/historical/__init__.py
src/turtle_value_engine/__init__.py
src/turtle_value_engine/cli.py                        # only for thin explicit CLI
schemas/historical-artifact-mirror-manifest.schema.json
tests/test_historical_artifact_mirror.py
docs/architecture/production-historical-data-and-research-archive.md
docs/operations/phase-5r-a-acquisition.md             # only if CLI is added
docs/status/phase-5r-a-2026-09-18.md or dated successor
```

Do not refactor provider adapters, acquisition logic or investment calculations
to complete M5-A.

## 6. Deterministic test matrix

At minimum cover:

1. build mirror manifest from one explicit frozen dataset;
2. inventory contains exactly the manifest and referenced shards, not unrelated
   files in the same source store;
3. push preserves byte-for-byte SHA-256 identities;
4. repeat push is idempotent for identical bytes;
5. conflicting destination content fails closed;
6. missing destination object makes verify fail;
7. corrupted destination object makes verify fail;
8. path traversal / absolute keys / symlink traversal fail closed;
9. pull/restore verifies every object before accepting the bundle;
10. restored shard hashes equal source shard hashes;
11. restored dataset validates/replays identically through existing offline
    boundaries;
12. mirror-manifest tampering fails validation;
13. no network is used by filesystem mirror tests;
14. existing Phase 5R/M4 tests remain green.

## 7. Verification

Run at minimum:

```bash
python -m ruff check .
python -m pytest tests/test_historical_artifact_mirror.py -q
python -m pytest tests/test_m4_reconciliation.py -q
python -m pytest
```

## 8. M5-A acceptance

M5-A is complete when:

- a frozen historical dataset can be mirrored from one local backend to another
  using only the backend-neutral contract;
- the mirror inventory is explicit and auditable;
- exact bytes and all existing shard hashes are preserved;
- a restored bundle passes existing offline validation/replay;
- no remote/cloud dependency is introduced into deterministic reads;
- no raw provider CAS is uploaded;
- ordinary CI stays offline;
- old store/manifests remain backward compatible.

## 9. Later M5 work — not current blockers

### M5-B — S3-compatible / Cloudflare R2 backend

After M5-A freezes the contract, add one real S3-compatible backend usable with
Cloudflare R2, MinIO or S3-style object storage.

That package should add:

- explicit network allow;
- endpoint/bucket configuration without credentials in manifests;
- environment/keyring/injected credential references using existing secret
  discipline;
- private-bucket defaults;
- exact-byte upload/download verification;
- no implicit fallback from deterministic analysis.

A small owner-authorized private R2/MinIO smoke run may then prove real mirror
and restore behavior.

### M5-C — Broader artifact classes and policy-aware remote mirroring

Only when needed, extend explicit mirroring to research sidecars, reconciliation
reports and possibly raw acquisition CAS. Raw provider bytes require a separate
storage-policy/terms decision and must never become remotely mirrored by
default.

## 10. Closure record

M5-A is implemented at the documented boundary. The local
HistoricalArtifactStore remains authoritative; the new mirror package contains
only the canonical dataset manifest and explicitly referenced JSONL shards.
The filesystem backend is offline-only, byte-preserving, immutable/idempotent
for identical writes, and fail-closed for conflicts, missing/corrupt objects,
path escapes and symlink traversal. M5-B remains the next optional package.

## 11. Out of scope

M5-A does not implement:

- M4-D corporate-action/reference-event reconciliation;
- M4-E official-exchange lifecycle reconciliation;
- M2-D;
- market-wide historical membership;
- terminal-value policy;
- Phase 6 monitoring;
- Web UI/API productization;
- Cloudflare Worker application code;
- live trading/orders/transfers;
- remote provider-data acquisition through object storage.
