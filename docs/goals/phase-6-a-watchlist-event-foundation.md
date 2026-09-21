# Phase 6-A — Watchlist State and Deterministic Event Planning Foundation

Status: **SELECTED / IMPLEMENTATION NOT STARTED**
Date: 2026-09-21
Selected after: M6-C3 COMPLETE

Parent context:
- AGENTS.md
- docs/architecture/runtime-and-automation.md
- docs/architecture/agent-api-web-surface.md
- docs/goals/phase-5-backtesting-calibration.md
- docs/goals/phase-5r-production-historical-corpus.md
- docs/goals/phase-5r-a-m6-c3-dashboard-ux-localization.md
- docs/status/phase-6-a-2026-09-21.md
- docs/roadmap.md

## 1. Objective

Build the first Phase 6 monitoring slice as an **offline, deterministic, replayable foundation**.

Phase 6-A must make a watchlist and already-frozen canonical events machine-processable without yet adding live polling, schedulers, model calls, automatic research, automatic adjustment approval, or automatic investment re-analysis.

The package should answer, deterministically:

1. what listings are being watched;
2. which canonical events are new as of a requested boundary;
3. which source/listing cursors may advance;
4. what impact class each event has;
5. which listings need no, partial, full, or urgent-manual follow-up;
6. what the next watchlist state would be after a successful atomic commit.

This is orchestration state, not investment semantics.

## 2. Why this is the next package

M6-C3 closed the owner-facing presentation boundary on top of the already deployed read-only Dashboard. The next major missing capability in the roadmap is watchlist/event-driven re-analysis.

Do not jump directly to live provider polling. A scheduler without a deterministic event/state core would make duplicate handling, point-in-time boundaries, cursor recovery and re-analysis scope hard to audit.

Phase 6-A therefore establishes the local contract first. Later packages may feed it live events and execute approved re-analysis work.

A6 remains a separate strict production-claim audit. Phase 6-A may operate on an explicitly bounded personal/fixed research universe while preserving all partial/missing/A6 blockers.

## 3. Frozen boundaries

Preserve all of the following:

1. strict-v1, CDC, Net Cash, Through Return, hard gates and valuation semantics are unchanged.
2. tve analyze remains offline and is not invoked implicitly by watchlist processing.
3. ResearchSurfaceSnapshotV1, M6-B API and the M6-C2 Access/Worker/Tunnel deployment boundary remain unchanged.
4. No page request may acquire events, run research or trigger re-analysis.
5. No LLM/model call is permitted inside the deterministic monitoring core or ordinary CI.
6. No agent/model may approve or apply adjustments.
7. Missing state remains missing; never convert absence into PASS, zero or a fabricated cursor.
8. Event processing must respect an explicit as_of boundary and must not consume future events.
9. Ordinary CI must remain network-independent.
10. M4-D/M4-E, M2-D and M5-C/R2 remain deferred unless a separate concrete requirement proves they are needed.
11. No trading, order, cancellation, transfer or other financial mutation is in Phase 6.
12. Monitoring configuration extends ProjectConfig; do not add an unrelated phase-local environment convention.

## 4. Required typed contracts

Use repository naming conventions, but keep these responsibilities distinct. Preferred public names are:

- WatchlistSpecV1
- WatchlistEntryV1
- MonitoringEventV1
- WatchlistEntryStateV1
- WatchlistStateV1
- EventImpactDecisionV1
- ReanalysisRequestV1
- ReanalysisPlanV1
- MonitoringRunV1

The exact class/file names may be adjusted only if an existing repository convention makes another name materially clearer.

### 4.1 WatchlistSpecV1

At minimum record:

- schema version;
- stable watchlist_id;
- rule/profile reference used by the watched analysis;
- listing identities using existing repository identity conventions;
- optional company display name;
- enabled/disabled state;
- explicit current analysis/surface references when known;
- open questions only when supplied by an existing validated artifact or explicit caller input.

Reject duplicate listing identities. Do not infer company identity, reporting currency, Business Quality or a current analysis result.

### 4.2 MonitoringEventV1

