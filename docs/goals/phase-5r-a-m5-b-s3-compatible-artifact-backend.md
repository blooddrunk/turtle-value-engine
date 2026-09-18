# Phase 5R-A M5-B — S3-compatible / Cloudflare R2 Artifact Backend

Status: **CLOSED / COMPLETE**
Date: 2026-09-18
Baseline: `79a64ae` (synchronized main; M5-A complete)
Parent goal:
- `docs/goals/phase-5r-a-m5-deployment-neutral-artifact-backend.md`

## 1. Objective

Implement one real networked `ArtifactObjectStore` backend for private
S3-compatible object storage, with Cloudflare R2 as the primary operator target
and MinIO / ordinary S3-style endpoints supported by the same runtime boundary.

M5-B must reuse the frozen M5-A mirror manifest and
`ArtifactObjectStore` protocol. It is a transport/backend extension, not a new
historical-data contract and not a rewrite of `HistoricalArtifactStore`.

The local `HistoricalArtifactStore` remains authoritative for deterministic
analysis/replay. Remote storage is an explicit push / verify / pull operation
only.

## 2. Audited M5-A baseline

At `84029b4`, M5-A provides:

- `HistoricalArtifactMirrorManifest` with explicit manifest + referenced shard
  membership and content SHA-256 identities;
- the provider-neutral `ArtifactObjectStore` protocol:
  `put_if_absent`, `get`, `stat`;
- an offline `FilesystemArtifactObjectStore` reference backend;
- explicit build / push / verify / pull functions;
- additive `tve artifacts mirror plan|push|verify|pull` commands;
- byte-preserving restore through the existing
  `HistoricalDatasetManifest + HistoricalArtifactStore` validator;
- fail-closed path, corruption, missing-object and conflicting-content behavior.

Recorded final verification for M5-A is `python3 -m ruff check .` PASS and
`python3 -m pytest` at 6265 passed / 2 skipped. GitHub has no attached CI
status for that commit, so M5-B must run a fresh full baseline before editing.

## 3. Frozen boundaries

M5-B must preserve all of the following:

1. Do not change `strict-v1`, CDC, Net Cash, Through Return, hard gates,
   valuation, PIT semantics, A6 semantics or deterministic investment math.
2. Do not change M5-A mirror-manifest membership or content identity merely to
   support one cloud vendor.
3. Do not add network fallback to `HistoricalArtifactStore`, dataset
   validation, analysis, backtest, reconciliation or calibration.
4. Ordinary CI stays offline and must not require cloud credentials.
5. Credentials or signed URLs must never enter mirror manifests, object keys,
   result JSON, logs, Git or command-line secret values.
6. `RawBlobStore` provider bytes are not mirrored in M5-B.
7. M4-D / M4-E remain optional claim-specific extensions.
8. M2-D remains gated and `H_PRICE_SOURCE_SELECTED_FUTU` remains unchanged.
9. M6 Agent/API/Web and Phase 6 monitoring remain separate later packages.

## 4. M5-B implementation scope

### 4.1 S3-compatible object-store adapter

Add a small `S3CompatibleArtifactObjectStore` (exact name may vary) that
implements the existing M5-A `ArtifactObjectStore` protocol.

The adapter must be scoped at construction time to:

- one explicit S3-compatible endpoint;
- one bucket;
- one optional deterministic key prefix;
- one region (Cloudflare R2 uses `auto`);
- resolved credentials supplied through the existing credential discipline;
- an injected S3 client in tests.

Do not add list, delete, bucket-create or arbitrary discovery APIs to the
M5-A protocol. Mirror operations know every required object key already.

Use an optional S3 dependency/runtime adapter (for example boto3) rather than
adding a cloud SDK to the project's core dependencies. Import it lazily so the
base package and ordinary offline tests remain usable without the S3 extra.

### 4.2 Runtime configuration and secret discipline

Backend configuration is runtime/deployment configuration and must stay
separate from `HistoricalArtifactMirrorManifest`.

If a typed configuration file is added, it may contain only non-secret fields
and credential references, for example:

- backend kind = S3-compatible;
- endpoint URL;
- bucket;
- region;
- key prefix;
- addressing style if required for compatibility;
- access-key credential reference;
- secret-key credential reference;
- optional session-token credential reference.

