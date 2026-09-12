import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.models import Evidence
from turtle_value_engine.providers import (
    EvidenceStoreConflictError,
    EvidenceStoreCorruptionError,
    EvidenceStoreMissError,
    EvidenceStoreRequestError,
    FilingDocument,
    FilingDocumentTextParser,
    FilingEvidenceStore,
    FilingExtractionResult,
    FilingMarket,
    FilingRecord,
    FilingReportExtractor,
    FilingSource,
    filing_evidence_id_for,
    filing_id_for,
)

ROOT = Path(__file__).parents[1]
DISCOVERY_FIXTURE = ROOT / "fixtures" / "filings" / "discovery_a_h.json"
EXTRACTION_FIXTURE = ROOT / "fixtures" / "filings" / "extraction_payloads.json"
EVIDENCE_FIXTURE = ROOT / "fixtures" / "filings" / "evidence_store_payloads.json"
SCHEMA_PATH = ROOT / "schemas" / "filing-evidence.schema.json"
RETRIEVED_AT = datetime(2026, 9, 12, 5, 6, 7, tzinfo=UTC)


def _filing(name: str, index: int = 0) -> FilingRecord:
    discovery = json.loads(DISCOVERY_FIXTURE.read_text(encoding="utf-8"))[name]
    descriptor = deepcopy(discovery["filings"][index])
    listing_id = discovery["listing_id"]
    market = FilingMarket.H if listing_id.startswith("HK") else FilingMarket.A
    source = FilingSource(discovery["source"])
    return FilingRecord(
        filing_id=filing_id_for(
            listing_id=listing_id,
            market=market,
            source=source,
            source_document_id=descriptor.get("source_document_id"),
            url=descriptor["url"],
        ),
        listing_id=listing_id,
        market=market,
        source=source,
        **descriptor,
    )


def _payload(name: str) -> dict:
    return json.loads(EXTRACTION_FIXTURE.read_text(encoding="utf-8"))[name]


def _evidence_payload(name: str) -> dict:
    return json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))[name]


def _document(name: str) -> FilingDocument:
    filing_name = "a_cninfo" if name == "a_annual_pdf" else "h_hkexnews"
    filing_index = 0 if name == "a_annual_pdf" else 1
    payload = _payload(name)
    content = base64.b64decode(payload["content_base64"])
    return FilingDocument(
        filing=_filing(filing_name, filing_index),
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_size=len(content),
        media_type=payload["media_type"],
        retrieved_at=RETRIEVED_AT,
    )


def _extraction(name: str) -> tuple[FilingExtractionResult, FilingDocument]:
    document = _document(name)
    payload = _payload(name)

    def parse(_document: FilingDocument) -> list[dict[str, object]]:
        return deepcopy(payload["blocks"])

    media_type = payload["media_type"].split(";", 1)[0]
    parser = FilingDocumentTextParser(
        media_type=media_type,
        parser_id=f"fixture-{name}",
        parser_version="1",
        parse=parse,
    )
    return FilingReportExtractor({media_type: parser}).extract(document), document


def _candidate(name: str) -> tuple[dict, int]:
    payload = _evidence_payload(name)
    return deepcopy(payload["evidence"]), payload["block_sequence"]


def test_append_binds_a_share_evidence_to_exact_pdf_block_and_schema(tmp_path: Path):
    extraction, document = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    store = FilingEvidenceStore(tmp_path)

    evidence = store.append(
        extraction,
        candidate,
        block_sequence=block_sequence,
        document=document,
    )

    block = extraction.blocks[block_sequence - 1]
    assert evidence.id == filing_evidence_id_for(extraction, candidate, block_sequence)
    assert evidence.source.document_id == "cninfo-600000-2024-annual"
    assert evidence.source.fiscal_period == "FY2024"
    assert evidence.source.page == block.page
    assert evidence.source.section is None
    assert evidence.source.locator == f"block:{block_sequence}"
    assert evidence.provenance is not None
    assert evidence.provenance.filing_id == extraction.filing_id
    assert evidence.provenance.filing_source == "CNINFO"
    assert evidence.provenance.content_sha256 == document.content_sha256
    assert evidence.provenance.parser_id == extraction.parser_id
    assert evidence.provenance.block_sha256 == block.text_sha256

    record = store.read_record(evidence.id, extraction=extraction, document=document)
    assert record is not None
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(record.model_dump(mode="json"))


