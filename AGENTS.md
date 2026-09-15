# Agent Guide — turtle-value-engine

This file is the repository-facing guide for coding and research agents such as Codex, ChatGPT, Hermes, and other tool-using agents.

The human-facing introduction is `README.md` (Chinese-first). This file is intentionally English-first so code identifiers, schemas, CLI contracts, and cross-agent instructions remain stable and unambiguous.

## 1. Mission

`turtle-value-engine` turns the Turtle value-investing method into an auditable, deterministic A/H-share analysis system.

Agents may help with data collection, filing research, evidence analysis, Business Quality assessment, explanation, orchestration, and code changes. Agents must not become the owner of deterministic investment math.

The core separation is:

```text
Agents / providers / filing research
        -> evidence, normalized facts, proposed adjustments,
           structured Business Quality assessment

Deterministic engine
        -> CDC, Net Cash, Through Return, hard gates,
           valuation, final deterministic state
```

## 2. Source-of-truth order

Before changing behavior, read the relevant sources in this order:

1. `docs/spec/`
2. `rules/strict-v1.yaml`
3. `schemas/`
4. `docs/architecture/`
5. the active goal under `docs/goals/`
6. `docs/roadmap.md`
7. `README.md`

If a lower-priority document conflicts with a higher-priority frozen contract, do not silently change the contract. Stop, report the conflict, and prefer an additive design.

Chat history is not a project specification.

## 3. Non-negotiable invariants

Preserve these boundaries unless an explicit specification change is requested:

- no fabricated facts;
- no silent defaults for missing financial data;
- no future-data leakage beyond the requested `as_of` boundary;
- no hidden network calls from deterministic analysis;
- no ad-hoc LLM recomputation of CDC, Net Cash, Through Return, hard gates, or valuation;
- no direct LLM approval or application of adjustments;
- only explicitly accepted adjustments may affect effective input;
- original source facts and provenance must remain auditable;
- ambiguous period, unit, entity scope, or economic meaning must fail closed;
- Business Quality requires evidence and counter-evidence;
- valuation must remain downstream of eligibility/business-quality gates.

`LLM` may propose an adjustment. `HUMAN` or `RULE_ENGINE` may approve according to the existing adjustment contract.

## 4. Current repository state

Phases 1, 2, and 3 are closed at the top-level integration boundary.

Available deterministic/replayable flow:

```text
A/H listing + as_of
  -> provider/cache preparation
  -> NormalizedCompanyInput
  -> optional explicitly accepted adjustment materialization
  -> offline deterministic analysis
  -> CompanyAnalysis
  -> deterministic decision trace
```

Key public boundaries include:

- `tve prepare`
- `tve analyze --input ... --profile strict-v1`
- `NormalizedCompanyInputBuilder`
- `materialize_effective_input`
- `run_analyze_with_accepted_adjustments`
- `build_decision_trace`

Phase 4 adds these model-neutral research boundaries:

- `AnalystClient` / `CallableAnalystClient` for injected external runtimes;
- `EvidencePacketBuilder` for bounded, reproducible, point-in-time packets;
- `run_business_quality_dimension` and `run_business_quality_research` for the
  Quality Analyst → Skeptic → Adjudicator workflow;
- `ResearchWorkspace` for immutable JSON packets, tasks, runs, sessions,
  validated Business Quality results, analyses, traces and reports;
- `ResearchOrchestrator` for research → explicit accepted-adjustment materialization
  → deterministic analysis → report;
- `compose_report` for a non-mutating human-readable projection.

The Phase 4 goal is implemented and its closure review is recorded in
`docs/goals/phase-4-agentic-analysis.md`. Phase 5 is implemented at its
documented integration boundary and its closure review is recorded in
`docs/goals/phase-5-backtesting-calibration.md`. Phase 4 contracts remain the
stable input/output boundary for ChatGPT, Codex, Hermes or another external
runtime; Phase 5 consumes their frozen artifacts without live-model
reconstruction.

