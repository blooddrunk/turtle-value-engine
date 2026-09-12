"""Injectable retrieval and content-addressed caching for official filings.

This module stops at the document-byte boundary.  It validates the
``FilingRecord`` supplied by discovery, lets the caller inject the transport,
and stores the returned bytes with auditable provenance.  It does not parse a
document, create evidence or infer any financial fact from its contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StrictStr,
    ValidationError,
    field_validator,
)

from .errors import (
    CacheCorruptionError,
    CacheMissError,
    CacheWriteError,
    FilingDocumentError,
    FilingDocumentRequestError,
    FilingDocumentResponseError,
)
from .filings import FilingMarket, FilingRecord, FilingSource, validate_filing_document_url
from .models import JSONValue, RetrievalMode, canonical_json_bytes, copy_json_object

FILING_DOCUMENT_ADAPTER_VERSION = "filing-document-v1"
FILING_DOCUMENT_SOURCE_NAME = "Official filing document sources"
FILING_DOCUMENT_CONTRACT = "filing_document_v1"

_CACHE_FORMAT_VERSION = 1
_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+\-]+/[a-z0-9!#$&^_.+\-]+$")
_REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "cache_format_version",
        "filing",
        "final_url",
        "retrieved_at",
        "content_sha256",
        "content_size",
        "media_type",
        "retrieval_metadata",
        "blob",
    }
)


def _canonical_media_type(value: str) -> str:
    """Return the stable type/subtype portion of an HTTP media type."""

    if not isinstance(value, str):
        raise TypeError("media_type must be a string")
    normalized = value.split(";", 1)[0].strip().lower()
    if not _MEDIA_TYPE_PATTERN.fullmatch(normalized):
        raise ValueError("media_type must be a valid type/subtype")
    return normalized


def _validated_filing(filing: FilingRecord) -> FilingRecord:
    """Revalidate even a mutated or ``model_construct`` filing record."""

    if not isinstance(filing, FilingRecord):
        raise TypeError("filing must be a FilingRecord")
    try:
        return FilingRecord.model_validate(filing.model_dump(mode="python", warnings=False))
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid filing record: {exc}") from exc


def _filing_snapshot(filing: FilingRecord) -> dict[str, JSONValue]:
    """Return the canonical identity/provenance snapshot used in a manifest."""

    validated = _validated_filing(filing)
    snapshot = validated.model_dump(mode="json")
    snapshot["url"] = validate_filing_document_url(validated.source, validated.url)
    return snapshot


def _filings_match(left: FilingRecord, right: FilingRecord) -> bool:
    return canonical_json_bytes(_filing_snapshot(left)) == canonical_json_bytes(
        _filing_snapshot(right)
    )


def _document_metadata(
    *,
    filing: FilingRecord,
    final_url: str,
    content_sha256: str,
    content_size: int,
    media_type: str,
) -> dict[str, JSONValue]:
    """Return manifest-bound metadata that cannot silently change scope."""

    return {
        "contract": FILING_DOCUMENT_CONTRACT,
        "filing_id": filing.filing_id,
        "listing_id": filing.listing_id,
        "market": filing.market.value,
        "source": filing.source.value,
        "requested_url": validate_filing_document_url(filing.source, filing.url),
        "final_url": final_url,
        "content_sha256": content_sha256,
        "content_size": content_size,
        "media_type": media_type,
    }


class FilingDownloadPayload(BaseModel):
    """Transport-neutral bytes and response metadata returned by an injector."""

    model_config = ConfigDict(extra="forbid")

    content: StrictBytes = Field(min_length=1)
    media_type: StrictStr = Field(min_length=1, max_length=256)
    final_url: AnyHttpUrl | None = None
    response_metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("media_type")
    @classmethod
    def _normalize_media_type(cls, value: str) -> str:
        return _canonical_media_type(value)

    @field_validator("response_metadata", mode="before")
    @classmethod
    def _validate_response_metadata(cls, value: object) -> dict[str, JSONValue]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("response_metadata must be a JSON object")
        return copy_json_object(value, path="response_metadata")


@dataclass(frozen=True, slots=True)
class FilingDocument:
    """One verified document body plus the filing provenance it belongs to."""

    filing: FilingRecord
    content: bytes
    content_sha256: str
    content_size: int
    media_type: str
    retrieved_at: datetime
    final_url: str | None = None
    retrieval_metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        filing = _validated_filing(self.filing)
        object.__setattr__(self, "filing", filing)
        if type(self.content) is not bytes:
            raise TypeError("document content must be bytes")
        if not self.content:
            raise ValueError("document content must not be empty")
        if len(self.content) > _MAX_DOCUMENT_BYTES:
            raise ValueError("document content exceeds the maximum configured size")
        if type(self.content_sha256) is not str or not _HASH_PATTERN.fullmatch(
            self.content_sha256
        ):
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        expected_hash = hashlib.sha256(self.content).hexdigest()
        if self.content_sha256 != expected_hash:
            raise ValueError("content_sha256 does not match document content")
        if type(self.content_size) is not int or self.content_size != len(self.content):
            raise ValueError("content_size does not match document content")
        media_type = _canonical_media_type(self.media_type)
        object.__setattr__(self, "media_type", media_type)
        if not isinstance(self.retrieved_at, datetime):
            raise TypeError("retrieved_at must be a datetime")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        object.__setattr__(self, "retrieved_at", self.retrieved_at.astimezone(UTC))
        final_url = self.final_url if self.final_url is not None else str(filing.url)
        final_url = validate_filing_document_url(filing.source, final_url)
        object.__setattr__(self, "final_url", final_url)
        metadata = copy_json_object(self.retrieval_metadata, path="retrieval_metadata")
        expected_metadata = _document_metadata(
            filing=filing,
            final_url=final_url,
            content_sha256=self.content_sha256,
            content_size=self.content_size,
            media_type=media_type,
        )
        for key, expected in expected_metadata.items():
            if key in metadata and metadata[key] != expected:
                raise ValueError(f"retrieval_metadata[{key!r}] does not match document")
            metadata[key] = expected
        object.__setattr__(self, "retrieval_metadata", metadata)

    @property
    def filing_id(self) -> str:
        return self.filing.filing_id

    @property
    def listing_id(self) -> str:
        return self.filing.listing_id

    @property
    def market(self) -> FilingMarket:
        return self.filing.market

    @property
    def source(self) -> FilingSource:
        return self.filing.source

    @property
    def url(self) -> AnyHttpUrl:
        return self.filing.url

    def manifest_payload(self, blob: str) -> dict[str, JSONValue]:
        """Return the JSON manifest persisted next to the binary content."""

        if not isinstance(blob, str) or not blob:
            raise ValueError("blob must be a non-empty filename")
        return {
            "cache_format_version": _CACHE_FORMAT_VERSION,
            "filing": _filing_snapshot(self.filing),
            "final_url": self.final_url,
            "retrieved_at": self.retrieved_at.isoformat().replace("+00:00", "Z"),
            "content_sha256": self.content_sha256,
            "content_size": self.content_size,
            "media_type": self.media_type,
            "retrieval_metadata": copy_json_object(
                self.retrieval_metadata, path="retrieval_metadata"
            ),
            "blob": blob,
        }


@dataclass(frozen=True, slots=True)
class FilingDocumentSourceClient:
    """One injected official-source transport implementation."""

    source: FilingSource
    download: Callable[[FilingRecord], FilingDownloadPayload | Mapping[str, object]]

    def __post_init__(self) -> None:
        try:
            source = FilingSource(self.source)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported filing source: {self.source!r}") from exc
        object.__setattr__(self, "source", source)
        if not callable(self.download):
            raise TypeError("download must be callable")


class FilingDocumentDownloader:
    """Download one official filing through a caller-supplied source client."""

    def __init__(
        self,
        clients: Mapping[FilingSource | str, FilingDocumentSourceClient],
        *,
        clock: Callable[[], datetime] | None = None,
        max_bytes: int = _MAX_DOCUMENT_BYTES,
    ) -> None:
        if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_DOCUMENT_BYTES:
            raise ValueError(
                f"max_bytes must be an integer between 1 and {_MAX_DOCUMENT_BYTES}"
            )
        normalized: dict[FilingSource, FilingDocumentSourceClient] = {}
        for source, client in clients.items():
            try:
                normalized_source = FilingSource(source)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unsupported filing source: {source!r}") from exc
            if not isinstance(client, FilingDocumentSourceClient):
                raise TypeError("clients must contain FilingDocumentSourceClient values")
            if client.source is not normalized_source:
                raise ValueError("client source does not match its mapping key")
            normalized[normalized_source] = client
        self._clients = normalized
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_bytes = max_bytes

    def download(self, filing: FilingRecord) -> FilingDocument:
        """Fetch, validate and hash one document without parsing its contents."""

        try:
            validated = _validated_filing(filing)
        except (TypeError, ValueError) as exc:
            raise FilingDocumentRequestError(f"invalid filing document request: {exc}") from exc
        client = self._clients.get(validated.source)
        if client is None:
            raise FilingDocumentRequestError(
                f"no injected filing document client configured for {validated.source.value}"
            )
        try:
            response = client.download(validated)
        except FilingDocumentError:
            raise
        except Exception as exc:
            raise FilingDocumentRequestError(
                f"official {validated.source.value} filing document download failed for "
                f"{validated.filing_id}"
            ) from exc
        try:
            payload = FilingDownloadPayload.model_validate(response)
        except (TypeError, ValueError, ValidationError) as exc:
            raise FilingDocumentResponseError(
                f"invalid {validated.source.value} filing document response for "
                f"{validated.filing_id}: {exc}"
            ) from exc
        if len(payload.content) > self._max_bytes:
            raise FilingDocumentResponseError(
                f"filing document exceeds max_bytes={self._max_bytes} for {validated.filing_id}"
            )
        final_url = str(payload.final_url) if payload.final_url is not None else str(validated.url)
        try:
            final_url = validate_filing_document_url(validated.source, final_url)
            metadata: dict[str, JSONValue] = {
                "retrieval_method": "injected_source_client",
            }
            if payload.response_metadata:
                metadata["transport"] = copy_json_object(
                    payload.response_metadata, path="response_metadata"
                )
            content_hash = hashlib.sha256(payload.content).hexdigest()
            return FilingDocument(
                filing=validated,
                content=bytes(payload.content),
                content_sha256=content_hash,
                content_size=len(payload.content),
                media_type=payload.media_type,
                retrieved_at=self._clock(),
                final_url=final_url,
                retrieval_metadata=metadata,
            )
        except FilingDocumentError:
            raise
        except (TypeError, ValueError) as exc:
            raise FilingDocumentResponseError(
                f"invalid filing document provenance for {validated.filing_id}: {exc}"
            ) from exc


class FilingDocumentCache(Protocol):
    """Minimal cache interface for immutable-ish filing document snapshots."""

    def read(
        self,
        filing: FilingRecord,
        *,
        max_age: timedelta | None = None,
        allow_stale: bool = False,
    ) -> FilingDocument | None:
        """Read a valid document or return ``None`` for a cache miss."""

        ...

    def write(self, document: FilingDocument) -> None:
        """Atomically persist document bytes and their manifest."""

        ...


class FilesystemFilingDocumentCache(FilingDocumentCache):
    """Content-addressed binary cache with an atomic JSON manifest."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _directory_for(self, filing: FilingRecord) -> Path:
        validated = _validated_filing(filing)
        return self.root / "filings" / validated.market.value / validated.source.value

    def path_for(self, filing: FilingRecord) -> Path:
        """Return the manifest path for one exact filing identity."""

        validated = _validated_filing(filing)
        return self._directory_for(validated) / f"{validated.filing_id}.json"

    def blob_path_for(self, filing: FilingRecord, content_sha256: str) -> Path:
        """Return the content path for a filing and verified SHA-256 digest."""

        validated = _validated_filing(filing)
        if type(content_sha256) is not str or not _HASH_PATTERN.fullmatch(content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        return self._directory_for(validated) / f"{validated.filing_id}.{content_sha256}.bin"

    def read(
        self,
        filing: FilingRecord,
        *,
        max_age: timedelta | None = None,
        allow_stale: bool = False,
    ) -> FilingDocument | None:
        """Read and verify a manifest plus its content-addressed bytes."""

        if max_age is not None and max_age < timedelta(0):
            raise ValueError("max_age must not be negative")
        validated = _validated_filing(filing)
        path = self.path_for(validated)
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise CacheCorruptionError(f"filing document manifest is not a regular file: {path}")
        try:
            with path.open("rb") as handle:
                envelope = json.load(handle, parse_constant=_reject_non_json_number)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise CacheCorruptionError(
                f"cannot read filing document manifest {path}: {exc}"
            ) from exc
        try:
            document = self._document_from_manifest(envelope, validated, path.parent)
        except CacheCorruptionError:
            raise
        except (TypeError, ValueError, KeyError, OSError, ValidationError) as exc:
            raise CacheCorruptionError(
                f"invalid filing document cache entry {path}: {exc}"
            ) from exc
        if max_age is not None:
            age = datetime.now(UTC) - document.retrieved_at
            if age > max_age and not allow_stale:
                return None
        return document

    def _document_from_manifest(
        self,
        envelope: object,
        filing: FilingRecord,
        directory: Path,
    ) -> FilingDocument:
        if not isinstance(envelope, Mapping):
            raise TypeError("filing document manifest must be a JSON object")
        missing = _REQUIRED_MANIFEST_FIELDS - set(envelope)
        if missing:
            raise ValueError(
                "filing document manifest is incomplete; missing " + ", ".join(sorted(missing))
            )
        unexpected = set(envelope) - _REQUIRED_MANIFEST_FIELDS
        if unexpected:
            raise ValueError(
                "filing document manifest has unexpected fields: " + ", ".join(sorted(unexpected))
            )
        if (
            type(envelope["cache_format_version"]) is not int
            or envelope["cache_format_version"] != _CACHE_FORMAT_VERSION
        ):
            raise ValueError("unsupported filing document cache format version")
        filing_payload = envelope["filing"]
        if not isinstance(filing_payload, Mapping):
            raise TypeError("filing provenance must be a JSON object")
        cached_filing = FilingRecord.model_validate(filing_payload)
        if not _filings_match(cached_filing, filing):
            raise ValueError("cached filing provenance does not match requested filing")
        final_url = envelope["final_url"]
        if not isinstance(final_url, str):
            raise TypeError("final_url must be a string")
        final_url = validate_filing_document_url(filing.source, final_url)
        content_hash = envelope["content_sha256"]
        if type(content_hash) is not str or not _HASH_PATTERN.fullmatch(content_hash):
            raise ValueError("manifest content_sha256 is invalid")
        content_size = envelope["content_size"]
        if type(content_size) is not int or not 1 <= content_size <= _MAX_DOCUMENT_BYTES:
            raise ValueError("manifest content_size is invalid")
        media_type = _canonical_media_type(envelope["media_type"])
        retrieved_at = _parse_timestamp(envelope["retrieved_at"])
        metadata = envelope["retrieval_metadata"]
        if not isinstance(metadata, Mapping):
            raise TypeError("retrieval_metadata must be a JSON object")
        blob = envelope["blob"]
        expected_blob = f"{filing.filing_id}.{content_hash}.bin"
        if blob != expected_blob:
            raise ValueError("manifest blob name does not match filing and content hash")
        blob_path = directory / expected_blob
        if blob_path.is_symlink() or not blob_path.is_file():
            raise CacheCorruptionError(f"filing document blob is not a regular file: {blob_path}")
        content = blob_path.read_bytes()
        if len(content) != content_size:
            raise CacheCorruptionError("filing document blob size does not match manifest")
        if hashlib.sha256(content).hexdigest() != content_hash:
            raise CacheCorruptionError("filing document blob hash does not match manifest")
        return FilingDocument(
            filing=filing,
            content=content,
            content_sha256=content_hash,
            content_size=content_size,
            media_type=media_type,
            retrieved_at=retrieved_at,
            final_url=final_url,
            retrieval_metadata=copy_json_object(metadata, path="retrieval_metadata"),
        )

    def write(self, document: FilingDocument) -> None:
        """Write bytes first and then atomically publish their manifest.

        If either replacement fails, an existing manifest remains untouched.
        A newly written but unreferenced blob is harmless and can be recovered
        or garbage-collected by a later explicit maintenance operation.
        """

        if not isinstance(document, FilingDocument):
            raise TypeError("document must be a FilingDocument")
        manifest_path = self.path_for(document.filing)
        blob_path = self.blob_path_for(document.filing, document.content_sha256)
        try:
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_replace(blob_path, document.content)
            manifest = document.manifest_payload(blob_path.name)
            _atomic_replace(manifest_path, canonical_json_bytes(manifest) + b"\n")
        except (OSError, TypeError, ValueError) as exc:
            raise CacheWriteError(
                f"cannot write filing document cache entry {manifest_path}: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class FilingDocumentFetchResult:
    """Downloaded document plus whether it was live or replayed."""

    document: FilingDocument
    mode: RetrievalMode


def fetch_filing_document_with_cache(
    downloader: FilingDocumentDownloader,
    filing: FilingRecord,
    cache: FilingDocumentCache,
    *,
    offline: bool = False,
    max_age: timedelta | None = None,
    allow_stale: bool = False,
) -> FilingDocumentFetchResult:
    """Fetch a document or explicitly replay its verified local snapshot."""

    if max_age is not None and max_age < timedelta(0):
        raise ValueError("max_age must not be negative")
    validated = _validated_filing(filing)
    if offline:
        cached = cache.read(validated, max_age=max_age, allow_stale=allow_stale)
        if cached is None:
            raise CacheMissError(f"no replayable filing document for {validated.filing_id}")
        return FilingDocumentFetchResult(
            document=cached,
            mode=(
                RetrievalMode.STALE_CACHE_REPLAY
                if _is_stale(cached, max_age)
                else RetrievalMode.CACHE_REPLAY
            ),
        )
    try:
        document = downloader.download(validated)
    except FilingDocumentError:
        if not allow_stale:
            raise
        cached = cache.read(validated, max_age=max_age, allow_stale=True)
        if cached is None:
            raise
        return FilingDocumentFetchResult(
            document=cached,
            mode=(
                RetrievalMode.STALE_CACHE_REPLAY
                if _is_stale(cached, max_age)
                else RetrievalMode.CACHE_REPLAY
            ),
        )
    if not isinstance(document, FilingDocument):
        raise FilingDocumentResponseError(
            "downloader returned something other than FilingDocument"
        )
    if not _filings_match(document.filing, validated):
        raise FilingDocumentResponseError(
            "downloaded document filing provenance does not match request"
        )
    cache.write(document)
    return FilingDocumentFetchResult(document=document, mode=RetrievalMode.LIVE)


def _atomic_replace(path: Path, content: bytes) -> None:
    temporary_path: Path | None = None
    descriptor = -1
    try:
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
        os.replace(temporary_path, path)
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


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("retrieved_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("retrieved_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _reject_non_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _is_stale(document: FilingDocument, max_age: timedelta | None) -> bool:
    if max_age is None:
        return False
    return datetime.now(UTC) - document.retrieved_at > max_age


OfficialFilingDocumentDownloader = FilingDocumentDownloader


__all__ = [
    "FILING_DOCUMENT_ADAPTER_VERSION",
    "FILING_DOCUMENT_CONTRACT",
    "FILING_DOCUMENT_SOURCE_NAME",
    "FilingDocument",
    "FilingDocumentCache",
    "FilingDocumentFetchResult",
    "FilingDocumentDownloader",
    "FilingDocumentSourceClient",
    "FilingDownloadPayload",
    "FilesystemFilingDocumentCache",
    "OfficialFilingDocumentDownloader",
    "fetch_filing_document_with_cache",
]