A canonical event must contain enough information to replay ordering and provenance:

- schema version;
- stable event_id;
- listing_id;
- canonical event_type;
- source/provider identity;
- source artifact/evidence identity or another auditable source reference;
- published_at when the source provides it;
- available_at or observed_at used for point-in-time eligibility;
- optional source event identity;
- optional bounded human-readable title/summary that is not treated as a deterministic fact.

Canonical event types for the first policy must cover at least:

- ANNUAL_REPORT
- INTERIM_REPORT
- EARNINGS_PREANNOUNCEMENT
- DIVIDEND_POLICY_CHANGE
- DIVIDEND_DECLARATION
- BUYBACK
- SHARE_ISSUANCE
- MAJOR_ACQUISITION
- MAJOR_DISPOSAL
- AUDIT_OPINION_CHANGE
- REGULATORY_PENALTY
- CONTROLLING_SHAREHOLDER_EVENT
- MATERIAL_LITIGATION
- PROFIT_WARNING
- TRADING_SUSPENSION
- INFORMATIONAL_DISCLOSURE

Unknown upstream event kinds must be mapped by a future adapter before entering this canonical contract. Do not silently coerce an unknown string into a harmless event.

### 4.3 Watchlist state and cursors

Persist enough state to support the roadmap fields without inventing facts:

- listing identity;
- last validated analysis/surface identity and content hash when known;
- last analysis as_of/profile/version when known;
- last deterministic result when known;
- last filing/source identity when known;
- source-scoped event cursor(s);
- unresolved/open questions when explicitly supplied;
- last successfully committed monitoring run identity.

A cursor is source/listing scoped. It may advance only after the corresponding monitoring run is durably committed.

## 5. Versioned event-impact policy

Implement a monitoring-only policy named event-impact-v1. It must be isolated from rules/strict-v1 and must not claim to alter investment decisions.

Required default mapping:

| Event type | Impact |
| --- | --- |
| INFORMATIONAL_DISCLOSURE | NO_REANALYSIS |
| INTERIM_REPORT | PARTIAL_REANALYSIS |
| EARNINGS_PREANNOUNCEMENT | PARTIAL_REANALYSIS |
| DIVIDEND_POLICY_CHANGE | PARTIAL_REANALYSIS |
| DIVIDEND_DECLARATION | PARTIAL_REANALYSIS |
| BUYBACK | PARTIAL_REANALYSIS |
| ANNUAL_REPORT | FULL_REANALYSIS |
| SHARE_ISSUANCE | FULL_REANALYSIS |
| MAJOR_ACQUISITION | FULL_REANALYSIS |
| MAJOR_DISPOSAL | FULL_REANALYSIS |
| AUDIT_OPINION_CHANGE | URGENT_MANUAL_REVIEW |
| REGULATORY_PENALTY | URGENT_MANUAL_REVIEW |
| CONTROLLING_SHAREHOLDER_EVENT | URGENT_MANUAL_REVIEW |
| MATERIAL_LITIGATION | URGENT_MANUAL_REVIEW |
| PROFIT_WARNING | URGENT_MANUAL_REVIEW |
| TRADING_SUSPENSION | URGENT_MANUAL_REVIEW |

When multiple new events affect one listing in one run, retain all event IDs and use the highest orchestration severity:

NO_REANALYSIS < PARTIAL_REANALYSIS < FULL_REANALYSIS < URGENT_MANUAL_REVIEW.

This precedence is an orchestration rule only. It does not turn an event into an investment PASS/FAIL/WATCH result.

## 6. Deterministic processing semantics

The pure processing layer must be independently testable without a filesystem, network, model or scheduler.

Required behavior:

1. validate the watchlist and event batch before mutating state;
2. canonicalize event ordering by an explicitly documented stable key;
3. process only events whose point-in-time availability is <= as_of;
4. identical duplicate event IDs are idempotent;
5. the same event_id with different semantic content is a hard conflict;
6. events for listings outside the enabled watchlist are not silently applied;
7. already-processed/stale events do not generate duplicate re-analysis requests;
8. future events do not advance cursors;
9. a run groups events by listing and emits a deterministic ReanalysisPlanV1;
10. a repeated replay with identical inputs and prior state produces byte-equivalent canonical artifacts;
11. no monitoring function imports or calls a provider transport, AnalystClient, ResearchOrchestrator, run_analyze*, brokerage code or Cloudflare API.

