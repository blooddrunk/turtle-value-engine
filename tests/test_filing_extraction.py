import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.providers import (
    FilesystemFilingDocumentCache,
    FilingDocument,
    FilingDocumentDownloader,
    FilingDocumentSourceClient,
    FilingDocumentTextParser,
    FilingExtractionRequestError,
    FilingExtractionResponseError,
    FilingMarket,
    FilingRecord,
    FilingReportExtractor,
    FilingSource,
    FilingTextBlockPayload,
    RetrievalMode,
    fetch_filing_document_with_cache,
    filing_id_for,
)

ROOT = Path(__file__).parents[1]
DISCOVERY_FIXTURE = ROOT / "fixtures" / "filings" / "discovery_a_h.json"
EXTRACTION_FIXTURE = ROOT / "fixtures" / "filings" / "extraction_payloads.json"
SCHEMA_PATH = ROOT / "schemas" / "filing-extraction.schema.json"
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


def _fixture(name: str) -> dict:
    return json.loads(EXTRACTION_FIXTURE.read_text(encoding="utf-8"))[name]


def _document(name: str) -> FilingDocument:
    filing_name = "a_cninfo" if name == "a_annual_pdf" else "h_hkexnews"
    filing_index = 0 if name == "a_annual_pdf" else 1
    payload = _fixture(name)
    content = base64.b64decode(payload["content_base64"])
    return FilingDocument(
        filing=_filing(filing_name, filing_index),
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_size=len(content),
        media_type=payload["media_type"],
        retrieved_at=RETRIEVED_AT,
    )


def _parser(name: str, seen: dict[str, object] | None = None) -> FilingDocumentTextParser:
    payload = _fixture(name)
    media_type = payload["media_type"].split(";", 1)[0]
    expected_content = base64.b64decode(payload["content_base64"])

    def parse(document: FilingDocument) -> list[dict[str, object]]:
        if seen is not None:
            seen["content"] = document.content
            seen["content_sha256"] = document.content_sha256
        assert document.content == expected_content
        return deepcopy(payload["blocks"])

    return FilingDocumentTextParser(
        media_type=media_type,
        parser_id=f"fixture-{name}",
        parser_version="1",
        parse=parse,
    )


def _extractor(seen: dict[str, object] | None = None) -> FilingReportExtractor:
    return FilingReportExtractor(
        {
            "application/pdf": _parser("a_annual_pdf", seen),
            "text/html": _parser("h_interim_html"),
        }
    )


def test_pdf_extraction_is_bounded_ordered_and_schema_valid_with_provenance():
    document = _document("a_annual_pdf")
    seen: dict[str, object] = {}
    result = _extractor(seen).extract(document)

    assert seen == {
        "content": document.content,
        "content_sha256": document.content_sha256,
    }
    assert result.filing_id == document.filing_id
    assert result.report_period == "FY2024"
    assert result.source is FilingSource.CNINFO
    assert result.document_sha256 == document.content_sha256
    assert result.media_type == "application/pdf"
    assert [block.sequence for block in result.blocks] == [1, 2, 3]
    assert [block.page for block in result.blocks] == [1, 2, 2]
    assert all(block.section is None for block in result.blocks)
    assert result.blocks[0].text_sha256 == hashlib.sha256(
        result.blocks[0].text.encode("utf-8")
    ).hexdigest()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))


def test_html_extraction_preserves_section_locations_and_h_report_provenance():
    document = _document("h_interim_html")
    result = _extractor().extract(document)

    assert result.filing_id == document.filing_id
    assert result.listing_id == "HK00700"
    assert result.report_period == "H1FY2025"
    assert result.source is FilingSource.HKEXNEWS
    assert result.media_type == "text/html"
    assert [block.sequence for block in result.blocks] == [1, 2]
    assert [block.section for block in result.blocks] == [
        "/html/body/section[1]",
        "/html/body/section[2]",
    ]
    assert all(block.page is None for block in result.blocks)


def test_cached_offline_replay_can_be_extracted_without_downloader_network(tmp_path: Path):
    document = _document("a_annual_pdf")
    calls: list[FilingRecord] = []

    def download(filing: FilingRecord) -> dict[str, object]:
        calls.append(filing)
        return {
            "content": document.content,
            "media_type": document.media_type,
            "response_metadata": {"fixture": True},
        }

    downloader = FilingDocumentDownloader(
        {
            document.source: FilingDocumentSourceClient(
                source=document.source,
                download=download,
            )
        },
        clock=lambda: RETRIEVED_AT,
    )
    cache = FilesystemFilingDocumentCache(tmp_path)
    extractor = _extractor()
    live = fetch_filing_document_with_cache(downloader, document.filing, cache)
    live_result = extractor.extract(live.document)
    calls.clear()

    replay = fetch_filing_document_with_cache(
        downloader,
        document.filing,
        cache,
        offline=True,
    )
    replay_result = extractor.extract(replay.document)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay_result == live_result
    assert replay_result.content_sha256 == document.content_sha256
    assert calls == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("page_order", "non-decreasing page"),
        ("sequence", "contiguous source order"),
        ("location_kind", "page locations only"),
        ("extra_provenance", "Extra|extra"),
    ],
)
def test_pdf_parser_rejects_malformed_order_location_and_provenance(
    mutation: str,
    message: str,
):
    blocks = deepcopy(_fixture("a_annual_pdf")["blocks"])
    if mutation == "page_order":
        blocks[1]["page"], blocks[2]["page"] = 3, 2
    elif mutation == "sequence":
        blocks[1]["sequence"] = 3
    elif mutation == "location_kind":
        blocks[0]["page"] = None
        blocks[0]["section"] = "/html/body/section[1]"
    else:
        blocks[0]["filing_id"] = "filing-forbidden"

    parser = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id="adversarial",
        parser_version="1",
        parse=lambda _document: blocks,
    )
    extractor = FilingReportExtractor({"application/pdf": parser})

    with pytest.raises(FilingExtractionResponseError, match=message):
        extractor.extract(_document("a_annual_pdf"))


