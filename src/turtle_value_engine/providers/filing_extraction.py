"""Bounded, parser-injected text extraction for official filing documents.

The extraction boundary consumes a verified :class:`FilingDocument` from the
document cache and returns only immutable text blocks with source locations.
It deliberately does not classify a report, interpret its text, create
evidence or infer a financial fact.  PDF/HTML parser dependencies are kept
outside the core package and are supplied through ``FilingDocumentTextParser``
instances.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

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

from .errors import (
    FilingExtractionError,
    FilingExtractionRequestError,
    FilingExtractionResponseError,
)
from .filing_documents import FilingDocument
from .filings import FilingRecord

FILING_EXTRACTION_ADAPTER_VERSION = "filing-extraction-v1"
FILING_EXTRACTION_SOURCE_NAME = "Official filing report extraction"
FILING_EXTRACTION_CONTRACT = "filing_report_extraction_v1"

_SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "text/html",
        "application/xhtml+xml",
    }
)
_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
_MAX_BLOCKS = 2_048
_MAX_BLOCK_CHARS = 100_000
_MAX_TOTAL_TEXT_CHARS = 5_000_000
_HASH_LENGTH = 64


def _canonical_media_type(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("media_type must be a string")
    normalized = value.split(";", 1)[0].strip().lower()
    if normalized not in _SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"unsupported extraction media_type: {normalized!r}")
    return normalized


def _validate_label(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError(f"{name} must not contain control characters")
    if len(normalized) > 128:
        raise ValueError(f"{name} is too long")
    return normalized


def _validate_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    if not value.strip():
        raise ValueError("text must contain non-whitespace characters")
    if any(
        (ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127
        for char in value
    ):
        raise ValueError("text must not contain unsupported control characters")
    return value


def _text_sha256(value: str) -> str:
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ValueError("text must be valid UTF-8") from exc


class FilingTextBlockPayload(BaseModel):
    """Parser output for one ordered page- or section-located text block."""

    model_config = ConfigDict(extra="forbid")

    sequence: StrictInt = Field(ge=1, le=_MAX_BLOCKS)
    page: StrictInt | None = Field(default=None, ge=1)
    section: StrictStr | None = Field(default=None, min_length=1, max_length=512)
    text: StrictStr = Field(min_length=1, max_length=_MAX_BLOCK_CHARS)

    @field_validator("section")
    @classmethod
    def _validate_section(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip():
            raise ValueError("section must not have surrounding whitespace")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("section must not contain control characters")
        return value

    @field_validator("text")
    @classmethod
    def _validate_block_text(cls, value: str) -> str:
        return _validate_text(value)

    @model_validator(mode="after")
    def _validate_location(self) -> FilingTextBlockPayload:
        if (self.page is None) == (self.section is None):
            raise ValueError("exactly one of page or section is required")
        return self


class FilingTextBlock(FilingTextBlockPayload):
    """Immutable canonical text block emitted by the extraction boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text_sha256: StrictStr = Field(pattern=rf"^[0-9a-f]{{{_HASH_LENGTH}}}$")

    @model_validator(mode="after")
    def _validate_text_hash(self) -> FilingTextBlock:
        if self.text_sha256 != _text_sha256(self.text):
            raise ValueError("text_sha256 does not match text")
        return self


FilingTextParserOutput: TypeAlias = (
    FilingTextBlockPayload | FilingTextBlock | Mapping[str, object]
)


@dataclass(frozen=True, slots=True)
class FilingDocumentTextParser:
    """One injected, local parser implementation for a supported media type."""

    media_type: str
    parser_id: str
    parser_version: str
    parse: Callable[[FilingDocument], Iterable[FilingTextParserOutput]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "media_type", _canonical_media_type(self.media_type))
        object.__setattr__(self, "parser_id", _validate_label(self.parser_id, name="parser_id"))
        object.__setattr__(
            self,
            "parser_version",
            _validate_label(self.parser_version, name="parser_version"),
        )
        if not callable(self.parse):
            raise TypeError("parse must be callable")


