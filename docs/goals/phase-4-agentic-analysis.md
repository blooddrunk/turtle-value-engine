# Goal: Phase 4 — Agent-Assisted Evidence Analysis and Business Quality

Status: ACTIVE

## Objective

Add an agent-assisted research layer on top of the completed deterministic Phase 1–3 foundation without moving investment math, hard-gate semantics, or adjustment approval into an LLM.

The target user experience is not "let an LLM analyze a stock from scratch". It is:

```text
listing + as_of
  -> deterministic/provider preparation
  -> official filing/evidence retrieval
  -> bounded agent research
  -> structured claims / Business Quality assessment / adjustment proposals
  -> explicit deterministic validation and approval boundaries
  -> deterministic analysis
  -> auditable report
```

The resulting architecture should be usable by ChatGPT, Codex, Hermes, or another tool-using agent through a thin, model-neutral interface.

## Source of truth

Before implementation, read and follow:

- `AGENTS.md`
- `README.md`
- `docs/spec/04-business-quality.md`
- all other relevant files under `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/runtime-and-automation.md`
- `docs/architecture/provider-and-cache.md`
- `docs/roadmap.md`

Do not silently alter frozen deterministic semantics to make agent integration easier.

## Non-goals

Do not use this phase to:

- let an LLM calculate CDC, Net Cash, Through Return, hard gates, or valuation;
- let an LLM approve or directly apply adjustments;
- hide network/model calls inside `tve analyze`;
- create a fully autonomous trading agent;
- add brokerage execution;
- implement broad backtesting/calibration;
- implement watchlist/event-driven monitoring;
- resume horizontal AKShare endpoint expansion without a concrete Phase 4 evidence need.

## Design principle

Treat model output as an untrusted, typed research proposal.

```text
LLM / agent
  -> claims, evidence references, counter-evidence, questions,
     Business Quality dimension proposals, adjustment proposals

validators / rule engine / explicit approval
  -> contract validation, evidence resolution, deterministic caps,
     accepted adjustments, gate semantics

engine
  -> metrics, gates, valuation, final state
```

Every material model-produced conclusion must either resolve to repository evidence or remain explicitly unresolved.

---

## Work package A — Agent/research contracts

Create typed, model-neutral contracts for agent-assisted research.

Recommended concepts (names may vary):

```text
ResearchTask
ResearchQuestion
EvidenceClaim
CounterEvidenceClaim
ResearchFinding
AnalystRun
AnalystRole
AgentRunMetadata
```

Contracts should capture at minimum:

- analysis/listing identity;
- `as_of` boundary;
- role (`RESEARCH`, `QUALITY_ANALYST`, `SKEPTIC`, `ADJUDICATOR`, `REPORT_COMPOSER` or equivalent);
- exact question/dimension;
- evidence IDs used;
- supporting vs counter-evidence;
- claim text;
- confidence;
- unresolved questions;
- model/provider identifier when applicable;
- prompt/protocol version;
- deterministic run ID / content hash where appropriate.

Requirements:

- no prose-only evidence linkage;
- referenced evidence IDs must exist;
- model output must not mutate source evidence;
- outputs must be serializable and schema-valid;
- model/provider-specific payloads must not leak into core business-quality validation.

Add JSON Schemas if repository conventions make these contracts externally persisted artifacts.

---

## Work package B — Model-neutral analyst interface

Define an injected analyst boundary rather than hard-coding OpenAI, Anthropic, Hermes, or another provider into investment logic.

Approximately:

```python
class AnalystClient(Protocol):
    def analyze(self, task: ResearchTask) -> AnalystRun: ...
```

or an equivalent async/interface design consistent with the codebase.

Provide:

1. deterministic scripted/fake implementation for tests;
2. optional adapter boundary for live model clients;
3. prompt/protocol versioning;
4. explicit token/context/evidence limits;
5. timeout/error behavior that fails closed;
6. no live model dependency in ordinary CI.

The repository should make it straightforward for an external agent runtime such as ChatGPT, Codex, or Hermes to consume/produce the same contracts without requiring a specific SDK.

---

## Work package C — Evidence packet builder

Create a deterministic evidence-packet assembly layer that gives an analyst only the evidence needed for a bounded question.

The packet should be assembled from existing normalized facts, filing evidence, deterministic metrics, and provenance.

It must:

