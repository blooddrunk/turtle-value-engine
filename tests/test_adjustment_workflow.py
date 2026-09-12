import hashlib
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.adjustments import (
    AdjustmentProposalWorkflow,
    adjustment_id_for,
)
from turtle_value_engine.input_loader import load_normalized_input
from turtle_value_engine.models import Evidence, NormalizedCompanyInput
from turtle_value_engine.models.common import AdjustmentStatus
from turtle_value_engine.providers import (
    AdjustmentWorkflowConflictError,
    AdjustmentWorkflowCorruptionError,
    AdjustmentWorkflowMissError,
    AdjustmentWorkflowRequestError,
    AdjustmentWorkflowTransitionError,
    FilingDocument,
    FilingDocumentTextParser,
    FilingEvidenceStore,
    FilingMarket,
    FilingRecord,
    FilingReportExtractor,
    FilingSource,
    filing_id_for,
)

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "adjustments" / "adjustment_workflow_payloads.json"
SCHEMA_PATH = ROOT / "schemas" / "adjustment-workflow.schema.json"
RETRIEVED_AT = datetime(2026, 9, 12, 5, 6, 7, tzinfo=UTC)


def _fixture(name: str) -> tuple[Evidence, dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[name]
    return Evidence.model_validate(payload["evidence"]), deepcopy(payload["proposal"])


def _filing_evidence_store(root: Path) -> tuple[FilingEvidenceStore, Evidence]:
    content = b"Synthetic annual filing text for adjustment provenance."
    filing = FilingRecord(
        filing_id=filing_id_for(
            listing_id="SH600000",
            market=FilingMarket.A,
            source=FilingSource.CNINFO,
            source_document_id="cninfo-adjustment-2024",
            url="https://static.cninfo.com.cn/adjustment-2024.pdf",
        ),
        listing_id="SH600000",
        market=FilingMarket.A,
        source=FilingSource.CNINFO,
        title="Synthetic adjustment annual report",
        document_type="ANNUAL_REPORT",
        published_date=date(2025, 3, 31),
        url="https://static.cninfo.com.cn/adjustment-2024.pdf",
        source_document_id="cninfo-adjustment-2024",
        report_period="FY2024",
        issuer_name="Synthetic A issuer",
    )
    document = FilingDocument(
        filing=filing,
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_size=len(content),
        media_type="application/pdf",
        retrieved_at=RETRIEVED_AT,
    )
    parser = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id="fixture-adjustment-parser",
        parser_version="1",
        parse=lambda _document: [
            {"sequence": 1, "page": 7, "text": "Synthetic annual filing disclosure."}
        ],
    )
    extraction = FilingReportExtractor({"application/pdf": parser}).extract(document)
    evidence = FilingEvidenceStore(root / "evidence").append(
        extraction,
        {
            "direction": "SUPPORT",
            "strength": "E3",
            "statement": "The filing provides the proposed adjustment evidence.",
            "source": {"type": "ANNUAL_REPORT", "title": filing.title},
            "confidence": 0.95,
        },
        block_sequence=1,
        document=document,
    )
    return FilingEvidenceStore(root / "evidence"), evidence


def test_append_is_deterministic_idempotent_and_schema_valid(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)

    first = workflow.append(proposal, evidence_index=[evidence])
    second = workflow.upsert(proposal, evidence_index=[evidence])

    assert first == second
    assert first.id == adjustment_id_for(proposal)
    assert first.status is AdjustmentStatus.PROPOSED
    record = workflow.read_record(first.id)
    assert record is not None
    assert record.evidence_bindings[0].evidence_id == evidence.id
    assert record.transition_history[0].action == "PROPOSE"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(record.model_dump(mode="json"))


def test_a_and_h_filing_evidence_can_back_proposals(tmp_path: Path):
    workflow = AdjustmentProposalWorkflow(tmp_path)
    a_evidence, a_proposal = _fixture("a_annual_proposal")
    h_evidence, h_proposal = _fixture("h_interim_proposal")

    a_adjustment = workflow.append(a_proposal, evidence_index=[a_evidence])
    h_adjustment = workflow.append(h_proposal, evidence_index=[h_evidence])

    assert workflow.read(a_adjustment.id).source_evidence_ids == [a_evidence.id]
    assert workflow.read(h_adjustment.id).source_evidence_ids == [h_evidence.id]
    assert {a_evidence.source.type.value, h_evidence.source.type.value} == {
        "ANNUAL_REPORT",
        "INTERIM_REPORT",
    }
    assert {item.id for item in workflow.lookup()} == {a_adjustment.id, h_adjustment.id}


