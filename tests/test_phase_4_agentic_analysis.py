"""Frozen Phase 4 research contracts, adversarial checks and A-share E2E."""

import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from turtle_value_engine import (
    AdjustmentProposalWorkflow,
    AnalystRole,
    DimensionResearchResult,
    ResearchFinding,
    ResearchIntent,
    ResearchOrchestrator,
    ResearchValidationError,
    ResearchWorkflowResult,
    ResearchWorkspace,
    ScriptedAnalystClient,
    build_evidence_packet,
    build_research_question,
    load_normalized_input,
    run_business_quality_dimension,
    run_business_quality_research,
)
from turtle_value_engine.calculations import BUSINESS_QUALITY_DIMENSIONS
from turtle_value_engine.config import load_profile
from turtle_value_engine.gates import evaluate_business_quality_gate
from turtle_value_engine.models import (
    Adjustment,
    Company,
    Evidence,
    Fact,
    NormalizedCompanyInput,
)
from turtle_value_engine.models.common import AdjustmentStatus, AdjustmentType
from turtle_value_engine.preparation import (
    AcquisitionRequest,
    NormalizedCompanyInputBuilder,
)
from turtle_value_engine.providers import FilesystemRawResponseCache, FilingEvidenceStore

ROOT = Path(__file__).parents[1]
BASE_INPUT = ROOT / "fixtures" / "healthy_cash_cow.json"


def _base_input() -> NormalizedCompanyInput:
    payload = load_normalized_input(BASE_INPUT).model_dump(mode="python", warnings=False)
    # The fixture contains a Phase 3 accepted boolean reclassification.  It is
    # useful for deterministic regression tests but is intentionally omitted
    # from these Phase 4 proposal tests, which target numeric source facts.
    payload["adjustments"] = []
    return NormalizedCompanyInput.model_validate(payload)


def _evidence(
    identifier: str,
    *,
    direction: str = "SUPPORT",
    strength: str = "E0",
    published_date: date | None = None,
) -> Evidence:
    source = {
        "type": "OTHER",
        "title": f"Frozen source {identifier}",
        "published_date": published_date,
        "document_id": None,
    }
    return Evidence(
        id=identifier,
        direction=direction,
        strength=strength,
        statement=f"Frozen statement for {identifier}.",
        source=source,
        confidence=0.95,
    )


def _with_evidence(
    normalized_input: NormalizedCompanyInput,
    evidence: list[Evidence],
    *,
    facts: list[Fact] | None = None,
) -> NormalizedCompanyInput:
    payload = normalized_input.model_dump(mode="python", warnings=False)
    payload["evidence_index"] = [*normalized_input.evidence_index, *evidence]
    if facts:
        payload["facts"] = [*normalized_input.facts, *facts]
    return NormalizedCompanyInput.model_validate(payload)


def _strong_input() -> NormalizedCompanyInput:
    return _with_evidence(
        _base_input(),
        [
            _evidence("strong-primary-000000000000000001", strength="E3"),
            _evidence("strong-operating-000000000000000002", strength="E2"),
            _evidence("strong-counter-000000000000000003", direction="COUNTER", strength="E1"),
        ],
    )


def _finding(
    task,
    *,
    score: int | None = None,
    support_ids: list[str] | None = None,
    counter_ids: list[str] | None = None,
    proposed_adjustments: list[Adjustment] | None = None,
    counter_evidence_checked: bool = True,
) -> ResearchFinding:
    support_ids = support_ids or [
        item.id
        for item in task.packet.evidence
        if item.direction.value == "SUPPORT" and item.strength.value in {"E3", "E2"}
    ]
    support_ids = support_ids or [task.packet.available_evidence_ids[0]]
    counter_ids = counter_ids or [
        item.id for item in task.packet.evidence if item.direction.value == "COUNTER"
    ]
    from turtle_value_engine.research import CounterEvidenceClaim, EvidenceClaim

    supporting = [
        EvidenceClaim(
            id=f"support-{task.role.value}-{task.question.dimension}",
            statement="The supplied evidence supports the operating thesis.",
            evidence_ids=support_ids,
            confidence=0.9,
        )
    ]
    counters = (
        [
            CounterEvidenceClaim(
                id=f"counter-{task.role.value}-{task.question.dimension}",
                statement="The supplied evidence identifies a material risk to the thesis.",
                evidence_ids=counter_ids,
                confidence=0.8,
            )
        ]
        if counter_ids
        else []
    )
    return ResearchFinding(
        id=f"finding-{task.role.value}-{task.question.dimension}",
        analysis_id=task.analysis_id,
        listing_id=task.listing_id,
        as_of=task.as_of,
        role=task.role,
        question_id=task.question.id,
        dimension=task.question.dimension,
        summary="The analyst reviewed the thesis and actively checked counter-evidence.",
        supporting_claims=supporting,
        counter_evidence_claims=counters,
        proposed_score=score,
        confidence="HIGH",
        counter_evidence_checked=counter_evidence_checked,
        proposed_adjustments=proposed_adjustments or [],
    )


