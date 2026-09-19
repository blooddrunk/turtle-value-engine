# Phase 5R-A M6-C1 — Personal Dashboard Foundation

Status: **ACTIVE / NEXT**
Date: 2026-09-19
Audited baseline: `dda3a0d` (M6-B complete on `main`)

Parent context:
- `AGENTS.md`
- `docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`
- `docs/goals/phase-5r-a-m6-b-read-only-api-adapter.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/status/phase-5r-a-2026-09-19.md`

## 1. Objective

Build the smallest useful **personal read-only Web Dashboard** over the frozen
M6-A/M6-B research-surface boundary.

M6-C1 is deliberately local/preview-first. It must prove the application,
contract and cross-stack integration without requiring a Cloudflare account,
browser clicks, a public hostname, a live VPS, remote artifact mirroring or
manual owner verification.

The Dashboard is a client of M6-B, not another analysis engine. It may display
and organize `ResearchSurfaceSnapshotV1` values, but it must not recalculate or
reinterpret CDC, Net Cash, Through Return, hard gates, valuation, Business
Quality, A6 acceptance, historical replay or any other investment semantics.

## 2. Why split M6-C into C1 and C2

The repository now has a validated local read model and a real read-only HTTP
adapter. The next useful step is a human-facing surface, but live Cloudflare
deployment introduces account/token/origin/authentication facts that are not
needed to prove the application itself.

Therefore:

- **M6-C1 (this goal)**: local/preview application, typed API contract, read-only
  Worker proxy, responsive UI, deterministic tests and real cross-stack smoke;
- **M6-C2 (later)**: owner-authorized Cloudflare deployment, authenticated
  ingress/origin integration, Access/OIDC/service-token decisions and any
  concrete remote artifact distribution need.

Do not let M6-C2 cloud setup become an excuse for incomplete M6-C1 automated
verification.

M5-C remains optional. It is opened only if M6-C2 selects a design that needs
surface artifacts mirrored to R2/S3 instead of consuming the M6-B API.

## 3. Frozen boundaries

Preserve all of the following:

1. `strict-v1` and deterministic investment math are unchanged.
2. `ResearchSurfaceSnapshotV1` remains the authoritative detail payload.
3. M6-B remains the only application/API boundary over loaded snapshots.
4. The Web app must not read repository files, raw CAS, historical stores,
   provider payloads or research workspaces directly.
5. No provider, broker, acquisition adapter, analyst/model or scheduler call is
   permitted from a page request.
6. No write/mutation endpoint for research, analysis, artifacts, orders,
   transfers, brokerage state or rule profiles.
7. Partial, blocked, unavailable and not-evaluated states must remain visibly
   partial/blocked/unavailable/not-evaluated.
8. Ordinary Python tests remain external-network-free and model-free.
9. M5-C, M6-C2 live deployment/authentication, Phase 6 monitoring, M4-D/M4-E
   and M2-D remain outside this goal.
10. `H_PRICE_SOURCE_SELECTED_FUTU`, A6/PIT semantics and existing source
    selection remain unchanged.

## 4. Preferred application shape

Use a small application under:

```text
apps/dashboard/
```

Preferred stack:

- React 19 + TypeScript;
- Vite;
- the official Cloudflare Vite plugin / Workers Static Assets path;
- TanStack Router for explicit list/detail routes;
- TanStack Query for read-only server-state fetching/caching;
- pnpm with a committed lockfile.

Do not convert the whole Python repository into a JavaScript monorepo merely to
host one app. Keep Dashboard tooling scoped to `apps/dashboard` unless a tiny
root-level helper is materially useful.

The intended flow is:

```text
explicit frozen ResearchSurfaceSnapshotV1 files
        |
        v
tve surface serve (M6-B)
        |
        v
M6-C1 Worker allowlist proxy (/api/*, GET/HEAD only)
        |
        v
typed API client
        |
        v
React read-only Dashboard
```

The browser must use same-origin `/api/*` requests. Do not require CORS changes
to M6-B merely for local development.

## 5. Worker proxy boundary

The Worker portion is a narrow transport adapter, not a general reverse proxy.

It may forward only the M6-B read contract:

- `GET /api/healthz`;
- `GET /api/v1/surfaces` with the supported bounded query parameters;
- `GET /api/v1/surfaces/{surface_id}`;
- `HEAD` only where the underlying read endpoint can safely support it.

Requirements:

- upstream origin comes from server-side environment/configuration, never from a
  browser-supplied URL;
