import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.providers import (
    CacheCorruptionError,
    CacheMissError,
    CacheWriteError,
    FilesystemFilingDocumentCache,
    FilingDocument,
    FilingDocumentDownloader,
    FilingDocumentRequestError,
    FilingDocumentResponseError,
    FilingDocumentSourceClient,
    FilingDownloadPayload,
    FilingMarket,
    FilingRecord,
    FilingSource,
    RetrievalMode,
    fetch_filing_document_with_cache,
    filing_id_for,
)

ROOT = Path(__file__).parents[1]
DISCOVERY_FIXTURE = ROOT / "fixtures" / "filings" / "discovery_a_h.json"
DOCUMENT_FIXTURE = ROOT / "fixtures" / "filings" / "document_payloads.json"
SCHEMA_PATH = ROOT / "schemas" / "filing-document.schema.json"
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


def _download_payload(name: str) -> dict:
    payload = json.loads(DOCUMENT_FIXTURE.read_text(encoding="utf-8"))[name]
    return {
        "content": base64.b64decode(payload["content_base64"]),
        "media_type": payload["media_type"],
        "response_metadata": payload["response_metadata"],
    }


def _downloader(
    filing: FilingRecord,
    name: str,
    calls: list[FilingRecord] | None = None,
    response: object | None = None,
    *,
    max_bytes: int = 50 * 1024 * 1024,
) -> FilingDocumentDownloader:
    def download(received: FilingRecord) -> object:
        if calls is not None:
            calls.append(received)
        return _download_payload(name) if response is None else response

    client = FilingDocumentSourceClient(source=filing.source, download=download)
    return FilingDocumentDownloader(
        {filing.source: client},
        clock=lambda: RETRIEVED_AT,
        max_bytes=max_bytes,
    )


def test_live_download_hashes_bytes_and_preserves_filing_provenance():
    filing = _filing("a_cninfo")
    calls: list[FilingRecord] = []
    document = _downloader(filing, "a_cninfo", calls).download(filing)
    content = base64.b64decode(
        json.loads(DOCUMENT_FIXTURE.read_text(encoding="utf-8"))["a_cninfo"]["content_base64"]
    )

    assert calls == [filing]
    assert document.filing == filing
    assert document.filing_id == filing.filing_id
    assert document.source is FilingSource.CNINFO
    assert document.content == content
    assert document.content_sha256 == hashlib.sha256(content).hexdigest()
    assert document.content_size == len(content)
    assert document.media_type == "application/pdf"
    assert document.retrieved_at == RETRIEVED_AT
    assert document.retrieval_metadata["contract"] == "filing_document_v1"
    assert document.retrieval_metadata["transport"]["http_status"] == 200


def test_h_share_download_normalizes_media_type_and_keeps_h_scope():
    filing = _filing("h_hkexnews", index=1)
    document = _downloader(filing, "h_hkexnews").download(filing)

    assert document.market is FilingMarket.H
    assert document.source is FilingSource.HKEXNEWS
    assert document.media_type == "text/html"
    assert document.retrieval_metadata["market"] == "H"
    assert document.retrieval_metadata["source"] == "HKEXNEWS"


@pytest.mark.parametrize(
    "mutated",
    [
        "https://documents.example.invalid/report.pdf",
        "https://cninfo.com.cn.evil.example/report.pdf",
    ],
)
def test_download_revalidates_mutated_filing_url_boundary(mutated: str):
    original = _filing("a_cninfo")
    mutated_filing = original.model_copy(update={"url": mutated})
    downloader = _downloader(original, "a_cninfo")

    with pytest.raises(FilingDocumentRequestError, match="invalid filing document request"):
        downloader.download(mutated_filing)


def test_download_rejects_out_of_scope_redirect_and_invalid_payload():
    filing = _filing("a_cninfo")
    outside = _download_payload("a_cninfo") | {
        "final_url": "https://documents.example.invalid/report.pdf"
    }
    with pytest.raises(FilingDocumentResponseError, match="provenance"):
        _downloader(filing, "a_cninfo", response=outside).download(filing)

    invalid_media = _download_payload("a_cninfo") | {"media_type": "not-a-media-type"}
    with pytest.raises(FilingDocumentResponseError, match="invalid .* response"):
        _downloader(filing, "a_cninfo", response=invalid_media).download(filing)


def test_download_enforces_injected_size_limit_and_rejects_empty_bytes():
    filing = _filing("a_cninfo")
    payload = _download_payload("a_cninfo")
    with pytest.raises(FilingDocumentResponseError, match="max_bytes"):
        _downloader(filing, "a_cninfo", response=payload, max_bytes=1).download(filing)

    empty = payload | {"content": b""}
    with pytest.raises(FilingDocumentResponseError, match="invalid .* response"):
        _downloader(filing, "a_cninfo", response=empty).download(filing)


def test_filesystem_cache_round_trip_publishes_manifest_and_content(tmp_path: Path):
    filing = _filing("a_cninfo")
    downloader = _downloader(filing, "a_cninfo")
    cache = FilesystemFilingDocumentCache(tmp_path)

    live = fetch_filing_document_with_cache(downloader, filing, cache)
    document = live.document
    manifest_path = cache.path_for(filing)
    blob_path = cache.blob_path_for(filing, document.content_sha256)

    assert live.mode is RetrievalMode.LIVE
    assert manifest_path.is_file()
    assert blob_path.is_file()
    assert blob_path.read_bytes() == document.content
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["filing"]["filing_id"] == filing.filing_id
    assert manifest["content_sha256"] == document.content_sha256
    assert manifest["content_size"] == len(document.content)
    assert manifest["blob"] == blob_path.name
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)

    loaded = cache.read(filing)
    assert loaded == document
    assert loaded.filing.source_document_id == filing.source_document_id