def _clients(
    *,
    scores: dict[str, int] | None = None,
    quality_transform=None,
    skeptic_transform=None,
    adjudicator_transform=None,
):
    scores = scores or {}

    def quality(task):
        result = _finding(task)
        return quality_transform(task, result) if quality_transform else result

    def skeptic(task):
        result = _finding(task)
        return skeptic_transform(task, result) if skeptic_transform else result

    def adjudicator(task):
        result = _finding(task, score=scores.get(task.question.dimension, 5))
        return adjudicator_transform(task, result) if adjudicator_transform else result

    return (
        ScriptedAnalystClient(quality),
        ScriptedAnalystClient(skeptic),
        ScriptedAnalystClient(adjudicator),
    )


def test_b01_vertical_slice_and_all_eight_roles_are_reproducible():
    normalized = _strong_input()
    clients = _clients()
    first = run_business_quality_dimension(normalized, "demand_durability", *clients)

    assert isinstance(first, DimensionResearchResult)
    assert [run.role.value for run in first.analyst_runs] == [
        "QUALITY_ANALYST",
        "SKEPTIC",
        "ADJUDICATOR",
    ]
    assert first.proposed_dimension.dimension == "demand_durability"
    assert first.proposed_dimension.score == 5
    assert first.proposed_dimension.supporting_evidence_ids
    assert first.proposed_dimension.counter_evidence_ids

    full_first = run_business_quality_research(normalized, *_clients())
    full_second = run_business_quality_research(normalized, *_clients())
    assert full_first.model_dump(mode="json") == full_second.model_dump(mode="json")
    assert full_first.business_quality.score == 40
    assert full_first.business_quality.confidence.value == "HIGH"
    assert len(full_first.dimension_runs) == 8
    assert len(full_first.analyst_runs) == 24


def _validate_research_schema(filename: str, value) -> None:
    schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value.model_dump(mode="json", warnings=False))


def test_research_artifacts_are_schema_valid_and_resume_from_workspace(tmp_path: Path):
    workspace = ResearchWorkspace(tmp_path / "research")
    workflow = ResearchOrchestrator(*_clients(), workspace=workspace).research(_strong_input())
    quality = workflow.business_quality_research
    dimension = quality.dimension_runs[0]
    packet = dimension.packets[0]
    task = dimension.tasks[0]
    run = dimension.analyst_runs[0]

    _validate_research_schema("research-question.schema.json", packet.question)
    _validate_research_schema("evidence-packet.schema.json", packet)
    _validate_research_schema("research-finding.schema.json", run.finding)
    _validate_research_schema("research-task.schema.json", task)
    _validate_research_schema("analyst-run.schema.json", run)
    _validate_research_schema("dimension-research-result.schema.json", dimension)
    _validate_research_schema("business-quality-research.schema.json", quality)
    _validate_research_schema("research-session.schema.json", workflow.session)
    _validate_research_schema("research-report.schema.json", workflow.report)
    _validate_research_schema("research-workflow-result.schema.json", workflow)
    restored = ResearchWorkflowResult.model_validate(
        workflow.model_dump(mode="python", warnings=False)
    )
    assert type(restored.decision_trace) is type(workflow.decision_trace)
    assert type(restored.report) is type(workflow.report)

    assert workflow.session.business_quality_artifact_id == quality.session_id
    assert workflow.session.final_analysis_artifact_id is not None
    assert workflow.session.final_trace_artifact_id is not None
    assert workspace.load_packet(packet.packet_id).model_dump(mode="json") == packet.model_dump(
        mode="json"
    )
    assert workspace.load_task(task.task_id).model_dump(mode="json") == task.model_dump(mode="json")
    assert workspace.load_run(run.run_id).model_dump(mode="json") == run.model_dump(mode="json")
    assert workspace.load_business_quality(quality.session_id).model_dump(
        mode="json"
    ) == quality.model_dump(mode="json")
    assert workspace.load_session(workflow.session.session_id).model_dump(
        mode="json"
    ) == workflow.session.model_dump(mode="json")
    assert workspace.load_analysis_artifact(workflow.session.final_analysis_artifact_id).model_dump(
        mode="json"
    ) == workflow.analysis.model_dump(mode="json")
    assert workspace.load_trace_artifact(workflow.session.final_trace_artifact_id).model_dump(
        mode="json"
    ) == workflow.decision_trace.model_dump(mode="json")
    assert workspace.load_report(workflow.report.report_id).model_dump(
        mode="json"
    ) == workflow.report.model_dump(mode="json")


