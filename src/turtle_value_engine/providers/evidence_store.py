"""Deterministic local storage for evidence anchored to filing text blocks.

This module is deliberately narrower than a filing-analysis workflow.  It
accepts a caller-supplied ``Evidence`` statement and binds it to one exact
``FilingExtractionResult`` block.  The store never interprets text, extracts
numbers, calls a model or reaches a network service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from turtle_value_engine.models import Evidence, EvidenceProvenance, Source
from turtle_value_engine.models.common import SourceType

from .errors import (
    EvidenceStoreConflictError,
    EvidenceStoreCorruptionError,
    EvidenceStoreError,
    EvidenceStoreMissError,
    EvidenceStoreRequestError,
    EvidenceStoreWriteError,
)
from .filing_documents import FilingDocument
from .filing_extraction import (
    FILING_EXTRACTION_CONTRACT,
    FilingExtractionResult,
    FilingReportExtractor,
)
from .filings import FilingRecord
from .models import JSONValue, canonical_json_bytes
from .normalization import deterministic_id

FILING_EVIDENCE_STORE_VERSION = "filing-evidence-v1"
FILING_EVIDENCE_STORE_CONTRACT = "filing_evidence_v1"
EVIDENCE_STORE_CACHE_FORMAT_VERSION = 1

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_FILING_ID_PATTERN = r"^filing-[0-9a-f]{24}$"
_EVIDENCE_ID_PATTERN = r"^filing-evidence-[0-9a-f]{24}$"
_MAX_BLOCK_SEQUENCE = 2_048
_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
_SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "text/html",
        "application/xhtml+xml",
    }
)
_REPORT_SOURCE_TYPES = frozenset(
    {
        SourceType.ANNUAL_REPORT,
        SourceType.INTERIM_REPORT,
    }
)


def _canonical_media_type(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("media_type must be a string")
    normalized = value.split(";", 1)[0].strip().lower()
    if normalized not in _SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"unsupported filing evidence media_type: {normalized!r}")
    return normalized


class FilingEvidenceBlockReference(BaseModel):
    """Stable location and digest of the extracted block being cited."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: StrictInt = Field(ge=1, le=_MAX_BLOCK_SEQUENCE)
    page: StrictInt | None = Field(default=None, ge=1)
    section: StrictStr | None = Field(default=None, min_length=1, max_length=512)
    locator: StrictStr = Field(min_length=1, max_length=128)
    text_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_location(self) -> FilingEvidenceBlockReference:
        if (self.page is None) == (self.section is None):
            raise ValueError("exactly one of page or section is required")
        return self


