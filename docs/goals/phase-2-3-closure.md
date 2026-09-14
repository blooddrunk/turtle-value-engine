# Goal: Phase 2 / Phase 3 Closure

Status: ACTIVE

This goal closes the gap between the repository's mature Phase 2/3 building blocks and a usable, auditable end-to-end workflow.

It is intentionally a **closure and integration** goal. Do not continue broad horizontal AKShare endpoint expansion unless a missing endpoint is strictly required to satisfy this goal's acceptance criteria.

## Source of truth

Before implementation, read and follow:

- `README.md`
- `docs/spec/`
- `docs/architecture/provider-and-cache.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/roadmap.md`
- `rules/strict-v1.yaml`
- relevant schemas under `schemas/`

If this goal conflicts with frozen investment semantics in `docs/spec/`, `rules/strict-v1.yaml`, or existing schemas, do not silently change the investment rule core. Prefer an integration design that preserves the frozen contracts.

## Background

The repository already has:

- a deterministic offline analysis engine;
- provider-neutral acquisition/cache primitives;
- broad AKShare A/H structured-data support;
- official filing discovery;
- filing document download/cache;
- bounded filing extraction;
- deterministic filing evidence storage;
- deterministic adjustment proposal review.

The remaining problem is vertical integration.

Today, the principal user-facing deterministic command still expects a prebuilt `NormalizedCompanyInput`, and an accepted adjustment is not automatically materialized into an effective analysis input.

This means the top-level Phase 2 and Phase 3 exit criteria are not yet fully closed even though many component milestones are complete.

## Non-goals

Do **not** use this goal to:

- add dozens of new AKShare endpoints;
- redesign CDC, Net Cash, Through Return, hard gates or valuation semantics;
- silently change `strict-v1` thresholds;
- let an LLM approve or directly apply adjustments;
- make `tve analyze` perform hidden network calls;
- replace missing facts with zero or guessed values;
- introduce backtesting, watchlists or Phase 4 agent orchestration yet.

## Work package A — Phase 2 closure: provider-backed preparation

Create a stable orchestration boundary that turns a listing-scoped acquisition request into a schema-valid `NormalizedCompanyInput` while preserving the existing provider/cache/normalizer contracts.

### Required architecture

Keep acquisition and deterministic analysis separate:

```text
NETWORKED / REPLAYABLE
listing + as_of + provider options
        ↓
provider acquisition
        ↓
cache / replay
        ↓
normalization / assembly
        ↓
NormalizedCompanyInput.json

OFFLINE / DETERMINISTIC
NormalizedCompanyInput.json
        ↓
tve analyze
        ↓
CompanyAnalysis.json
```

`tve analyze` must remain offline-only.

### Required capabilities

Implement a provider-backed preparation layer with explicit models/contracts, approximately equivalent to:

```text
AcquisitionRequest
AcquisitionBundle
NormalizedCompanyInputBuilder
```

Names may differ if a better repository-consistent abstraction already exists.

The builder/orchestrator must explicitly handle:

- canonical listing identity;
- `as_of` boundaries;
- publication-date / point-in-time constraints where available;
- provider source priority;
- duplicate facts;
- conflicting facts;
- currency and units;
- accounting/report periods;
- critical missing fields;
- provenance and evidence linkage;
- cache replay;
- provider failure without corrupting prior valid cache state.

Do not fabricate facts from raw-only provider slices whose period/unit/economic meaning remains unresolved.

### CLI

Add a user-facing preparation command. Preferred interface:

```bash
tve prepare 600519.SH \
  --as-of 2026-09-14 \
  --provider akshare \
  --output normalized.json
```

Equivalent syntax is acceptable if it fits the existing CLI architecture better.

The command may perform network access when explicitly invoked in live mode, but the underlying orchestration must also support injected/frozen provider data and offline cache replay for deterministic tests.

Do not make live-provider integration part of ordinary CI.

### Phase 2 acceptance tests

Add at least two end-to-end frozen acceptance scenarios:

1. one A-share listing;
2. one H-share listing.

Each must demonstrate:

```text
injected/frozen provider data
→ acquisition bundle
→ normalized input
→ schema validation
→ run_analyze / tve analyze
→ schema-valid CompanyAnalysis
```

The test should prove that provider-specific field names do not leak into calculation modules.

## Work package B — Phase 3 closure: accepted adjustment materialization

Close the missing link between an `ACCEPTED` adjustment and deterministic analysis without mutating original source facts.

### Required model

Introduce an explicit effective-input/materialization boundary, approximately equivalent to:

```text
NormalizedCompanyInput
+ accepted Adjustment records
        ↓
EffectiveInputBuilder / materialize_effective_input
        ↓
analysis-ready NormalizedCompanyInput (or a clearly versioned equivalent)
```