def test_filing_evidence_store_provenance_and_record_hash_are_retained(tmp_path: Path):
    evidence_store, evidence = _filing_evidence_store(tmp_path)
    workflow = AdjustmentProposalWorkflow(tmp_path / "adjustments")
    proposal = {
        "target_field": "restricted_cash",
        "adjustment_type": "HAIRCUT",
        "status": "PROPOSED",
        "reason": "Review the filing disclosure before considering a haircut.",
        "source_evidence_ids": [evidence.id],
        "proposed_by": "HUMAN",
        "confidence": 0.9,
    }

    adjustment = workflow.append(proposal, evidence_store=evidence_store)
    record = workflow.read_record(adjustment.id, evidence_store=evidence_store)

    assert record is not None
    assert record.evidence_bindings[0].evidence_store_record_sha256 is not None
    assert evidence.provenance is not None
    assert evidence.provenance.filing_id.startswith("filing-")
    accepted = workflow.accept(adjustment.id, actor="HUMAN", evidence_store=evidence_store)
    assert accepted.approved_by.value == "HUMAN"


def test_unknown_duplicate_and_missing_evidence_references_are_rejected(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)

    unknown = deepcopy(proposal)
    unknown["source_evidence_ids"] = ["ev-does-not-exist"]
    with pytest.raises(AdjustmentWorkflowRequestError, match="unknown evidence ID"):
        workflow.append(unknown, evidence_index=[evidence])

    duplicate = deepcopy(proposal)
    duplicate["source_evidence_ids"] = [evidence.id, evidence.id]
    with pytest.raises(AdjustmentWorkflowRequestError, match="duplicates"):
        workflow.append(duplicate, evidence_index=[evidence])

    with pytest.raises(AdjustmentWorkflowRequestError, match="resolver"):
        workflow.append(proposal)


def test_conflicting_evidence_for_same_proposal_id_is_rejected(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)
    first = workflow.append(proposal, evidence_index=[evidence])

    changed_evidence = evidence.model_copy(
        update={"statement": "A conflicting statement uses the same evidence ID."}
    )
    conflicting = deepcopy(proposal)
    conflicting["id"] = first.id
    with pytest.raises(AdjustmentWorkflowConflictError, match="different proposal"):
        workflow.append(conflicting, evidence_index=[changed_evidence])


