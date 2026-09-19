# Agent/API/Web Read-only Surface

Status: **M6-A frozen / M6-B complete / M6-C1 local preview complete**

## Purpose

ResearchSurfaceSnapshotV1 is the first stable read model for Hermes, Skills,
future read-only APIs and a personal dashboard. It is a derived artifact, not
another analysis engine. The deterministic engine remains the sole owner of
CDC, Net Cash, Through Return, hard gates, valuation and the final decision.

The surface is built from explicit, already validated artifacts:

    CompanyAnalysis
      + optional matching DecisionTrace / ResearchReport
      + optional HistoricalDatasetManifest / acceptance / readiness / validation
      -> ResearchSurfaceSnapshotV1

No workspace or store root is scanned. The builder receives objects or explicit
JSON mappings and validates them against the existing contracts before
projecting them.

## Contract and identity

The persisted contract is research_surface_snapshot_v1 with schema version
1.0.0, defined by schemas/research-surface-snapshot.schema.json.
surface_id and content_sha256 are the same SHA-256 identity. The hash is
calculated over canonical JSON for the complete snapshot with those two fields
excluded, then validated when the artifact is loaded.

Source artifact references contain only artifact type, stable artifact ID,
content hash and the analysis as_of boundary. Analysis, trace and report
references use hashes of their validated canonical models; historical
manifests and reports retain their existing content/report hashes. Therefore a
source identity or projected value change changes the surface identity.

There is no generated-at timestamp in the surface. Operational freshness is
copied only when it already exists in an explicit historical readiness or
source descriptor artifact.

## Projection rules

The analysis view uses explicit allowlists for metric fields. In particular,
extra fields permitted by the internal CDC model are not copied. Company
identity, deterministic metrics, gate statuses/reasons, valuation, decision
state, data quality and validated Business Quality are represented as typed
fields.

Business Quality is NOT_EVALUATED when the source has no validated result or
its Business Quality gate is NOT_EVALUATED; the surface never supplies a
score. Historical status is NOT_AVAILABLE when no historical artifact is
provided. A supplied blocked or partial artifact remains blocked or partial,
with exact blockers, warnings and manifest limitations visible.

Trace/report references must match the analysis identity and point-in-time
boundary. Historical artifact dataset identities must agree, and historical
coverage/readiness must not extend beyond the analysis as_of. Conflicts fail
closed.

The projection deliberately excludes credentials, resolved secret values,
signed URLs, raw provider response bodies, filing/source bytes and provider
request metadata. It keeps IDs and hashes needed to audit the source without
publishing source contents.

## Offline interface

The reusable Python boundary is:

    from turtle_value_engine.surface import build_research_surface_snapshot

    snapshot = build_research_surface_snapshot(
        analysis,
        decision_trace=trace,
        research_report=report,
    )

The additive CLI is local and offline:

    tve surface build --analysis analysis.json [--trace trace.json]
      [--report report.json] [--historical-manifest manifest.json]
      [--acceptance acceptance.json] [--readiness readiness.json]
      [--validation validation.json] --output research-surface.json

    tve surface validate --input research-surface.json

This milestone does not serve HTTP, publish artifacts remotely, add auth,
create Worker/D1/UI code, schedule refreshes or monitor watchlists. Those are
separate follow-on packages.


## M6-B API adapter — complete

M6-B consumes only already validated `ResearchSurfaceSnapshotV1` artifacts.
The intended boundary is:

```text
explicit snapshot paths / in-memory validated snapshots
  -> SurfaceRegistry
  -> framework-neutral read service
  -> thin ASGI/FastAPI adapter
  -> local/private read-only clients
```

The registry must not recursively scan a workspace, raw CAS, historical store or
research workspace. Startup validates every configured snapshot and fails closed
on malformed identities or duplicate/ambiguous registrations.

The initial HTTP surface is deliberately small:

- `GET /healthz`;
- `GET /v1/surfaces` for deterministic metadata/filtering;
- `GET /v1/surfaces/{surface_id}` for the complete frozen snapshot;
- generated OpenAPI for the same read-only contract.

No POST/PUT/PATCH/DELETE endpoint may mutate repository or investment state.
The server defaults to `127.0.0.1`; CORS is disabled by default. Public
internet exposure, identity-provider integration and Cloudflare Access belong to
a later deployment/security package. A non-loopback bind, if supported at all,
must require an explicit opt-in flag and must never be the default.

The implemented framework-neutral boundary is `SurfaceRegistry` plus
`SurfaceReadService`. `SurfaceRegistry.from_paths(...)` accepts only the
explicit paths supplied by the caller, validates each snapshot through the
M6-A loader, rejects empty or duplicate registrations, and keeps only detached
validated models in memory. List results are ordered by `as_of` descending and
then `surface_id`; supported filters are `primary_listing`, `profile_id` and
`as_of`.

The optional `api` extra provides FastAPI, uvicorn and httpx. The adapter is
lazy: importing the deterministic package does not require the extra. The
entry point is:

```bash
tve surface serve \
  --snapshot research-surface.json \
  --host 127.0.0.1 \
  --port 8787
```

Unknown surfaces, invalid filters, malformed startup inputs and duplicate
registrations have stable machine-readable error codes. A snapshot response
uses its validated `content_sha256` as an ETag and supports `If-None-Match`.
There are no write routes; unsupported mutation methods remain 405 responses.

M6-B acceptance must be automated: focused API tests, M6-A regression tests,
full pytest/ruff, and one real loopback socket smoke test that starts the server,
fetches health + a known surface, verifies a missing ID and a mutation rejection,
then shuts the server down. External cloud accounts, browsers and manual clicks
are not M6-B acceptance prerequisites. The dated verification record is in
`docs/status/phase-5r-a-2026-09-19.md`.

## M6-C1 Dashboard — local/preview complete

M6-C1 adds a human-facing read-only client without changing the M6-A or M6-B
contracts:

```text
M6-B /healthz, /v1/surfaces, /v1/surfaces/{surface_id}
  -> Cloudflare Worker allowlist proxy at same-origin /api/*
  -> typed React Dashboard list/detail routes
```

The Dashboard lives under `apps/dashboard` and uses React 19, TypeScript, Vite,
TanStack Router and TanStack Query. The official Cloudflare Vite plugin builds
the Worker and Static Assets output. The browser only requests same-origin
`/api/*` paths; the Worker accepts GET/HEAD for the bounded M6-B read contract,
forwards only an explicit server-side `SURFACE_API_ORIGIN`, preserves relevant
ETag/cache headers, and rejects mutation methods before any upstream request.
It does not read repository files, raw stores or provider data and it never
recomputes investment values.

The checked-in
`schemas/research-surface-api-v1.openapi.json` is exported from the real
FastAPI route and response models using an explicit in-memory fixture. Dashboard
types are generated into
`apps/dashboard/src/generated/surface-api.d.ts`; a deterministic drift check
fails when the generated file is stale.

The C1 surface includes responsive overview/detail views, explicit loading,
empty and error states, visible keyboard focus, and exact null/PARTIAL/BLOCKED/
NOT_AVAILABLE/NOT_EVALUATED rendering. It has no mutation UI. Local acceptance
starts the real `tve surface serve` process and the built Cloudflare/Vite
preview, then checks same-origin health/list/detail/404/mutation rejection and
clean shutdown. Cloudflare deployment, authentication and non-loopback origin
security remain M6-C2.
