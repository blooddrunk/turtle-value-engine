# Codex Goal — Phase 5R-A M5-B S3-compatible Artifact Backend

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

Status: **CLOSED / M5-B COMPLETE; M5-A COMPLETE; A6 PENDING**

## Current audited state — 2026-09-18

Read and follow `AGENTS.md` and its source-of-truth order before editing. Read at least:

- `docs/goals/phase-5r-a-m5-b-s3-compatible-artifact-backend.md`
- `docs/goals/phase-5r-a-m5-deployment-neutral-artifact-backend.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/architecture/production-historical-data-and-research-archive.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `docs/status/phase-5r-a-2026-09-18.md`

M5-A is complete on main at `84029b4`. It freezes:

- the backend-neutral `ArtifactObjectStore` protocol;
- `HistoricalArtifactMirrorManifest`;
- exact manifest + referenced-shard inventory;
- offline `FilesystemArtifactObjectStore`;
- explicit build / push / verify / pull;
- restored validation through the existing local historical store;
- fail-closed corruption/conflict/path behavior.

Recorded M5-A verification: `python3 -m ruff check .` PASS; focused mirror tests
10 passed; M4 tests 19 passed; full suite 6265 passed / 2 skipped. GitHub has no
attached CI status for `84029b4`, so run a fresh full baseline before editing.

M4-D/M4-E remain optional and are not current blockers. M2-D remains gated.
Keep `H_PRICE_SOURCE_SELECTED_FUTU` unchanged.

## Preflight

Before editing:

```bash
python -m ruff check .
python -m pytest
```

If only `python3` exists, use the equivalent `python3 -m ...` commands.
Do not build M5-B on a red baseline.

## Objective

Implement **M5-B — S3-compatible / Cloudflare R2 artifact backend** exactly as
specified in:

`docs/goals/phase-5r-a-m5-b-s3-compatible-artifact-backend.md`

Add one real S3-compatible implementation of the existing M5-A
`ArtifactObjectStore` contract. Cloudflare R2 is the primary operator target,
while the same adapter should remain usable with MinIO / ordinary S3-compatible
endpoints.

This is an optional network transport layer. The local
`HistoricalArtifactStore` remains authoritative and deterministic replay must
remain offline.

## Required implementation

1. Add a narrowly scoped `S3CompatibleArtifactObjectStore` or equivalent.
2. Reuse the frozen M5-A mirror manifest unchanged.
3. Prefer an optional/lazy S3 SDK dependency, not a mandatory core dependency.
4. Accept runtime endpoint/bucket/region/prefix configuration without secrets in
   manifests or persisted result artifacts.
5. Reuse existing credential-reference / resolver discipline where practical.
6. Require explicit network opt-in before any remote client call.
7. Preserve immutable `put_if_absent` semantics:
   - identical existing bytes => idempotent success;
   - different existing bytes => conflict;
   - missing object => conditional create when supported;
   - concurrent conditional-create race => verify winner and accept only if identical.
8. Persist/read an explicit non-secret SHA-256 object metadata field when
   available.
9. **Do not use S3/R2 ETag as the historical artifact SHA-256 identity.**
10. Normalize missing/conflict/auth/transport/config errors without leaking
    credentials.
11. Extend `tve artifacts mirror push|verify|pull` with explicit remote-backend
    selection while preserving the current filesystem syntax and offline
    default.
12. Keep `plan` backend-neutral/offline and pull results restored into a local
    verified `HistoricalArtifactStore`.

## Deterministic tests

Use injected/fake S3 clients in ordinary CI; no real network or cloud credentials.

At minimum cover all cases in the M5-B goal, especially:

- network denied before client use;
- credential missing before client use;
- secret redaction;
- deterministic prefix/key mapping;
- identical/different existing objects;
- conditional-write race;
- missing vs permission failure;
- SHA metadata handling;
- ETag never treated as SHA-256;
- fake-S3 push -> verify -> pull exact restore;
- no list/delete requirement;
- unchanged M5-A filesystem behavior.

## Preferred scope

Keep changes close to:

```text
pyproject.toml
src/turtle_value_engine/historical/mirror.py
src/turtle_value_engine/historical/s3_store.py
src/turtle_value_engine/historical/acquisition.py
src/turtle_value_engine/historical/__init__.py
src/turtle_value_engine/__init__.py
src/turtle_value_engine/cli.py
tests/test_historical_artifact_s3_mirror.py
tests/test_historical_artifact_mirror.py
docs/architecture/production-historical-data-and-research-archive.md
docs/operations/phase-5r-a-acquisition.md
docs/status/phase-5r-a-2026-09-18.md
docs/status/phase-5r-a-next-codex-goal.md
```

Do not refactor provider adapters, M4 reconciliation or deterministic investment
math merely to add the object-store backend.

## Explicitly not current work

Do not implement:

- raw `RawBlobStore` remote mirroring;
- M5-C broader artifact classes;
- M4-D;
- M4-E;
- M2-D;
- Phase 6 watchlist/event monitoring;
- M6/Web UI/API/Worker productization;
- trading/orders/transfers;
- changes to `strict-v1`, PIT/A6 semantics or investment math.

## Verification

After implementation run at minimum:

```bash
python -m ruff check .
python -m pytest tests/test_historical_artifact_mirror.py -q
python -m pytest tests/test_historical_artifact_s3_mirror.py -q
python -m pytest tests/test_m4_reconciliation.py -q
python -m pytest
```

Record exact results in the status document.

## Live smoke

A real private R2 / MinIO / S3 smoke is optional and owner-authorized only.
Do not request or paste credentials into chat. If credentials are already
available in the execution environment, a bounded smoke may push, verify and
pull one compact/private mirror package and record only non-secret evidence.

Absence of live credentials is not an M5-B implementation blocker.

## Acceptance

M5-B is complete when the existing frozen M5-A mirror package can be pushed,
verified and pulled through one real S3-compatible backend contract while exact
bytes/SHA-256 identities, explicit network opt-in, secret discipline and
offline deterministic replay remain intact; ordinary CI remains network- and
credential-free; filesystem behavior remains backward compatible.

## Completion record — 2026-09-18

M5-B implementation is complete on top of synchronized `main` at `79a64ae`.
The optional/lazy S3-compatible backend, runtime-only non-secret configuration,
credential resolver boundary, explicit network gate, conditional immutable
writes, 409/412 race handling, sanitized error mapping, SHA-256 metadata and
ETag separation are implemented. The additive CLI supports `--backend s3`
for `push|verify|pull`; `plan`, filesystem defaults, frozen M5-A manifests and
local restore validation remain unchanged.

Exact verification from this working tree:

~~~text
python -m ruff check .: unavailable (shell has no python executable)
python -m pytest: unavailable (shell has no python executable)
python3 -m ruff check .: PASS
python3 -m pytest tests/test_historical_artifact_mirror.py -q: 10 passed
python3 -m pytest tests/test_historical_artifact_s3_mirror.py -q: 11 passed
python3 -m pytest tests/test_m4_reconciliation.py -q: 19 passed
python3 -m pytest: 6276 passed, 2 skipped
~~~

The two skips are the existing opt-in live AKShare tests. No real R2/MinIO
smoke was run because no owner-authorized cloud credential was supplied; this
is not an M5-B implementation blocker. Next work remains outside this goal:
M5-C policy/artifact-class expansion, A6 corpus evidence, or a separately
authorized later product milestone.