@pytest.mark.parametrize(
    "media_type",
    ["application/octet-stream", "text/plain", "image/png"],
)
def test_unsupported_media_is_rejected_even_without_a_parser(media_type: str):
    original = _document("a_annual_pdf")
    document = FilingDocument(
        filing=original.filing,
        content=original.content,
        content_sha256=original.content_sha256,
        content_size=original.content_size,
        media_type=media_type,
        retrieved_at=original.retrieved_at,
    )

    with pytest.raises(FilingExtractionRequestError, match="unsupported"):
        _extractor().extract(document)


def test_supported_media_without_injected_parser_fails_closed():
    with pytest.raises(FilingExtractionRequestError, match="no parser configured"):
        FilingReportExtractor({}).extract(_document("a_annual_pdf"))


def test_empty_parser_output_and_parser_failure_are_not_successful_extractions():
    empty = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id="empty",
        parser_version="1",
        parse=lambda _document: [],
    )
    with pytest.raises(FilingExtractionResponseError, match="no text blocks"):
        FilingReportExtractor({"application/pdf": empty}).extract(_document("a_annual_pdf"))

    def fail(_document: FilingDocument) -> object:
        raise RuntimeError("parser failure")

    failing = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id="failing",
        parser_version="1",
        parse=fail,
    )
    with pytest.raises(FilingExtractionResponseError, match="parser .* failed"):
        FilingReportExtractor({"application/pdf": failing}).extract(_document("a_annual_pdf"))


def test_extraction_revalidates_document_hash_and_result_provenance():
    document = _document("a_annual_pdf")
    extractor = _extractor()
    result = extractor.extract(document)

    tampered_result = result.model_copy(update={"content_sha256": "0" * 64})
    with pytest.raises(FilingExtractionResponseError, match="content_sha256"):
        extractor.validate(tampered_result, document)

    other_filing = _filing("a_cninfo", index=1)
    wrong_provenance = result.model_copy(update={"filing": other_filing})
    with pytest.raises(FilingExtractionResponseError, match="provenance"):
        extractor.validate(wrong_provenance, document)

    out_of_order_page = result.model_copy(
        update={
            "blocks": (
                result.blocks[0],
                result.blocks[1].model_copy(update={"page": 3}),
                result.blocks[2],
            )
        }
    )
    with pytest.raises(FilingExtractionResponseError, match="page order"):
        extractor.validate(out_of_order_page, document)

    object.__setattr__(document, "content", b"tampered bytes")
    with pytest.raises(FilingExtractionRequestError, match="invalid filing extraction request"):
        extractor.extract(document)


def test_extraction_bounds_fail_closed_without_truncating_parser_output():
    blocks = deepcopy(_fixture("a_annual_pdf")["blocks"])
    bounded_parser = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id="bounded",
        parser_version="1",
        parse=lambda _document: blocks,
    )
    with pytest.raises(FilingExtractionResponseError, match="max_blocks"):
        FilingReportExtractor(
            {"application/pdf": bounded_parser},
            max_blocks=2,
        ).extract(_document("a_annual_pdf"))

    too_long = deepcopy(blocks[:1])
    too_long[0]["text"] = "long text"
    with pytest.raises(FilingExtractionResponseError, match="max_block_chars"):
        FilingReportExtractor(
            {
                "application/pdf": FilingDocumentTextParser(
                    media_type="application/pdf",
                    parser_id="bounded-text",
                    parser_version="1",
                    parse=lambda _document: too_long,
                )
            },
            max_block_chars=4,
        ).extract(_document("a_annual_pdf"))


def test_payload_model_is_strict_and_does_not_admit_accounting_or_provenance_fields():
    with pytest.raises((TypeError, ValueError)):
        FilingTextBlockPayload.model_validate(
            {
                "sequence": 1,
                "page": 1,
                "text": "text",
                "reported_revenue": 123,
            }
        )


@pytest.mark.parametrize("mode", ["iterator", "utf8"])
def test_parser_boundary_wraps_iterator_and_text_encoding_failures(mode: str):
    if mode == "iterator":

        class BrokenBlocks:
            def __iter__(self):
                raise RuntimeError("iterator failure")

        def parse(_document):
            return BrokenBlocks()
    else:

        def parse(_document):
            return [{"sequence": 1, "page": 1, "text": "contains lone surrogate \ud800"}]

    parser = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id=f"broken-{mode}",
        parser_version="1",
        parse=parse,
    )
    with pytest.raises(FilingExtractionResponseError, match="parser|invalid parser text block"):
        FilingReportExtractor({"application/pdf": parser}).extract(_document("a_annual_pdf"))
