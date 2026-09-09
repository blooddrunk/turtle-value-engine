"""Atomic filesystem cache for opaque provider responses."""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from .base import StructuredDataProvider
from .errors import (
    CacheCorruptionError,
    CacheMissError,
    CacheWriteError,
    ProviderError,
)
from .models import (
    DataCategory,
    JSONValue,
    ProviderIdentity,
    ProviderRequest,
    RawProviderRecord,
    RetrievalMode,
    canonical_json_bytes,
    copy_json_object,
)

_CACHE_FORMAT_VERSION = 1
_REQUIRED_ENVELOPE_FIELDS = frozenset(
    {
        "cache_format_version",
        "provider",
        "request",
        "retrieved_at",
        "raw_payload",
        "source_uri",
        "response_metadata",
    }
)


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Deterministic identity for one provider/category/entity request."""

    provider: str
    category: DataCategory
    entity_id: str
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)
    provider_version: str = "unknown"

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider must be a non-empty string")
        if not isinstance(self.provider_version, str) or not self.provider_version.strip():
            raise ValueError("provider_version must be a non-empty string")
        try:
            category = DataCategory(self.category)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported data category: {self.category!r}") from exc
        object.__setattr__(self, "category", category)
        if not isinstance(self.entity_id, str) or not self.entity_id.strip():
            raise ValueError("entity_id must be a non-empty string")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a JSON object")
        object.__setattr__(self, "parameters", copy_json_object(self.parameters, path="parameters"))

    @classmethod
    def from_request(
        cls,
        provider: ProviderIdentity,
        request: ProviderRequest,
    ) -> "CacheKey":
        """Build a key using provider version as part of cache identity."""

        return cls(
            provider=provider.provider_id,
            provider_version=provider.provider_version,
            category=request.category,
            entity_id=request.entity_id,
            parameters=request.parameters,
        )

    @classmethod
    def from_record(cls, record: RawProviderRecord) -> "CacheKey":
        """Build the key represented by one raw provider record."""

        return cls.from_request(record.provider, record.request)

    def identity_payload(self) -> dict[str, JSONValue]:
        """Return all identity fields that participate in the digest."""

        return {
            "provider": self.provider,
            "provider_version": self.provider_version,
            "category": self.category.value,
            "entity_id": self.entity_id,
            "parameters": copy_json_object(self.parameters, path="parameters"),
        }

    @property
    def digest(self) -> str:
        """Return the stable SHA-256 request digest used in the filename."""

        return hashlib.sha256(canonical_json_bytes(self.identity_payload())).hexdigest()

    @property
    def relative_path(self) -> Path:
        """Return a readable provider/category path plus the opaque digest."""

        return Path(_safe_segment(self.provider)) / _safe_segment(self.category.value) / (
            f"{self.digest}.json"
        )


def deterministic_cache_key(
    provider: ProviderIdentity | str,
    request: ProviderRequest,
    *,
    provider_version: str = "unknown",
) -> str:
    """Return only the deterministic digest for callers that need a string key."""

    identity = provider if isinstance(provider, ProviderIdentity) else None
    key = CacheKey.from_request(
        identity
        if identity is not None
        else ProviderIdentity(
            provider_id=provider,
            provider_version=provider_version,
            source_name=provider,
        ),
        request,
    )
    return key.digest


@dataclass(frozen=True, slots=True)
class ProviderFetchResult:
    """Raw record plus whether it came from live acquisition or replay."""

    record: RawProviderRecord
    mode: RetrievalMode


class RawResponseCache(Protocol):
    """Minimal cache interface used by provider orchestration."""

    def read(
        self,
        key: CacheKey,
        *,
        max_age: timedelta | None = None,
        allow_stale: bool = False,
    ) -> RawProviderRecord | None:
        """Read a valid record, returning ``None`` for a miss or disallowed stale entry."""

        ...


    def write(self, record: RawProviderRecord) -> None:
        """Atomically persist a successful raw provider response."""

        ...


class FilesystemRawResponseCache(RawResponseCache):
    """JSON-envelope cache with atomic replacement and strict validation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, key: CacheKey) -> Path:
        """Return the exact path for a key without creating directories."""

        return self.root / key.relative_path

    def read(
        self,
        key: CacheKey,
        *,
        max_age: timedelta | None = None,
        allow_stale: bool = False,
    ) -> RawProviderRecord | None:
        """Read and validate a cache envelope without mutating it."""

        if max_age is not None and max_age < timedelta(0):
            raise ValueError("max_age must not be negative")
        path = self.path_for(key)
        if not path.exists():
            return None
        if not path.is_file():
            raise CacheCorruptionError(f"cache entry is not a file: {path}")
        try:
            with path.open("rb") as handle:
                payload = json.load(handle, parse_constant=_reject_non_json_number)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise CacheCorruptionError(f"cannot read cache entry {path}: {exc}") from exc

        try:
            record = _record_from_envelope(payload, expected_key=key)
        except (TypeError, ValueError, KeyError) as exc:
            raise CacheCorruptionError(f"invalid cache entry {path}: {exc}") from exc

        if max_age is not None:
            age = datetime.now(UTC) - record.retrieved_at
            if age > max_age and not allow_stale:
                return None
        return record

    def write(self, record: RawProviderRecord) -> None:
        """Persist a response only after its complete envelope is serialized.

        A temporary file in the destination directory is fsynced and then
        atomically replaced.  Serialization, directory creation or replace
        failures leave an existing valid snapshot untouched.
        """

        key = CacheKey.from_record(record)
        path = self.path_for(key)
        temporary_path: Path | None = None
        try:
            envelope = _envelope_from_record(record)
            serialized = canonical_json_bytes(envelope) + b"\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{key.digest}.",
                suffix=".tmp",
                dir=path.parent,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        except (OSError, TypeError, ValueError) as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise CacheWriteError(f"cannot write cache entry {path}: {exc}") from exc