## 7. Local MonitoringWorkspace

Add a small local workspace with immutable run artifacts and an atomic current-state pointer.

Preferred layout:

~~~
<workspace>/
  watchlists/
  event-batches/
  runs/
  states/
~~~

Requirements:

- canonical JSON and stable hashes/IDs;
- immutable run artifacts;
- atomic writes;
- verify hashes on read;
- corrupted/truncated artifacts fail closed;
- the current-state pointer changes only after every artifact for the run is durably written;
- a simulated write failure must leave the previous committed state readable;
- retrying the same successful run must be idempotent.

Do not add a database in Phase 6-A. D1/R2/Postgres are later deployment choices only if a concrete remote-state need is demonstrated.

## 8. CLI surface

Add an offline watch namespace. Preferred commands:

~~~
tve watch validate --watchlist <watchlist.json>

tve watch replay \
  --watchlist <watchlist.json> \
  --events <events.json> \
  --workspace <dir> \
  --as-of <ISO-8601> \
  --output <monitoring-run.json>

tve watch status \
  --workspace <dir> \
  --watchlist-id <id>
~~~

Exact spelling may follow existing argparse conventions, but the semantics above must remain.

All three commands are offline. Phase 6-A must contain no --network=allow path.

## 9. ProjectConfig extension

Extend the existing typed project configuration rather than creating another config file family.

Preferred non-secret fields:

~~~
[monitoring]
watchlist_path = ".tve-private/monitoring/watchlist.json"
workspace_root = ".tve-private/monitoring"
event_impact_policy = "event-impact-v1"
~~~

tve config validate must continue to print a secret-safe summary. No schedule, webhook credential, provider token or notification secret is required in Phase 6-A.

## 10. Expected implementation scope

Primarily:

~~~
src/turtle_value_engine/monitoring/__init__.py
src/turtle_value_engine/monitoring/models.py
src/turtle_value_engine/monitoring/policy.py
src/turtle_value_engine/monitoring/service.py
src/turtle_value_engine/monitoring/workspace.py
src/turtle_value_engine/config/project.py
src/turtle_value_engine/cli.py
config/project.example.toml
tests/test_monitoring_models.py
tests/test_monitoring_service.py
tests/test_monitoring_workspace.py
tests/test_monitoring_cli.py
fixtures/monitoring/**
docs/architecture/runtime-and-automation.md
docs/goals/phase-6-a-watchlist-event-foundation.md
docs/status/phase-6-a-2026-09-21.md or a dated successor
docs/status/phase-5r-a-next-codex-goal.md
docs/roadmap.md
AGENTS.md only when milestone state changes
~~~

If public JSON artifact schemas are the repository convention for the new contracts, add checked-in schemas plus deterministic drift tests. Do not add schemas merely as dead documentation.

## 11. Required automated verification

Codex must execute every machine-verifiable check available in its environment. Routine validation is not owner work.

### 11.1 Permanent owner test environment

The preferred owner test root is:

~~~
D:\code\research
~~~

Under WSL it is normally reachable under /mnt/d/code/research. Discover the actual turtle-value-engine checkout; do not assume a fixed subdirectory.

Record before editing:

~~~
git status --short --branch
git rev-parse HEAD
git remote -v
~~~

If no checkout is present under the permanent root, record that exact fact and use the actual synchronized repository checkout. This is not a reason to skip tests.

### 11.2 Baseline gate

Before editing, synchronize main with fast-forward only and prove the GitHub Actions run for the exact baseline commit is green.

Run the repository baseline checks that are available locally, including at minimum:

~~~
python -m ruff check .
python -m pytest
~~~

Where the current environment has the Dashboard toolchain, also run the same existing current-main gates rather than assuming an unrelated backend change cannot break them:

~~~
pnpm --dir apps/dashboard install --frozen-lockfile
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
~~~

Use python3 consistently if that is the only interpreter available and record the actual commands.

### 11.3 Phase 6-A focused tests

Automate at least these cases:

1. schema/version validation and duplicate-listing rejection;
2. stable canonical IDs/hashes for watchlist, event batch, state, plan and run;
3. exact event-impact-v1 mapping and severity precedence;
4. out-of-order input yields the same canonical run;
5. identical duplicate events are idempotent;
6. same event_id with changed content fails closed;
7. future events are deferred and do not advance cursors;
8. stale/already-processed events create no duplicate re-analysis request;
9. events for disabled/out-of-watchlist listings are explicitly rejected or reported according to one documented rule;
10. cursor advances only after a successful atomic workspace commit;
11. injected write failure leaves the previous committed state intact;
12. corrupted workspace artifacts fail closed;
13. replaying the same run twice is idempotent and byte-equivalent;
14. unknown canonical event type is rejected, not mapped to NO_REANALYSIS;
15. missing provenance/source identity is rejected;
16. no network/model/analysis/research function is called during validate/replay/status;
17. ProjectConfig monitoring fields round-trip and safe_summary contains no secret values;
18. CLI exit codes are non-zero for malformed/conflicting input and output the exact blocker;
19. existing strict-v1/rule files remain byte-identical;
20. all prior Python and Dashboard CI gates remain green.

### 11.4 Post-push verification

After the implementation is pushed, inspect GitHub Actions for the exact pushed commit. Do not close Phase 6-A while required CI is red, cancelled or still running.

Record:

- commit SHA;
- workflow run ID;
- conclusion;
- failing step and logs if any;
- exact local pass counts.

## 12. Manual verification boundary

**No manual functional acceptance is planned for Phase 6-A.**

There is no live provider, scheduler, browser workflow, model runtime or cloud mutation in this package. Codex must not delegate correctness to the owner with phrases such as "please verify the monitoring behavior manually".

The only permitted owner/environment note is infrastructure availability, for example that D:\code\research is not mounted in the agent environment. That note does not waive automated tests.

If Codex unexpectedly believes manual work is unavoidable, it must stop short of claiming completion and record:

1. the exact automated command attempted;
2. the exact failure/output;
3. why the missing capability cannot be replaced by a deterministic test;
4. the smallest bounded owner action;
5. the exact expected result and failure symptom.

## 13. Acceptance

Phase 6-A closes only when:

- typed watchlist/event/state/plan/run contracts exist;
- event-impact-v1 is deterministic, versioned and separate from strict-v1;
- point-in-time filtering and source/listing cursors are deterministic;
- duplicate/conflicting event behavior is proven;
- local workspace writes are atomic/idempotent and corruption fails closed;
- CLI validate/replay/status works entirely offline;
- ProjectConfig is extended without secrets;
- no provider/model/analysis/cloud call occurs implicitly;
- full current CI plus focused monitoring tests pass;
- the exact closing commit has green GitHub Actions;
- no Phase 6-B live polling/scheduling/notification work is mixed into this package.

Stop after Phase 6-A closure and select Phase 6-B through a separate audit.

## 14. Planned later Phase 6 packages

These are direction, not current acceptance criteria.

- **Phase 6-B — Opt-in event acquisition and cursors**: provider/official-disclosure adapters feed MonitoringEventV1, explicit network allow, fake-transport CI, real owner-authorized probes when credentials/access exist.
- **Phase 6-C — Re-analysis executor**: consume ReanalysisPlanV1, run only the explicitly permitted preparation/research/analysis slices, persist job lifecycle and failures, preserve adjustment approval boundaries.
- **Phase 6-D — Scheduler, notifications and Dashboard status**: unattended runner (GitHub Actions/Hermes/VPS), alert payloads and read-only watchlist/run state in the Dashboard; add remote derived-state storage only if a concrete need exists.
- **Phase 6-E — Owner live acceptance**: bounded real watchlist, real event detection, restart/replay/idempotency proof and notification acceptance.

None of these later packages may introduce trading or autonomous rule mutation.
