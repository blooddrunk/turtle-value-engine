# Agent/API/Web Read-only Surface

Status: **M6-A frozen / offline projection**

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