The original source facts and provenance must remain preserved and auditable.

### Rules

Only `ACCEPTED` adjustments may affect effective analysis values.

Approval semantics must preserve the existing boundary:

- `HUMAN` may approve;
- `RULE_ENGINE` may approve;
- `LLM` may propose but must not approve.

Define and test deterministic behavior for:

- allowed target fields;
- each supported `AdjustmentType`;
- stale proposals where `input_value` no longer matches the scoped fact;
- multiple adjustments targeting the same field/fact;
- ordering and conflict resolution;
- duplicate/idempotent application;
- scope mismatch;
- missing evidence;
- rejected/proposed adjustments;
- invalid or unsupported targets.

Prefer fail-closed behavior when the correct economic treatment is ambiguous.

Do not overwrite the original fact record in place. Preserve enough lineage for the final analysis to distinguish source fact, accepted adjustment and effective value.

## Work package C — Phase 3 traceability closure

Add a deterministic end-to-end acceptance workflow covering:

```text
Official filing discovery
→ document retrieval/cache
→ extraction
→ filing evidence store
→ adjustment proposal
→ HUMAN or RULE_ENGINE acceptance
→ effective-input materialization
→ deterministic analysis
→ CompanyAnalysis
```

The final result must be traceable back through the chain required by the Phase 3 exit criteria:

```text
Decision
→ Gate
→ Metric
→ Adjustment
→ Fact
→ Evidence
→ Filing / official source
```

Implement whatever small additive provenance fields or trace helpers are required, but do not weaken existing schemas or silently redefine investment semantics.

Add at least one A-share traceability acceptance fixture. Add H-share coverage as well if the existing filing fixtures make this practical without inventing new semantics.

## Work package D — CLI / UX closure

Keep the public CLI small and composable.

Required:

```text
tve prepare
tve analyze
```

Add additional filing/evidence/adjustment subcommands only if they materially improve the end-to-end workflow and can remain thin orchestration layers.

CLI code must not become the owner of calculation, provider, evidence or adjustment business logic.

## Work package E — documentation reconciliation

After the implementation is complete:

1. update `docs/roadmap.md` so its current milestone section no longer claims that the Phase 3 filing/evidence layer is unimplemented;
2. distinguish component completion from top-level Phase closure;
3. mark Phase 2 and Phase 3 complete only when their exit criteria are actually satisfied;
4. update `README.md` only where the newly implemented user workflow changes current capabilities or Quick Start usage;
5. keep detailed endpoint implementation history out of the root README.

Do not rewrite historical documentation unnecessarily.

## Engineering requirements

- Python >= 3.11.
- Preserve strict typing/model validation patterns already used in the repository.
- Preserve deterministic IDs and canonical JSON/hash conventions where appropriate.
- No hidden network access in deterministic pipeline functions.
- No LLM dependency in ordinary tests or deterministic execution.
- No live external provider dependency in ordinary CI.
- Fail closed on ambiguous period/unit/entity/economic scope.
- Add adversarial tests for provenance tampering, conflicts and replay where relevant.
- Keep backwards compatibility for existing `tve analyze --input ... --profile strict-v1` behavior unless an explicit schema/version change is unavoidable.

## Verification

Before declaring this goal complete, run at minimum:

```bash
python -m ruff check .
python -m pytest
```

All existing tests must continue to pass.

Also exercise the new frozen end-to-end Phase 2 and Phase 3 acceptance flows.

## Completion criteria

This goal is complete only when all of the following are true:

### Phase 2

A caller can start from a canonical A/H listing plus an `as_of` date and produce a schema-valid normalized input through the provider/cache/normalization stack, then feed that frozen artifact to the unchanged offline deterministic analysis pipeline.

### Phase 3

A filing-backed evidence item can support an adjustment proposal, an allowed actor can explicitly accept it, the accepted adjustment can deterministically affect the effective analysis input without mutating the source fact, and the resulting CompanyAnalysis can be traced back to the adjustment, evidence block and official filing.

### Safety boundary

LLM-assisted evidence analysis may remain unimplemented. Phase 4 agents are not required for this goal. The deterministic engine remains the sole owner of formulas, gates and valuation calculations.

## Expected delivery

Treat this as one large goal, but implement it as reviewable commits/work units in this order:

1. preparation contracts/orchestrator;
2. `tve prepare` + Phase 2 E2E tests;
3. accepted-adjustment materialization;
4. Phase 3 traceability integration + E2E tests;
5. documentation reconciliation.

At completion, summarize:

- architecture changes;
- public CLI changes;
- schema/model changes;
- tests added;
- any unresolved gaps that prevent Phase 2 or Phase 3 from being marked COMPLETE.
