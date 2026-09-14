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

The next major milestone is Phase 4: agent-assisted evidence analysis, Business Quality roles, and a thin model-neutral agent/Skill interface. See `docs/goals/phase-4-agentic-analysis.md`.

## 5. Working with company data

Keep networked preparation and deterministic analysis separate:

```text
NETWORKED / REPLAYABLE
listing + as_of -> provider acquisition -> raw cache -> normalization

OFFLINE / DETERMINISTIC
NormalizedCompanyInput -> accepted-adjustment materialization -> analysis
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

Evidence identity, source identity, locators, hashes, and provenance are first-class data. Do not replace them with prose-only citations.

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