- enforce `as_of` boundaries;
- retain evidence IDs and filing locators;
- distinguish primary evidence from derived deterministic metrics;
- support both supporting and falsification-oriented retrieval;
- avoid dumping the entire repository/document corpus into every prompt;
- record which evidence was made available to each analyst run;
- be reproducible from frozen inputs.

A model must not cite evidence it was never given unless the architecture explicitly performs an additional retrieval step whose result is persisted.

---

## Work package D — Business Quality agent workflow

Implement the eight-dimension workflow defined by `docs/spec/04-business-quality.md`.

For each dimension B01–B08:

1. build a bounded research task;
2. require supporting evidence;
3. require active counter-evidence search;
4. attach deterministic quantitative metrics where available;
5. produce a proposed score and confidence;
6. preserve unresolved questions;
7. validate evidence references and deterministic score caps before the assessment may enter the engine.

The agent must not directly construct a final `BUSINESS_PASS` by prose.

### Adversarial roles

For high-priority/full analysis, implement the specification's role separation:

```text
Quality Analyst
    -> strongest evidence-based durability case

Skeptic Analyst
    -> attempts to falsify the case

Adjudicator
    -> may use only the persisted outputs/evidence of the two analyst roles
    -> produces the structured proposed final assessment
```

The Adjudicator must not silently perform new web/provider research unless such a step is explicitly modeled and persisted.

### Deterministic validation

Reuse the existing Business Quality calculation/gate layer for:

- dimension completeness;
- evidence reference resolution;
- high-score evidence caps;
- confidence/coverage logic;
- critical-dimension weakness handling;
- final Business Quality gate semantics.

Do not duplicate those rules in prompts as executable authority.

---

## Work package E — Adjustment proposal assistance

Allow bounded analyst workflows to propose filing-backed adjustments for existing supported adjustment targets.

Preserve the current boundary:

```text
LLM -> PROPOSED
HUMAN / RULE_ENGINE -> ACCEPTED or REJECTED
```

Requirements:

- proposals must cite persisted evidence IDs;
- stale input values remain fail-closed;
- unsupported targets remain rejected;
- no LLM auto-approval switch;
- no prompt may instruct the model to overwrite facts directly;
- existing `materialize_effective_input` remains the application boundary.

This work package should reuse rather than replace the Phase 3 adjustment workflow.

---

## Work package F — Orchestration boundary

Add a composable top-level research orchestration API while keeping `tve analyze` deterministic and offline.

Recommended separation:

```text
prepare       # networked/replayable structured data
research      # network/model-assisted evidence and BQ proposals
review        # explicit adjustment/BQ review boundary as needed
analyze       # offline deterministic engine
report        # explain validated result without changing it
```

CLI names are not mandatory, but if CLI commands are added, prefer thin wrappers over reusable Python orchestration APIs.

A possible future UX is:

```bash
tve research 600519.SH --as-of 2026-09-14 --workspace runs/600519-20260914
```

This must not turn `tve analyze` into a networked or model-dependent command.

Persist enough run artifacts for another agent/runtime to resume the workflow without relying on chat history.

---

## Work package G — Agent-facing interface / Skill packaging

Create a thin interface for external tool-using agents.

The repository-level `AGENTS.md` is the stable operating guide. In addition, add a compact agent/Skill package only if it materially improves invocation from supported runtimes.

The package should teach an agent to:

- locate repository contracts;
- prepare or request company data;
- run or consume deterministic engine output;
- execute bounded Quality/Skeptic/Adjudicator research;
- cite persisted evidence;
- explain results consistently;
- never recompute deterministic metrics ad hoc.

Do not duplicate the entire specification into a Skill prompt. Reference repository resources or generate compact, versioned protocol material.

Favor a model-neutral protocol first. Provider-specific ChatGPT/Hermes/Codex wrappers should be thin adapters.

---

## Work package H — Auditable report composer

Add a report-composition boundary that converts validated artifacts into a concise human-readable investment research report without altering the validated result.

The report should clearly separate:

- deterministic metrics and gates;
- Business Quality agent judgment;
- accepted adjustments;
- unresolved/missing data;
- valuation;
- final deterministic state;
- evidence/filing provenance;
- `as_of` date and rule profile.

The composer may use an LLM for wording, but tests must prove it cannot change the underlying structured state.

Prefer a structured report model plus renderers over free-form text as the only artifact.