def fetch_with_cache(
    provider: StructuredDataProvider,
    request: ProviderRequest,
    cache: RawResponseCache,
    *,
    offline: bool = False,
    max_age: timedelta | None = None,
    allow_stale: bool = False,
) -> ProviderFetchResult:
    """Acquire a record or explicitly replay cache without hiding failures.

    ``offline=True`` never calls the provider.  A provider failure falls back
    to cache only when ``allow_stale=True`` is explicitly requested; the
    default re-raises the provider error.  A cache write occurs only after a
    successful, identity-checked provider response.
    """

    if max_age is not None and max_age < timedelta(0):
        raise ValueError("max_age must not be negative")
    key = CacheKey.from_request(provider.identity, request)
    if offline:
        cached = cache.read(key, max_age=max_age, allow_stale=allow_stale)
        if cached is None:
            raise CacheMissError(f"no replayable cache entry for {key.digest}")
        mode = (
            RetrievalMode.STALE_CACHE_REPLAY
            if _is_stale(cached, max_age)
            else RetrievalMode.CACHE_REPLAY
        )
        return ProviderFetchResult(record=cached, mode=mode)

    try:
        record = provider.fetch(request)
    except ProviderError:
        if not allow_stale:
            raise
        cached = cache.read(key, max_age=max_age, allow_stale=True)
        if cached is None:
            raise
        mode = (
            RetrievalMode.STALE_CACHE_REPLAY
            if _is_stale(cached, max_age)
            else RetrievalMode.CACHE_REPLAY
        )
        return ProviderFetchResult(record=cached, mode=mode)

    cache.write(record)
    return ProviderFetchResult(record=record, mode=RetrievalMode.LIVE)


def _is_stale(record: RawProviderRecord, max_age: timedelta | None) -> bool:
    if max_age is None:
        return False
    return datetime.now(UTC) - record.retrieved_at > max_age


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    return f"_{segment}" if segment in {".", ".."} else segment


def _reject_non_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _envelope_from_record(record: RawProviderRecord) -> dict[str, JSONValue]:
    return {
        "cache_format_version": _CACHE_FORMAT_VERSION,
        "provider": record.provider.as_dict(),
        "request": record.request.as_dict(),
        "retrieved_at": record.retrieved_at.isoformat().replace("+00:00", "Z"),
        "raw_payload": record.raw_payload,
        "source_uri": record.source_uri,
        "response_metadata": copy_json_object(record.response_metadata, path="response_metadata"),
    }


def _record_from_envelope(
    envelope: object,
    *,
    expected_key: CacheKey,
) -> RawProviderRecord:
    if not isinstance(envelope, Mapping):
        raise TypeError("cache envelope must be a JSON object")
    missing = _REQUIRED_ENVELOPE_FIELDS - set(envelope)
    if missing:
        raise ValueError("cache envelope is incomplete; missing " + ", ".join(sorted(missing)))
    if (
        type(envelope["cache_format_version"]) is not int
        or envelope["cache_format_version"] != _CACHE_FORMAT_VERSION
    ):
        raise ValueError("unsupported cache format version")

    provider_data = envelope["provider"]
    if not isinstance(provider_data, Mapping):
        raise TypeError("provider metadata must be a JSON object")
    provider = ProviderIdentity(
        provider_id=_required_string(provider_data, "id"),
        provider_version=_required_string(provider_data, "version"),
        source_name=_required_string(provider_data, "source_name"),
    )

    request_data = envelope["request"]
    if not isinstance(request_data, Mapping):
        raise TypeError("request metadata must be a JSON object")
    if "parameters" not in request_data:
        raise ValueError("request metadata is incomplete; missing parameters")
    parameters = request_data["parameters"]
    if not isinstance(parameters, Mapping):
        raise TypeError("request parameters must be a JSON object")
    request = ProviderRequest(
        category=_required_string(request_data, "category"),
        entity_id=_required_string(request_data, "entity_id"),
        parameters=parameters,
    )
    actual_key = CacheKey.from_request(provider, request)
    if actual_key != expected_key:
        raise ValueError("cache entry identity does not match requested key")

    retrieved_at = _parse_timestamp(envelope["retrieved_at"])
    source_uri = envelope["source_uri"]
    if source_uri is not None and not isinstance(source_uri, str):
        raise TypeError("source_uri must be a string or null")
    response_metadata = envelope["response_metadata"]
    if not isinstance(response_metadata, Mapping):
        raise TypeError("response_metadata must be a JSON object")
    return RawProviderRecord(
        provider=provider,
        request=request,
        retrieved_at=retrieved_at,
        raw_payload=envelope["raw_payload"],
        source_uri=source_uri,
        response_metadata=response_metadata,
    )


def _required_string(mapping: Mapping[object, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("retrieved_at must be an ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    return parsed.astimezone(UTC)