def test_skeptic_counter_evidence_can_force_a_critical_dimension_review():
    normalized = _strong_input()
    result = run_business_quality_research(
        normalized,
        *_clients(scores={"demand_durability": 1}),
    )

    assert "demand_durability" in result.business_quality.critical_weaknesses
    gate = evaluate_business_quality_gate(
        result.business_quality,
        load_profile("strict-v1"),
        normalized_input=normalized,
    )
    assert gate.status.value in {"FAIL", "SPECIAL_REVIEW"}
    skeptic_runs = [run for run in result.analyst_runs if run.role.value == "SKEPTIC"]
    assert all(run.finding.counter_evidence_checked for run in skeptic_runs)


def test_insufficient_evidence_is_low_confidence_and_never_a_business_pass():
    normalized = _base_input()
    result = run_business_quality_research(
        normalized,
        *_clients(scores={dimension: 5 for dimension in BUSINESS_QUALITY_DIMENSIONS}),
    )

    assert result.business_quality.score == 24
    assert result.business_quality.confidence.value == "LOW"
    assert result.business_quality.flags
    gate = evaluate_business_quality_gate(
        result.business_quality,
        load_profile("strict-v1"),
        normalized_input=normalized,
    )
    assert gate.status.value == "SPECIAL_REVIEW"


def test_packet_builder_rejects_explicit_future_evidence_and_omits_it_by_default():
    normalized = _with_evidence(
        _base_input(),
        [_evidence("future-evidence", published_date=date(2026, 9, 9))],
    )
    question = build_research_question("demand_durability", ResearchIntent.THESIS)
    packet = build_evidence_packet(
        normalized,
        question=question,
        role=AnalystRole.QUALITY_ANALYST,
    )
    assert "future-evidence" not in packet.available_evidence_ids
    with pytest.raises(ValueError, match="published after as_of"):
        build_evidence_packet(
            normalized,
            question=question,
            role="QUALITY_ANALYST",
            evidence_ids=["future-evidence"],
        )


def test_hallucinated_evidence_id_is_rejected_at_typed_run_boundary():
    normalized = _strong_input()

    def hallucinate(task, result):
        from turtle_value_engine.research import EvidenceClaim

        return result.model_copy(
            update={
                "supporting_claims": [
                    EvidenceClaim(
                        id="hallucinated-claim",
                        statement="This cites evidence never supplied.",
                        evidence_ids=["evidence-that-does-not-exist"],
                        confidence=1,
                    )
                ]
            }
        )

    with pytest.raises(ResearchValidationError, match="outside"):
        run_business_quality_dimension(
            normalized,
            "demand_durability",
            *_clients(quality_transform=hallucinate),
        )