---

## Work package I — Frozen evaluation and adversarial tests

Ordinary CI must not call a live model.

Create frozen scripted analyst fixtures that test at minimum:

1. a strong business with adequate supporting and counter-evidence;
2. a superficially attractive company where the Skeptic reveals a critical weakness;
3. insufficient evidence causing LOW confidence / manual review;
4. hallucinated/nonexistent evidence ID rejection;
5. future-dated evidence rejection;
6. an attempted LLM-approved adjustment rejection;
7. an unsupported adjustment target rejection;
8. Adjudicator trying to introduce evidence not supplied by analyst runs;
9. score-5 proposal with insufficient E3/E2 evidence being deterministically capped;
10. report generation that preserves the exact deterministic final state.

Add at least one frozen end-to-end A-share scenario:

```text
provider/cache preparation
-> filing/evidence
-> scripted Quality analyst
-> scripted Skeptic
-> scripted Adjudicator
-> validated BusinessQuality
-> optional HUMAN-accepted adjustment
-> deterministic analysis
-> decision trace
-> report artifact
```

Add an H-share scenario if existing fixtures make it practical without inventing semantics.

---

## Work package J — Documentation and roadmap reconciliation

During this phase:

- keep `README.md` concise and human-facing;
- keep `AGENTS.md` as the stable agent operating guide;
- document new runtime boundaries under `docs/architecture/`;
- update `docs/roadmap.md` with Phase 4 sub-milestones and status;
- add protocol/schema docs when new persisted artifacts become public contracts.

Do not turn the roadmap into an endpoint-by-endpoint implementation log for Phase 4.

---

## Engineering requirements

- Python >= 3.11.
- Preserve strict typing/model validation patterns.
- Deterministic analysis remains runnable with zero model/network access.
- Ordinary tests use fake/scripted analyst clients.
- Live model tests/evals are opt-in.
- Preserve deterministic IDs/hashes where appropriate.
- Persist prompt/protocol versions for model-produced artifacts.
- Fail closed on invalid evidence references, time leakage, missing required counter-evidence, unsupported targets, or ambiguous economic treatment.
- Do not persist secrets/API keys in run artifacts.
- Do not treat model confidence as deterministic truth.

## Verification

Before declaring this goal complete, run at minimum:

```bash
python -m ruff check .
python -m pytest
```

Also execute the frozen Phase 4 end-to-end acceptance scenario(s).

If optional live-model smoke tests are implemented, they must be gated by an explicit environment variable and are not part of ordinary CI success.

## Exit criteria

Phase 4 is complete only when all of the following are true:

1. A model-neutral analyst contract exists and can be implemented by an external runtime.
2. Analyst runs operate on bounded, persisted evidence packets with `as_of` enforcement.
3. The eight Business Quality dimensions can be produced through Quality/Skeptic/Adjudicator roles and pass deterministic evidence/score validation.
4. LLM-originated adjustments remain proposals only and reuse the Phase 3 approval/materialization boundary.
5. A frozen end-to-end workflow can start from repository fixtures and end in a schema-valid deterministic `CompanyAnalysis` plus an auditable human-readable report.
6. Every material Business Quality conclusion can be traced to persisted evidence and analyst-run artifacts.
7. The same deterministic inputs and scripted analyst outputs reproduce the same validated result.
8. `tve analyze` remains offline and model-independent.
9. External agents such as ChatGPT, Codex, or Hermes can understand the repository workflow from `AGENTS.md` and the stable typed contracts without relying on prior chat history.

## Suggested implementation order

Treat this as one large goal but deliver it as reviewable work units:

1. research/analyst contracts + schemas;
2. injected analyst interface + scripted test client;
3. evidence packet builder;
4. single-dimension Business Quality vertical slice;
5. full B01–B08 workflow;
6. Quality/Skeptic/Adjudicator orchestration;
7. adjustment-proposal integration;
8. top-level research orchestration and persisted run workspace;
9. report composer;
10. frozen E2E/adversarial suite;
11. optional thin runtime/Skill adapters;
12. documentation reconciliation and Phase 4 closure review.

At completion, summarize:

- public contracts added;
- orchestration/runtime changes;
- model-neutral vs provider-specific boundaries;
- schemas/artifacts added;
- deterministic safety boundaries preserved;
- tests/evaluations added;
- unresolved gaps before Phase 5.