def test_h_share_html_evidence_preserves_section_and_hkex_provenance(tmp_path: Path):
    extraction, _document_value = _extraction("h_interim_html")
    candidate, block_sequence = _candidate("h_interim_counter")
    evidence = FilingEvidenceStore(tmp_path).append(
        extraction,
        candidate,
        block_sequence=block_sequence,
    )

    assert evidence.source.type.value == "INTERIM_REPORT"
    assert evidence.source.document_id == "HKEX-2025081300456"
    assert evidence.source.page is None
    assert evidence.source.section == "/html/body/section[2]"
    assert evidence.source.url is not None
    assert "hkexnews.hk" in str(evidence.source.url)
    assert evidence.provenance is not None
    assert evidence.provenance.filing_source == "HKEXNEWS"
    assert evidence.provenance.report_period == "H1FY2025"


def test_append_is_idempotent_and_lookup_replay_are_offline_and_deterministic(tmp_path: Path):
    extraction, _document_value = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    store = FilingEvidenceStore(tmp_path)

    first = store.append(extraction, candidate, block_sequence=block_sequence)
    second = store.upsert(extraction, candidate, block_sequence=block_sequence)

    assert second == first
    assert store.replay(first.id, extraction=extraction) == first
    assert store.lookup(extraction=extraction) == (first,)
    assert store.lookup(filing_id=extraction.filing_id) == (first,)
    assert store.lookup(content_sha256=extraction.content_sha256) == (first,)
    assert store.lookup(extraction=extraction, block_sequence=block_sequence) == (first,)
    assert sorted(path.name for path in (tmp_path / "evidence").iterdir()) == [
        f"{first.id}.json"
    ]


def test_missing_id_is_generated_but_supplied_non_deterministic_id_is_rejected(tmp_path: Path):
    extraction, _document_value = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    store = FilingEvidenceStore(tmp_path)

    generated = store.append(extraction, candidate, block_sequence=block_sequence)
    assert generated.id.startswith("filing-evidence-")

    conflicting = deepcopy(candidate)
    conflicting["id"] = "caller-chosen-id"
    with pytest.raises(EvidenceStoreRequestError, match="deterministic"):
        store.append(extraction, conflicting, block_sequence=block_sequence)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("document_id", "wrong-document", "document_id"),
        ("url", "https://example.invalid/wrong.pdf", "url"),
        ("page", 99, "page"),
        ("locator", "block:99", "locator"),
        ("fiscal_period", "FY1900", "fiscal_period"),
    ],
)
def test_wrong_source_references_are_rejected(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
):
    extraction, _document_value = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    candidate["source"][field] = value

    with pytest.raises(EvidenceStoreRequestError, match=message):
        FilingEvidenceStore(tmp_path).append(
            extraction,
            candidate,
            block_sequence=block_sequence,
        )


def test_wrong_html_page_reference_and_wrong_provenance_are_rejected(tmp_path: Path):
    extraction, _document_value = _extraction("h_interim_html")
    candidate, block_sequence = _candidate("h_interim_counter")
    candidate["source"]["page"] = 1

    with pytest.raises(EvidenceStoreRequestError, match="page"):
        FilingEvidenceStore(tmp_path).append(
            extraction,
            candidate,
            block_sequence=block_sequence,
        )

    candidate, block_sequence = _candidate("h_interim_counter")
    candidate["provenance"] = {
        "filing_id": extraction.filing_id,
        "filing_source": "CNINFO",
        "source_document_id": extraction.source_document_id,
        "report_period": extraction.report_period,
        "content_sha256": extraction.content_sha256,
        "content_size": extraction.content_size,
        "media_type": extraction.media_type,
        "extraction_contract": extraction.contract,
        "parser_id": extraction.parser_id,
        "parser_version": extraction.parser_version,
        "block_sequence": block_sequence,
        "block_sha256": extraction.blocks[block_sequence - 1].text_sha256,
    }
    with pytest.raises(EvidenceStoreRequestError, match="provenance"):
        FilingEvidenceStore(tmp_path).append(
            extraction,
            candidate,
            block_sequence=block_sequence,
        )