@pytest.mark.parametrize("target_field", ["capitalized_dev_already_in_capex", "not_a_source_fact"])
def test_analyst_adjustments_cannot_be_approved_or_target_unsupported_fields(target_field):
    normalized = _strong_input()
    adjustment = Adjustment(
        id="untrusted-proposal-id",
        target_field=target_field,
        target_period="AS_OF_2026-09-08",
        adjustment_type=AdjustmentType.INCLUDE,
        input_value=0.0,
        proposed_adjusted_value=10.0,
        status=AdjustmentStatus.PROPOSED,
        reason="A filing-backed proposal in a frozen test.",
        source_evidence_ids=["strong-primary-000000000000000001"],
        proposed_by="LLM",
        approved_by="HUMAN" if target_field.startswith("capitalized") else None,
        confidence=0.9,
    )

    def add_adjustment(task, result):
        return result.model_copy(update={"proposed_adjustments": [adjustment]})

    with pytest.raises(
        ResearchValidationError,
        match="cannot be approved|unsupported adjustment target",
    ):
        run_business_quality_dimension(
            normalized,
            "demand_durability",
            *_clients(quality_transform=add_adjustment),
        )


def test_adjudicator_cannot_introduce_unseen_evidence():
    normalized = _strong_input()

    def unseen(task, result):
        from turtle_value_engine.research import CounterEvidenceClaim

        return result.model_copy(
            update={
                "counter_evidence_claims": [
                    CounterEvidenceClaim(
                        id="unseen-counter",
                        statement="The adjudicator invented a new source.",
                        evidence_ids=["unseen-adjudicator-source"],
                        confidence=1,
                    )
                ]
            }
        )

    with pytest.raises(ResearchValidationError, match="outside"):
        run_business_quality_dimension(
            normalized,
            "demand_durability",
            *_clients(adjudicator_transform=unseen),
        )


def test_score_five_without_strong_evidence_is_deterministically_capped():
    normalized = _base_input()
    result = run_business_quality_research(
        normalized,
        *_clients(scores={dimension: 5 for dimension in BUSINESS_QUALITY_DIMENSIONS}),
    )

    assert result.business_quality.score == 24
    assert all(item.score == 3 for item in result.business_quality.dimension_results)
    assert any(
        "SCORE_CAPPED_INSUFFICIENT_STRONG_EVIDENCE" in flag
        for flag in result.business_quality.flags
    )


def _validate_company_analysis(analysis) -> None:
    schema = json.loads((ROOT / "schemas" / "company-analysis.schema.json").read_text())
    valuation = json.loads((ROOT / "schemas" / "valuation-result.schema.json").read_text())
    evidence = json.loads((ROOT / "schemas" / "evidence.schema.json").read_text())
    registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (valuation["$id"], Resource.from_contents(valuation)),
            (evidence["$id"], Resource.from_contents(evidence)),
        ]
    )
    Draft202012Validator(schema, registry=registry).validate(analysis.model_dump(mode="json"))