class FilingEvidenceStoreRecord(BaseModel):
    """On-disk envelope for one evidence item and its extraction identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cache_format_version: Literal[EVIDENCE_STORE_CACHE_FORMAT_VERSION] = (
        EVIDENCE_STORE_CACHE_FORMAT_VERSION
    )
    contract: Literal[FILING_EVIDENCE_STORE_CONTRACT] = FILING_EVIDENCE_STORE_CONTRACT
    evidence: Evidence
    filing: FilingRecord
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    content_size: StrictInt = Field(ge=1, le=_MAX_DOCUMENT_BYTES)
    media_type: StrictStr = Field(min_length=1, max_length=256)
    extraction_contract: StrictStr = Field(min_length=1, max_length=128)
    parser_id: StrictStr = Field(min_length=1, max_length=128)
    parser_version: StrictStr = Field(min_length=1, max_length=128)
    block: FilingEvidenceBlockReference
    record_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, value: str) -> str:
        return _canonical_media_type(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> FilingEvidenceStoreRecord:
        _validate_record_consistency(self)
        return self


FilingEvidenceInput: TypeAlias = Evidence | Mapping[str, object]
FilingExtractionInput: TypeAlias = FilingExtractionResult | Mapping[str, object]


def _validated_filing(filing: FilingRecord) -> FilingRecord:
    try:
        return FilingRecord.model_validate(filing.model_dump(mode="python", warnings=False))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid filing record: {exc}") from exc


def _validated_extraction(extraction: FilingExtractionInput) -> FilingExtractionResult:
    try:
        if isinstance(extraction, FilingExtractionResult):
            payload = extraction.model_dump(mode="python", warnings=False)
        elif isinstance(extraction, Mapping):
            payload = extraction
        else:
            raise TypeError("extraction must be a FilingExtractionResult or JSON object")
        return FilingExtractionResult.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid filing extraction: {exc}") from exc


def _validated_document(document: FilingDocument) -> FilingDocument:
    if not isinstance(document, FilingDocument):
        raise TypeError("document must be a FilingDocument")
    try:
        return FilingDocument(
            filing=_validated_filing(document.filing),
            content=document.content,
            content_sha256=document.content_sha256,
            content_size=document.content_size,
            media_type=document.media_type,
            retrieved_at=document.retrieved_at,
            final_url=document.final_url,
            retrieval_metadata=document.retrieval_metadata,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid filing document: {exc}") from exc


def _filing_payload(filing: FilingRecord) -> dict[str, JSONValue]:
    return filing.model_dump(mode="json")


def _filings_match(left: FilingRecord, right: FilingRecord) -> bool:
    return canonical_json_bytes(_filing_payload(left)) == canonical_json_bytes(
        _filing_payload(right)
    )


def _validate_extraction_document(
    extraction: FilingExtractionResult,
    document: FilingDocument,
    extractor: FilingReportExtractor | None,
) -> FilingDocument:
    validated_document = _validated_document(document)
    if not _filings_match(extraction.filing, validated_document.filing):
        raise ValueError("filing extraction provenance does not match document filing")
    if hashlib.sha256(validated_document.content).hexdigest() != validated_document.content_sha256:
        raise ValueError("filing document content hash is invalid")
    if extraction.content_sha256 != validated_document.content_sha256:
        raise ValueError("filing extraction content_sha256 does not match document")
    if extraction.content_size != validated_document.content_size:
        raise ValueError("filing extraction content_size does not match document")
    if extraction.media_type != validated_document.media_type:
        raise ValueError("filing extraction media_type does not match document")
    if extractor is not None:
        extractor.validate(extraction, validated_document)
    return validated_document


def _block_for(
    extraction: FilingExtractionResult,
    block_sequence: int,
):
    if type(block_sequence) is not int or not 1 <= block_sequence <= len(extraction.blocks):
        raise ValueError("block_sequence must identify one extracted text block")
    return extraction.blocks[block_sequence - 1]


def _block_locator(sequence: int) -> str:
    """Return the stable locator syntax used by filing evidence."""

    return f"block:{sequence}"


def _provenance_for(
    extraction: FilingExtractionResult,
    block,
) -> EvidenceProvenance:
    return EvidenceProvenance(
        filing_id=extraction.filing_id,
        filing_source=extraction.source.value,
        source_document_id=extraction.source_document_id,
        report_period=extraction.report_period,
        content_sha256=extraction.content_sha256,
        content_size=extraction.content_size,
        media_type=extraction.media_type,
        extraction_contract=extraction.contract,
        parser_id=extraction.parser_id,
        parser_version=extraction.parser_version,
        block_sequence=block.sequence,
        block_sha256=block.text_sha256,
    )


def _block_reference(extraction: FilingExtractionResult, block) -> FilingEvidenceBlockReference:
    return FilingEvidenceBlockReference(
        sequence=block.sequence,
        page=block.page,
        section=block.section,
        locator=_block_locator(block.sequence),
        text_sha256=block.text_sha256,
    )


def _coerce_evidence(evidence: FilingEvidenceInput) -> tuple[Evidence, bool]:
    if isinstance(evidence, Evidence):
        payload = evidence.model_dump(mode="python", warnings=False)
        supplied_id = True
    elif isinstance(evidence, Mapping):
        payload = dict(evidence)
        supplied_id = "id" in payload
        if not supplied_id:
            payload["id"] = "pending"
    else:
        raise TypeError("evidence must be an Evidence model or JSON object")
    try:
        return Evidence.model_validate(payload), supplied_id
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid evidence: {exc}") from exc


def _same_optional(actual: object, expected: object, *, name: str) -> None:
    if actual is not None and actual != expected:
        raise ValueError(f"evidence source {name} does not match filing provenance")


def _canonical_source(
    source: Source,
    extraction: FilingExtractionResult,
    block,
) -> Source:
    if source.type not in _REPORT_SOURCE_TYPES:
        raise ValueError("filing text evidence source.type must be ANNUAL_REPORT or INTERIM_REPORT")
    if extraction.filing.document_type in {"ANNUAL_REPORT", "INTERIM_REPORT"} and (
        source.type.value != extraction.filing.document_type
    ):
        raise ValueError("evidence source.type does not match filing document_type")
    if source.title != extraction.filing.title:
        raise ValueError("evidence source title does not match filing title")

    _same_optional(source.issuer, extraction.filing.issuer_name, name="issuer")
    _same_optional(source.published_date, extraction.filing.published_date, name="published_date")
    _same_optional(source.fiscal_period, extraction.report_period, name="fiscal_period")
    _same_optional(source.document_id, extraction.source_document_id, name="document_id")
    _same_optional(source.page, block.page, name="page")
    _same_optional(source.section, block.section, name="section")
    _same_optional(source.locator, _block_locator(block.sequence), name="locator")
    if source.url is not None and str(source.url) != str(extraction.filing.url):
        raise ValueError("evidence source url does not match filing URL")
    if block.page is None and source.page is not None:
        raise ValueError("HTML filing evidence must not contain a page reference")
    if block.section is None and source.section is not None:
        raise ValueError("PDF filing evidence must not contain a section reference")

    return Source(
        type=source.type,
        title=extraction.filing.title,
        issuer=extraction.filing.issuer_name,
        published_date=extraction.filing.published_date,
        fiscal_period=extraction.report_period,
        url=str(extraction.filing.url),
        document_id=extraction.source_document_id,
        page=block.page,
        section=block.section,
        table_or_note=source.table_or_note,
        locator=_block_locator(block.sequence),
    )


def _evidence_identity(
    extraction: FilingExtractionResult,
    evidence: Evidence,
    block,
) -> dict[str, JSONValue]:
    return {
        "filing_id": extraction.filing_id,
        "filing_source": extraction.source.value,
        "content_sha256": extraction.content_sha256,
        "extraction_contract": extraction.contract,
        "parser_id": extraction.parser_id,
        "parser_version": extraction.parser_version,
        "block_sequence": block.sequence,
        "block_sha256": block.text_sha256,
        "source_type": evidence.source.type.value,
        "direction": evidence.direction.value,
        "strength": evidence.strength.value,
        "statement": evidence.statement,
        "metric_context": (
            evidence.metric_context.model_dump(mode="json")
            if evidence.metric_context is not None
            else None
        ),
        "notes": evidence.notes,
        "table_or_note": evidence.source.table_or_note,
    }


def filing_evidence_id_for(
    extraction: FilingExtractionInput,
    evidence: FilingEvidenceInput,
    block_sequence: int,
) -> str:
    """Return the stable identity for one semantic claim at one block."""

    try:
        validated_extraction = _validated_extraction(extraction)
        block = _block_for(validated_extraction, block_sequence)
        candidate, _ = _coerce_evidence(evidence)
        return deterministic_id(
            "filing-evidence",
            _evidence_identity(validated_extraction, candidate, block),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise EvidenceStoreRequestError(f"cannot derive filing evidence ID: {exc}") from exc


evidence_id_for = filing_evidence_id_for


def _canonical_evidence(
    extraction: FilingExtractionResult,
    evidence: FilingEvidenceInput,
    block_sequence: int,
) -> Evidence:
    candidate, supplied_id = _coerce_evidence(evidence)
    block = _block_for(extraction, block_sequence)
    source = _canonical_source(candidate.source, extraction, block)
    expected_provenance = _provenance_for(extraction, block)
    if candidate.provenance is not None and candidate.provenance != expected_provenance:
        raise ValueError("evidence provenance does not match extracted filing block")
    candidate = Evidence.model_validate(
        candidate.model_copy(
            update={
                "source": source,
                "provenance": expected_provenance,
            }
        ).model_dump(mode="python", warnings=False)
    )
    expected_id = filing_evidence_id_for(extraction, candidate, block_sequence)
    if supplied_id and candidate.id != expected_id:
        raise ValueError("evidence id does not match deterministic filing evidence identity")
    return Evidence.model_validate(
        candidate.model_copy(update={"id": expected_id}).model_dump(
            mode="python", warnings=False
        )
    )


def _validate_record_consistency(record: FilingEvidenceStoreRecord) -> None:
    if record.extraction_contract != FILING_EXTRACTION_CONTRACT:
        raise ValueError("unsupported filing extraction contract")
    filing = _validated_filing(record.filing)
    evidence = record.evidence
    provenance = evidence.provenance
    if provenance is None:
        raise ValueError("filing evidence must contain provenance")
    expected_provenance = EvidenceProvenance(
        filing_id=filing.filing_id,
        filing_source=filing.source.value,
        source_document_id=filing.source_document_id,
        report_period=filing.report_period,
        content_sha256=record.content_sha256,
        content_size=record.content_size,
        media_type=record.media_type,
        extraction_contract=record.extraction_contract,
        parser_id=record.parser_id,
        parser_version=record.parser_version,
        block_sequence=record.block.sequence,
        block_sha256=record.block.text_sha256,
    )
    if provenance != expected_provenance:
        raise ValueError("evidence provenance does not match store record identity")
    source = evidence.source
    if source.type not in _REPORT_SOURCE_TYPES:
        raise ValueError("filing text evidence source.type must be ANNUAL_REPORT or INTERIM_REPORT")
    if filing.document_type in {"ANNUAL_REPORT", "INTERIM_REPORT"} and (
        source.type.value != filing.document_type
    ):
        raise ValueError("evidence source.type does not match filing document_type")
    expected_source_values = {
        "title": filing.title,
        "issuer": filing.issuer_name,
        "published_date": filing.published_date,
        "fiscal_period": filing.report_period,
        "document_id": filing.source_document_id,
        "page": record.block.page,
        "section": record.block.section,
        "locator": record.block.locator,
    }
    for name, expected in expected_source_values.items():
        if getattr(source, name) != expected:
            raise ValueError(f"evidence source {name} does not match store block provenance")
    if source.url is None or str(source.url) != str(filing.url):
        raise ValueError("evidence source url does not match store filing provenance")
    if record.block.locator != _block_locator(record.block.sequence):
        raise ValueError("stored block locator is not canonical")
    if record.media_type == "application/pdf" and record.block.page is None:
        raise ValueError("PDF filing evidence must use a page block reference")
    if record.media_type != "application/pdf" and record.block.section is None:
        raise ValueError("HTML filing evidence must use a section block reference")
    expected_id = deterministic_id(
        "filing-evidence",
        {
            "filing_id": filing.filing_id,
            "filing_source": filing.source.value,
            "content_sha256": record.content_sha256,
            "extraction_contract": record.extraction_contract,
            "parser_id": record.parser_id,
            "parser_version": record.parser_version,
            "block_sequence": record.block.sequence,
            "block_sha256": record.block.text_sha256,
            "source_type": source.type.value,
            "direction": evidence.direction.value,
            "strength": evidence.strength.value,
            "statement": evidence.statement,
            "metric_context": (
                evidence.metric_context.model_dump(mode="json")
                if evidence.metric_context is not None
                else None
            ),
            "notes": evidence.notes,
            "table_or_note": source.table_or_note,
        },
    )
    if evidence.id != expected_id:
        raise ValueError("evidence id does not match deterministic store identity")


def _record_without_hash(record: FilingEvidenceStoreRecord) -> dict[str, JSONValue]:
    return record.model_dump(mode="json", exclude={"record_sha256"})


def _record_with_hash(record: FilingEvidenceStoreRecord) -> FilingEvidenceStoreRecord:
    digest = hashlib.sha256(canonical_json_bytes(_record_without_hash(record))).hexdigest()
    return FilingEvidenceStoreRecord.model_validate(
        record.model_copy(update={"record_sha256": digest}).model_dump(
            mode="python", warnings=False
        )
    )


def _record_for(
    extraction: FilingExtractionResult,
    evidence: FilingEvidenceInput,
    block_sequence: int,
) -> FilingEvidenceStoreRecord:
    block = _block_for(extraction, block_sequence)
    canonical_evidence = _canonical_evidence(extraction, evidence, block_sequence)
    record = FilingEvidenceStoreRecord(
        evidence=canonical_evidence,
        filing=extraction.filing,
        content_sha256=extraction.content_sha256,
        content_size=extraction.content_size,
        media_type=extraction.media_type,
        extraction_contract=extraction.contract,
        parser_id=extraction.parser_id,
        parser_version=extraction.parser_version,
        block=_block_reference(extraction, block),
        record_sha256="0" * 64,
    )
    return _record_with_hash(record)


def _validate_record_against_extraction(
    record: FilingEvidenceStoreRecord,
    extraction: FilingExtractionResult,
    document: FilingDocument | None,
    extractor: FilingReportExtractor | None,
) -> None:
    if document is not None:
        _validate_extraction_document(extraction, document, extractor)
    if not _filings_match(record.filing, extraction.filing):
        raise ValueError("stored evidence filing does not match requested extraction")
    for name in (
        "content_sha256",
        "content_size",
        "media_type",
        "extraction_contract",
        "parser_id",
        "parser_version",
    ):
        extraction_name = "contract" if name == "extraction_contract" else name
        if getattr(record, name) != getattr(extraction, extraction_name):
            raise ValueError(f"stored evidence {name} does not match requested extraction")
    block = _block_for(extraction, record.block.sequence)
    expected = _block_reference(extraction, block)
    if record.block != expected:
        raise ValueError("stored evidence block reference does not match requested extraction")
    if record.evidence.provenance != _provenance_for(extraction, block):
        raise ValueError("stored evidence provenance does not match requested extraction")


def _record_from_file(path: Path) -> FilingEvidenceStoreRecord:
    if path.is_symlink() or not path.is_file():
        raise EvidenceStoreCorruptionError(f"evidence store entry is not a regular file: {path}")
    try:
        with path.open("rb") as handle:
            payload = json.load(handle, parse_constant=_reject_non_json_number)
        record = FilingEvidenceStoreRecord.model_validate(payload)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise EvidenceStoreCorruptionError(f"invalid evidence store entry {path}: {exc}") from exc
    if path.stem != record.evidence.id:
        raise EvidenceStoreCorruptionError(
            f"evidence store filename does not match evidence ID: {path}"
        )
    expected_hash = hashlib.sha256(canonical_json_bytes(_record_without_hash(record))).hexdigest()
    if record.record_sha256 != expected_hash:
        raise EvidenceStoreCorruptionError(f"evidence store record hash mismatch: {path}")
    return record


class FilingEvidenceStore:
    """Append-only deterministic filesystem store for filing evidence."""

    def __init__(
        self,
        root: str | Path,
        *,
        extractor: FilingReportExtractor | None = None,
    ) -> None:
        if extractor is not None and not isinstance(extractor, FilingReportExtractor):
            raise TypeError("extractor must be a FilingReportExtractor")
        self.root = Path(root)
        self._extractor = extractor

    def path_for(self, evidence_id: str) -> Path:
        """Return the exact path for a deterministic evidence ID."""

        if not isinstance(evidence_id, str) or not re.fullmatch(_EVIDENCE_ID_PATTERN, evidence_id):
            raise ValueError("evidence_id must be a deterministic filing evidence ID")
        return self.root / "evidence" / f"{evidence_id}.json"

    def append(
        self,
        extraction: FilingExtractionInput,
        evidence: FilingEvidenceInput,
        *,
        block_sequence: int,
        document: FilingDocument | None = None,
    ) -> Evidence:
        """Persist one evidence item, idempotently, after strict validation."""

        try:
            validated_extraction = _validated_extraction(extraction)
            if document is not None:
                _validate_extraction_document(validated_extraction, document, self._extractor)
            record = _record_for(validated_extraction, evidence, block_sequence)
        except EvidenceStoreError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise EvidenceStoreRequestError(f"invalid filing evidence request: {exc}") from exc

        path = self.path_for(record.evidence.id)
        if path.exists() or path.is_symlink():
            existing = _record_from_file(path)
            if canonical_json_bytes(existing.model_dump(mode="json")) == canonical_json_bytes(
                record.model_dump(mode="json")
            ):
                return existing.evidence
            raise EvidenceStoreConflictError(
                f"evidence ID already stores a different record: {record.evidence.id}"
            )
        serialized = canonical_json_bytes(record.model_dump(mode="json")) + b"\n"
        try:
            _atomic_create(path, serialized)
        except FileExistsError:
            existing = _record_from_file(path)
            if canonical_json_bytes(existing.model_dump(mode="json")) == canonical_json_bytes(
                record.model_dump(mode="json")
            ):
                return existing.evidence
            raise EvidenceStoreConflictError(
                f"evidence ID already stores a different record: {record.evidence.id}"
            )
        except (OSError, TypeError, ValueError) as exc:
            raise EvidenceStoreWriteError(
                f"cannot write evidence store entry {path}: {exc}"
            ) from exc
        return record.evidence

    def upsert(
        self,
        extraction: FilingExtractionInput,
        evidence: FilingEvidenceInput,
        *,
        block_sequence: int,
        document: FilingDocument | None = None,
    ) -> Evidence:
        """Idempotent upsert; conflicting reuse of an ID is rejected."""

        return self.append(
            extraction,
            evidence,
            block_sequence=block_sequence,
            document=document,
        )

    def read_record(
        self,
        evidence_id: str,
        *,
        extraction: FilingExtractionInput | None = None,
        document: FilingDocument | None = None,
    ) -> FilingEvidenceStoreRecord | None:
        """Read one verified local record, optionally against an extraction."""

        try:
            path = self.path_for(evidence_id)
        except (TypeError, ValueError) as exc:
            raise EvidenceStoreRequestError(f"invalid filing evidence ID: {exc}") from exc
        if not path.exists() and not path.is_symlink():
            return None
        record = _record_from_file(path)
        if extraction is not None:
            try:
                validated_extraction = _validated_extraction(extraction)
                _validate_record_against_extraction(
                    record,
                    validated_extraction,
                    document,
                    self._extractor,
                )
            except EvidenceStoreError:
                raise
            except (TypeError, ValueError, ValidationError) as exc:
                raise EvidenceStoreRequestError(
                    f"stored evidence does not match requested extraction: {exc}"
                ) from exc
        elif document is not None:
            raise EvidenceStoreRequestError("document validation requires an extraction")
        return record

    def read(
        self,
        evidence_id: str,
        *,
        extraction: FilingExtractionInput | None = None,
        document: FilingDocument | None = None,
    ) -> Evidence | None:
        """Read one evidence item from the local store without network access."""

        record = self.read_record(evidence_id, extraction=extraction, document=document)
        return None if record is None else record.evidence

    get = read

    def replay(
        self,
        evidence_id: str,
        *,
        extraction: FilingExtractionInput | None = None,
        document: FilingDocument | None = None,
    ) -> Evidence:
        """Require and return one verified offline evidence replay."""

        evidence = self.read(evidence_id, extraction=extraction, document=document)
        if evidence is None:
            raise EvidenceStoreMissError(f"no replayable filing evidence: {evidence_id}")
        return evidence

    def lookup(
        self,
        *,
        extraction: FilingExtractionInput | None = None,
        filing_id: str | None = None,
        content_sha256: str | None = None,
        block_sequence: int | None = None,
    ) -> tuple[Evidence, ...]:
        """Return deterministic local evidence matches in ID order."""

        try:
            validated_extraction = (
                _validated_extraction(extraction) if extraction is not None else None
            )
            if validated_extraction is not None:
                if filing_id is not None and filing_id != validated_extraction.filing_id:
                    raise ValueError("filing_id does not match extraction")
                filing_id = validated_extraction.filing_id
                if (
                    content_sha256 is not None
                    and content_sha256 != validated_extraction.content_sha256
                ):
                    raise ValueError("content_sha256 does not match extraction")
                content_sha256 = validated_extraction.content_sha256
            if filing_id is None and content_sha256 is None:
                raise ValueError("lookup requires extraction, filing_id or content_sha256")
            if filing_id is not None and (
                not isinstance(filing_id, str) or not re.fullmatch(_FILING_ID_PATTERN, filing_id)
            ):
                raise ValueError("filing_id must be a filing identity")
            if content_sha256 is not None:
                if not isinstance(content_sha256, str) or not re.fullmatch(
                    _HASH_PATTERN, content_sha256
                ):
                    raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
            if block_sequence is not None and (
                type(block_sequence) is not int or block_sequence < 1
            ):
                raise ValueError("block_sequence must be a positive integer")
        except (TypeError, ValueError, ValidationError) as exc:
            raise EvidenceStoreRequestError(f"invalid filing evidence lookup: {exc}") from exc

        directory = self.root / "evidence"
        if not directory.exists():
            return ()
        if directory.is_symlink() or not directory.is_dir():
            raise EvidenceStoreCorruptionError(
                f"evidence store directory is not a directory: {directory}"
            )
        matches: list[Evidence] = []
        for path in sorted(directory.glob("*.json")):
            record = _record_from_file(path)
            if filing_id is not None and record.filing.filing_id != filing_id:
                continue
            if content_sha256 is not None and record.content_sha256 != content_sha256:
                continue
            if block_sequence is not None and record.block.sequence != block_sequence:
                continue
            if validated_extraction is not None:
                try:
                    _validate_record_against_extraction(
                        record,
                        validated_extraction,
                        None,
                        self._extractor,
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise EvidenceStoreRequestError(
                        f"stored evidence does not match requested extraction: {exc}"
                    ) from exc
            matches.append(record.evidence)
        return tuple(matches)


def _atomic_create(path: Path, content: bytes) -> None:
    """Publish one new record without replacing an existing record."""

    temporary_path: Path | None = None
    descriptor = -1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, path)
        try:
            temporary_path.unlink()
        except OSError:
            pass
        temporary_path = None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _reject_non_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


__all__ = [
    "EVIDENCE_STORE_CACHE_FORMAT_VERSION",
    "FILING_EVIDENCE_STORE_CONTRACT",
    "FILING_EVIDENCE_STORE_VERSION",
    "FilingEvidenceBlockReference",
    "FilingEvidenceInput",
    "FilingEvidenceStore",
    "FilingEvidenceStoreRecord",
    "evidence_id_for",
    "filing_evidence_id_for",
]