def test_tampered_extraction_or_document_hash_cannot_be_stored(tmp_path: Path):
    extraction, document = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")

    tampered_extraction = extraction.model_copy(update={"content_sha256": "0" * 64})
    with pytest.raises(EvidenceStoreRequestError, match="content_sha256"):
        FilingEvidenceStore(tmp_path).append(
            tampered_extraction,
            candidate,
            block_sequence=block_sequence,
            document=document,
        )

    object.__setattr__(document, "content", b"tampered document")
    with pytest.raises(EvidenceStoreRequestError, match="invalid filing document"):
        FilingEvidenceStore(tmp_path).append(
            extraction,
            candidate,
            block_sequence=block_sequence,
            document=document,
        )


def test_same_deterministic_id_with_changed_statement_is_a_conflict(tmp_path: Path):
    extraction, _document_value = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    store = FilingEvidenceStore(tmp_path)
    first = store.append(extraction, candidate, block_sequence=block_sequence)

    changed = deepcopy(candidate)
    changed["confidence"] = 0.4
    changed["id"] = first.id
    with pytest.raises(EvidenceStoreConflictError, match="different record"):
        store.append(extraction, changed, block_sequence=block_sequence)


def test_corrupt_replay_hash_and_json_are_detected(tmp_path: Path):
    extraction, _document_value = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    store = FilingEvidenceStore(tmp_path)
    evidence = store.append(extraction, candidate, block_sequence=block_sequence)
    path = store.path_for(evidence.id)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence"]["statement"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        EvidenceStoreCorruptionError,
        match="hash mismatch|deterministic store identity",
    ):
        store.replay(evidence.id)

    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(EvidenceStoreCorruptionError, match="invalid"):
        store.replay(evidence.id)


def test_replay_of_missing_evidence_is_explicit(tmp_path: Path):
    with pytest.raises(EvidenceStoreMissError, match="no replayable"):
        FilingEvidenceStore(tmp_path).replay("filing-evidence-" + "0" * 24)

    with pytest.raises(EvidenceStoreRequestError, match="invalid filing evidence ID"):
        FilingEvidenceStore(tmp_path).replay("not-an-evidence-id")


def test_lookup_requires_a_complete_filing_id_format(tmp_path: Path):
    with pytest.raises(EvidenceStoreRequestError, match="filing_id"):
        FilingEvidenceStore(tmp_path).lookup(filing_id="filing-not-complete")


def test_store_rejects_wrong_extraction_on_replay(tmp_path: Path):
    extraction, _document_value = _extraction("a_annual_pdf")
    other_extraction, _other_document = _extraction("h_interim_html")
    candidate, block_sequence = _candidate("a_annual_support")
    store = FilingEvidenceStore(tmp_path)
    evidence = store.append(extraction, candidate, block_sequence=block_sequence)

    with pytest.raises(EvidenceStoreRequestError, match="does not match"):
        store.replay(evidence.id, extraction=other_extraction)


def test_evidence_schema_accepts_filing_provenance_and_existing_evidence_stays_compatible(
    tmp_path: Path,
):
    extraction, _document_value = _extraction("a_annual_pdf")
    candidate, block_sequence = _candidate("a_annual_support")
    evidence = FilingEvidenceStore(tmp_path).append(
        extraction,
        candidate,
        block_sequence=block_sequence,
    )
    evidence_schema = json.loads((ROOT / "schemas" / "evidence.schema.json").read_text())
    Draft202012Validator.check_schema(evidence_schema)
    Draft202012Validator(evidence_schema).validate(evidence.model_dump(mode="json"))
    Draft202012Validator(evidence_schema).validate(
        Evidence(
            id="legacy-evidence",
            direction="CONTEXT",
            strength="E0",
            statement="Legacy structured evidence remains valid.",
            source={"type": "OTHER", "title": "Legacy source"},
            confidence=0.5,
        ).model_dump(mode="json")
    )