def test_frozen_a_share_provider_cache_filing_agent_analysis_and_report_e2e(tmp_path: Path):
    # Phase 2/3's injected provider is reused here; the live provider is never
    # reached and the second preparation is an offline cache replay.
    from tests.test_phase_2_3_closure import RETRIEVED_AT, FrozenAKShare, akshare_provider

    company = Company(
        name="Frozen A-share Phase 4 company",
        primary_listing="SH600000",
        sector="frozen-sector",
        reporting_currency="CNY",
    )
    request = AcquisitionRequest(
        listing_id="SH600000",
        as_of=RETRIEVED_AT.date(),
        provider="akshare",
        company=company,
    )
    raw_cache = FilesystemRawResponseCache(tmp_path / "raw")
    live_provider = FrozenAKShare()
    _, prepared = NormalizedCompanyInputBuilder(akshare_provider(live_provider), raw_cache).prepare(
        request
    )
    replay_provider = FrozenAKShare()
    replay_provider.fail = True
    bundle, replayed = NormalizedCompanyInputBuilder(
        akshare_provider(replay_provider), raw_cache
    ).prepare(request, offline=True)
    assert len(live_provider.calls) == 6
    assert replay_provider.calls == []
    assert bundle.replayable
    assert replayed.model_dump(mode="json") == prepared.model_dump(mode="json")

    from tests.test_filing_evidence_store import _candidate, _extraction

    extraction, filing_document = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    filing_store = FilingEvidenceStore(tmp_path / "filing-evidence")
    filing = filing_store.append(
        extraction,
        candidate,
        block_sequence=block_sequence,
        document=filing_document,
    )
    assert filing_store.replay(filing.id, extraction=extraction, document=filing_document) == filing
    target_fact = Fact(
        id="frozen-e2e-restricted-cash",
        field="restricted_cash",
        value=0.0,
        period="AS_OF_2026-09-12",
        source_evidence_ids=[filing.id],
        confidence=0.95,
        unit="CNY_million",
        currency="CNY",
    )
    replayed = _with_evidence(replayed, [filing], facts=[target_fact])
    proposal = Adjustment(
        id="untrusted-e2e-proposal-id",
        target_field="restricted_cash",
        target_period="AS_OF_2026-09-12",
        adjustment_type=AdjustmentType.INCLUDE,
        input_value=0.0,
        proposed_adjusted_value=20.0,
        status=AdjustmentStatus.PROPOSED,
        reason="The official filing identifies cash restricted from ordinary use.",
        source_evidence_ids=[filing.id],
        proposed_by="LLM",
        confidence=0.9,
    )

    def propose(task, result):
        if task.question.dimension == "demand_durability":
            return result.model_copy(update={"proposed_adjustments": [proposal]})
        return result

    workspace = ResearchWorkspace(tmp_path / "research")
    result = ResearchOrchestrator(
        *_clients(quality_transform=propose),
        workspace=workspace,
    ).research(replayed)
    assert result.business_quality_research.proposed_adjustments
    proposed = result.business_quality_research.proposed_adjustments[0]
    assert proposed.status is AdjustmentStatus.PROPOSED
    assert proposed.approved_by is None
    assert workspace.path_for(
        "runs", result.business_quality_research.analyst_runs[0].run_id
    ).is_file()
    assert workspace.path_for(
        "packets", result.business_quality_research.packets[0].packet_id
    ).is_file()

    workflow = AdjustmentProposalWorkflow(workspace.root)
    accepted = workflow.accept(
        proposed.id,
        actor="HUMAN",
        normalized_input=replayed,
        evidence_index=replayed.evidence_index,
    )
    assert accepted.status is AdjustmentStatus.ACCEPTED
    final = ResearchOrchestrator(
        *_clients(quality_transform=propose),
        workspace=workspace,
    ).research(replayed, accepted_adjustments=[accepted])

    _validate_company_analysis(final.analysis)
    report_schema = json.loads((ROOT / "schemas" / "research-report.schema.json").read_text())
    Draft202012Validator(report_schema).validate(final.report.model_dump(mode="json"))
    assert final.analysis.company.primary_listing == "SH600000"
    assert final.analysis.adjustments[-1].status is AdjustmentStatus.ACCEPTED
    assert final.session.final_analysis_artifact_id is not None
    assert final.session.final_trace_artifact_id is not None
    assert workspace.load_analysis_artifact(final.session.final_analysis_artifact_id).model_dump(
        mode="json"
    ) == final.analysis.model_dump(mode="json")
    assert workspace.load_trace_artifact(final.session.final_trace_artifact_id).model_dump(
        mode="json"
    ) == final.decision_trace.model_dump(mode="json")
    effective = next(fact for fact in final.analysis.facts if fact.field == "restricted_cash")
    assert effective.value == 20.0
    assert effective.source_fact_id == target_fact.id
    assert accepted.id in effective.applied_adjustment_ids
    assert filing.provenance.filing_id in {item.filing_id for item in final.decision_trace.filings}
    assert f"Final deterministic state: {final.analysis.decision.state.value}" in final.report.text


def test_report_composer_cannot_persist_a_state_that_contradicts_analysis():
    normalized = _base_input()
    workflow = ResearchOrchestrator(*_clients()).research(normalized)
    payload = workflow.report.model_dump(mode="python", warnings=False)
    payload["deterministic_state"] = (
        "PASS" if workflow.analysis.decision.state.value != "PASS" else "FAIL"
    )
    with pytest.raises(ValueError, match="contradicts"):
        type(workflow.report).model_validate(payload)

    trace_payload = workflow.report.model_dump(mode="python", warnings=False)
    trace_payload["decision_trace"]["decision_state"] = (
        "PASS"
        if workflow.analysis.decision.state.value != "PASS"
        else "FAIL"
    )
    with pytest.raises(ValueError, match="trace contradicts"):
        type(workflow.report).model_validate(trace_payload)