def test_proposer_must_match_existing_adjustment_contract(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    with pytest.raises(AdjustmentWorkflowRequestError, match="proposer"):
        AdjustmentProposalWorkflow(tmp_path).append(
            proposal,
            proposer="RULE_ENGINE",
            evidence_index=[evidence],
        )


def test_creation_rejects_accepted_without_approval_and_non_proposed_status(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)

    accepted = deepcopy(proposal)
    accepted["status"] = "ACCEPTED"
    with pytest.raises(AdjustmentWorkflowRequestError, match="approved_by"):
        workflow.append(accepted, evidence_index=[evidence])

    rejected = deepcopy(proposal)
    rejected["status"] = "REJECTED"
    with pytest.raises(AdjustmentWorkflowRequestError, match="only PROPOSED"):
        workflow.append(rejected, evidence_index=[evidence])


def test_accept_and_reject_require_valid_review_actor_and_are_terminal(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)
    adjustment = workflow.append(proposal, evidence_index=[evidence])

    with pytest.raises(AdjustmentWorkflowRequestError, match="HUMAN or RULE_ENGINE"):
        workflow.accept(adjustment.id, actor="LLM")
    with pytest.raises(AdjustmentWorkflowRequestError, match="HUMAN or RULE_ENGINE"):
        workflow.reject(adjustment.id, actor="LLM")

    accepted = workflow.accept(adjustment.id, actor="HUMAN")
    assert accepted.id == adjustment.id
    assert accepted.status is AdjustmentStatus.ACCEPTED
    assert accepted.approved_by.value == "HUMAN"
    assert workflow.read_record(accepted.id).transition_history[-1].action == "ACCEPT"
    with pytest.raises(AdjustmentWorkflowTransitionError, match="terminal"):
        workflow.reject(accepted.id, actor="RULE_ENGINE")


def test_rejection_is_explicit_and_does_not_gain_an_approver(tmp_path: Path):
    evidence, proposal = _fixture("h_interim_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)
    adjustment = workflow.append(proposal, evidence_index=[evidence])

    rejected = workflow.reject(adjustment.id, actor="RULE_ENGINE")
    assert rejected.status is AdjustmentStatus.REJECTED
    assert rejected.approved_by is None
    record = workflow.read_record(rejected.id)
    assert record is not None
    assert record.transition_history[-1].model_dump(mode="json") == {
        "action": "REJECT",
        "status": "REJECTED",
        "actor": "RULE_ENGINE",
    }


def test_normalized_input_scope_is_bound_and_remains_compatible(tmp_path: Path):
    normalized = load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    evidence = normalized.evidence_index[0]
    proposal = {
        "target_field": "restricted_cash",
        "adjustment_type": "HAIRCUT",
        "status": "PROPOSED",
        "reason": "An explicit review proposal remains separate from engine values.",
        "source_evidence_ids": [evidence.id],
        "proposed_by": "HUMAN",
        "confidence": 0.7,
    }
    workflow = AdjustmentProposalWorkflow(tmp_path)
    adjustment = workflow.append(proposal, normalized_input=normalized)

    assert normalized.adjustments == load_normalized_input(
        ROOT / "fixtures" / "healthy_cash_cow.json"
    ).adjustments
    compatible_payload = normalized.model_dump(mode="python")
    compatible_payload["adjustments"] = [*compatible_payload["adjustments"], adjustment]
    compatible = NormalizedCompanyInput.model_validate(compatible_payload)
    assert compatible.adjustments[-1].id == adjustment.id
    assert workflow.replay(adjustment.id, normalized_input=normalized) == adjustment

    different_scope = normalized.model_dump(mode="python")
    different_scope["analysis_id"] = "different-analysis"
    different_input = NormalizedCompanyInput.model_validate(different_scope)
    with pytest.raises(AdjustmentWorkflowRequestError, match="scope"):
        workflow.replay(adjustment.id, normalized_input=different_input)


def test_deterministic_identity_changes_for_immutable_proposal_content(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    first_id = adjustment_id_for(proposal)
    changed = deepcopy(proposal)
    changed["proposed_adjusted_value"] = 25.0
    assert adjustment_id_for(changed) != first_id

    wrong_id = deepcopy(proposal)
    wrong_id["id"] = "caller-chosen-adjustment"
    with pytest.raises(AdjustmentWorkflowRequestError, match="deterministic"):
        AdjustmentProposalWorkflow(tmp_path).append(wrong_id, evidence_index=[evidence])


def test_tampered_hash_and_malformed_replay_are_detected(tmp_path: Path):
    evidence, proposal = _fixture("a_annual_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)
    adjustment = workflow.append(proposal, evidence_index=[evidence])
    path = workflow.path_for(adjustment.id)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["adjustment"]["reason"] = "Tampered after persistence."
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AdjustmentWorkflowCorruptionError, match="hash mismatch|invalid"):
        workflow.replay(adjustment.id)

    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(AdjustmentWorkflowCorruptionError, match="invalid"):
        workflow.replay(adjustment.id)


def test_tampered_filing_evidence_is_rejected_when_rebound(tmp_path: Path):
    evidence_store, evidence = _filing_evidence_store(tmp_path)
    workflow = AdjustmentProposalWorkflow(tmp_path / "adjustments")
    proposal = {
        "target_field": "restricted_cash",
        "adjustment_type": "HAIRCUT",
        "status": "PROPOSED",
        "reason": "Verify the filing evidence before review.",
        "source_evidence_ids": [evidence.id],
        "proposed_by": "HUMAN",
        "confidence": 0.8,
    }
    adjustment = workflow.append(proposal, evidence_store=evidence_store)
    evidence_path = evidence_store.path_for(evidence.id)
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_payload["evidence"]["statement"] = "Tampered filing evidence."
    evidence_path.write_text(json.dumps(evidence_payload), encoding="utf-8")

    with pytest.raises(AdjustmentWorkflowCorruptionError, match="referenced evidence"):
        workflow.replay(adjustment.id, evidence_store=evidence_store)


def test_lookup_replays_a_generator_once_for_all_records(tmp_path: Path):
    a_evidence, a_proposal = _fixture("a_annual_proposal")
    h_evidence, h_proposal = _fixture("h_interim_proposal")
    workflow = AdjustmentProposalWorkflow(tmp_path)
    workflow.append(a_proposal, evidence_index=[a_evidence])
    workflow.append(h_proposal, evidence_index=[h_evidence])

    records = workflow.lookup(evidence_index=(item for item in [a_evidence, h_evidence]))
    assert len(records) == 2


def test_missing_replay_and_invalid_path_ids_are_explicit(tmp_path: Path):
    workflow = AdjustmentProposalWorkflow(tmp_path)
    missing_id = "adjustment-proposal-" + "0" * 24
    with pytest.raises(AdjustmentWorkflowMissError, match="no replayable"):
        workflow.replay(missing_id)
    with pytest.raises(AdjustmentWorkflowRequestError, match="invalid adjustment ID"):
        workflow.replay("not-an-adjustment-id")