Reuse `CredentialReferenceV1` / `CredentialResolver` semantics where
practical. CLI use must not accept raw access keys or secrets as flags.

Remote non-loopback endpoints must use HTTPS. A loopback/local MinIO test
endpoint may use HTTP only when explicitly configured for that local test
boundary.

### 4.3 Exact-byte integrity and immutable put-if-absent

Preserve M5-A immutability semantics on an object store that normally permits
overwrites.

For `put_if_absent(key, content)`:

1. validate the relative object key and runtime prefix;
2. if an object already exists, verify exact declared bytes/hash:
   - identical content => idempotent success;
   - different content => `ArtifactObjectConflictError`;
3. for a missing object, use an atomic/conditional create when supported
   (`If-None-Match: *` for S3-compatible PutObject);
4. if a concurrent writer wins the conditional create, read/verify the winner:
   identical => idempotent success; different => conflict;
5. never perform an unconditional overwrite as the normal implementation of
   `put_if_absent`.

Persist a non-secret SHA-256 metadata field such as `tve-sha256` when the
backend supports user metadata. `stat()` may expose that value as
`content_sha256`.

Do **not** treat S3/R2 ETag as the M5 SHA-256 identity. ETag is transport/object
metadata and is not a reliable full-object SHA-256 contract. Final mirror
verification must still use the M5-A declared SHA-256 and exact downloaded
bytes.

### 4.4 Error normalization

Normalize remote failures into bounded repository errors without leaking secret
material.

At minimum distinguish:

- object not found -> `ArtifactObjectMissingError`;
- immutable-key content conflict -> `ArtifactObjectConflictError`;
- invalid endpoint/key/prefix/security configuration ->
  `ArtifactObjectSecurityError` or a dedicated mirror configuration error;
- credential unavailable before network -> existing credential-unavailable
  semantics;
- remote auth/permission/transport failures -> a dedicated sanitized remote
  mirror error, not "missing object".

Do not include resolved credentials, signed request headers or secret query
parameters in exception text.

### 4.5 Explicit CLI backend selection

Extend the existing additive mirror CLI without breaking M5-A filesystem
syntax.

A suitable shape is:

```text
tve artifacts mirror push   ... --backend s3 --remote-config <config.json> --network=allow
tve artifacts mirror verify ... --backend s3 --remote-config <config.json> --network=allow
tve artifacts mirror pull   ... --backend s3 --remote-config <config.json> --network=allow
```

Exact flags may differ, but the following semantics are required:

- filesystem remains the default/backward-compatible offline backend;
- S3-compatible access is denied unless the command explicitly opts into
  network access;
- network denial and missing credentials fail before the remote client is used;
- `plan` remains backend-neutral and offline;
- remote backend selection does not alter the mirror manifest;
- pull still restores into a verified local `HistoricalArtifactStore`.

## 5. Deterministic test matrix

Ordinary tests must use an injected/fake S3 client and no real network.

At minimum prove:

1. M5-A filesystem mirror tests remain unchanged and green;
2. remote backend uses the same `ArtifactObjectStore` protocol;
3. endpoint/bucket/prefix configuration is validated;
4. remote access is blocked without explicit network allow before client use;
5. missing credential references fail before client use;
6. resolved secret values never appear in returned metadata/errors;
7. object keys map deterministically under the configured prefix;
8. existing identical object is idempotent;
9. existing different object fails closed;
10. missing-object conditional PutObject uses immutable create semantics;
11. simulated 412/precondition race re-reads the winner and accepts only
    identical bytes;
12. remote `stat` returns content length and trustworthy explicit SHA metadata
    when present;
13. ETag is never accepted as the historical artifact SHA-256 identity;
14. missing object maps to `ArtifactObjectMissingError`;
15. permission/auth failure is not misclassified as missing;
16. push -> verify -> pull through the fake S3 backend reproduces the exact
    M5-A dataset and shard hashes;
17. no list/delete operation is required for deterministic mirror workflows;
18. full existing Phase 5R/M4/M5-A test suite remains green.

## 6. Preferred file scope

Keep the implementation approximately within:

