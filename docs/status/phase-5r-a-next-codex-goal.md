# Codex Goal — Phase 5R-A M5-A Deployment-neutral Artifact Mirror

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

## Current audited state — 2026-09-18

Read and follow `AGENTS.md` and its source-of-truth order before editing. Read at least:

- `docs/goals/phase-5r-a-m5-deployment-neutral-artifact-backend.md`
- `docs/goals/phase-5r-a-m4-cross-source-reconciliation.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/architecture/production-historical-data-and-research-archive.md`
- `docs/status/phase-5r-a-2026-09-18.md`

M4-A/B/C are implemented. M4-C has:

- artifact-backed two-source reconciliation;
- persisted sample/provider/upstream guards;
- additive `tve dataset reconcile-artifacts`;
- owner-authorized `SH600000` BaoStock/Hithink price evidence with 2/2 comparisons PASS;
- deterministic replay with the same report hash.

The price report is PASS, while overall M4 is closed as
`M4_FIXED_A_RECONCILIATION_PARTIAL` because M4-D corporate-action and M4-E lifecycle
cross-checks were deliberately deferred as optional extensions. Do not reopen them in this goal.

There is one verification debt from the M4-C commit: focused tests were recorded, but there is
no recorded post-change full `python -m pytest` result and GitHub has no attached CI status.

## Preflight — mandatory before M5 edits

Run:

```bash
python -m ruff check .
python -m pytest
```

If the full suite is not green, fix the M4-C regression first and record the exact result. Do not
start M5 implementation on a red baseline.

## Objective

Implement only **M5-A** from
`docs/goals/phase-5r-a-m5-deployment-neutral-artifact-backend.md`:

> Add a backend-neutral, explicit, byte-preserving mirror / verify / restore boundary for a
> frozen `HistoricalDatasetManifest` package, with a filesystem reference backend, while
> keeping the existing local `HistoricalArtifactStore` authoritative and all deterministic
> analysis/replay offline.

This is a mirror layer, not a cloud-storage rewrite.

## Required implementation

### 1. Backend-neutral immutable object protocol

Add a small provider-neutral protocol/interface for artifact transport. It should support the
minimum operations needed to:

- put exact bytes at a deterministic explicit key if absent;
- get exact bytes by key;
- inspect/verify object size/hash metadata where available;
- fail closed on conflicting content.

Do not couple the protocol to Cloudflare, boto3, AWS or one vendor.

### 2. Typed deterministic mirror manifest

Add a versioned mirror manifest contract/schema such as
`historical_artifact_mirror_manifest_v1`.

At minimum retain:

- source dataset/manifest identity;
- deterministic object key / relative path;
- artifact role/type;
- SHA-256;
- byte length;
- mirror-manifest content SHA-256.

Build the inventory only from the explicitly supplied `HistoricalDatasetManifest` and its
referenced shards. Do **not** recursively upload everything under the source store root.

For M5-A, the package only needs:

- canonical serialized dataset manifest;
- all shards referenced by that manifest.

Do not include `RawBlobStore` provider data in M5-A.

### 3. Filesystem reference backend

Implement an offline filesystem backend that exercises the exact same object protocol.

It must:

- reject absolute/path-escape keys;
- reject symlink traversal;
- preserve exact bytes;
- allow idempotent same-byte writes;
- reject conflicting destination bytes;
- fail on missing/corrupt objects.

### 4. Explicit mirror workflow

Provide library functions for:

1. build/freeze mirror manifest;
2. push only declared objects;
3. verify destination;
4. pull/restore only declared objects;
5. validate the restored dataset through the existing
   `HistoricalDatasetManifest` + `HistoricalArtifactStore` boundary.

The restored dataset must retain the same shard hashes and deterministic validation/replay
semantics.

A thin additive CLI is encouraged if it stays small and future-compatible, for example:

```text
tve artifacts mirror plan
tve artifacts mirror push
tve artifacts mirror verify
tve artifacts mirror pull
```

For M5-A, support only the real filesystem backend. Do not add placeholder R2/S3 flags.

## Preferred file scope

Keep the change approximately within:

```text
src/turtle_value_engine/historical/store.py
src/turtle_value_engine/historical/mirror.py
src/turtle_value_engine/historical/contracts.py
src/turtle_value_engine/historical/__init__.py
src/turtle_value_engine/__init__.py
src/turtle_value_engine/cli.py
schemas/historical-artifact-mirror-manifest.schema.json
tests/test_historical_artifact_mirror.py
docs/architecture/production-historical-data-and-research-archive.md
docs/operations/phase-5r-a-acquisition.md   # only if CLI exists
docs/status/phase-5r-a-2026-09-18.md or a dated successor
docs/status/phase-5r-a-next-codex-goal.md
```

Do not refactor provider adapters or investment calculation code.

## Deterministic tests

At minimum prove:

1. mirror manifest is built from one explicit frozen dataset;
2. inventory includes the manifest + exactly referenced shards, not unrelated store files;
3. push preserves exact SHA-256 bytes;
4. repeat push is idempotent;
5. conflicting destination bytes fail closed;
6. missing destination object fails verification;
7. corrupt destination object fails verification;
8. absolute/path traversal/symlink paths fail closed;
9. restore verifies all objects before accepting the local bundle;
10. restored shard hashes equal source shard hashes;
11. restored dataset validates/replays through existing offline boundaries;
12. tampered mirror manifest fails validation;
13. filesystem mirror uses no network;
14. M4 reconciliation and all previous Phase 5R tests remain compatible.

## Verification

After implementation run at minimum:

```bash
python -m ruff check .
python -m pytest tests/test_historical_artifact_mirror.py -q
python -m pytest tests/test_m4_reconciliation.py -q
python -m pytest
```

Record the full-suite result in the status document.

## Explicitly not current work

Do not implement:

- M5-B S3 / Cloudflare R2 backend;
- remote credentials or live object-store smoke tests;
- raw `RawBlobStore` mirroring;
- M4-D;
- M4-E;
- M2-D;
- Phase 6 monitoring;
- Web UI/API/Worker productization;
- any change to `strict-v1`, PIT/A6 semantics or deterministic investment math.

Keep `H_PRICE_SOURCE_SELECTED_FUTU` unchanged.

## Acceptance

M5-A is complete when a declared frozen historical dataset can be mirrored to a second
filesystem backend and restored byte-for-byte through the backend-neutral contract, with the
same shard identities and successful existing offline validation/replay; ordinary CI remains
offline; no unreferenced/raw provider artifacts are mirrored; and the current local
`HistoricalArtifactStore` remains backward compatible.

After M5-A is green, the next optional implementation package is M5-B: one real
S3-compatible backend for private Cloudflare R2 / MinIO / S3-style storage, using the frozen
M5-A protocol and explicit network/credential boundaries.