def test_offline_replay_never_calls_downloader_and_missing_is_explicit(tmp_path: Path):
    filing = _filing("h_hkexnews")
    calls: list[FilingRecord] = []
    downloader = _downloader(filing, "h_hkexnews", calls)
    cache = FilesystemFilingDocumentCache(tmp_path)
    live = fetch_filing_document_with_cache(downloader, filing, cache)
    calls.clear()

    replay = fetch_filing_document_with_cache(downloader, filing, cache, offline=True)
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.document == live.document
    assert calls == []

    missing = _filing("h_hkexnews", index=1)
    with pytest.raises(CacheMissError, match=missing.filing_id):
        fetch_filing_document_with_cache(downloader, missing, cache, offline=True)
    assert calls == []


def test_offline_corrupt_blob_is_not_treated_as_cache_miss(tmp_path: Path):
    filing = _filing("a_cninfo")
    downloader = _downloader(filing, "a_cninfo")
    cache = FilesystemFilingDocumentCache(tmp_path)
    document = fetch_filing_document_with_cache(downloader, filing, cache).document
    cache.blob_path_for(filing, document.content_sha256).write_bytes(b"tampered")

    with pytest.raises(CacheCorruptionError, match="hash|size"):
        fetch_filing_document_with_cache(downloader, filing, cache, offline=True)


@pytest.mark.parametrize(
    "field",
    ["filing", "filing_url", "content_sha256", "content_size", "blob"],
)
def test_cache_rejects_manifest_scope_or_hash_tampering(tmp_path: Path, field: str):
    filing = _filing("a_cninfo")
    cache = FilesystemFilingDocumentCache(tmp_path)
    fetch_filing_document_with_cache(
        _downloader(filing, "a_cninfo"), filing, cache
    )
    manifest_path = cache.path_for(filing)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if field == "filing":
        manifest["filing"]["listing_id"] = "HK00700"
    elif field == "filing_url":
        manifest["filing"]["url"] = "https://documents.example.invalid/report.pdf"
    elif field == "content_sha256":
        manifest[field] = "0" * 64
    elif field == "content_size":
        manifest[field] += 1
    else:
        manifest[field] = "../../outside.bin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CacheCorruptionError):
        cache.read(filing)


def test_fetch_rejects_a_downloader_returning_a_different_filing(tmp_path: Path):
    requested = _filing("a_cninfo")
    other = _filing("a_cninfo", index=1)
    other_document = _downloader(other, "a_cninfo").download(other)

    class WrongDownloader:
        def download(self, _filing: FilingRecord) -> FilingDocument:
            return other_document

    with pytest.raises(FilingDocumentResponseError, match="provenance"):
        fetch_filing_document_with_cache(
            WrongDownloader(), requested, FilesystemFilingDocumentCache(tmp_path)
        )


def test_failed_atomic_replacement_keeps_previous_document_snapshot(monkeypatch, tmp_path: Path):
    filing = _filing("a_cninfo")
    cache = FilesystemFilingDocumentCache(tmp_path)
    original = fetch_filing_document_with_cache(
        _downloader(filing, "a_cninfo"), filing, cache
    ).document
    manifest_path = cache.path_for(filing)
    before = manifest_path.read_bytes()
    replacement_payload = _download_payload("a_cninfo") | {"content": b"new bytes"}

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr("turtle_value_engine.providers.filing_documents.os.replace", fail_replace)
    with pytest.raises(CacheWriteError, match="cannot write filing document cache entry"):
        cache.write(_downloader(filing, "a_cninfo", response=replacement_payload).download(filing))

    assert manifest_path.read_bytes() == before
    assert cache.read(filing) == original


def test_live_download_failure_can_explicitly_fall_back_to_cached_document(tmp_path: Path):
    filing = _filing("a_cninfo")
    cache = FilesystemFilingDocumentCache(tmp_path)
    good = _downloader(filing, "a_cninfo")
    original = fetch_filing_document_with_cache(good, filing, cache).document

    def fail(_filing: FilingRecord) -> object:
        raise RuntimeError("offline transport")

    failing = FilingDocumentDownloader(
        {filing.source: FilingDocumentSourceClient(filing.source, fail)},
        clock=lambda: RETRIEVED_AT,
    )
    replay = fetch_filing_document_with_cache(
        failing,
        filing,
        cache,
        allow_stale=True,
    )
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.document == original


def test_document_constructor_rejects_wrong_hash_or_size():
    filing = _filing("a_cninfo")
    content = b"synthetic"
    with pytest.raises(ValueError, match="content_sha256"):
        FilingDocument(
            filing=filing,
            content=content,
            content_sha256="0" * 64,
            content_size=len(content),
            media_type="application/pdf",
            retrieved_at=RETRIEVED_AT,
        )
    with pytest.raises(ValueError, match="content_size"):
        FilingDocument(
            filing=filing,
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
            content_size=len(content) + 1,
            media_type="application/pdf",
            retrieved_at=RETRIEVED_AT,
        )


def test_payload_rejects_non_bytes_and_extra_fields():
    with pytest.raises((TypeError, ValueError)):
        FilingDownloadPayload.model_validate(
            {"content": "not bytes", "media_type": "application/pdf"}
        )
    with pytest.raises((TypeError, ValueError)):
        FilingDownloadPayload.model_validate(
            {
                "content": b"bytes",
                "media_type": "application/pdf",
                "unexpected": True,
            }
        )