- do not implement an arbitrary path/URL proxy;
- reject POST/PUT/PATCH/DELETE at the Worker boundary;
- preserve M6-B status codes and ETag/If-None-Match behavior where applicable;
- do not expose Cloudflare tokens, service credentials or origin secrets to the
  browser bundle;
- local preview may use an explicit loopback M6-B origin;
- public ingress, Access/OIDC and service-token policy belong to M6-C2.

## 6. Typed contract: generate, do not hand-copy

M6-C1 must not manually maintain a second TypeScript interpretation of the API.

Add a deterministic export/check path for the M6-B OpenAPI document and generate
the Dashboard client types from that checked-in contract. A preferred shape is:

```text
schemas/research-surface-api-v1.openapi.json
apps/dashboard/src/generated/surface-api.d.ts
```

Exact filenames may follow repository conventions.

Requirements:

- OpenAPI export is produced from the real `create_surface_app(...)` route and
  response models using an explicit fixture/in-memory registry;
- generation performs no external network access;
- generated files are deterministic;
- CI/test commands can regenerate to a temporary location and fail on drift;
- generated TypeScript is not manually edited;
- the existing `schemas/research-surface-snapshot.schema.json` remains the
  canonical persisted snapshot schema.

## 7. Minimum UI

### Overview / surfaces list

Show:

- API-local health and loaded-snapshot count;
- deterministic surface metadata from `GET /v1/surfaces`;
- listing, as-of date, profile and compact identity/hash;
- bounded filters for listing/profile/as-of;
- explicit empty/error states.

Do not fetch every detail snapshot merely to decorate the list with values that
are not in the metadata endpoint.

### Surface detail

Render the frozen surface without recomputation, including at minimum:

- company/listing, `analysis_id`, `surface_id`, `as_of`, profile and content
  hash;
- deterministic decision and valuation state;
- key CDC, Net Cash and Through Return values exactly as provided;
- all six hard-gate statuses and blocking reasons;
- data-quality state and flags;
- Business Quality status, including `NOT_EVALUATED`;
- historical availability/claim state, acceptance/readiness/validation state,
  blockers, warnings and limitations;
- source-artifact identities/hashes without local filesystem paths or raw
  provider content.

Display unavailable values as unavailable. Do not convert `null`, `PARTIAL`,
`BLOCKED`, `NOT_AVAILABLE` or `NOT_EVALUATED` into zero, PASS or a green
visual state.

### Interaction constraints

The first version is read-only. Filtering, routing, copying an ID/hash and a
GET-only refresh are acceptable. Editing rules, triggering acquisition,
starting analysis, approving proposals, trading or changing remote state is not.

## 8. Accessibility and responsive baseline

The Dashboard must be usable on desktop and mobile widths.

At minimum:

- semantic headings/landmarks;
- keyboard-accessible links/buttons;
- visible focus states;
- labels for filters;
- no status communicated by color alone;
- no horizontal overflow for the primary detail view at a narrow mobile width.

Do not spend M6-C1 on a large design-system migration. A small consistent visual
system is enough.

## 9. Required automated verification

**Automate every check Codex can automate. Do not delegate routine verification
to the owner.**

### Before editing

Run:

```bash
python3 -m ruff check .
python3 -m pytest
node --version
pnpm --version
```

If `pnpm` is unavailable but Corepack is available, bootstrap the
repository-declared pnpm version automatically. If dependencies need to be
downloaded and the execution environment permits it, install them automatically.

Record exact commands, exit codes and test counts.

### After implementation

Run at minimum:

```bash
python3 -m ruff check .
python3 -m pytest tests/test_research_surface.py -q
python3 -m pytest tests/test_surface_api.py -q
python3 -m pytest

pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build

python3 scripts/export_surface_openapi.py --check
```

If the exact OpenAPI script path differs, document and run the equivalent
deterministic check.

### Required real cross-stack smoke

Add an automated repository test/script that:

1. creates or copies one valid frozen surface fixture without network/model use;
2. starts the actual M6-B `tve surface serve` process on loopback;
3. starts the built/local Cloudflare/Vite preview on loopback with the M6-B
   origin supplied explicitly;
4. waits for both processes to become reachable;
5. fetches the Dashboard root and asserts a successful HTML response;
6. fetches Dashboard same-origin `/api/healthz`;
7. lists surfaces through `/api/v1/surfaces`;
8. fetches one known detail through the Worker proxy and verifies
   `surface_id` + `content_sha256`;
9. verifies an unknown ID remains 404;
10. verifies a mutation request is rejected at the Worker boundary;
11. shuts down both processes and asserts clean exit.

This is a black-box transport/application smoke. Do not replace it with only
mocked fetch tests.

