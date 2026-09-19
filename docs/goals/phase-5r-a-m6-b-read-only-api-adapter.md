# Phase 5R-A M6-B — Read-only API Adapter

Status: **ACTIVE / NEXT**
Date: 2026-09-19
Audited baseline: `ad864510` (M6-A complete on `main`)

Parent context:
- `AGENTS.md`
- `docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/status/phase-5r-a-2026-09-19.md`

## 1. Objective

Add the smallest useful **read-only application/API boundary** over the frozen
M6-A `ResearchSurfaceSnapshotV1` contract.

M6-B is an adapter, not another engine. It must serve only already validated
surface snapshots and must not recalculate CDC, Net Cash, Through Return,
hard gates, valuation, Business Quality, historical replay, A6 acceptance or
any other investment semantics.

The result should be usable by Hermes/Skills, a local client, a private VPS
consumer and a later M6-C Worker/Dashboard without forcing those consumers to
understand repository-internal analysis/workspace/storage models.

## 2. Why M6-B is next

M6-A already froze the product-facing read model. The next highest-value step is
to expose that read model through a stable machine boundary before building a
UI or scheduler.

M5-C is not a prerequisite: M6-B can serve explicitly supplied local/private
surface artifacts without remotely mirroring new artifact classes.

A6 production eligibility is also not a prerequisite. If a surface says
PARTIAL, BLOCKED, NOT_AVAILABLE or NOT_EVALUATED, the API must return that state
unchanged.

## 3. Frozen boundaries

Preserve all of the following:

1. `strict-v1` and deterministic investment math are unchanged.
2. `ResearchSurfaceSnapshotV1` remains the authoritative API payload.
3. The API may validate and select snapshots; it may not rebuild investment
   state from lower-level artifacts.
4. No provider, analyst/model, broker, acquisition adapter or raw historical
   store call is permitted in a request path.
5. No recursive workspace/store discovery.
6. No silent fallback from a missing/tampered snapshot to another artifact.
7. No write/mutation endpoint for analysis, research, artifacts, orders,
   transfers or brokerage state.
8. Ordinary tests remain external-network-free and model-free.
9. M5-C, M6-C Worker/Dashboard, Phase 6 monitoring, M4-D/M4-E and M2-D remain
   outside this goal.
10. `H_PRICE_SOURCE_SELECTED_FUTU` remains unchanged.

## 4. Architecture

Keep the core registry/service independent from the HTTP framework:

```text
explicit snapshot paths / validated snapshot objects
        |
        v
SurfaceRegistry
  - load via load_research_surface_snapshot
  - index by surface_id
  - deterministic metadata/filtering
  - reject duplicate/ambiguous registrations
        |
        v
Read-only application service
        |
        v
thin ASGI/FastAPI adapter
```

Prefer a small optional `api` dependency group for FastAPI/uvicorn/httpx so the
base deterministic engine does not gain a mandatory web-server dependency.
Imports must remain lazy enough that users who never serve the API do not need
the optional stack.

## 5. Explicit snapshot loading

The first implementation must use **explicit inputs**.

Preferred CLI shape:

```bash
tve surface serve \
  --snapshot research-surface-a.json \
  --snapshot research-surface-b.json \
  --host 127.0.0.1 \
  --port 8787
```

`--snapshot` is repeatable. Do not implement recursive directory scans, raw
artifact discovery, “find latest file”, or implicit workspace roots.

Startup rules:

- require at least one snapshot;
- validate every snapshot through the M6-A loader/model;
- fail closed on a malformed content hash/schema/model;
- reject duplicate `surface_id` registrations unless the implementation can
  prove byte-identical input and still keeps one unambiguous registration;
- deterministic list ordering must not depend on filesystem enumeration order.

## 6. HTTP contract

Minimum endpoints:

### `GET /healthz`

Return a small service status including API contract/version and loaded snapshot
count. It must not claim that upstream providers, A6 or external services are
healthy.

### `GET /v1/surfaces`

Return deterministic metadata for loaded surfaces. Support only bounded,
well-defined filters useful to clients, such as:

- `primary_listing`;
- `profile_id`;
- `as_of`.

Return stable ordering, preferably `as_of` descending then `surface_id`.

Do not expose arbitrary filesystem paths.

### `GET /v1/surfaces/{surface_id}`

Return the complete validated `ResearchSurfaceSnapshotV1` payload.

Requirements:

- unknown ID -> 404 with stable machine-readable error code;
- use the snapshot hash as an ETag when practical;
- support `If-None-Match` -> 304 when implemented;
- never open a URL/path derived directly from `surface_id`;
- serialize the validated model, not raw file bytes.

FastAPI's generated `/openapi.json` may be used as the first OpenAPI contract,
but route names and response models must be explicit and test-covered.

## 7. Read-only and network safety

There must be no POST/PUT/PATCH/DELETE endpoint that changes engine/project
state. Unsupported mutation requests must return 404/405 and tests must prove
that behavior.

Server defaults:

- host: `127.0.0.1`;
- CORS: disabled unless explicitly added by a later package;
- no authentication claim in M6-B;
- no public-internet exposure claim.