Phase 5 adds the offline, model-neutral backtesting boundary described in
`docs/goals/phase-5-backtesting-calibration.md` and
`docs/architecture/backtesting-and-calibration.md`: `BacktestDatasetManifest`,
`HistoricalDecisionArtifact`, `DecisionSnapshot`, signal/return evaluation,
the versioned `portfolio-policy-v1` simulator, benchmark/metric attribution,
and chronological calibration proposals. These contracts consume frozen
artifacts only; they do not change `strict-v1` or recalculate deterministic
investment semantics.

Phase 5R adds the source-aware production historical boundary described in
`docs/goals/phase-5r-production-historical-corpus.md` and
`docs/architecture/production-historical-data-and-research-archive.md`.
`HistoricalDatasetManifest` declares a named, bounded A/H target scope and
source/coverage evidence, while `HistoricalArtifactStore` persists large
collections as verified content-addressed JSONL shards. The offline compiler
projects only validated rows into the Phase 5 manifest. A historical or
survivorship-free claim requires complete source-backed membership and
coverage evidence, established authority/licensing and an independent
reconciliation. Production source descriptors must retain license-evidence
URI/hash and restricted sources must retain an access-grant reference; a prose
license label is insufficient. The compact Git corpus is an acceptance fixture
and does not make a market-wide production claim. Delisted/terminal listings
and unresolved terminal economics remain explicit. The research archive
validator is the only permitted path for historical Business Quality artifacts.
No provider or
live model is invoked by dataset validation, freezing, snapshotting, backtest
or calibration commands.

Current Phase 5R status is `ACTIVE / PARTIAL`: the offline replay and
validation boundary plus the Phase 5R-A project-owned opt-in acquisition,
credential, raw provenance and deterministic compiler foundation are
implemented. A real private A/H corpus has not been accepted, so H-share
capability, historical membership, terminal economics, source terms and full
category coverage remain fail-closed blockers. This is not a requirement for
the user to manually assemble market data. Phase 5R primarily needs historical
data; real-time/event-driven acquisition belongs to Phase 6. Ordinary CI
remains offline and model-independent.

Phase 5R-A acquisition commands are separate from replay:
`tve historical source probe` and `tve historical acquire` require explicit
`--network=allow`; `tve historical compile` only reads local raw CAS and batch
receipts. Credentials may come only from declared environment/keyring
references or an injected resolver, never from chat. The exact remaining
blockers are recorded in `docs/operations/phase-5r-a-acquisition.md`.
`tve historical accept` is an additional offline-only A6 audit; it reads the
persisted batch, probe report, raw CAS, compiled manifest and shard store,
replays compilation, and writes exact blockers before failing closed. It does
not resolve credentials, access the network, invoke a provider, or invoke a
model.
The built-in CLI live transport additionally requires a non-empty declared
`ENVIRONMENT` credential reference before any network request; keyring/injected
resolution is limited to explicitly controlled library runners or fake
transports. This repository does not treat a chat value as a credential.
The executable next-stage package is
`docs/goals/phase-5r-a-production-source-acquisition.md`. Its minimum path is
personal-first: official public and documented personal-account sources, local
private content-addressed storage, and no mandatory institutional data contract.
Commercial adapters and remote object storage are optional extensions.

## 5. Working with company data

Keep networked preparation and deterministic analysis separate:

```text
NETWORKED / REPLAYABLE
listing + as_of -> provider acquisition -> raw cache -> normalization

OFFLINE / DETERMINISTIC
NormalizedCompanyInput -> accepted-adjustment materialization -> analysis

OFFLINE / DETERMINISTIC BACKTEST
BacktestDatasetManifest + frozen decisions -> signals -> optional portfolio
policy replay -> metrics / calibration proposal
```

Provider-specific field names must not leak into calculation modules.

Raw-only provider slices must stay raw-only until period, unit, entity scope, and economic meaning are sufficiently explicit for canonical mapping.

## 6. Filing and evidence workflow