### UI behavior tests

Use deterministic component tests (for example Vitest + a DOM test environment)
to prove at least:

- list loading/empty/error states;
- filters produce only the supported query parameters;
- detail rendering shows provided decision/metrics without recomputation;
- `PARTIAL`, `BLOCKED`, `NOT_AVAILABLE` and `NOT_EVALUATED` are visible
  and are not presented as PASS/available;
- mutation controls do not exist.

A real browser screenshot test may be added, but it is not required for C1 if
the DOM tests and real HTTP preview smoke are green.

## 10. Verification evidence rules

After implementation, update the dated status record with:

- baseline commands/results;
- Node/pnpm versions actually used;
- dependency install command/result;
- Python focused/full test counts;
- Dashboard lint/typecheck/test/build results;
- OpenAPI drift-check result;
- the exact cross-stack smoke command and result;
- any skips, with the exact reason.

A phrase such as "tests look good", "manual verification recommended" or
"evidence not fully recorded" is not acceptance evidence.

Do not mark M6-C1 complete if a required automated gate was never executed.

## 11. Manual-intervention boundary

**No human/cloud step is required for M6-C1 acceptance.**

Do not ask the owner to:

- log into Cloudflare;
- create a Worker manually;
- click through a deployment wizard;
- provide a public domain;
- create D1/R2;
- set up Access/OIDC;
- open a browser to confirm basic behavior;
- run commands that the Codex environment itself can run.

If the Codex execution environment genuinely blocks package installation,
process spawning, loopback networking or the local Workers runtime, record:

1. the exact failing command;
2. the exact error;
3. which automated gates succeeded;
4. which specific acceptance item remains unverified;
5. the exact fallback command sequence for the owner's machine.

In that case use the explicit state
`BLOCKED_BY_EXECUTION_ENVIRONMENT`; do not close M6-C1 and do not downgrade the
missing automated check to a vague documentation note.

## 12. M6-C2 boundary after C1

M6-C2 is opened only after M6-C1 is fully automated and green.

It may then decide and implement, as a separate package:

- live Cloudflare Workers deployment;
- authenticated ingress (for example Cloudflare Access or another explicit
  owner-controlled mechanism);
- secure connectivity from the Worker to a non-loopback M6-B origin;
- secrets/service-token handling;
- custom domain/preview policy;
- whether a concrete surface-artifact distribution need now justifies M5-C/R2.

M6-C2 must never expose an unauthenticated mutable engine or silently turn
M6-B's local-first server into a public service.

## 13. Preferred implementation scope

Keep changes near:

```text
apps/dashboard/**
schemas/research-surface-api-v1.openapi.json
scripts/export_surface_openapi.py
tests/ or scripts/ for the cross-stack smoke
docs/architecture/agent-api-web-surface.md
docs/goals/phase-5r-a-m6-c1-personal-dashboard-foundation.md
docs/status/phase-5r-a-2026-09-19.md or a dated successor
docs/status/phase-5r-a-next-codex-goal.md
docs/roadmap.md only if milestone status genuinely changes
```

Small additive Python changes required solely to export deterministic OpenAPI are
allowed. Do not refactor analysis, acquisition, historical storage or investment
math for Dashboard convenience.

## 14. Explicitly out of scope

Do not implement in M6-C1:

- live Cloudflare deployment;
- Cloudflare Access/OAuth/OIDC setup;
- D1/R2 persistence;
- M5-C artifact-class expansion;
- direct browser access to raw provider/CAS files;
- live acquisition or provider calls;
- analyst/model calls;
- scheduled refresh or Phase 6 event monitoring;
- write/mutation actions;
- trading/order/transfer actions;
- M4-D/M4-E;
- M2-D;
- changes to `strict-v1`, source-selection, A6/PIT or deterministic investment
  semantics.

## 15. Acceptance

M6-C1 is complete only when:

- a typed React/Vite Dashboard consumes M6-B through a bounded same-origin
  read-only Worker proxy;
- API types are generated from a deterministic checked-in OpenAPI contract;
- list and detail views preserve the frozen surface semantics, including
  negative/partial/unavailable states;
- there is no mutation UI or arbitrary reverse-proxy path;
- Python regressions remain green;
- Dashboard lint, typecheck, unit/DOM tests and production build pass;
- deterministic OpenAPI drift checking passes;
- the actual Python API + local Workers/Vite preview cross-stack smoke passes
  automatically;
- exact verification evidence is recorded in the repository.

Stop after M6-C1 closure. Do not automatically start M6-C2, M5-C or Phase 6 in
the same goal.