```text
pyproject.toml                                  # optional S3 extra only
src/turtle_value_engine/historical/mirror.py   # shared errors/helpers only if needed
src/turtle_value_engine/historical/s3_store.py # preferred remote adapter
src/turtle_value_engine/historical/acquisition.py # reuse credential types; avoid broad refactor
src/turtle_value_engine/historical/__init__.py
src/turtle_value_engine/__init__.py
src/turtle_value_engine/cli.py
tests/test_historical_artifact_s3_mirror.py
tests/test_historical_artifact_mirror.py        # only additive compatibility assertions if needed
docs/architecture/production-historical-data-and-research-archive.md
docs/operations/phase-5r-a-acquisition.md
docs/status/phase-5r-a-2026-09-18.md or dated successor
docs/status/phase-5r-a-next-codex-goal.md
```

Do not refactor source adapters, deterministic investment calculations or M4
reconciliation merely to add the object-store backend.

## 7. Verification

Before editing, run the current full baseline. After implementation run at
minimum:

```bash
python -m ruff check .
python -m pytest tests/test_historical_artifact_mirror.py -q
python -m pytest tests/test_historical_artifact_s3_mirror.py -q
python -m pytest tests/test_m4_reconciliation.py -q
python -m pytest
```

If the environment exposes only `python3`, the equivalent `python3 -m ...`
commands are acceptable; record the exact commands/results.

## 8. Owner-authorized live smoke — optional, not a completion blocker

M5-B code/contract completion does not require the owner to paste credentials
into chat or Codex.

After deterministic tests are green, an owner may separately authorize a small
private Cloudflare R2 / MinIO / S3 smoke run using credentials already present
in the runtime environment. The smoke should:

1. build/use one existing compact/private mirror manifest;
2. push to a dedicated private test prefix;
3. verify every declared object;
4. pull into a fresh local target;
5. validate/replay the restored dataset;
6. record only non-secret endpoint class/bucket or redacted identifier,
   mirror_id, object count, hashes and PASS/FAIL.

Absence of live credentials or a cloud account is not an M5-B implementation
failure and must not be mislabeled as a code blocker.

## 9. Acceptance

M5-B is complete when:

- one real S3-compatible backend implements the frozen M5-A
  `ArtifactObjectStore` boundary;
- filesystem behavior remains backward compatible;
- remote use requires explicit network opt-in and secret references;
- immutable/idempotent writes cannot silently overwrite different content;
- exact bytes are verified against the M5-A SHA-256 identities;
- ETag is not substituted for content SHA-256;
- push / verify / pull can run against the remote adapter and restore to the
  same valid local dataset through deterministic fake-client tests;
- ordinary CI remains offline and credential-free;
- no `RawBlobStore`, M4-D/M4-E, M2-D, M6 or investment-math scope is pulled
  into the implementation.

After M5-B closes, M5-C remains optional policy/artifact-class expansion. The
repository can then explicitly choose between proceeding to M6 Agent/API/Web
surface work or adding M5-C only when a concrete research artifact requires
remote mirroring.

## 10. Closure record — 2026-09-18

M5-B is implemented at the documented boundary. The new
`S3CompatibleArtifactObjectStore` is an optional/lazy boto3-backed adapter with
injected-client support for offline tests. It validates endpoint/bucket/prefix
configuration, uses the existing credential-reference/resolver discipline,
requires explicit network allow before client use, and supports HTTPS R2/S3
endpoints plus explicitly configured loopback HTTP test endpoints.

The adapter preserves M5-A immutable `put_if_absent` behavior with
`If-None-Match: *`, 409/412 conditional-race winner verification, exact-byte
comparison, and sanitized missing/permission/transport/config errors. It
stores/reads explicit `tve-sha256` metadata when available, never treats ETag
as SHA-256, and leaves mirror manifests unchanged. CLI `push|verify|pull`
accept `--backend s3 --remote-config ... --network=allow`; filesystem syntax
and `plan` remain backward-compatible and offline. Pull still restores through
the existing local `HistoricalArtifactStore` validation path.

The ordinary test suite uses only an injected fake S3 client and no credentials
or network. No live R2/MinIO smoke was run; absent owner-authorized cloud
credentials is not a blocker.