The intended traceability chain is:

```text
Official filing
  -> cached document
  -> bounded extraction
  -> evidence item
  -> adjustment proposal or Business Quality claim
  -> explicit review/adjudication where required
  -> effective input / structured assessment
  -> deterministic analysis
  -> Decision -> Gate -> Metric -> Fact -> Evidence -> Filing
```

The agent research path is bounded and persisted:

```text
NormalizedCompanyInput
  -> EvidencePacket -> ResearchTask -> AnalystRun
  -> deterministic evidence/score validation
  -> optional Phase 3 adjustment workflow
  -> CompanyAnalysis -> DecisionTrace -> ResearchReport
```

`tve analyze` remains offline and does not instantiate an analyst client.

Evidence identity, source identity, locators, hashes, and provenance are first-class data. Do not replace them with prose-only citations.

Phase 5 backtest artifacts persist manifest IDs/content hashes, snapshot and
analysis identities, run specifications, policy version/hash, replayable
portfolio events and calibration experiment/holdout boundaries. Calibration
may emit only a candidate profile proposal; it cannot apply a rule change.

## 7. Business Quality rules for agents

Read `docs/spec/04-business-quality.md` before implementing or running any Business Quality agent.

The eight dimensions are fixed by the specification. Agents must:

1. explain how the company makes money;
2. identify major business-model risks;
3. search for counter-evidence before scoring;
4. gather supporting evidence;
5. attach quantitative metrics from deterministic/validated sources;
6. score each dimension only after evidence collection;
7. assign confidence and unresolved questions.

For high-priority candidates, preserve the specification's adversarial pattern:

```text
Quality Analyst -> strongest evidence-based durability case
Skeptic Analyst -> attempts to falsify it
Adjudicator      -> may use only evidence supplied by the analysts
```

An agent may produce a structured Business Quality assessment, but deterministic validation remains responsible for score caps, evidence references, confidence handling, and gate semantics.

## 8. Coding-agent protocol

For implementation tasks:

1. inspect the active goal and affected contracts before editing;
2. make the smallest coherent change that closes the requested acceptance criteria;
3. prefer typed models and explicit boundaries over implicit dictionaries;
4. keep provider, evidence, orchestration, and calculation responsibilities separated;
5. add frozen deterministic tests for new orchestration behavior;
6. use injected/fake provider or analyst clients in ordinary tests;
7. keep live-provider or live-LLM integration opt-in and outside ordinary CI;
8. update architecture/goal documentation when public contracts change.

Do not expand provider endpoint coverage merely because an endpoint exists. Add data only when it closes a clearly stated analysis requirement.

## 9. Verification

At minimum, before declaring a coding goal complete, run:

```bash
python -m ruff check .
python -m pytest
```

For model/agent integrations, ordinary CI must remain deterministic. Use scripted/fake analyst responses and frozen evidence fixtures for acceptance tests. Any live-model evaluation must be opt-in and must not be required for a green test suite.

## 10. Output discipline for research agents

When producing an investment analysis from this repository:

- cite exact evidence IDs / filing provenance when available;
- clearly separate deterministic engine results from agent judgment;
- surface missing data and unresolved questions;
- never convert `NOT_EVALUATED`, `WATCH`, or `SPECIAL_REVIEW` into a confident pass by prose;
- do not invent a recommendation that contradicts the validated `CompanyAnalysis` state;
- state the `as_of` date and rule profile used;
- preserve reproducibility by referencing the normalized input / analysis artifact identities when available.

## 11. Documentation ownership

- `README.md`: concise human-facing Chinese-first introduction and usage.
- `AGENTS.md`: stable agent-facing repository operating guide.
- `docs/spec/`: investment semantics and evidence rules.
- `docs/architecture/`: system boundaries and runtime design.
- `docs/goals/`: active implementation packages and acceptance criteria.
- `docs/roadmap.md`: milestone-level development direction and historical phase record.

Keep detailed implementation history out of the root README and this file.