If a non-loopback bind is supported, require an explicit opt-in flag such as
`--allow-non-loopback`; never silently bind `0.0.0.0`. Cloudflare Access,
OAuth/OIDC, public ingress and production secrets are a later security/deploy
package, not M6-B acceptance.

## 8. Error semantics

Define stable machine-readable errors for at least:

- surface not found;
- invalid query parameter;
- startup snapshot validation failure;
- duplicate/ambiguous registration.

Do not return Python stack traces, local absolute paths, credentials or raw
source payloads in normal HTTP responses.

## 9. Deterministic tests

At minimum add offline/model-free tests for:

1. registry loads a valid M6-A snapshot;
2. tampered snapshot fails startup;
3. duplicate/ambiguous registration fails closed;
4. registry ordering is deterministic;
5. health returns only API-local status;
6. list endpoint returns stable metadata and filters correctly;
7. get-by-id returns exactly the validated surface payload;
8. unknown ID returns stable 404;
9. mutation methods cannot change state;
10. path-traversal-like IDs cannot read arbitrary files;
11. ETag/304 behavior if implemented;
12. default bind is loopback and non-loopback requires explicit opt-in if
    supported;
13. M6-A `tests/test_research_surface.py` remains green;
14. full existing suite remains green.

## 10. Required automated verification

**Do not replace verification with prose. Do not ask the owner to manually run
checks that Codex can run itself.**

Before editing:

```bash
python3 -m ruff check .
python3 -m pytest
```

If `python3` is unavailable, detect the available interpreter and record the
exact substitute. If declared API/dev dependencies are missing, install the
repository-declared extras automatically when the environment permits it, then
rerun the baseline.

After implementation, run at minimum:

```bash
python3 -m ruff check .
python3 -m pytest tests/test_research_surface.py -q
python3 -m pytest tests/test_surface_api.py -q
python3 -m pytest
```

Also add and execute an **automated real-loopback smoke**. It must start the
actual server on `127.0.0.1` using an ephemeral/test port, then automatically:

1. wait until `/healthz` is reachable;
2. fetch one known `/v1/surfaces/{surface_id}`;
3. verify the returned `surface_id` and `content_sha256`;
4. verify one unknown ID returns 404;
5. verify one mutation request is rejected;
6. stop the server and assert clean shutdown.

Implement this as a pytest integration test or repository script invoked by
pytest; do not require the owner to open a browser or copy/paste curl commands.

Record the exact commands, exit status and pass/skip counts in the dated status
document. A green focused test without the full suite is not enough.

## 11. Manual-intervention boundary

No human/manual step is required for M6-B acceptance.

If the Codex environment itself forbids loopback socket binding, missing package
installation or process spawning, do **not** write “evidence incomplete” and
declare success. Record:

- the exact failing command;
- the exact error;
- which automated checks did run;
- which acceptance item is unverified;
- the exact manual fallback command sequence needed on the owner's machine.

In that situation, implementation may be code-complete but verification is
explicitly `BLOCKED_BY_EXECUTION_ENVIRONMENT`; do not call M6-B fully closed
until the required smoke has been executed somewhere.

External Cloudflare/VPS/browser testing is optional evidence only and is not an
M6-B completion requirement.

## 12. Preferred implementation scope

Keep changes close to:

```text
src/turtle_value_engine/surface/api.py
src/turtle_value_engine/surface/registry.py
src/turtle_value_engine/surface/__init__.py
src/turtle_value_engine/cli.py
pyproject.toml
tests/test_surface_api.py
docs/architecture/agent-api-web-surface.md
docs/goals/phase-5r-a-m6-b-read-only-api-adapter.md
docs/status/phase-5r-a-2026-09-19.md
docs/status/phase-5r-a-next-codex-goal.md
docs/roadmap.md
AGENTS.md
```

Exact module names may follow repository conventions. Avoid broad refactors of
analysis, research orchestration, acquisition, historical stores or M5 mirror
code.

## 13. Explicitly out of scope

Do not implement in M6-B:

- Cloudflare Worker/D1 application code;
- React/TanStack/UI;
- remote artifact publication/synchronization;
- M5-C raw/research-sidecar mirroring;
- authentication provider integration;
- public internet exposure;
- scheduled refresh/polling;
- Phase 6 watchlist/event monitoring;
- live provider acquisition;
- live analyst/model calls;
- M4-D/M4-E;
- M2-D;
- trading/order/transfer actions;
- changes to `strict-v1`, A6/PIT semantics or deterministic investment math.

## 14. Acceptance

M6-B is complete only when:

- explicitly supplied valid M6-A snapshots can be loaded into a deterministic
  read-only registry;
- the HTTP API serves the frozen snapshots without recomputation;
- missing/tampered/duplicate inputs fail closed;
- no mutation endpoint exists;
- default serving is loopback-first and non-loopback exposure is never implicit;
- the focused API tests, M6-A regression tests, ruff and full pytest suite pass;
- an actual loopback server smoke passes automatically;
- exact verification evidence is recorded in the repository.

Stop after M6-B closure. Do not automatically start M5-C, M6-C or Phase 6 in
the same goal.