def _validated_document(document: FilingDocument) -> FilingDocument:
    """Revalidate a possibly mutated document before giving it to a parser."""

    if not isinstance(document, FilingDocument):
        raise TypeError("document must be a FilingDocument")
    try:
        return FilingDocument(
            filing=document.filing,
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


class FilingExtractionResult(BaseModel):
    """Deterministic extraction result bound to one exact document snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: StrictStr = FILING_EXTRACTION_CONTRACT
    filing: FilingRecord
    content_sha256: StrictStr = Field(pattern=rf"^[0-9a-f]{{{_HASH_LENGTH}}}$")
    content_size: StrictInt = Field(ge=1, le=_MAX_DOCUMENT_BYTES)
    media_type: StrictStr
    parser_id: StrictStr = Field(min_length=1, max_length=128)
    parser_version: StrictStr = Field(min_length=1, max_length=128)
    blocks: tuple[FilingTextBlock, ...] = Field(
        min_length=1,
        max_length=_MAX_BLOCKS,
    )

    @field_validator("contract")
    @classmethod
    def _validate_contract(cls, value: str) -> str:
        if value != FILING_EXTRACTION_CONTRACT:
            raise ValueError("unsupported filing extraction contract")
        return value

    @field_validator("media_type")
    @classmethod
    def _validate_result_media_type(cls, value: str) -> str:
        return _canonical_media_type(value)

    @field_validator("parser_id", "parser_version")
    @classmethod
    def _validate_parser_labels(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "parser label")
        return _validate_label(value, name=field_name)

    @model_validator(mode="after")
    def _validate_block_order_and_bound(self) -> FilingExtractionResult:
        expected = list(range(1, len(self.blocks) + 1))
        sequences = [block.sequence for block in self.blocks]
        if sequences != expected:
            raise ValueError("extraction blocks must have contiguous source order")
        previous_page: int | None = None
        for block in self.blocks:
            if self.media_type == "application/pdf":
                if block.page is None or block.section is not None:
                    raise ValueError("PDF extraction blocks must use page locations only")
                if previous_page is not None and block.page < previous_page:
                    raise ValueError("PDF extraction blocks must use non-decreasing page order")
                previous_page = block.page
            elif block.section is None or block.page is not None:
                raise ValueError("HTML extraction blocks must use section locations only")
        total_chars = sum(len(block.text) for block in self.blocks)
        if total_chars > _MAX_TOTAL_TEXT_CHARS:
            raise ValueError("extraction text exceeds the maximum configured size")
        return self

    @property
    def filing_id(self) -> str:
        """Return the source filing identity without duplicating it in JSON."""

        return self.filing.filing_id

    @property
    def listing_id(self) -> str:
        return self.filing.listing_id

    @property
    def market(self):
        return self.filing.market

    @property
    def source(self):
        return self.filing.source

    @property
    def source_document_id(self) -> str | None:
        return self.filing.source_document_id

    @property
    def report_period(self) -> str | None:
        return self.filing.report_period

    @property
    def document_sha256(self) -> str:
        """Compatibility name for the exact raw document digest."""

        return self.content_sha256


def _bound(value: int, *, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    return value


class FilingReportExtractor:
    """Extract bounded text blocks with no implicit parser or network access."""

    def __init__(
        self,
        parsers: Mapping[str, FilingDocumentTextParser],
        *,
        max_blocks: int = _MAX_BLOCKS,
        max_block_chars: int = _MAX_BLOCK_CHARS,
        max_total_chars: int = _MAX_TOTAL_TEXT_CHARS,
    ) -> None:
        if not isinstance(parsers, Mapping):
            raise TypeError("parsers must be a mapping")
        self._max_blocks = _bound(max_blocks, name="max_blocks", maximum=_MAX_BLOCKS)
        self._max_block_chars = _bound(
            max_block_chars,
            name="max_block_chars",
            maximum=_MAX_BLOCK_CHARS,
        )
        self._max_total_chars = _bound(
            max_total_chars,
            name="max_total_chars",
            maximum=_MAX_TOTAL_TEXT_CHARS,
        )
        normalized: dict[str, FilingDocumentTextParser] = {}
        for media_type, parser in parsers.items():
            if not isinstance(parser, FilingDocumentTextParser):
                raise TypeError("parsers must contain FilingDocumentTextParser values")
            key = _canonical_media_type(media_type)
            if key != parser.media_type:
                raise ValueError("parser media_type does not match its mapping key")
            if key in normalized:
                raise ValueError(f"duplicate parser for media_type {key!r}")
            normalized[key] = parser
        self._parsers = normalized

    def extract(self, document: FilingDocument) -> FilingExtractionResult:
        """Extract parser-supplied text from one verified cached/live document."""

        try:
            validated = _validated_document(document)
        except (TypeError, ValueError) as exc:
            raise FilingExtractionRequestError(f"invalid filing extraction request: {exc}") from exc

        media_type = validated.media_type
        if media_type not in _SUPPORTED_MEDIA_TYPES:
            raise FilingExtractionRequestError(
                f"unsupported filing document media_type {media_type!r}"
            )
        parser = self._parsers.get(media_type)
        if parser is None:
            raise FilingExtractionRequestError(
                f"no parser configured for filing document media_type {media_type!r}"
            )
        try:
            parsed_blocks = parser.parse(validated)
        except FilingExtractionError:
            raise
        except Exception as exc:
            raise FilingExtractionResponseError(
                f"filing {validated.filing_id} parser {parser.parser_id!r} failed"
            ) from exc
        blocks = self._consume_blocks(
            parsed_blocks,
            media_type=media_type,
            filing_id=validated.filing_id,
        )
        try:
            result = FilingExtractionResult(
                filing=validated.filing,
                content_sha256=validated.content_sha256,
                content_size=validated.content_size,
                media_type=validated.media_type,
                parser_id=parser.parser_id,
                parser_version=parser.parser_version,
                blocks=tuple(blocks),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise FilingExtractionResponseError(
                f"invalid filing extraction result for {validated.filing_id}: {exc}"
            ) from exc
        return self.validate(result, validated)

    def validate(
        self,
        result: FilingExtractionResult | Mapping[str, object],
        document: FilingDocument,
    ) -> FilingExtractionResult:
        """Revalidate a serialized result against the exact document snapshot."""

        try:
            validated_document = _validated_document(document)
        except (TypeError, ValueError) as exc:
            raise FilingExtractionRequestError(
                f"invalid filing extraction document: {exc}"
            ) from exc
        try:
            validated_result = (
                result
                if isinstance(result, FilingExtractionResult)
                else FilingExtractionResult.model_validate(result)
            )
            if isinstance(result, FilingExtractionResult):
                validated_result = FilingExtractionResult.model_validate(
                    result.model_dump(mode="python")
                )
        except (TypeError, ValueError, ValidationError) as exc:
            raise FilingExtractionResponseError(f"invalid filing extraction result: {exc}") from exc

        if validated_result.filing != validated_document.filing:
            raise FilingExtractionResponseError(
                "filing extraction provenance does not match document filing"
            )
        if validated_result.content_sha256 != validated_document.content_sha256:
            raise FilingExtractionResponseError(
                "filing extraction content_sha256 does not match document"
            )
        if validated_result.content_size != validated_document.content_size:
            raise FilingExtractionResponseError(
                "filing extraction content_size does not match document"
            )
        if validated_result.media_type != validated_document.media_type:
            raise FilingExtractionResponseError(
                "filing extraction media_type does not match document"
            )
        parser = self._parsers.get(validated_result.media_type)
        if parser is None:
            raise FilingExtractionResponseError(
                f"no parser configured for filing extraction media_type "
                f"{validated_result.media_type!r}"
            )
        if (
            validated_result.parser_id != parser.parser_id
            or validated_result.parser_version != parser.parser_version
        ):
            raise FilingExtractionResponseError(
                "filing extraction parser provenance does not match configured parser"
            )
        if len(validated_result.blocks) > self._max_blocks:
            raise FilingExtractionResponseError("filing extraction exceeds max_blocks")
        total_chars = 0
        for block in validated_result.blocks:
            if len(block.text) > self._max_block_chars:
                raise FilingExtractionResponseError(
                    "filing extraction block exceeds max_block_chars"
                )
            total_chars += len(block.text)
        if total_chars > self._max_total_chars:
            raise FilingExtractionResponseError("filing extraction exceeds max_total_chars")
        return validated_result

    def _consume_blocks(
        self,
        parsed_blocks: object,
        *,
        media_type: str,
        filing_id: str,
    ) -> list[FilingTextBlock]:
        if parsed_blocks is None or isinstance(
            parsed_blocks, (str, bytes, bytearray, Mapping)
        ):
            raise FilingExtractionResponseError(
                f"parser for {filing_id} must return an iterable of text blocks"
            )
        try:
            iterator = iter(parsed_blocks)  # type: ignore[arg-type]
        except Exception as exc:
            raise FilingExtractionResponseError(
                f"parser for {filing_id} must return an iterable of text blocks"
            ) from exc

        blocks: list[FilingTextBlock] = []
        total_chars = 0
        previous_page: int | None = None
        for expected_sequence in range(1, self._max_blocks + 2):
            try:
                item = next(iterator)
            except StopIteration:
                break
            except Exception as exc:
                raise FilingExtractionResponseError(
                    f"parser for {filing_id} failed while producing text blocks"
                ) from exc
            if expected_sequence > self._max_blocks:
                raise FilingExtractionResponseError("filing extraction exceeds max_blocks")
            try:
                if isinstance(item, FilingTextBlock):
                    payload = FilingTextBlockPayload.model_validate(
                        item.model_dump(mode="python", exclude={"text_sha256"})
                    )
                else:
                    payload = FilingTextBlockPayload.model_validate(item)
            except (TypeError, ValueError, ValidationError) as exc:
                raise FilingExtractionResponseError(
                    f"invalid parser text block {expected_sequence} for {filing_id}: {exc}"
                ) from exc
            if payload.sequence != expected_sequence:
                raise FilingExtractionResponseError(
                    "parser text blocks must preserve contiguous source order"
                )
            if len(payload.text) > self._max_block_chars:
                raise FilingExtractionResponseError(
                    "filing extraction block exceeds max_block_chars"
                )
            if media_type == "application/pdf":
                if payload.page is None or payload.section is not None:
                    raise FilingExtractionResponseError(
                        "PDF parser blocks must use page locations only"
                    )
                if previous_page is not None and payload.page < previous_page:
                    raise FilingExtractionResponseError(
                        "PDF parser blocks must use non-decreasing page order"
                    )
                previous_page = payload.page
            elif payload.section is None or payload.page is not None:
                raise FilingExtractionResponseError(
                    "HTML parser blocks must use section locations only"
                )
            total_chars += len(payload.text)
            if total_chars > self._max_total_chars:
                raise FilingExtractionResponseError("filing extraction exceeds max_total_chars")
            try:
                blocks.append(
                    FilingTextBlock(
                        **payload.model_dump(mode="python"),
                        text_sha256=_text_sha256(payload.text),
                    )
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise FilingExtractionResponseError(
                    f"invalid parser text block {expected_sequence} for {filing_id}: {exc}"
                ) from exc
        if not blocks:
            raise FilingExtractionResponseError(
                f"parser for {filing_id} returned no text blocks"
            )
        return blocks


AnnualInterimReportExtractor = FilingReportExtractor


__all__ = [
    "AnnualInterimReportExtractor",
    "FILING_EXTRACTION_ADAPTER_VERSION",
    "FILING_EXTRACTION_CONTRACT",
    "FILING_EXTRACTION_SOURCE_NAME",
    "FilingDocumentTextParser",
    "FilingExtractionResult",
    "FilingReportExtractor",
    "FilingTextBlock",
    "FilingTextBlockPayload",
]
