"""Opt-in historical source acquisition and offline ingestion boundaries.

This module deliberately stops at raw bytes and typed historical rows.  It
does not calculate investment metrics, apply adjustments, or invoke a model.
Network access is only reachable through :class:`HistoricalAcquisitionService`
when its caller explicitly supplies ``network_allowed=True``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse, urlunparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from turtle_value_engine.backtest import (
    BenchmarkObservation,
    CorporateAction,
    FXObservation,
    HistoricalAvailability,
    HistoricalDecisionArtifact,
    ListingLifecycle,
    MarketBar,
    UniverseMembership,
)
from turtle_value_engine.backtest.contracts import CorporateActionType
from turtle_value_engine.providers.errors import FilingDocumentError
from turtle_value_engine.providers.filing_documents import FilingDocumentDownloader
from turtle_value_engine.providers.filings import (
    FilingDescriptor,
    FilingDiscoveryQuery,
    FilingMarket,
    FilingRecord,
    FilingSource,
    filing_id_for,
    validate_filing_document_url,
)
from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    CoverageEvidenceBasis,
    HistoricalCoverageReport,
    HistoricalDatasetManifest,
    HistoricalFilingDocumentRecord,
    HistoricalSourceKind,
    HistoricalTargetScope,
    LicenseStatus,
    ShardArtifactKind,
    SourceAuthority,
    filing_document_artifact_id,
)
from .coverage import build_coverage_report
from .store import HistoricalArtifactStore

ACQUISITION_CONTRACT_VERSION = "historical-acquisition-v1"
RAW_BLOB_CONTRACT_VERSION = "historical-raw-blob-v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "access_key",
    "access_token",
    "auth",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
}
_SAFE_RESPONSE_HEADERS = {
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "retry-after",
    "request-id",
    "x-request-id",
}
_SAFE_CREDENTIAL_CONFIGURATION_KEYS = {
    "credential_header",
    "credential_scheme",
}
_MAX_DOWNLOADS_PER_REQUEST = 10_000
_UNSET = object()
_MODEL_BY_KIND: dict[ShardArtifactKind, type[BaseModel]] = {
    ShardArtifactKind.LISTING_LIFECYCLE: ListingLifecycle,
    ShardArtifactKind.UNIVERSE_MEMBERSHIP: UniverseMembership,
    ShardArtifactKind.AVAILABILITY: HistoricalAvailability,
    ShardArtifactKind.MARKET_BAR: MarketBar,
    ShardArtifactKind.CORPORATE_ACTION: CorporateAction,
    ShardArtifactKind.FX_OBSERVATION: FXObservation,
    ShardArtifactKind.BENCHMARK_OBSERVATION: BenchmarkObservation,
    ShardArtifactKind.DECISION_ARTIFACT: HistoricalDecisionArtifact,
}


class AcquisitionError(RuntimeError):
    """Base error for the opt-in historical acquisition boundary."""


class NetworkDisabledError(AcquisitionError):
    """Raised before any transport is touched without explicit opt-in."""


class CredentialUnavailableError(AcquisitionError):
    """Raised when a required credential reference cannot be resolved."""


class NetworkTransportError(AcquisitionError):
    """Raised for connection failures after bounded retries."""


class RawBlobError(AcquisitionError):
    """Raised when a raw blob cannot be verified or immutably stored."""


class HistoricalSourceSchemaError(AcquisitionError):
    """Raised when an upstream response shape is not explicitly supported."""


class HistoricalIngestionError(AcquisitionError):
    """Raised when raw bytes cannot be compiled into canonical historical rows."""


class ReadinessBlocker(AcquisitionError):
    """Raised only when an operator requests a claim that is not proven."""


class CredentialKind(StrEnum):
    """Credential references are names, never secret values."""

    ENVIRONMENT = "ENVIRONMENT"
    KEYRING = "KEYRING"
    INJECTED = "INJECTED"
    NONE = "NONE"


class NetworkMode(StrEnum):
    DENY = "deny"
    ALLOW = "allow"


class StoragePolicy(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    PRIVATE_REMOTE_ALLOWED = "PRIVATE_REMOTE_ALLOWED"
    REDISTRIBUTABLE = "REDISTRIBUTABLE"


class ProbeStatus(StrEnum):
    PASS = "PASS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"


class AccountEntitlement(StrEnum):
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


class CoverageEvidenceStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class ReadinessLevel(StrEnum):
    NOT_READY = "NOT_READY"
    ACQUISITION_READY = "ACQUISITION_READY"
    PERSONAL_RESEARCH_READY = "PERSONAL_RESEARCH_READY"
    PRODUCTION_ELIGIBLE = "PRODUCTION_ELIGIBLE"


# Pydantic v2 does not accept the recursive alias in this persisted envelope;
# the runtime validator below still enforces JSON shape and rejects secrets.
JSONValue: TypeAlias = Any


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    return any(
        fragment in normalized
        for fragment in (
            "api_key",
            "apikey",
            "access_key",
            "access_token",
            "authorization",
            "client_secret",
            "credential",
            "password",
            "secret",
            "signature",
            "token",
        )
    )


def _is_uri_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized == "url" or normalized.endswith("_url") or normalized.endswith("_uri")


def _utc_now(clock: Any | None = None) -> datetime:
    value = datetime.now(UTC) if clock is None else clock()
    if not isinstance(value, datetime):
        raise TypeError("acquisition clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("acquisition clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _reject_secret_keys(value: object, *, path: str = "value") -> JSONValue:
    """Copy JSON data while refusing the common places a secret can hide."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JSONValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} object keys must be strings")
            if _is_sensitive_key(key) and key.lower().replace("-", "_") not in (
                _SAFE_CREDENTIAL_CONFIGURATION_KEYS
            ):
                raise ValueError(f"{path}.{key} must be a credential reference, not a secret")
            if _is_uri_key(key) and isinstance(child, str):
                parsed = urlparse(child)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    child = _safe_uri(child)
            result[key] = _reject_secret_keys(child, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _reject_secret_keys(item, path=f"{path}[{index}]") for index, item in enumerate(value)
        ]
    raise TypeError(f"{path} must be JSON-compatible")


def _safe_json_object(value: Mapping[str, object], *, path: str) -> dict[str, JSONValue]:
    copied = _reject_secret_keys(value, path=path)
    if not isinstance(copied, dict):
        raise TypeError(f"{path} must be a JSON object")
    return copied


def _safe_uri(value: str | None) -> str | None:
    """Return a stable URI without query credentials or expiring signatures."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source URI must be a non-empty string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URI must be an absolute HTTP(S) URI")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source URI must not contain userinfo")
    if any(_is_sensitive_key(key) for key, _ in parse_qsl(parsed.query)):
        raise ValueError("source URI must not contain credential query parameters")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _safe_headers(headers: Mapping[str, object] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_value in (headers or {}).items():
        key = str(raw_key).lower()
        if key not in _SAFE_RESPONSE_HEADERS:
            continue
        value = str(raw_value)
        if "\r" in value or "\n" in value:
            raise ValueError("response header contains a line break")
        result[key] = value[:2_000]
    return dict(sorted(result.items()))


def _model_sha256(model: BaseModel, *, exclude: set[str] | None = None) -> str:
    payload = model.model_dump(
        mode="json",
        exclude=exclude or set(),
        warnings=False,
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class CredentialReferenceV1(BaseModel):
    """A non-secret pointer to an environment variable or OS keyring entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["credential_reference_v1"] = "credential_reference_v1"
    reference_id: StrictStr = Field(min_length=1)
    kind: Literal["ENVIRONMENT", "KEYRING", "INJECTED", "NONE"]
    name: StrictStr | None = Field(default=None, min_length=1)
    service: StrictStr | None = Field(default=None, min_length=1)
    account: StrictStr | None = Field(default=None, min_length=1)
    required: StrictBool = True

    @model_validator(mode="after")
    def validate_reference(self) -> CredentialReferenceV1:
        if self.kind == CredentialKind.ENVIRONMENT and self.name is None:
            raise ValueError("ENVIRONMENT credential references require name")
        if self.kind == CredentialKind.KEYRING and (self.service is None or self.account is None):
            raise ValueError("KEYRING credential references require service and account")
        if self.kind in {CredentialKind.INJECTED, CredentialKind.NONE} and self.name is not None:
            raise ValueError("INJECTED/NONE credential references must not carry a secret name")
        return self


class HistoricalSourceSpecV1(BaseModel):
    """Operator-declared source policy; actual access is established by probes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_source_spec_v1"] = "historical_source_spec_v1"
    source_id: StrictStr = Field(min_length=1)
    source_kind: HistoricalSourceKind
    adapter_id: StrictStr = Field(min_length=1)
    provider_id: StrictStr = Field(min_length=1)
    source_name: StrictStr = Field(min_length=1)
    source_uri: StrictStr | None = Field(default=None, min_length=1)
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    license_status: LicenseStatus = LicenseStatus.UNKNOWN
    licensing_constraints: StrictStr = Field(min_length=1)
    license_evidence_uri: StrictStr | None = Field(default=None, min_length=1)
    license_evidence_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    access_grant_reference: StrictStr | None = Field(default=None, min_length=1)
    historical_capable: StrictBool = False
    is_current_snapshot: StrictBool = False
    coverage_start: date
    coverage_end: date
    coverage_listing_ids: list[StrictStr] = Field(min_length=1)
    source_version: StrictStr | None = Field(default=None, min_length=1)

    @field_validator("source_uri", "license_evidence_uri")
    @classmethod
    def validate_uri(cls, value: str | None) -> str | None:
        return _safe_uri(value)

    @field_validator("coverage_listing_ids")
    @classmethod
    def validate_listings(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("coverage_listing_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> HistoricalSourceSpecV1:
        if self.coverage_end < self.coverage_start:
            raise ValueError("source coverage_end must not precede coverage_start")
        if (self.license_evidence_uri is None) != (self.license_evidence_sha256 is None):
            raise ValueError("license evidence URI and hash must be supplied together")
        if (
            self.source_kind is HistoricalSourceKind.UNIVERSE_MEMBERSHIP
            and self.is_current_snapshot
        ):
            raise ValueError("current snapshots cannot be historical membership")
        return self


class HistoricalAcquisitionRequestV1(BaseModel):
    """One bounded, replayable request owned by a source adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_acquisition_request_v1"] = "historical_acquisition_request_v1"
    request_id: StrictStr = Field(min_length=1)
    source_id: StrictStr = Field(min_length=1)
    adapter_id: StrictStr = Field(min_length=1)
    source_kind: HistoricalSourceKind
    artifact_kind: ShardArtifactKind
    schema_version: StrictStr = Field(min_length=1)
    listing_ids: list[StrictStr] = Field(min_length=1)
    start_date: date
    end_date: date
    parameters: dict[str, JSONValue] = Field(default_factory=dict)
    credential_ref: CredentialReferenceV1 | None = None
    expected_sessions_by_listing: dict[str, list[date]] | None = None
    coverage_evidence_basis: CoverageEvidenceBasis | None = None

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: Mapping[str, object]) -> dict[str, JSONValue]:
        return _safe_json_object(value, path="parameters")

    @field_validator("listing_ids")
    @classmethod
    def validate_listing_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("listing_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> HistoricalAcquisitionRequestV1:
        if self.end_date < self.start_date:
            raise ValueError("request end_date must not precede start_date")
        if (
            self.artifact_kind is ShardArtifactKind.FILING_DOCUMENT
            and self.source_kind is not HistoricalSourceKind.FILINGS
        ):
            raise ValueError("FILING_DOCUMENT requests must use the FILINGS source category")
        if self.expected_sessions_by_listing is not None:
            unknown = set(self.expected_sessions_by_listing) - set(self.listing_ids)
            if unknown:
                raise ValueError(
                    "expected_sessions_by_listing contains listings outside request: "
                    + ",".join(sorted(unknown))
                )
            for listing_id, values in self.expected_sessions_by_listing.items():
                if len(values) != len(set(values)):
                    raise ValueError(f"expected sessions contain duplicates: {listing_id}")
                if any(value < self.start_date or value > self.end_date for value in values):
                    raise ValueError(f"expected sessions lie outside request: {listing_id}")
        return self

    @property
    def request_identity(self) -> str:
        payload = {
            "source_id": self.source_id,
            "adapter_id": self.adapter_id,
            "source_kind": self.source_kind.value,
            "artifact_kind": self.artifact_kind.value,
            "schema_version": self.schema_version,
            "listing_ids": sorted(self.listing_ids),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "parameters": self.parameters,
        }
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class HistoricalAcquisitionPlanV1(BaseModel):
    """Complete non-secret plan needed to reproduce an acquisition batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_acquisition_plan_v1"] = "historical_acquisition_plan_v1"
    plan_id: StrictStr = Field(min_length=1)
    plan_version: StrictStr = Field(min_length=1)
    created_at: datetime
    target: HistoricalTargetScope
    sources: list[HistoricalSourceSpecV1] = Field(min_length=1)
    requests: list[HistoricalAcquisitionRequestV1] = Field(min_length=1)
    credential_references: list[CredentialReferenceV1] = Field(default_factory=list)
    network_default: Literal["deny", "allow"] = NetworkMode.DENY
    storage_policy: Literal["LOCAL_ONLY", "PRIVATE_REMOTE_ALLOWED", "REDISTRIBUTABLE"] = (
        StoragePolicy.LOCAL_ONLY
    )
    notes: list[StrictStr] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_plan(self) -> HistoricalAcquisitionPlanV1:
        if self.created_at.tzinfo is None:
            raise ValueError("plan created_at must be timezone-aware")
        source_ids = [item.source_id for item in self.sources]
        request_ids = [item.request_id for item in self.requests]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique")
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("request IDs must be unique")
        source_by_id = {item.source_id: item for item in self.sources}
        target_ids = set(self.target.listing_ids)
        for source in self.sources:
            if not set(source.coverage_listing_ids).issubset(target_ids):
                raise ValueError(
                    "source coverage lists a listing outside target: " + source.source_id
                )
        for request in self.requests:
            source = source_by_id.get(request.source_id)
            if source is None:
                raise ValueError("request references unknown source: " + request.source_id)
            if request.adapter_id != source.adapter_id:
                raise ValueError("request/source adapter mismatch: " + request.request_id)
            if request.source_kind is not source.source_kind:
                raise ValueError("request/source category mismatch: " + request.request_id)
            if not set(request.listing_ids).issubset(target_ids):
                raise ValueError("request listing lies outside target: " + request.request_id)
            if not set(request.listing_ids).issubset(set(source.coverage_listing_ids)):
                raise ValueError(
                    "request listing is outside declared source coverage: "
                    + request.request_id
                )
            if (
                request.start_date < source.coverage_start
                or request.end_date > source.coverage_end
            ):
                raise ValueError(
                    "request date range is outside declared source coverage: "
                    + request.request_id
                )
            if (
                request.start_date < self.target.start_date
                or request.end_date > self.target.end_date
            ):
                raise ValueError("request date range lies outside target: " + request.request_id)
        reference_ids = [item.reference_id for item in self.credential_references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("credential reference IDs must be unique")
        references_by_id = {
            item.reference_id: item for item in self.credential_references
        }
        for request in self.requests:
            if request.credential_ref is not None:
                declared = references_by_id.get(request.credential_ref.reference_id)
                if declared is None:
                    raise ValueError(
                        "request references undeclared credential: " + request.request_id
                    )
                if declared != request.credential_ref:
                    raise ValueError(
                        "request credential reference differs from plan declaration: "
                        + request.request_id
                    )
        if self.storage_policy == StoragePolicy.REDISTRIBUTABLE:
            for source in self.sources:
                if source.license_status is not LicenseStatus.OPEN_REDISTRIBUTABLE:
                    raise ValueError(
                        "REDISTRIBUTABLE storage requires an open-redistributable source: "
                        + source.source_id
                    )
                if source.license_evidence_uri is None or source.license_evidence_sha256 is None:
                    raise ValueError(
                        "REDISTRIBUTABLE storage requires license evidence: " + source.source_id
                    )
        return self

    @property
    def content_sha256(self) -> str:
        return _model_sha256(self)


class RawArtifactReceiptV1(BaseModel):
    """Receipt for one exact raw response body; no secret value is persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["raw_artifact_receipt_v1"] = "raw_artifact_receipt_v1"
    receipt_id: StrictStr = Field(min_length=1)
    artifact_id: StrictStr = Field(min_length=1)
    batch_id: StrictStr = Field(min_length=1)
    parent_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    request_id: StrictStr = Field(min_length=1)
    request_identity: StrictStr = Field(pattern=_HASH_PATTERN)
    source_id: StrictStr = Field(min_length=1)
    source_kind: HistoricalSourceKind
    adapter_id: StrictStr = Field(min_length=1)
    adapter_version: StrictStr = Field(min_length=1)
    artifact_role: Literal["DATA", "FILING_DOCUMENT"] = "DATA"
    artifact_kind: ShardArtifactKind | None = None
    schema_version: StrictStr | None = Field(default=None, min_length=1)
    canonical_parameters: dict[str, JSONValue] = Field(default_factory=dict)
    artifact_metadata: dict[str, JSONValue] = Field(default_factory=dict)
    source_uri: StrictStr = Field(min_length=1)
    retrieval_started_at: datetime
    retrieval_finished_at: datetime
    http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    content_type: StrictStr | None = Field(default=None, min_length=1)
    content_length: StrictInt = Field(ge=0)
    response_headers: dict[str, StrictStr] = Field(default_factory=dict)
    byte_length: StrictInt = Field(ge=0)
    sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    license_evidence_uri: StrictStr | None = Field(default=None, min_length=1)
    license_evidence_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    access_grant_reference: StrictStr | None = Field(default=None, min_length=1)
    storage_policy: Literal["LOCAL_ONLY", "PRIVATE_REMOTE_ALLOWED", "REDISTRIBUTABLE"] = (
        StoragePolicy.LOCAL_ONLY
    )

    @field_validator("canonical_parameters")
    @classmethod
    def validate_parameters(cls, value: Mapping[str, object]) -> dict[str, JSONValue]:
        return _safe_json_object(value, path="canonical_parameters")

    @field_validator("artifact_metadata")
    @classmethod
    def validate_artifact_metadata(cls, value: Mapping[str, object]) -> dict[str, JSONValue]:
        return _safe_json_object(value, path="artifact_metadata")

    @field_validator("source_uri")
    @classmethod
    def validate_source_uri(cls, value: str) -> str:
        safe = _safe_uri(value)
        if safe is None:
            raise ValueError("raw receipt requires a stable source URI")
        return safe

    @field_validator("license_evidence_uri")
    @classmethod
    def validate_license_evidence_uri(cls, value: str | None) -> str | None:
        return _safe_uri(value)

    @field_validator("response_headers")
    @classmethod
    def validate_headers(cls, value: Mapping[str, object]) -> dict[str, str]:
        return _safe_headers(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> RawArtifactReceiptV1:
        if self.retrieval_started_at.tzinfo is None or self.retrieval_finished_at.tzinfo is None:
            raise ValueError("receipt retrieval timestamps must be timezone-aware")
        if self.retrieval_finished_at < self.retrieval_started_at:
            raise ValueError("receipt retrieval_finished_at must not precede start")
        expected_artifact_id = "raw-" + self.sha256[:32]
        if self.artifact_id != expected_artifact_id:
            raise ValueError("receipt artifact_id does not match sha256")
        expected_receipt_id = "receipt-" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "request_identity": self.request_identity,
                    "sha256": self.sha256,
                    "artifact_role": self.artifact_role,
                    "artifact_metadata": self.artifact_metadata,
                }
            )
        ).hexdigest()[:32]
        if self.receipt_id != expected_receipt_id:
            raise ValueError("receipt_id does not match request/content identity")
        if self.byte_length != self.content_length:
            raise ValueError("receipt content_length must equal byte_length")
        if (
            self.response_headers.get("content-length") is not None
            and int(self.response_headers["content-length"]) != self.byte_length
        ):
            raise ValueError("receipt response content-length does not match bytes")
        if self.artifact_role == "DATA" and self.artifact_kind is None:
            raise ValueError("DATA receipt requires an artifact kind")
        if self.schema_version is None:
            raise ValueError("raw receipt requires a schema version")
        if self.artifact_role == "FILING_DOCUMENT" and self.artifact_kind is not None:
            raise ValueError("FILING_DOCUMENT receipt must not carry a canonical data kind")
        if (self.license_evidence_uri is None) != (self.license_evidence_sha256 is None):
            raise ValueError("receipt license evidence URI and hash must be supplied together")
        return self

    @classmethod
    def build(
        cls,
        *,
        batch_id: str,
        request: HistoricalAcquisitionRequestV1,
        adapter_version: str,
        body: bytes,
        retrieval_started_at: datetime,
        retrieval_finished_at: datetime,
        source_uri: str,
        http_status: int | None,
        content_type: str | None,
        response_headers: Mapping[str, object] | None,
        artifact_role: str = "DATA",
        parent_artifact_id: str | None = None,
        artifact_kind: ShardArtifactKind | None | object = _UNSET,
        schema_version: str | None = None,
        artifact_metadata: Mapping[str, object] | None = None,
        license_evidence_uri: str | None = None,
        license_evidence_sha256: str | None = None,
        access_grant_reference: str | None = None,
        storage_policy: str = StoragePolicy.LOCAL_ONLY,
    ) -> RawArtifactReceiptV1:
        digest = hashlib.sha256(body).hexdigest()
        safe_artifact_metadata = _safe_json_object(
            artifact_metadata or {}, path="artifact_metadata"
        )
        identity_payload = {
            "request_identity": request.request_identity,
            "sha256": digest,
            "artifact_role": artifact_role,
            "artifact_metadata": safe_artifact_metadata,
        }
        receipt_id = (
            "receipt-" + hashlib.sha256(canonical_json_bytes(identity_payload)).hexdigest()[:32]
        )
        artifact_id = "raw-" + digest[:32]
        return cls(
            receipt_id=receipt_id,
            artifact_id=artifact_id,
            batch_id=batch_id,
            parent_artifact_id=parent_artifact_id,
            request_id=request.request_id,
            request_identity=request.request_identity,
            source_id=request.source_id,
            source_kind=request.source_kind,
            adapter_id=request.adapter_id,
            adapter_version=adapter_version,
            artifact_role=artifact_role,
            artifact_kind=(
                (
                    None
                    if artifact_role == "FILING_DOCUMENT"
                    else request.artifact_kind
                )
                if artifact_kind is _UNSET
                else artifact_kind
            ),
            schema_version=schema_version if schema_version is not None else request.schema_version,
            canonical_parameters=request.parameters,
            artifact_metadata=safe_artifact_metadata,
            source_uri=source_uri,
            retrieval_started_at=retrieval_started_at,
            retrieval_finished_at=retrieval_finished_at,
            http_status=http_status,
            content_type=content_type,
            content_length=len(body),
            response_headers=response_headers or {},
            byte_length=len(body),
            sha256=digest,
            license_evidence_uri=license_evidence_uri,
            license_evidence_sha256=license_evidence_sha256,
            access_grant_reference=access_grant_reference,
            storage_policy=storage_policy,
        )


def _batch_id_from_artifacts(
    plan_sha256: str,
    artifacts: Sequence[Mapping[str, object]],
) -> str:
    """Derive a batch identity from every child artifact, not list position."""

    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "plan_sha256": plan_sha256,
                "artifacts": sorted(
                    artifacts,
                    key=lambda item: (
                        item["request_id"],
                        item["sha256"],
                        item["artifact_role"],
                    ),
                ),
            }
        )
    ).hexdigest()
    return "batch-" + digest[:32]


def _expected_batch_id(
    plan_sha256: str,
    receipts: Sequence[RawArtifactReceiptV1],
) -> str:
    """Derive a batch identity from every receipt, not from a list position."""

    return _batch_id_from_artifacts(
        plan_sha256,
        [
            {
                "request_id": receipt.request_id,
                "request_identity": receipt.request_identity,
                "sha256": receipt.sha256,
                "artifact_role": receipt.artifact_role,
                "artifact_metadata": receipt.artifact_metadata,
            }
            for receipt in receipts
        ],
    )


class RawSourceAggregateV1(BaseModel):
    """Stable per-source artifact listing every child receipt and blob hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["raw_source_aggregate_v1"] = "raw_source_aggregate_v1"
    aggregate_id: StrictStr = Field(min_length=1)
    source_id: StrictStr = Field(min_length=1)
    source_kind: HistoricalSourceKind
    request_ids: list[StrictStr] = Field(min_length=1)
    child_receipt_ids: list[StrictStr] = Field(min_length=1)
    child_blob_sha256: list[StrictStr] = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("request_ids", "child_receipt_ids")
    @classmethod
    def validate_unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source aggregate child IDs must not contain duplicates")
        return value

    @field_validator("child_blob_sha256")
    @classmethod
    def validate_child_hashes(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(_HASH_PATTERN, item) for item in value):
            raise ValueError("source aggregate child blobs must be lowercase SHA-256 hashes")
        return value

    @model_validator(mode="after")
    def validate_aggregate(self) -> RawSourceAggregateV1:
        if len(self.child_receipt_ids) != len(self.child_blob_sha256):
            raise ValueError("source aggregate receipt/blob lists must have equal length")
        expected_content = _model_sha256(
            self,
            exclude={"content_sha256", "aggregate_id"},
        )
        if self.content_sha256 != expected_content:
            raise ValueError("source aggregate content_sha256 does not match content")
        if self.aggregate_id != "aggregate-" + self.content_sha256[:32]:
            raise ValueError("source aggregate ID does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        source_kind: HistoricalSourceKind,
        receipts: Sequence[RawArtifactReceiptV1],
    ) -> RawSourceAggregateV1:
        ordered = sorted(
            receipts,
            key=lambda item: (item.request_id, item.receipt_id, item.sha256),
        )
        if not ordered:
            raise ValueError("source aggregate requires at least one receipt")
        if any(
            item.source_id != source_id or item.source_kind is not source_kind
            for item in ordered
        ):
            raise ValueError("source aggregate receipts do not match source identity")
        candidate = cls.model_construct(
            contract="raw_source_aggregate_v1",
            aggregate_id="aggregate-" + "0" * 32,
            source_id=source_id,
            source_kind=source_kind,
            request_ids=sorted({item.request_id for item in ordered}),
            child_receipt_ids=[item.receipt_id for item in ordered],
            child_blob_sha256=[item.sha256 for item in ordered],
            content_sha256="0" * 64,
        )
        content_sha256 = _model_sha256(
            candidate,
            exclude={"content_sha256", "aggregate_id"},
        )
        candidate = candidate.model_copy(
            update={
                "content_sha256": content_sha256,
                "aggregate_id": "aggregate-" + content_sha256[:32],
            }
        )
        return cls.model_validate(candidate.model_dump(mode="python", warnings=False))


def _build_source_aggregates(
    receipts: Sequence[RawArtifactReceiptV1],
) -> list[RawSourceAggregateV1]:
    grouped: dict[str, list[RawArtifactReceiptV1]] = defaultdict(list)
    for receipt in receipts:
        grouped[receipt.source_id].append(receipt)
    return [
        RawSourceAggregateV1.build(
            source_id=source_id,
            source_kind=items[0].source_kind,
            receipts=items,
        )
        for source_id, items in sorted(grouped.items())
    ]


class RawAcquisitionBatchManifestV1(BaseModel):
    """Immutable batch index linking requests, receipts and raw blob hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["raw_acquisition_batch_manifest_v1"] = "raw_acquisition_batch_manifest_v1"
    batch_id: StrictStr = Field(min_length=1)
    plan_id: StrictStr = Field(min_length=1)
    plan_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    created_at: datetime
    plan: HistoricalAcquisitionPlanV1
    receipts: list[RawArtifactReceiptV1] = Field(min_length=1)
    # Additive field: old v1 batch files omit it and remain readable.  New
    # batches persist the explicit aggregate artifact required for multi-page
    # source provenance.
    source_aggregates: list[RawSourceAggregateV1] = Field(default_factory=list)
    batch_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_batch(self) -> RawAcquisitionBatchManifestV1:
        if self.created_at.tzinfo is None:
            raise ValueError("batch created_at must be timezone-aware")
        if self.plan.plan_id != self.plan_id or self.plan.content_sha256 != self.plan_sha256:
            raise ValueError("batch plan identity does not match embedded plan")
        if any(item.batch_id != self.batch_id for item in self.receipts):
            raise ValueError("receipt batch identity does not match batch")
        receipt_ids = [item.receipt_id for item in self.receipts]
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("receipt IDs must be unique within a batch")
        plan_request_ids = {item.request_id for item in self.plan.requests}
        receipt_request_ids = {item.request_id for item in self.receipts}
        unknown_request_ids = receipt_request_ids - plan_request_ids
        if unknown_request_ids:
            raise ValueError(
                "batch receipts reference unknown requests: "
                + ",".join(sorted(unknown_request_ids))
            )
        missing_request_ids = plan_request_ids - receipt_request_ids
        if missing_request_ids:
            raise ValueError(
                "batch is missing receipts for requests: "
                + ",".join(sorted(missing_request_ids))
            )
        if self.source_aggregates:
            expected_aggregates = _build_source_aggregates(self.receipts)
            if self.source_aggregates != expected_aggregates:
                raise ValueError("source aggregate artifacts do not match receipts")
        expected_batch_id = _expected_batch_id(self.plan_sha256, self.receipts)
        if self.batch_id != expected_batch_id:
            raise ValueError("batch_id does not match plan and receipt identities")
        expected = _model_sha256(self, exclude={"batch_sha256"})
        if self.batch_sha256 != expected:
            # Batches written before source_aggregates was added remain valid
            # wire artifacts; no new batch can use this legacy hash path.
            legacy_expected = _model_sha256(
                self,
                exclude={"batch_sha256", "source_aggregates"},
            )
            if self.source_aggregates or self.batch_sha256 != legacy_expected:
                raise ValueError("batch_sha256 does not match batch content")
        return self

    @classmethod
    def build(
        cls,
        *,
        batch_id: str,
        plan: HistoricalAcquisitionPlanV1,
        created_at: datetime,
        receipts: list[RawArtifactReceiptV1],
    ) -> RawAcquisitionBatchManifestV1:
        candidate = cls.model_construct(
            contract="raw_acquisition_batch_manifest_v1",
            batch_id=batch_id,
            plan_id=plan.plan_id,
            plan_sha256=plan.content_sha256,
            created_at=created_at,
            plan=plan,
            receipts=receipts,
            source_aggregates=_build_source_aggregates(receipts),
            batch_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["batch_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "batch_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)

    def source_aggregate_hash(self, source_id: str) -> str:
        """Hash all child blobs for a source, never an arbitrary page hash."""

        for aggregate in self.source_aggregates:
            if aggregate.source_id == source_id:
                return aggregate.content_sha256

        child_hashes = sorted(
            {receipt.sha256 for receipt in self.receipts if receipt.source_id == source_id}
        )
        return hashlib.sha256(
            canonical_json_bytes({"source_id": source_id, "child_sha256": child_hashes})
        ).hexdigest()


class SourceProbeReportV1(BaseModel):
    """Observed source capability, entitlement and coverage evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["source_probe_report_v1"] = "source_probe_report_v1"
    report_id: StrictStr = Field(min_length=1)
    plan_id: StrictStr = Field(min_length=1)
    request_id: StrictStr = Field(min_length=1)
    source_id: StrictStr = Field(min_length=1)
    adapter_id: StrictStr = Field(min_length=1)
    adapter_version: StrictStr = Field(min_length=1)
    source_kind: HistoricalSourceKind
    status: Literal["PASS", "FAILED", "BLOCKED", "NOT_RUN"]
    started_at: datetime
    finished_at: datetime
    http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    content_type: StrictStr | None = Field(default=None, min_length=1)
    content_length: StrictInt | None = Field(default=None, ge=0)
    response_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    source_uri: StrictStr | None = Field(default=None, min_length=1)
    observed_start: date | None = None
    observed_end: date | None = None
    observed_listing_ids: list[StrictStr] = Field(default_factory=list)
    account_entitlement: Literal["CONFIRMED", "DENIED", "UNKNOWN"] = AccountEntitlement.UNKNOWN
    historical_capable: StrictBool = False
    terminal_coverage: Literal["CONFIRMED", "UNVERIFIED", "UNKNOWN"] = (
        CoverageEvidenceStatus.UNKNOWN
    )
    action_coverage: Literal["CONFIRMED", "UNVERIFIED", "UNKNOWN"] = CoverageEvidenceStatus.UNKNOWN
    throttling_observed: StrictBool = False
    license_evidence_uri: StrictStr | None = Field(default=None, min_length=1)
    license_evidence_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    access_grant_reference: StrictStr | None = Field(default=None, min_length=1)
    blockers: list[StrictStr] = Field(default_factory=list, max_length=256)
    warnings: list[StrictStr] = Field(default_factory=list, max_length=256)
    report_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("source_uri", "license_evidence_uri")
    @classmethod
    def validate_uri(cls, value: str | None) -> str | None:
        return _safe_uri(value)

    @model_validator(mode="after")
    def validate_probe(self) -> SourceProbeReportV1:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("probe timestamps must be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("probe finished_at must not precede started_at")
        if self.observed_start and self.observed_end and self.observed_end < self.observed_start:
            raise ValueError("probe observed_end must not precede observed_start")
        if (self.license_evidence_uri is None) != (self.license_evidence_sha256 is None):
            raise ValueError("probe license evidence URI and hash must be supplied together")
        if self.report_sha256 != _model_sha256(self, exclude={"report_sha256"}):
            raise ValueError("probe report_sha256 does not match report content")
        return self

    @classmethod
    def build(cls, **values: Any) -> SourceProbeReportV1:
        values = dict(values)
        values.setdefault("report_sha256", "0" * 64)
        candidate = cls.model_construct(**values)
        values["report_sha256"] = _model_sha256(candidate, exclude={"report_sha256"})
        return cls.model_validate(values)


class AcquisitionReadinessReportV1(BaseModel):
    """Separate readiness claims; ``production_eligible`` is never inferred."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["acquisition_readiness_report_v1"] = "acquisition_readiness_report_v1"
    report_id: StrictStr = Field(min_length=1)
    plan_id: StrictStr = Field(min_length=1)
    generated_at: datetime
    network_used: StrictBool = False
    readiness: Literal[
        "NOT_READY", "ACQUISITION_READY", "PERSONAL_RESEARCH_READY", "PRODUCTION_ELIGIBLE"
    ] = ReadinessLevel.NOT_READY
    acquisition_ready: StrictBool = False
    personal_research_ready: StrictBool = False
    production_eligible: StrictBool = False
    probe_reports: list[SourceProbeReportV1] = Field(default_factory=list)
    batch_ids: list[StrictStr] = Field(default_factory=list)
    compiled_dataset_id: StrictStr | None = Field(default=None, min_length=1)
    blockers: list[StrictStr] = Field(default_factory=list, max_length=512)
    warnings: list[StrictStr] = Field(default_factory=list, max_length=512)
    report_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_report(self) -> AcquisitionReadinessReportV1:
        if self.generated_at.tzinfo is None:
            raise ValueError("readiness generated_at must be timezone-aware")
        if self.readiness == ReadinessLevel.NOT_READY and (
            self.acquisition_ready
            or self.personal_research_ready
            or self.production_eligible
        ):
            raise ValueError("NOT_READY cannot carry a ready flag")
        if self.production_eligible and self.readiness != ReadinessLevel.PRODUCTION_ELIGIBLE:
            raise ValueError("production_eligible requires PRODUCTION_ELIGIBLE readiness")
        if self.personal_research_ready and not self.acquisition_ready:
            raise ValueError("personal research readiness requires acquisition readiness")
        if self.readiness == ReadinessLevel.ACQUISITION_READY and not self.acquisition_ready:
            raise ValueError("ACQUISITION_READY requires acquisition_ready")
        if self.readiness == ReadinessLevel.PERSONAL_RESEARCH_READY and not (
            self.personal_research_ready
        ):
            raise ValueError("PERSONAL_RESEARCH_READY requires personal_research_ready")
        if self.readiness == ReadinessLevel.PRODUCTION_ELIGIBLE and not (
            self.production_eligible
        ):
            raise ValueError("PRODUCTION_ELIGIBLE requires production_eligible")
        if self.personal_research_ready and self.blockers:
            raise ValueError("personal research readiness cannot carry blockers")
        if self.production_eligible and self.blockers:
            raise ValueError("production eligibility cannot carry blockers")
        acquisition_blockers = (
            "RAW_",
            "SOURCE_TERMS_UNVERIFIED",
            "SOURCE_LICENSE_",
            "ACCESS_GRANT_UNVERIFIED",
        )
        if self.acquisition_ready and any(
            blocker.startswith(acquisition_blockers) for blocker in self.blockers
        ):
            raise ValueError("acquisition readiness cannot carry raw or authorization blockers")
        if self.report_sha256 != _model_sha256(self, exclude={"report_sha256"}):
            raise ValueError("readiness report_sha256 does not match report content")
        return self

    @classmethod
    def build(cls, **values: Any) -> AcquisitionReadinessReportV1:
        values = dict(values)
        values.setdefault("report_sha256", "0" * 64)
        candidate = cls.model_construct(**values)
        values["report_sha256"] = _model_sha256(candidate, exclude={"report_sha256"})
        return cls.model_validate(values)


class CredentialResolver(Protocol):
    """Resolve a reference without exposing the resolved secret to callers."""

    def resolve(self, reference: CredentialReferenceV1) -> str | None:
        """Return a secret for the reference, or ``None`` when unavailable."""


class EnvironmentCredentialResolver:
    """Environment/keyring resolver; it never reads chat or process arguments."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = os.environ if environment is None else environment

    def resolve(self, reference: CredentialReferenceV1) -> str | None:
        if reference.kind == CredentialKind.NONE:
            return None
        if reference.kind == CredentialKind.ENVIRONMENT:
            value = self._environment.get(reference.name or "")
            return value if value else None
        if reference.kind == CredentialKind.KEYRING:
            try:
                import keyring  # type: ignore[import-not-found]

                return keyring.get_password(reference.service or "", reference.account or "")
            except Exception:
                return None
        # INJECTED values require an explicitly supplied resolver.
        return None


class MappingCredentialResolver:
    """Test/operator-injected resolver; values stay in memory only."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def resolve(self, reference: CredentialReferenceV1) -> str | None:
        return self._values.get(reference.reference_id)


@dataclass(frozen=True, slots=True)
class NetworkResponse:
    """Minimal transport response retaining exact body bytes."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    @property
    def content_type(self) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == "content-type":
                return value.split(";", 1)[0].strip().lower() or None
        return None


class NetworkTransport(Protocol):
    """Injected network boundary used by adapters and deterministic tests."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> NetworkResponse:
        """Execute one request; retry policy belongs to the wrapper."""


class UrllibNetworkTransport:
    """Small standard-library HTTP transport with no implicit retry."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> NetworkResponse:
        request = UrlRequest(url, method=method.upper(), headers=dict(headers or {}))
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                body = response.read()
                return NetworkResponse(
                    status_code=int(response.status),
                    headers=dict(response.headers.items()),
                    body=body,
                    url=response.geturl(),
                )
        except HTTPError as exc:
            try:
                body = exc.read()
            except OSError:
                body = b""
            return NetworkResponse(
                status_code=int(exc.code),
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=body,
                url=url,
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise NetworkTransportError("network connection failed") from exc


@dataclass(slots=True)
class _HostState:
    semaphore: threading.BoundedSemaphore
    rate_lock: threading.Lock = field(default_factory=threading.Lock)
    tokens: float = 1.0
    last_refill: float | None = None


class ResilientNetworkTransport:
    """Bounded retry, host concurrency and conservative token pacing."""

    _RETRYABLE_SERVER_STATUSES = frozenset({500, 502, 503, 504})

    def __init__(
        self,
        inner: NetworkTransport,
        *,
        max_attempts: int = 4,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 30.0,
        per_host_concurrency: int = 2,
        per_host_min_interval_seconds: float = 0.25,
        clock: Any = time.monotonic,
        wall_clock: Any | None = None,
        sleep: Any = time.sleep,
        random_value: Any = random.random,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if base_delay_seconds < 0 or max_delay_seconds < base_delay_seconds:
            raise ValueError("invalid retry delay bounds")
        if per_host_concurrency < 1 or per_host_min_interval_seconds < 0:
            raise ValueError("invalid host rate limits")
        self.inner = inner
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.per_host_concurrency = per_host_concurrency
        self.per_host_min_interval_seconds = per_host_min_interval_seconds
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.random_value = random_value
        self._states: dict[str, _HostState] = {}
        self._state_lock = threading.Lock()
        self.throttling_observed = False

    def _state_for(self, host: str) -> _HostState:
        with self._state_lock:
            state = self._states.get(host)
            if state is None:
                state = _HostState(threading.BoundedSemaphore(self.per_host_concurrency))
                self._states[host] = state
            return state

    def _pace(self, state: _HostState) -> None:
        interval = self.per_host_min_interval_seconds
        if interval == 0:
            return
        with state.rate_lock:
            now = float(self.clock())
            if state.last_refill is None:
                state.last_refill = now
            else:
                state.tokens = min(1.0, state.tokens + max(0.0, now - state.last_refill) / interval)
                state.last_refill = now
            if state.tokens < 1.0:
                self.sleep((1.0 - state.tokens) * interval)
                state.last_refill = float(self.clock())
                state.tokens = 0.0
            else:
                state.tokens = 0.0

    def _retry_delay(self, response: NetworkResponse, attempt: int) -> float:
        retry_after = next(
            (value for key, value in response.headers.items() if key.lower() == "retry-after"),
            None,
        )
        if retry_after:
            try:
                return min(self.max_delay_seconds, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    return min(
                        self.max_delay_seconds,
                        max(0.0, (retry_at - _utc_now(self.wall_clock)).total_seconds()),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        bound = min(self.max_delay_seconds, self.base_delay_seconds * (2**attempt))
        return min(self.max_delay_seconds, bound * (0.5 + float(self.random_value())))

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> NetworkResponse:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host:
            raise NetworkTransportError("network URL has no host")
        state = self._state_for(host)
        state.semaphore.acquire()
        try:
            for attempt in range(self.max_attempts):
                self._pace(state)
                try:
                    response = self.inner.request(
                        method,
                        url,
                        headers=headers,
                        timeout_seconds=timeout_seconds,
                    )
                except (NetworkTransportError, TimeoutError, OSError) as exc:
                    if attempt + 1 >= self.max_attempts:
                        raise NetworkTransportError(
                            "network connection failed after retries"
                        ) from exc
                    bound = min(self.max_delay_seconds, self.base_delay_seconds * (2**attempt))
                    self.sleep(
                        min(self.max_delay_seconds, bound * (0.5 + float(self.random_value())))
                    )
                    continue
                if (
                    response.status_code == 429
                    or response.status_code in self._RETRYABLE_SERVER_STATUSES
                ):
                    self.throttling_observed = (
                        self.throttling_observed or response.status_code == 429
                    )
                    if attempt + 1 < self.max_attempts:
                        self.sleep(self._retry_delay(response, attempt))
                        continue
                if response.status_code == 408:
                    if attempt + 1 < self.max_attempts:
                        self.sleep(self._retry_delay(response, attempt))
                        continue
                return response
        finally:
            state.semaphore.release()
        raise NetworkTransportError("network request failed")


def _is_builtin_live_transport(transport: object) -> bool:
    """Identify the standard-library transport used by the live CLI path."""

    if isinstance(transport, UrllibNetworkTransport):
        return True
    if isinstance(transport, ResilientNetworkTransport):
        return _is_builtin_live_transport(transport.inner)
    return False


class RawBlobStore:
    """Private, immutable exact-byte store under ``sha256/<prefix>/<hash>.blob``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RawBlobError("raw store root must be a regular directory")
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
        except OSError as exc:
            raise RawBlobError("cannot secure raw store root") from exc

    @staticmethod
    def _validate_hash(value: str) -> None:
        if not re.fullmatch(_HASH_PATTERN, value):
            raise RawBlobError("raw blob hash must be a lowercase SHA-256")

    def path_for(self, sha256: str) -> Path:
        self._validate_hash(sha256)
        return self.root / "sha256" / sha256[:2] / f"{sha256}.blob"

    def put(self, body: bytes, *, expected_sha256: str | None = None) -> str:
        if not isinstance(body, bytes):
            raise TypeError("raw blob body must be bytes")
        actual = hashlib.sha256(body).hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            raise RawBlobError(f"raw blob checksum mismatch: {actual} != {expected_sha256}")
        path = self.path_for(actual)
        self._write_immutable(path, body)
        return actual

    def put_stream(
        self,
        chunks: Iterable[bytes],
        *,
        expected_sha256: str | None = None,
        expected_length: int | None = None,
        quarantine_id: str | None = None,
    ) -> str:
        """Stream into quarantine, then promote only after length/hash checks."""

        if expected_length is not None and expected_length < 0:
            raise ValueError("expected_length must not be negative")
        quarantine = self._secure_directory(self.root / "quarantine")
        name = quarantine_id or hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:24]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise RawBlobError("quarantine ID contains an unsafe path component")
        partial = quarantine / f"{name}.part"
        digest = hashlib.sha256()
        length = 0
        descriptor = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            no_follow = getattr(os, "O_NOFOLLOW", 0)
            if no_follow:
                flags |= no_follow
            elif partial.is_symlink():
                raise RawBlobError("quarantine partial path is not a regular file")
            try:
                descriptor = os.open(partial, flags, 0o600)
            except OSError as exc:
                raise RawBlobError("quarantine partial path is not a regular file") from exc
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                os.fchmod(handle.fileno(), 0o600)
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise TypeError("raw stream chunks must be bytes")
                    handle.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            actual = digest.hexdigest()
            if expected_length is not None and length != expected_length:
                raise RawBlobError(f"raw blob length mismatch: {length} != {expected_length}")
            if expected_sha256 is not None and actual != expected_sha256:
                raise RawBlobError(f"raw blob checksum mismatch: {actual} != {expected_sha256}")
            read_flags = os.O_RDONLY | no_follow
            if not no_follow and partial.is_symlink():
                raise RawBlobError("quarantine partial path is not a regular file")
            try:
                read_descriptor = os.open(partial, read_flags)
            except OSError as exc:
                raise RawBlobError("quarantine partial path is not a regular file") from exc
            with os.fdopen(read_descriptor, "rb") as handle:
                body = handle.read()
            if len(body) != length or hashlib.sha256(body).hexdigest() != actual:
                raise RawBlobError("quarantine partial changed during verification")
            self._write_immutable(self.path_for(actual), body)
            partial.unlink(missing_ok=True)
            return actual
        except Exception:
            # The .part remains quarantined and can be inspected/deleted by the
            # operator; it is never reachable through the content-addressed path.
            raise
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def read(self, sha256: str, *, expected_length: int | None = None) -> bytes:
        path = self.path_for(sha256)
        self._check_directory(path.parent)
        if path.is_symlink() or not path.is_file():
            raise RawBlobError(f"raw blob is missing: {path}")
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise RawBlobError("raw blob cannot be read") from exc
        actual = hashlib.sha256(body).hexdigest()
        if actual != sha256:
            raise RawBlobError(f"raw blob checksum mismatch on read: {actual} != {sha256}")
        if expected_length is not None and len(body) != expected_length:
            raise RawBlobError("raw blob length mismatch on read")
        return body

    def write_receipt(self, receipt: RawArtifactReceiptV1) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", receipt.receipt_id):
            raise RawBlobError("receipt ID contains an unsafe path component")
        payload = canonical_json_bytes(receipt.model_dump(mode="json", warnings=False)) + b"\n"
        path = self.root / "receipts" / f"{receipt.receipt_id}.json"
        self._write_immutable(path, payload)
        return path

    def read_receipt(self, receipt_id: str) -> RawArtifactReceiptV1:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", receipt_id):
            raise RawBlobError("invalid receipt ID")
        path = self.root / "receipts" / f"{receipt_id}.json"
        self._check_directory(path.parent)
        if path.is_symlink() or not path.is_file():
            raise RawBlobError(f"raw receipt is missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return RawArtifactReceiptV1.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RawBlobError("raw receipt is invalid") from exc

    def _secure_directory(self, path: Path) -> Path:
        """Create a private directory while rejecting symlinked components."""

        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise RawBlobError("raw artifact path escapes raw store root") from exc
        current = self.root
        try:
            for component in relative.parts:
                current = current / component
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise RawBlobError(
                        "raw store directory component is not a regular directory: "
                        + str(current)
                    )
                current.mkdir(exist_ok=True, mode=0o700)
                current.chmod(0o700)
        except RawBlobError:
            raise
        except OSError as exc:
            raise RawBlobError("cannot secure raw store directory") from exc
        return path

    def _check_directory(self, path: Path) -> None:
        """Check an existing store-relative directory without following links."""

        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise RawBlobError("raw artifact path escapes raw store root") from exc
        current = self.root
        for component in relative.parts:
            current = current / component
            if current.is_symlink() or not current.is_dir():
                raise RawBlobError(
                    "raw store directory component is not a regular directory: "
                    + str(current)
                )

    def _write_immutable(self, path: Path, body: bytes) -> None:
        self._secure_directory(path.parent)
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != body:
                raise RawBlobError(f"raw artifact path contains conflicting content: {path}")
            return
        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_path, path)
            temporary_path.unlink()
            temporary_path = None
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != body:
                raise RawBlobError(f"raw artifact path contains conflicting content: {path}")
        except (OSError, TypeError, ValueError) as exc:
            raise RawBlobError("cannot persist raw artifact") from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class RawDownload:
    body: bytes
    response: NetworkResponse
    source_uri: str | None
    artifact_role: str = "DATA"
    parent_blob_sha256: str | None = None
    parent_artifact_id: str | None = None
    artifact_kind: ShardArtifactKind | None = None
    schema_version: str | None = None
    artifact_metadata: Mapping[str, object] = field(default_factory=dict)


class HistoricalSourceAdapter(Protocol):
    """Source-specific endpoint and schema boundary."""

    adapter_id: str
    adapter_version: str

    def probe(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
        plan_id: str,
        clock: Any,
    ) -> SourceProbeReportV1:
        """Observe actual access and response shape without claiming more."""

    def acquire(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> list[RawDownload]:
        """Download exact response bodies; pagination stays inside the adapter."""


def _credential_value(
    request: HistoricalAcquisitionRequestV1,
    resolver: CredentialResolver,
) -> str | None:
    if request.credential_ref is None:
        return None
    try:
        value = resolver.resolve(request.credential_ref)
    except Exception as exc:
        # A custom keyring/injected resolver must not be able to surface a
        # provider secret through an exception message or CLI output.
        raise CredentialUnavailableError(
            "credential resolver failed for reference: " + request.credential_ref.reference_id
        ) from exc
    if value is not None and not isinstance(value, str):
        raise CredentialUnavailableError(
            "credential resolver returned an invalid value for reference: "
            + request.credential_ref.reference_id
        )
    if value is None and request.credential_ref.required:
        raise CredentialUnavailableError(
            "required credential is unavailable: " + request.credential_ref.reference_id
        )
    return value


def _http_error_blocker(status_code: int) -> str:
    if status_code in {401, 403}:
        return f"SOURCE_ACCESS_DENIED: HTTP {status_code}"
    return f"SOURCE_HTTP_ERROR: HTTP {status_code}"


class ConfiguredHttpSourceAdapter:
    """Generic GET adapter for a documented endpoint returning canonical JSON."""

    adapter_id = "http-json"
    adapter_version = "1"

    def _url(self, request: HistoricalAcquisitionRequestV1) -> str:
        raw = request.parameters.get("source_uri") or request.parameters.get("url")
        if not isinstance(raw, str):
            raise HistoricalSourceSchemaError(
                "http-json request requires a source_uri/url parameter"
            )
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HistoricalSourceSchemaError("http-json request URL must be absolute HTTP(S)")
        return raw

    def _headers(
        self,
        request: HistoricalAcquisitionRequestV1,
        credentials: CredentialResolver,
    ) -> dict[str, str]:
        value = _credential_value(request, credentials)
        if value is None:
            return {}
        header = request.parameters.get("credential_header", "Authorization")
        scheme = request.parameters.get("credential_scheme")
        if not isinstance(header, str) or not re.fullmatch(r"[A-Za-z0-9-]+", header):
            raise HistoricalSourceSchemaError("credential header name is invalid")
        if scheme is not None and not isinstance(scheme, str):
            raise HistoricalSourceSchemaError("credential scheme is invalid")
        return {header: f"{scheme} {value}" if scheme else value}

    def acquire(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> list[RawDownload]:
        url = self._url(request)
        response = transport.request("GET", url, headers=self._headers(request, credentials))
        if not 200 <= response.status_code <= 299:
            raise AcquisitionError(_http_error_blocker(response.status_code))
        return [
            RawDownload(
                body=response.body,
                response=response,
                source_uri=_safe_uri(url),
                schema_version=request.schema_version,
            )
        ]

    def probe(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
        plan_id: str,
        clock: Any,
    ) -> SourceProbeReportV1:
        started = _utc_now(clock)
        try:
            url = self._url(request)
            response = transport.request("GET", url, headers=self._headers(request, credentials))
            finished = _utc_now(clock)
        except CredentialUnavailableError as exc:
            finished = _utc_now(clock)
            return SourceProbeReportV1.build(
                report_id=f"probe-{request.request_id}",
                plan_id=plan_id,
                request_id=request.request_id,
                source_id=request.source_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                source_kind=request.source_kind,
                status=ProbeStatus.BLOCKED,
                started_at=started,
                finished_at=finished,
                account_entitlement=AccountEntitlement.UNKNOWN,
                historical_capable=False,
                blockers=["CREDENTIAL_UNAVAILABLE: " + str(exc)],
            )
        except AcquisitionError as exc:
            finished = _utc_now(clock)
            return SourceProbeReportV1.build(
                report_id=f"probe-{request.request_id}",
                plan_id=plan_id,
                request_id=request.request_id,
                source_id=request.source_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                source_kind=request.source_kind,
                status=ProbeStatus.FAILED,
                started_at=started,
                finished_at=finished,
                blockers=[str(exc)],
            )
        status = ProbeStatus.PASS if 200 <= response.status_code <= 299 else ProbeStatus.FAILED
        blockers = [] if status == ProbeStatus.PASS else [_http_error_blocker(response.status_code)]
        return SourceProbeReportV1.build(
            report_id=f"probe-{request.request_id}",
            plan_id=plan_id,
            request_id=request.request_id,
            source_id=request.source_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_kind=request.source_kind,
            status=status,
            started_at=started,
            finished_at=finished,
            http_status=response.status_code,
            content_type=response.content_type,
            content_length=len(response.body),
            response_sha256=hashlib.sha256(response.body).hexdigest(),
            source_uri=_safe_uri(url),
            account_entitlement=(
                AccountEntitlement.CONFIRMED
                if status == ProbeStatus.PASS
                else AccountEntitlement.DENIED
                if response.status_code in {401, 403}
                else AccountEntitlement.UNKNOWN
            ),
            historical_capable=False,
            blockers=blockers
            + [
                "HISTORICAL_CAPABILITY_UNVERIFIED: response shape/date/listing coverage "
                "requires a source-specific decoder and evidence"
            ],
        )


class HithinkMarketDumpAdapter:
    """A-share Hithink market-dump adapter based only on documented endpoints."""

    adapter_id = "hithink-market-dumps"
    adapter_version = "1"
    provider_id = "hithink-financial-api"
    source_name = "HiThink Financial-API Market Dumps"
    base_uri = "https://fuyao.aicubes.cn/api/dump/market-dumps"
    _ENDPOINTS = {
        "daily-k": "daily-k/download-url",
        "daily-k-10d": "daily-k-10d/download-url",
        "adjustment-factors": "adjustment-factors/download-url",
    }
    _DAILY_K_COLUMNS = frozenset(
        {
            "thscode",
            "currency",
            "interval",
            "adjusted",
            "date_ms",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
        }
    )
    _ADJUSTMENT_COLUMNS = frozenset(
        {
            "thscode",
            "ticker",
            "ex_date_ms",
            "dividend_per_share",
            "per_share_bonus",
            "allotment_ratio",
            "allotment_price",
            "currency",
        }
    )

    def _endpoint(self, request: HistoricalAcquisitionRequestV1) -> str:
        if any(
            not re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", listing_id)
            for listing_id in request.listing_ids
        ):
            raise HistoricalSourceSchemaError(
                "Hithink market-dump adapter requires canonical A-share listing IDs"
            )
        dump_type = request.parameters.get("dump_type")
        if dump_type not in self._ENDPOINTS:
            raise HistoricalSourceSchemaError(
                "Hithink dump_type must be daily-k, daily-k-10d, or adjustment-factors"
            )
        return f"{self.base_uri}/{self._ENDPOINTS[dump_type]}"

    def _api_headers(
        self,
        request: HistoricalAcquisitionRequestV1,
        credentials: CredentialResolver,
    ) -> dict[str, str]:
        value = _credential_value(request, credentials)
        if value is None:
            raise CredentialUnavailableError("Hithink API key is unavailable")
        return {"X-api-key": value}

    @staticmethod
    def _parse_download_url(body: bytes) -> str:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HistoricalSourceSchemaError("Hithink signing response is not JSON") from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            code = payload.get("code") if isinstance(payload, dict) else None
            if code in {2002, 2004}:
                raise AcquisitionError("SOURCE_ACCESS_DENIED: Hithink account access was denied")
            raise HistoricalSourceSchemaError("Hithink signing response has an unsupported schema")
        data = payload.get("data")
        url = data.get("presigned_url") if isinstance(data, dict) else None
        if not isinstance(url, str):
            raise HistoricalSourceSchemaError("Hithink response has no presigned_url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HistoricalSourceSchemaError("Hithink presigned URL is invalid")
        return url

    @staticmethod
    def _date_from_milliseconds(value: object, *, field_name: str) -> date:
        if isinstance(value, bool):
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid")
        try:
            milliseconds = float(value)
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid") from exc
        if not math.isfinite(milliseconds):
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid")
        try:
            return datetime.fromtimestamp(
                milliseconds / 1000,
                tz=ZoneInfo("Asia/Shanghai"),
            ).date()
        except (OverflowError, OSError, ValueError) as exc:
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid") from exc

    @classmethod
    def _inspect_parquet_dump(
        cls,
        request: HistoricalAcquisitionRequestV1,
        body: bytes,
    ) -> tuple[
        date,
        date,
        list[str],
        dict[str, tuple[date, date]],
        dict[str, set[date]],
    ]:
        """Inspect a dump without retaining the expiring download URL.

        Probe must establish the actual response span and listing coverage;
        an HTTP 200 from the signing endpoint alone is not evidence that the
        account received a usable historical file.  The full row decoder still
        performs the same strict checks during offline compilation.
        """

        try:
            import io

            import pyarrow.parquet as parquet  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HistoricalIngestionError(
                "Hithink Parquet probe requires the optional parquet dependency"
            ) from exc
        try:
            parquet_file = parquet.ParquetFile(io.BytesIO(body))
            column_names = list(parquet_file.schema_arrow.names)
        except Exception as exc:
            raise HistoricalIngestionError("Hithink dump Parquet schema is invalid") from exc

        dump_type = request.parameters.get("dump_type")
        expected_columns = (
            cls._ADJUSTMENT_COLUMNS
            if dump_type == "adjustment-factors"
            else cls._DAILY_K_COLUMNS
        )
        if len(column_names) != len(expected_columns) or set(column_names) != expected_columns:
            raise HistoricalIngestionError("Hithink dump Parquet columns changed")

        observed_dates: set[date] = set()
        observed_listings: set[str] = set()
        observed_dates_by_listing: dict[str, set[date]] = defaultdict(set)
        columns = (
            ["thscode", "ex_date_ms", "currency"]
            if dump_type == "adjustment-factors"
            else ["thscode", "currency", "interval", "adjusted", "date_ms"]
        )
        try:
            batches = parquet_file.iter_batches(columns=columns, batch_size=65_536)
            for record_batch in batches:
                values = record_batch.to_pydict()
                row_count = len(values[columns[0]])
                for index in range(row_count):
                    listing_id = _canonical_hithink_a_listing(values["thscode"][index])
                    currency = values["currency"][index]
                    if currency != "CNY":
                        raise HistoricalIngestionError(
                            "Hithink dump currency is not the documented CNY value"
                        )
                    if dump_type != "adjustment-factors":
                        if values["interval"][index] != "1d":
                            raise HistoricalIngestionError(
                                "Hithink dump contains a non-daily interval"
                            )
                        if values["adjusted"][index] != "none":
                            raise HistoricalIngestionError(
                                "Hithink dump contains adjusted prices"
                            )
                        observation_date = cls._date_from_milliseconds(
                            values["date_ms"][index],
                            field_name="date_ms",
                        )
                    else:
                        observation_date = cls._date_from_milliseconds(
                            values["ex_date_ms"][index],
                            field_name="ex_date_ms",
                        )
                    observed_listings.add(listing_id)
                    observed_dates.add(observation_date)
                    observed_dates_by_listing[listing_id].add(observation_date)
        except HistoricalIngestionError:
            raise
        except Exception as exc:
            raise HistoricalIngestionError("Hithink dump Parquet rows are invalid") from exc
        if not observed_dates or not observed_listings:
            raise HistoricalIngestionError("Hithink dump Parquet contains no observations")
        observed_ranges = {
            listing_id: (min(dates), max(dates))
            for listing_id, dates in observed_dates_by_listing.items()
        }
        return (
            min(observed_dates),
            max(observed_dates),
            sorted(observed_listings),
            observed_ranges,
            dict(observed_dates_by_listing),
        )

    def acquire(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> list[RawDownload]:
        endpoint = self._endpoint(request)
        signing_response = transport.request(
            "GET", endpoint, headers=self._api_headers(request, credentials)
        )
        if not 200 <= signing_response.status_code <= 299:
            raise AcquisitionError(_http_error_blocker(signing_response.status_code))
        presigned_url = self._parse_download_url(signing_response.body)
        data_response = transport.request("GET", presigned_url)
        if not 200 <= data_response.status_code <= 299:
            raise AcquisitionError(_http_error_blocker(data_response.status_code))
        # The signing response contains an expiring URL.  It is used only in
        # memory and is never persisted as a raw artifact; the stable parent
        # identity still makes the presigned hop auditable without caching a
        # credential-bearing URL.
        parent_identity = "presign-" + hashlib.sha256(
            canonical_json_bytes(
                {"endpoint": endpoint, "request_identity": request.request_identity}
            )
        ).hexdigest()[:32]
        return [
            RawDownload(
                body=data_response.body,
                response=data_response,
                source_uri=endpoint,
                artifact_role="DATA",
                parent_artifact_id=parent_identity,
                schema_version=request.schema_version,
            ),
        ]

    def probe(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
        plan_id: str,
        clock: Any,
    ) -> SourceProbeReportV1:
        started = _utc_now(clock)
        try:
            downloads = self.acquire(request, transport=transport, credentials=credentials)
            data = next(
                (item for item in downloads if item.artifact_role == "DATA"),
                None,
            )
            if data is None:
                raise HistoricalSourceSchemaError("Hithink response contained no data artifact")
            (
                observed_start,
                observed_end,
                observed_listing_ids,
                observed_ranges,
                observed_dates_by_listing,
            ) = self._inspect_parquet_dump(request, data.body)
            finished = _utc_now(clock)
        except CredentialUnavailableError as exc:
            finished = _utc_now(clock)
            return SourceProbeReportV1.build(
                report_id=f"probe-{request.request_id}",
                plan_id=plan_id,
                request_id=request.request_id,
                source_id=request.source_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                source_kind=request.source_kind,
                status=ProbeStatus.BLOCKED,
                started_at=started,
                finished_at=finished,
                account_entitlement=AccountEntitlement.UNKNOWN,
                blockers=["CREDENTIAL_UNAVAILABLE: " + str(exc)],
            )
        except AcquisitionError as exc:
            finished = _utc_now(clock)
            return SourceProbeReportV1.build(
                report_id=f"probe-{request.request_id}",
                plan_id=plan_id,
                request_id=request.request_id,
                source_id=request.source_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                source_kind=request.source_kind,
                status=ProbeStatus.FAILED,
                started_at=started,
                finished_at=finished,
                account_entitlement=(
                    AccountEntitlement.DENIED
                    if str(exc).startswith("SOURCE_ACCESS_DENIED")
                    else AccountEntitlement.UNKNOWN
                ),
                blockers=[str(exc)],
            )
        uncovered_listings = [
            listing_id
            for listing_id in request.listing_ids
            if listing_id not in observed_ranges
            or observed_ranges[listing_id][0] > request.start_date
            or observed_ranges[listing_id][1] < request.end_date
        ]
        historical_capable = (
            not uncovered_listings
            and observed_start <= request.start_date
            and observed_end >= request.end_date
        )
        missing_expected_sessions = sorted(
            listing_id
            for listing_id, expected_sessions in (
                request.expected_sessions_by_listing or {}
            ).items()
            if set(expected_sessions) - observed_dates_by_listing.get(listing_id, set())
        )
        historical_capable = historical_capable and not missing_expected_sessions
        dump_type = request.parameters.get("dump_type")
        warnings = [
            "HITHINK_TERMINAL_LIFECYCLE_NOT_INCLUDED: market dumps do not prove "
            "delisting, suspension or terminal economics"
        ]
        if dump_type == "daily-k-10d":
            warnings.append(
                "HITHINK_RECENT_WINDOW_ONLY: daily-k-10d is a recent incremental dump"
            )
        blockers = []
        if not historical_capable:
            blocker = (
                "HISTORICAL_CAPABILITY_UNVERIFIED: observed Hithink dump does not cover "
                "every requested listing and date"
            )
            if uncovered_listings and (
                observed_start <= request.start_date and observed_end >= request.end_date
            ):
                blocker += ": " + ",".join(sorted(uncovered_listings))
            if uncovered_listings or (
                observed_start > request.start_date or observed_end < request.end_date
            ):
                blockers.append(blocker)
        if missing_expected_sessions:
            blockers.append(
                "HISTORICAL_CAPABILITY_UNVERIFIED: expected Hithink sessions are missing: "
                + ",".join(missing_expected_sessions)
            )
        return SourceProbeReportV1.build(
            report_id=f"probe-{request.request_id}",
            plan_id=plan_id,
            request_id=request.request_id,
            source_id=request.source_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_kind=request.source_kind,
            status=ProbeStatus.PASS,
            started_at=started,
            finished_at=finished,
            http_status=data.response.status_code,
            content_type=data.response.content_type,
            content_length=len(data.body),
            response_sha256=hashlib.sha256(data.body).hexdigest(),
            source_uri=self.base_uri,
            account_entitlement=AccountEntitlement.CONFIRMED,
            observed_start=observed_start,
            observed_end=observed_end,
            observed_listing_ids=observed_listing_ids,
            historical_capable=historical_capable,
            terminal_coverage=CoverageEvidenceStatus.UNVERIFIED,
            action_coverage=(
                CoverageEvidenceStatus.CONFIRMED
                if dump_type == "adjustment-factors"
                else CoverageEvidenceStatus.UNKNOWN
            ),
            throttling_observed=False,
            blockers=blockers,
            warnings=warnings,
        )


class OfficialFilingDocumentAdapter:
    """Bridge the existing official filing downloader into acquisition batches.

    The downloader and its source clients remain injected.  In particular,
    this class does not scrape HKEXnews or invent an alternative access route;
    a caller must supply the already validated, lawful Phase 3 client.  A
    discovery callback may be supplied so the project selects filing records
    from the existing official discovery boundary instead of requiring a hand-
    assembled ``filing_ids`` list.
    """

    adapter_id = "official-filing-documents"
    adapter_version = "filing-document-receipt-v1"

    def __init__(
        self,
        downloader: FilingDocumentDownloader,
        filings: Mapping[str, FilingRecord] | None = None,
        *,
        discover: Callable[
            [FilingDiscoveryQuery],
            Iterable[FilingRecord | FilingDescriptor | Mapping[str, object]],
        ]
        | None = None,
    ) -> None:
        if filings is None and discover is None:
            raise ValueError(
                "official-filing-documents requires a filing mapping or discovery callback"
            )
        self.downloader = downloader
        if filings is None:
            self.filings = {}
        else:
            normalized: dict[str, FilingRecord] = {}
            for key, filing in filings.items():
                if not isinstance(filing, FilingRecord):
                    raise TypeError("filings must contain FilingRecord values")
                if key != filing.filing_id:
                    raise ValueError("filing mapping key does not match filing_id")
                try:
                    normalized[key] = FilingRecord.model_validate(
                        filing.model_dump(mode="python", warnings=False)
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise ValueError("filings contains an invalid FilingRecord") from exc
            self.filings = normalized
        if discover is not None and not callable(discover):
            raise TypeError("discover must be callable")
        self.discover = discover

    @staticmethod
    def _validated_filing(filing: FilingRecord) -> FilingRecord:
        try:
            return FilingRecord.model_validate(
                filing.model_dump(mode="python", warnings=False)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise HistoricalSourceSchemaError("official filing record is invalid") from exc

    def _filings_from_mapping(self, request: HistoricalAcquisitionRequestV1) -> list[FilingRecord]:
        raw_ids = request.parameters.get("filing_ids")
        if not isinstance(raw_ids, list) or not raw_ids or not all(
            isinstance(item, str) and item for item in raw_ids
        ):
            raise HistoricalSourceSchemaError(
                "official-filing-documents requires a non-empty filing_ids list"
            )
        if len(raw_ids) != len(set(raw_ids)):
            raise HistoricalSourceSchemaError(
                "official-filing-documents filing_ids must not contain duplicates"
            )
        unknown = set(raw_ids) - set(self.filings)
        if unknown:
            raise HistoricalSourceSchemaError(
                "official-filing-documents references unknown filing IDs"
            )
        return [self._validated_filing(self.filings[item]) for item in raw_ids]

    @staticmethod
    def _discovery_source(request: HistoricalAcquisitionRequestV1) -> FilingSource:
        raw_source = request.parameters.get("source")
        if raw_source is None:
            raw_source = request.parameters.get("filing_source")
        if not isinstance(raw_source, str) or not raw_source:
            raise HistoricalSourceSchemaError(
                "official-filing-documents discovery requires a source parameter"
            )
        try:
            return FilingSource(raw_source)
        except (TypeError, ValueError) as exc:
            raise HistoricalSourceSchemaError(
                "official-filing-documents discovery source is unsupported"
            ) from exc

    def _filings_from_discovery(
        self,
        request: HistoricalAcquisitionRequestV1,
    ) -> list[FilingRecord]:
        if self.discover is None:
            raise HistoricalSourceSchemaError(
                "official-filing-documents requires filing_ids when no discovery "
                "callback is configured"
            )
        source = self._discovery_source(request)
        raw_limit = request.parameters.get("limit", 50)
        document_type = request.parameters.get("document_type")
        if document_type is not None and not isinstance(document_type, str):
            raise HistoricalSourceSchemaError("official filing document_type must be a string")
        records_by_id: dict[str, FilingRecord] = {}
        urls: set[str] = set()
        for listing_id in request.listing_ids:
            try:
                query = FilingDiscoveryQuery(
                    listing_id=listing_id,
                    source=source,
                    published_from=request.start_date,
                    published_to=request.end_date,
                    document_type=document_type,
                    limit=raw_limit,
                    as_of=request.end_date,
                )
                discovered = self.discover(query)
            except HistoricalSourceSchemaError:
                raise
            except (TypeError, ValueError, ValidationError) as exc:
                raise HistoricalSourceSchemaError(
                    "official filing discovery query is invalid"
                ) from exc
            except AcquisitionError:
                raise
            except Exception as exc:
                raise AcquisitionError("official filing discovery failed") from exc
            if isinstance(discovered, (str, bytes, bytearray, Mapping)):
                raise HistoricalSourceSchemaError(
                    "official filing discovery must return an iterable of filing metadata"
                )
            returned_count = 0
            try:
                for item in discovered:
                    returned_count += 1
                    if returned_count > query.limit:
                        raise HistoricalSourceSchemaError(
                            "official filing discovery returned rows over requested limit"
                        )
                    if isinstance(item, FilingRecord):
                        filing = self._validated_filing(item)
                    else:
                        descriptor = FilingDescriptor.model_validate(item)
                        filing = FilingRecord(
                            filing_id=filing_id_for(
                                listing_id=listing_id,
                                market=query.market,
                                source=source,
                                source_document_id=descriptor.source_document_id,
                                url=descriptor.url,
                            ),
                            listing_id=listing_id,
                            market=query.market,
                            source=source,
                            title=descriptor.title,
                            document_type=descriptor.document_type,
                            published_date=descriptor.published_date,
                            url=descriptor.url,
                            source_document_id=descriptor.source_document_id,
                            report_period=descriptor.report_period,
                            issuer_name=descriptor.issuer_name,
                        )
                    if (
                        filing.listing_id != listing_id
                        or filing.market is not query.market
                        or filing.source is not source
                        or not request.start_date <= filing.published_date <= request.end_date
                    ):
                        raise HistoricalSourceSchemaError(
                            "official filing discovery returned a row outside query scope"
                        )
                    if document_type is not None and filing.document_type != document_type:
                        raise HistoricalSourceSchemaError(
                            "official filing discovery returned an unexpected document type"
                        )
                    filing_url = str(filing.url)
                    previous = records_by_id.get(filing.filing_id)
                    if previous is not None:
                        if previous.model_dump(mode="json") != filing.model_dump(mode="json"):
                            raise HistoricalSourceSchemaError(
                                "official filing discovery returned conflicting filing identity"
                            )
                        continue
                    if filing_url in urls:
                        raise HistoricalSourceSchemaError(
                            "official filing discovery returned duplicate filing URLs"
                        )
                    records_by_id[filing.filing_id] = filing
                    urls.add(filing_url)
            except HistoricalSourceSchemaError:
                raise
            except (TypeError, ValueError, ValidationError) as exc:
                raise HistoricalSourceSchemaError(
                    "official filing discovery metadata is invalid"
                ) from exc
            except AcquisitionError:
                raise
            except Exception as exc:
                raise AcquisitionError("official filing discovery iteration failed") from exc
        if not records_by_id:
            raise HistoricalSourceSchemaError(
                "official filing discovery returned no in-scope filings"
            )
        return sorted(
            records_by_id.values(),
            key=lambda filing: (-filing.published_date.toordinal(), filing.filing_id),
        )

    @staticmethod
    def _validate_scope(
        request: HistoricalAcquisitionRequestV1,
        filings: Iterable[FilingRecord],
    ) -> list[FilingRecord]:
        selected = [filing for filing in filings]
        if not selected:
            raise HistoricalSourceSchemaError(
                "official-filing-documents has no filings to acquire"
            )
        requested_source = request.parameters.get("source") or request.parameters.get(
            "filing_source"
        )
        source_values = {filing.source for filing in selected}
        if len(source_values) != 1:
            raise HistoricalSourceSchemaError(
                "official-filing-documents request must use one filing source"
            )
        if requested_source is not None:
            if not isinstance(requested_source, str):
                raise HistoricalSourceSchemaError("official filing source must be a string")
            try:
                normalized_source = FilingSource(requested_source)
            except (TypeError, ValueError) as exc:
                raise HistoricalSourceSchemaError(
                    "official filing source is unsupported"
                ) from exc
            if source_values != {normalized_source}:
                raise HistoricalSourceSchemaError("official filing source does not match request")
        for filing in selected:
            if filing.listing_id not in request.listing_ids:
                raise HistoricalSourceSchemaError(
                    "filing listing lies outside acquisition request: " + filing.filing_id
                )
            if not request.start_date <= filing.published_date <= request.end_date:
                raise HistoricalSourceSchemaError(
                    "filing publication date lies outside acquisition request: "
                    + filing.filing_id
                )
        return sorted(
            selected,
            key=lambda filing: (-filing.published_date.toordinal(), filing.filing_id),
        )

    def _selected_filings(self, request: HistoricalAcquisitionRequestV1) -> list[FilingRecord]:
        if "filing_ids" in request.parameters:
            filings = self._filings_from_mapping(request)
        else:
            filings = self._filings_from_discovery(request)
        return self._validate_scope(request, filings)

    def acquire(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> list[RawDownload]:
        del transport, credentials
        result: list[RawDownload] = []
        for filing in self._selected_filings(request):
            try:
                document = self.downloader.download(filing)
            except FilingDocumentError as exc:
                raise AcquisitionError("official filing document download failed") from exc
            response_headers: dict[str, str] = {
                "content-type": document.media_type,
                "content-length": str(document.content_size),
            }
            transport_metadata = document.retrieval_metadata.get("transport")
            if isinstance(transport_metadata, Mapping):
                response_headers.update(_safe_headers(transport_metadata))
                nested_headers = transport_metadata.get("headers")
                if isinstance(nested_headers, Mapping):
                    response_headers.update(_safe_headers(nested_headers))
            response = NetworkResponse(
                status_code=200,
                headers=response_headers,
                body=document.content,
                url=document.final_url or str(filing.url),
            )
            result.append(
                RawDownload(
                    body=document.content,
                    response=response,
                    source_uri=str(filing.url),
                    artifact_role="FILING_DOCUMENT",
                    schema_version=request.schema_version,
                    artifact_metadata={
                        "filing_id": filing.filing_id,
                        "listing_id": filing.listing_id,
                        "market": filing.market.value,
                        "source": filing.source.value,
                        "title": filing.title,
                        "document_type": filing.document_type,
                        "published_date": filing.published_date.isoformat(),
                        "source_document_id": filing.source_document_id,
                        "report_period": filing.report_period,
                        "document_sha256": document.content_sha256,
                        "document_size": document.content_size,
                        "media_type": document.media_type,
                        "retrieved_at": document.retrieved_at.isoformat(),
                        "final_url": document.final_url,
                        "revision_identity": (
                            filing.filing_id + ":" + document.content_sha256
                        ),
                    },
                )
            )
        return result

    def probe(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
        plan_id: str,
        clock: Any,
    ) -> SourceProbeReportV1:
        started = _utc_now(clock)
        try:
            documents = self.acquire(
                request,
                transport=transport,
                credentials=credentials,
            )
        except AcquisitionError as exc:
            finished = _utc_now(clock)
            return SourceProbeReportV1.build(
                report_id=f"probe-{request.request_id}",
                plan_id=plan_id,
                request_id=request.request_id,
                source_id=request.source_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                source_kind=request.source_kind,
                status=ProbeStatus.FAILED,
                started_at=started,
                finished_at=finished,
                blockers=[str(exc)],
            )
        finished = _utc_now(clock)
        observed = [
            date.fromisoformat(str(item.artifact_metadata["published_date"]))
            for item in documents
        ]
        return SourceProbeReportV1.build(
            report_id=f"probe-{request.request_id}",
            plan_id=plan_id,
            request_id=request.request_id,
            source_id=request.source_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_kind=request.source_kind,
            status=ProbeStatus.PASS,
            started_at=started,
            finished_at=finished,
            http_status=200,
            content_type=documents[0].response.content_type if documents else None,
            content_length=sum(len(item.body) for item in documents),
            observed_start=min(observed) if observed else None,
            observed_end=max(observed) if observed else None,
            observed_listing_ids=sorted(
                str(item.artifact_metadata["listing_id"]) for item in documents
            ),
            account_entitlement=AccountEntitlement.CONFIRMED,
            historical_capable=True,
            terminal_coverage=CoverageEvidenceStatus.UNVERIFIED,
            warnings=[
                "FILING_SCOPE_LIMITED: probe confirms only supplied official filing "
                "documents, not complete historical filing coverage"
            ],
        )


class HistoricalRawDecoder(Protocol):
    """Decode one verified raw blob into typed canonical rows."""

    def decode(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
    ) -> Iterable[BaseModel]:
        """Raise on unsupported schema or ambiguous semantics."""


class ScopedHistoricalRawDecoder(Protocol):
    """Optional decoder boundary for filtering a full-market artifact early."""

    def decode_scoped(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
        request: HistoricalAcquisitionRequestV1,
    ) -> Iterable[BaseModel]:
        """Decode only rows that can enter the declared acquisition request."""


class CanonicalJsonDecoder:
    """Offline decoder accepting only already-canonical contract rows."""

    def __init__(self, artifact_kind: ShardArtifactKind, schema_version: str) -> None:
        self.artifact_kind = artifact_kind
        self.schema_version = schema_version
        self.model_type = _MODEL_BY_KIND[artifact_kind]

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        if receipt.artifact_kind is not self.artifact_kind:
            raise HistoricalIngestionError("canonical JSON decoder artifact kind mismatch")
        if receipt.schema_version != self.schema_version:
            raise HistoricalIngestionError("canonical JSON decoder schema version mismatch")
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HistoricalIngestionError("canonical JSON raw artifact is invalid") from exc
        rows = payload.get("rows") if isinstance(payload, dict) and "rows" in payload else payload
        if not isinstance(rows, list):
            rows = [rows]
        try:
            return [self.model_type.model_validate(row) for row in rows]
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError("canonical JSON row schema validation failed") from exc


class HithinkDailyKParquetDecoder:
    """Optional pyarrow decoder for documented unadjusted daily-k dumps."""

    _BATCH_SIZE = 16_384

    def __init__(self, schema_version: str = "market-bar-v1") -> None:
        self.schema_version = schema_version

    def _validate_receipt(self, receipt: RawArtifactReceiptV1) -> None:
        if receipt.artifact_kind is not ShardArtifactKind.MARKET_BAR:
            raise HistoricalIngestionError("Hithink daily-k decoder requires MARKET_BAR")
        if receipt.schema_version != self.schema_version:
            raise HistoricalIngestionError("Hithink daily-k schema version is unrecognized")

    @staticmethod
    def _numeric_values(row: Mapping[str, object]) -> dict[str, float]:
        result: dict[str, float] = {}
        for field_name in (
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
        ):
            value = row[field_name]
            if isinstance(value, bool):
                raise HistoricalIngestionError(
                    "Hithink daily-k row failed canonical validation"
                )
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise HistoricalIngestionError(
                    "Hithink daily-k row failed canonical validation"
                ) from exc
            if not math.isfinite(number):
                raise HistoricalIngestionError(
                    "Hithink daily-k row failed canonical validation"
                )
            if field_name in {"volume", "turnover"} and number < 0:
                raise HistoricalIngestionError(
                    "Hithink daily-k row failed canonical validation"
                )
            if field_name == "close_price" and number <= 0:
                raise HistoricalIngestionError(
                    "Hithink daily-k row failed canonical validation"
                )
            result[field_name] = number
        return result

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> Iterable[BaseModel]:
        self._validate_receipt(receipt)
        return self._iter_rows(receipt, raw_bytes)

    def decode_scoped(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
        request: HistoricalAcquisitionRequestV1,
    ) -> Iterable[BaseModel]:
        self._validate_receipt(receipt)
        return self._iter_rows(receipt, raw_bytes, request=request)

    def _iter_rows(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
        *,
        request: HistoricalAcquisitionRequestV1 | None = None,
    ) -> Iterable[BaseModel]:
        try:
            import pyarrow as arrow  # type: ignore[import-not-found]
            import pyarrow.parquet as parquet  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HistoricalIngestionError(
                "Hithink Parquet decoding requires the optional parquet dependency"
            ) from exc
        required = HithinkMarketDumpAdapter._DAILY_K_COLUMNS
        try:
            # BufferReader over py_buffer avoids making another full-size
            # Python bytes copy before Parquet's row-group reader starts.
            parquet_file = parquet.ParquetFile(
                arrow.BufferReader(arrow.py_buffer(raw_bytes))
            )
            column_names = list(parquet_file.schema_arrow.names)
        except Exception as exc:
            raise HistoricalIngestionError("Hithink daily-k Parquet schema is invalid") from exc
        if len(column_names) != len(required) or set(column_names) != required:
            raise HistoricalIngestionError("Hithink daily-k columns changed")

        zone = ZoneInfo("Asia/Shanghai")
        requested_listings = set(request.listing_ids) if request is not None else None
        columns = sorted(required)
        try:
            batches = parquet_file.iter_batches(
                columns=columns,
                batch_size=self._BATCH_SIZE,
            )
            for record_batch in batches:
                values = record_batch.to_pydict()
                if set(values) != required:
                    raise HistoricalIngestionError("Hithink daily-k columns changed")
                row_count = len(values[columns[0]])
                if any(len(values[column]) != row_count for column in columns[1:]):
                    raise HistoricalIngestionError("Hithink daily-k batch columns are misaligned")
                for index in range(row_count):
                    row = {column: values[column][index] for column in columns}
                    if row["interval"] != "1d" or row["adjusted"] != "none":
                        raise HistoricalIngestionError(
                            "Hithink adjusted/non-daily data cannot become canonical "
                            "unadjusted bars"
                        )
                    if row["currency"] != "CNY":
                        raise HistoricalIngestionError(
                            "Hithink daily-k currency is not the documented CNY value"
                        )
                    listing_id = _canonical_hithink_a_listing(row["thscode"])
                    if isinstance(row["date_ms"], bool):
                        raise HistoricalIngestionError("Hithink daily-k date_ms is invalid")
                    try:
                        milliseconds = float(row["date_ms"])
                    except (TypeError, ValueError) as exc:
                        raise HistoricalIngestionError(
                            "Hithink daily-k date_ms is invalid"
                        ) from exc
                    if not math.isfinite(milliseconds):
                        raise HistoricalIngestionError("Hithink daily-k date_ms is invalid")
                    try:
                        trading_datetime = datetime.fromtimestamp(milliseconds / 1000, tz=zone)
                    except (OSError, ValueError, OverflowError) as exc:
                        raise HistoricalIngestionError(
                            "Hithink daily-k date_ms is invalid"
                        ) from exc
                    trading_date = trading_datetime.date()
                    numeric_values = self._numeric_values(row)
                    if (
                        requested_listings is not None
                        and (
                            listing_id not in requested_listings
                            or not request.start_date <= trading_date <= request.end_date
                        )
                    ):
                        continue
                    try:
                        yield MarketBar(
                            bar_id=f"{listing_id}:{trading_date.isoformat()}",
                            listing_id=listing_id,
                            market="A",
                            trading_date=trading_date,
                            timestamp=trading_datetime,
                            open=numeric_values["open_price"],
                            high=numeric_values["high_price"],
                            low=numeric_values["low_price"],
                            close=numeric_values["close_price"],
                            volume=numeric_values["volume"],
                            amount=numeric_values["turnover"],
                            currency=str(row["currency"]),
                            source_hash=receipt.sha256,
                        )
                    except (TypeError, ValueError) as exc:
                        raise HistoricalIngestionError(
                            "Hithink daily-k row failed canonical validation"
                        ) from exc
        except HistoricalIngestionError:
            raise
        except Exception as exc:
            raise HistoricalIngestionError("Hithink daily-k Parquet rows are invalid") from exc


def _canonical_hithink_a_listing(value: object) -> str:
    """Map Hithink's ``600519.SH`` identity to the engine's ``SH600519`` form."""

    if not isinstance(value, str):
        raise HistoricalIngestionError("Hithink thscode must be a string")
    normalized = value.strip().upper()
    if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", normalized):
        ticker, exchange = normalized.split(".", 1)
        return exchange + ticker
    if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", normalized):
        return normalized
    raise HistoricalIngestionError("Hithink daily-k row is not an A-share listing")


class HithinkAdjustmentFactorParquetDecoder:
    """Decode Hithink adjustment rows only after explicit basis approval.

    The documented factor dump is useful as reconciliation input by default.
    ``allow_as_corporate_actions=True`` is an operator decision that must be
    backed by a probe and terms review; it is never enabled by the default
    decoder registry.
    """

    _COLUMNS = {
        "thscode",
        "ticker",
        "ex_date_ms",
        "dividend_per_share",
        "per_share_bonus",
        "allotment_ratio",
        "allotment_price",
        "currency",
    }

    def __init__(
        self,
        schema_version: str = "corporate-action-v1",
        *,
        allow_as_corporate_actions: bool = False,
    ) -> None:
        self.schema_version = schema_version
        self.allow_as_corporate_actions = allow_as_corporate_actions

    @staticmethod
    def _nonnegative(value: object, field_name: str) -> float:
        if isinstance(value, bool):
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid") from exc
        if not number >= 0 or not number < float("inf"):
            raise HistoricalIngestionError(f"Hithink {field_name} is invalid")
        return number

    @staticmethod
    def _date(value: object) -> date:
        if isinstance(value, bool):
            raise HistoricalIngestionError("Hithink ex_date_ms is invalid")
        try:
            milliseconds = float(value)
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError("Hithink ex_date_ms is invalid") from exc
        if not math.isfinite(milliseconds):
            raise HistoricalIngestionError("Hithink ex_date_ms is invalid")
        try:
            return datetime.fromtimestamp(
                milliseconds / 1000,
                tz=ZoneInfo("Asia/Shanghai"),
            ).date()
        except (OSError, ValueError, OverflowError) as exc:
            raise HistoricalIngestionError("Hithink ex_date_ms is invalid") from exc

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        if not self.allow_as_corporate_actions:
            raise HistoricalIngestionError(
                "Hithink adjustment factors are reconciliation-only until basis is proven"
            )
        if receipt.artifact_kind is not ShardArtifactKind.CORPORATE_ACTION:
            raise HistoricalIngestionError(
                "Hithink adjustment decoder requires CORPORATE_ACTION"
            )
        if receipt.schema_version != self.schema_version:
            raise HistoricalIngestionError(
                "Hithink adjustment-factor schema version is unrecognized"
            )
        try:
            import io

            import pyarrow.parquet as parquet  # type: ignore[import-not-found]
            rows = parquet.read_table(io.BytesIO(raw_bytes)).to_pylist()
        except ImportError as exc:
            raise HistoricalIngestionError(
                "Hithink adjustment decoding requires the optional parquet dependency"
            ) from exc
        except Exception as exc:
            raise HistoricalIngestionError(
                "Hithink adjustment-factor Parquet schema is invalid"
            ) from exc
        result: list[BaseModel] = []
        for row in rows:
            if set(row) != self._COLUMNS:
                raise HistoricalIngestionError("Hithink adjustment-factor columns changed")
            listing_id = _canonical_hithink_a_listing(row["thscode"])
            effective_date = self._date(row["ex_date_ms"])
            currency = row["currency"]
            if currency != "CNY":
                raise HistoricalIngestionError("Hithink adjustment currency is invalid")
            ticker = row["ticker"]
            if not isinstance(ticker, str) or not ticker.strip():
                raise HistoricalIngestionError("Hithink adjustment ticker is invalid")
            dividend = self._nonnegative(row["dividend_per_share"], "dividend_per_share")
            bonus = self._nonnegative(row["per_share_bonus"], "per_share_bonus")
            rights_ratio = self._nonnegative(row["allotment_ratio"], "allotment_ratio")
            rights_price = self._nonnegative(row["allotment_price"], "allotment_price")
            if rights_ratio == 0 and rights_price != 0:
                raise HistoricalIngestionError(
                    "Hithink allotment_price is nonzero without allotment_ratio"
                )
            if rights_ratio > 0 and rights_price <= 0:
                raise HistoricalIngestionError(
                    "Hithink rights issue has no positive allotment_price"
                )
            identity = {
                "listing_id": listing_id,
                "date": effective_date.isoformat(),
                "ticker": ticker,
                "dividend": dividend,
                "bonus": bonus,
                "rights_ratio": rights_ratio,
                "rights_price": rights_price,
            }
            identity_hash = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:24]
            if dividend > 0:
                result.append(
                    CorporateAction(
                        action_id=f"hithink-dividend-{identity_hash}",
                        listing_id=listing_id,
                        action_type=CorporateActionType.CASH_DIVIDEND,
                        effective_date=effective_date,
                        ex_date=effective_date,
                        cash_per_share=dividend,
                        currency=currency,
                        source_hash=receipt.sha256,
                    )
                )
            if bonus > 0:
                result.append(
                    CorporateAction(
                        action_id=f"hithink-split-{identity_hash}",
                        listing_id=listing_id,
                        action_type=CorporateActionType.SPLIT,
                        effective_date=effective_date,
                        ex_date=effective_date,
                        split_factor=1 + bonus,
                        currency=currency,
                        source_hash=receipt.sha256,
                    )
                )
            if rights_ratio > 0:
                result.append(
                    CorporateAction(
                        action_id=f"hithink-rights-{identity_hash}",
                        listing_id=listing_id,
                        action_type=CorporateActionType.RIGHTS_ISSUE,
                        effective_date=effective_date,
                        ex_date=effective_date,
                        rights_ratio=rights_ratio,
                        rights_price=rights_price,
                        currency=currency,
                        source_hash=receipt.sha256,
                    )
                )
        return result


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    batch: RawAcquisitionBatchManifestV1
    readiness: AcquisitionReadinessReportV1


class HistoricalAcquisitionService:
    """Orchestrate probes/acquisition while keeping raw storage local."""

    def __init__(
        self,
        adapters: Mapping[str, HistoricalSourceAdapter] | None = None,
        *,
        transport: NetworkTransport | None = None,
        credentials: CredentialResolver | None = None,
        clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self.adapters = dict(default_source_adapters() if adapters is None else adapters)
        self.transport = (
            ResilientNetworkTransport(UrllibNetworkTransport())
            if transport is None
            else transport
        )
        self.credentials = EnvironmentCredentialResolver() if credentials is None else credentials
        self.clock = clock
        # The built-in transport is the only path used by the CLI for real
        # network access. Require every required ENVIRONMENT credential before
        # touching it; injected transports remain available to deterministic
        # tests and explicitly controlled runners.
        self._requires_environment_credential = _is_builtin_live_transport(self.transport)

    def _require_network_authorization(
        self,
        plan: HistoricalAcquisitionPlanV1,
        *,
        network_allowed: bool,
    ) -> None:
        if network_allowed is not True:
            raise NetworkDisabledError(
                "network is denied; pass --network=allow for an explicit live operation"
            )
        if not self._requires_environment_credential:
            return
        if not isinstance(self.credentials, EnvironmentCredentialResolver):
            raise CredentialUnavailableError(
                "built-in live transport requires EnvironmentCredentialResolver"
            )
        environment_references: dict[str, CredentialReferenceV1] = {}
        for request in plan.requests:
            reference = request.credential_ref
            if reference is None:
                continue
            if reference.kind != CredentialKind.ENVIRONMENT:
                raise CredentialUnavailableError(
                    "built-in live transport accepts only ENVIRONMENT credential references: "
                    + request.request_id
                )
            environment_references[reference.reference_id] = reference
        if not environment_references:
            raise NetworkDisabledError(
                "live network requires a non-empty ENVIRONMENT credential reference "
                "and --network=allow"
            )
        missing_references: list[str] = []
        resolved_any = False
        for reference in environment_references.values():
            try:
                value = self.credentials.resolve(reference)
            except Exception as exc:
                raise CredentialUnavailableError(
                    "credential resolver failed for reference: " + reference.reference_id
                ) from exc
            if value is not None and not isinstance(value, str):
                raise CredentialUnavailableError(
                    "credential resolver returned an invalid value for reference: "
                    + reference.reference_id
                )
            if value:
                resolved_any = True
            elif reference.required:
                missing_references.append(reference.reference_id)
        if missing_references:
            raise CredentialUnavailableError(
                "required environment credentials are unavailable for live network access: "
                + ",".join(sorted(missing_references))
            )
        if resolved_any:
            return
        raise CredentialUnavailableError(
            "required environment credential is unavailable for live network access"
        )

    def _adapter(self, request: HistoricalAcquisitionRequestV1) -> HistoricalSourceAdapter:
        adapter = self.adapters.get(request.adapter_id)
        if adapter is None:
            raise HistoricalSourceSchemaError("no adapter is registered: " + request.adapter_id)
        if getattr(adapter, "adapter_id", None) != request.adapter_id:
            raise HistoricalSourceSchemaError(
                "registered adapter identity does not match request: " + request.request_id
            )
        if not isinstance(getattr(adapter, "adapter_version", None), str) or not getattr(
            adapter, "adapter_version", ""
        ).strip():
            raise HistoricalSourceSchemaError(
                "registered adapter has no stable version: " + request.request_id
            )
        return adapter

    def probe(
        self,
        plan: HistoricalAcquisitionPlanV1,
        *,
        network_allowed: bool = False,
    ) -> AcquisitionReadinessReportV1:
        self._require_network_authorization(plan, network_allowed=network_allowed)
        reports = []
        sources = {source.source_id: source for source in plan.sources}
        for request in plan.requests:
            report = self._adapter(request).probe(
                request,
                transport=self.transport,
                credentials=self.credentials,
                plan_id=plan.plan_id,
                clock=self.clock,
            )
            payload = report.model_dump(mode="python", warnings=False)
            payload.pop("report_sha256", None)
            source = sources[request.source_id]
            payload.update(
                {
                    "license_evidence_uri": source.license_evidence_uri,
                    "license_evidence_sha256": source.license_evidence_sha256,
                    "access_grant_reference": source.access_grant_reference,
                    "throttling_observed": bool(
                        getattr(self.transport, "throttling_observed", False)
                    ),
                }
            )
            reports.append(SourceProbeReportV1.build(**payload))
        return build_readiness_report(
            plan,
            probe_reports=reports,
            network_used=True,
            throttling_observed=bool(getattr(self.transport, "throttling_observed", False)),
            clock=self.clock,
        )

    def acquire(
        self,
        plan: HistoricalAcquisitionPlanV1,
        *,
        raw_store: RawBlobStore,
        network_allowed: bool = False,
    ) -> AcquisitionResult:
        self._require_network_authorization(plan, network_allowed=network_allowed)
        pending: list[
            tuple[HistoricalAcquisitionRequestV1, RawDownload, str, datetime, datetime]
        ] = []
        for request in plan.requests:
            adapter = self._adapter(request)
            retrieval_started_at = _utc_now(self.clock)
            downloads = adapter.acquire(
                request,
                transport=self.transport,
                credentials=self.credentials,
            )
            retrieval_finished_at = _utc_now(self.clock)
            try:
                iterator = iter(downloads)
            except TypeError as exc:
                raise HistoricalSourceSchemaError(
                    "source adapter returned a non-iterable raw download collection"
                ) from exc
            for download_index, download in enumerate(iterator, start=1):
                if download_index > _MAX_DOWNLOADS_PER_REQUEST:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned too many raw downloads for request: "
                        + request.request_id
                    )
                if not isinstance(download, RawDownload):
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an invalid raw download"
                    )
                if not isinstance(download.response, NetworkResponse):
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an invalid network response"
                    )
                if type(download.body) is not bytes or type(download.response.body) is not bytes:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned a non-byte response body"
                    )
                if type(download.response.status_code) is not int or not (
                    100 <= download.response.status_code <= 599
                ):
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an invalid HTTP status"
                    )
                if not 200 <= download.response.status_code <= 299:
                    raise AcquisitionError(_http_error_blocker(download.response.status_code))
                if download.body != download.response.body:
                    raise RawBlobError("raw download body does not match transport response")
                if download.artifact_role not in {"DATA", "FILING_DOCUMENT"}:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an unsupported artifact role"
                    )
                if download.schema_version != request.schema_version:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an incompatible schema version: "
                        + request.request_id
                    )
                if download.artifact_role == "DATA" and download.artifact_kind not in {
                    None,
                    request.artifact_kind,
                }:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an incompatible artifact kind: "
                        + request.request_id
                    )
                if download.artifact_role == "FILING_DOCUMENT":
                    if request.artifact_kind is not ShardArtifactKind.FILING_DOCUMENT:
                        raise HistoricalSourceSchemaError(
                            "filing document role does not match request artifact kind: "
                            + request.request_id
                        )
                    if download.artifact_kind is not None:
                        raise HistoricalSourceSchemaError(
                            "filing document role must not carry a data artifact kind: "
                            + request.request_id
                        )
                elif request.artifact_kind is ShardArtifactKind.FILING_DOCUMENT:
                    raise HistoricalSourceSchemaError(
                        "data role does not match filing request artifact kind: "
                        + request.request_id
                    )
                try:
                    safe_source_uri = _safe_uri(download.source_uri)
                except (AttributeError, TypeError, ValueError) as exc:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned an invalid source URI"
                    ) from exc
                if safe_source_uri is None:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned a raw download without a stable source URI"
                    )
                try:
                    safe_artifact_metadata = _safe_json_object(
                        download.artifact_metadata,
                        path="artifact_metadata",
                    )
                    safe_headers = _safe_headers(download.response.headers)
                    content_length = safe_headers.get("content-length")
                    if content_length is not None and int(content_length) != len(download.body):
                        raise RawBlobError(
                            "response content-length does not match raw response bytes"
                        )
                except (AttributeError, TypeError, ValueError) as exc:
                    raise HistoricalSourceSchemaError(
                        "source adapter returned invalid raw provenance metadata"
                    ) from exc
                download = RawDownload(
                    body=download.body,
                    response=download.response,
                    source_uri=safe_source_uri,
                    artifact_role=download.artifact_role,
                    parent_blob_sha256=download.parent_blob_sha256,
                    parent_artifact_id=download.parent_artifact_id,
                    artifact_kind=download.artifact_kind,
                    schema_version=download.schema_version,
                    artifact_metadata=safe_artifact_metadata,
                )
                digest = raw_store.put(download.body)
                pending.append(
                    (
                        request,
                        download,
                        digest,
                        retrieval_started_at,
                        retrieval_finished_at,
                    )
                )
        batch_artifacts = []
        for request, download, digest, _, _ in pending:
            batch_artifacts.append(
                {
                    "request_id": request.request_id,
                    "request_identity": request.request_identity,
                    "sha256": digest,
                    "artifact_role": download.artifact_role,
                    "artifact_metadata": download.artifact_metadata,
                }
            )
        acquired_request_ids = {item[0].request_id for item in pending}
        missing_request_ids = {
            request.request_id
            for request in plan.requests
            if request.request_id not in acquired_request_ids
        }
        if missing_request_ids:
            raise HistoricalIngestionError(
                "RAW_REQUEST_MISSING: acquisition returned no raw artifact for requests: "
                + ",".join(sorted(missing_request_ids))
            )
        batch_id = _batch_id_from_artifacts(plan.content_sha256, batch_artifacts)
        artifact_by_digest = {
            digest: "raw-" + digest[:32]
            for _, _, digest, _, _ in pending
        }
        sources = {source.source_id: source for source in plan.sources}
        receipts: list[RawArtifactReceiptV1] = []
        for request, download, digest, retrieval_started_at, retrieval_finished_at in pending:
            source = sources[request.source_id]
            receipt = RawArtifactReceiptV1.build(
                batch_id=batch_id,
                request=request,
                adapter_version=self._adapter(request).adapter_version,
                body=download.body,
                retrieval_started_at=retrieval_started_at,
                retrieval_finished_at=retrieval_finished_at,
                source_uri=download.source_uri,
                http_status=download.response.status_code,
                content_type=download.response.content_type,
                response_headers=download.response.headers,
                artifact_role=download.artifact_role,
                artifact_kind=(
                    request.artifact_kind if download.artifact_role == "DATA" else None
                ),
                schema_version=download.schema_version,
                artifact_metadata=download.artifact_metadata,
                parent_artifact_id=download.parent_artifact_id
                or (
                    artifact_by_digest.get(download.parent_blob_sha256)
                    if download.parent_blob_sha256
                    else None
                ),
                license_evidence_uri=source.license_evidence_uri,
                license_evidence_sha256=source.license_evidence_sha256,
                access_grant_reference=source.access_grant_reference,
                storage_policy=plan.storage_policy,
            )
            if receipt.sha256 != digest:
                raise RawBlobError("receipt/blob identity mismatch")
            raw_store.write_receipt(receipt)
            receipts.append(receipt)
        if not receipts:
            raise HistoricalIngestionError(
                "source acquisition returned no raw artifacts for the declared plan"
            )
        batch = RawAcquisitionBatchManifestV1.build(
            batch_id=batch_id,
            plan=plan,
            created_at=_utc_now(self.clock),
            receipts=receipts,
        )
        return AcquisitionResult(
            batch=batch,
            readiness=build_readiness_report(
                plan,
                batch=batch,
                raw_store=raw_store,
                network_used=True,
                throttling_observed=bool(getattr(self.transport, "throttling_observed", False)),
                clock=self.clock,
            ),
        )


def default_source_adapters() -> dict[str, HistoricalSourceAdapter]:
    return {
        "http-json": ConfiguredHttpSourceAdapter(),
        "hithink-market-dumps": HithinkMarketDumpAdapter(),
    }


def default_decoders(
    *,
    include_optional_parquet: bool = True,
    include_hithink_adjustments: bool = False,
) -> dict[tuple[str, ShardArtifactKind, str], HistoricalRawDecoder]:
    decoders: dict[tuple[str, ShardArtifactKind, str], HistoricalRawDecoder] = {}
    if include_optional_parquet:
        decoders[("hithink-market-dumps", ShardArtifactKind.MARKET_BAR, "market-bar-v1")] = (
            HithinkDailyKParquetDecoder()
        )
        if include_hithink_adjustments:
            decoders[
                (
                    "hithink-market-dumps",
                    ShardArtifactKind.CORPORATE_ACTION,
                    "corporate-action-v1",
                )
            ] = HithinkAdjustmentFactorParquetDecoder(allow_as_corporate_actions=True)
    return decoders


def _source_for_request(
    plan: HistoricalAcquisitionPlanV1,
    request_id: str,
) -> HistoricalSourceSpecV1:
    request = next((item for item in plan.requests if item.request_id == request_id), None)
    if request is None:
        raise HistoricalIngestionError("batch references unknown request: " + request_id)
    return next(item for item in plan.sources if item.source_id == request.source_id)


def _row_id(kind: ShardArtifactKind, row: BaseModel) -> str:
    fields = {
        ShardArtifactKind.LISTING_LIFECYCLE: "listing_id",
        ShardArtifactKind.UNIVERSE_MEMBERSHIP: "membership_id",
        ShardArtifactKind.AVAILABILITY: "artifact_id",
        ShardArtifactKind.MARKET_BAR: "bar_id",
        ShardArtifactKind.CORPORATE_ACTION: "action_id",
        ShardArtifactKind.FX_OBSERVATION: "observation_id",
        ShardArtifactKind.BENCHMARK_OBSERVATION: "observation_id",
        ShardArtifactKind.DECISION_ARTIFACT: "artifact_id",
        ShardArtifactKind.FILING_DOCUMENT: "artifact_id",
    }
    return str(getattr(row, fields[kind]))


def _natural_key(kind: ShardArtifactKind, row: BaseModel) -> tuple[object, ...]:
    if kind is ShardArtifactKind.MARKET_BAR:
        return (row.listing_id, row.trading_date)
    if kind is ShardArtifactKind.CORPORATE_ACTION:
        return (
            row.listing_id,
            row.action_type,
            row.effective_date,
            row.ex_date,
            row.payment_date,
        )
    if kind is ShardArtifactKind.FX_OBSERVATION:
        return (row.listing_id, row.base_currency, row.quote_currency, row.observation_date)
    if kind is ShardArtifactKind.BENCHMARK_OBSERVATION:
        return (row.benchmark_id, row.observation_date)
    if kind is ShardArtifactKind.UNIVERSE_MEMBERSHIP:
        return (row.universe_id, row.listing_id, row.valid_from, row.valid_to, row.included)
    if kind is ShardArtifactKind.FILING_DOCUMENT:
        return (row.filing_id, row.document_hash)
    return (_row_id(kind, row),)


def _semantic_payload(row: BaseModel) -> bytes:
    payload = row.model_dump(mode="json", warnings=False)
    payload.pop("source_hash", None)
    payload.pop("source_artifact_id", None)
    for identifier in (
        "bar_id",
        "action_id",
        "observation_id",
        "membership_id",
        "artifact_id",
    ):
        payload.pop(identifier, None)
    return canonical_json_bytes(payload)


def _sort_key(kind: ShardArtifactKind, row: BaseModel) -> tuple[str, ...]:
    values: list[object]
    if kind is ShardArtifactKind.LISTING_LIFECYCLE:
        values = [row.listing_id, row.listing_date]
    elif kind is ShardArtifactKind.UNIVERSE_MEMBERSHIP:
        values = [row.universe_id, row.listing_id, row.valid_from, row.valid_to or date.max]
    elif kind is ShardArtifactKind.AVAILABILITY:
        values = [row.artifact_id]
    elif kind is ShardArtifactKind.MARKET_BAR:
        values = [row.listing_id, row.trading_date, row.bar_id]
    elif kind is ShardArtifactKind.CORPORATE_ACTION:
        values = [row.listing_id, row.effective_date, row.action_id]
    elif kind is ShardArtifactKind.FX_OBSERVATION:
        values = [row.listing_id, row.observation_date, row.observation_id]
    elif kind is ShardArtifactKind.BENCHMARK_OBSERVATION:
        values = [row.benchmark_id, row.observation_date, row.observation_id]
    elif kind is ShardArtifactKind.FILING_DOCUMENT:
        values = [row.listing_id, row.published_at, row.filing_id, row.document_hash]
    else:
        values = [row.listing_id, row.as_of, row.artifact_id]
    return tuple(value.isoformat() if isinstance(value, date) else str(value) for value in values)


def _row_listing(row: BaseModel) -> str | None:
    value = getattr(row, "listing_id", None)
    return str(value) if value is not None else None


def _row_date(kind: ShardArtifactKind, row: BaseModel) -> date | None:
    field_by_kind = {
        ShardArtifactKind.LISTING_LIFECYCLE: "listing_date",
        ShardArtifactKind.UNIVERSE_MEMBERSHIP: "valid_from",
        ShardArtifactKind.AVAILABILITY: None,
        ShardArtifactKind.MARKET_BAR: "trading_date",
        ShardArtifactKind.CORPORATE_ACTION: "effective_date",
        ShardArtifactKind.FX_OBSERVATION: "observation_date",
        ShardArtifactKind.BENCHMARK_OBSERVATION: "observation_date",
        ShardArtifactKind.DECISION_ARTIFACT: "as_of",
        ShardArtifactKind.FILING_DOCUMENT: "published_at",
    }
    name = field_by_kind[kind]
    return None if name is None else getattr(row, name)


def _row_in_request(
    request: HistoricalAcquisitionRequestV1,
    kind: ShardArtifactKind,
    row: BaseModel,
) -> bool:
    """Keep only the declared request scope from a full-market response."""

    listing_id = _row_listing(row)
    if listing_id is not None and listing_id not in request.listing_ids:
        return False
    if kind is ShardArtifactKind.AVAILABILITY:
        # Availability is metadata rather than a session row.  Use only
        # semantic publication/availability dates for the point-in-time
        # boundary; retrieval time can be today even when the artifact was
        # historically available.  Unknown-dated metadata is omitted so a
        # dangling reference makes validation fail closed.
        scope_dates = [
            value
            for value in (
                getattr(row, "period_end", None),
                (
                    row.published_at.date()
                    if isinstance(row.published_at, datetime)
                    else row.published_at
                ),
                (
                    row.available_at.date()
                    if isinstance(row.available_at, datetime)
                    else row.available_at
                ),
            )
            if isinstance(value, date)
        ]
        if not scope_dates or any(value > request.end_date for value in scope_dates):
            return False
        return True
    if kind is ShardArtifactKind.LISTING_LIFECYCLE:
        # Keep an interval that overlaps the requested window, including a
        # lifecycle that began before it.  A lifecycle beginning after the
        # request end is future data and must not enter the compiled corpus.
        return row.listing_date <= request.end_date and (
            row.delisting_date is None or row.delisting_date >= request.start_date
        )
    if kind is ShardArtifactKind.UNIVERSE_MEMBERSHIP:
        # Membership intervals use the same overlap rule.  This preserves
        # pre-window context without retaining intervals that ended before the
        # request or begin after its point-in-time boundary.
        return row.valid_from <= request.end_date and (
            row.valid_to is None or row.valid_to >= request.start_date
        )
    row_date = _row_date(kind, row)
    return row_date is None or request.start_date <= row_date <= request.end_date


def _required_metadata_text(
    metadata: Mapping[str, object],
    key: str,
    *,
    allow_none: bool = False,
) -> str | None:
    value = metadata.get(key)
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HistoricalIngestionError(
            f"filing document metadata is missing a non-empty {key}: raw receipt"
        )
    return value.strip()


def _filing_document_row(
    receipt: RawArtifactReceiptV1,
    batch: RawAcquisitionBatchManifestV1,
    request: HistoricalAcquisitionRequestV1,
) -> HistoricalFilingDocumentRecord:
    """Project receipt metadata into a typed filing revision row.

    The document body remains in the raw CAS.  Only metadata needed for
    point-in-time scoping and future filing/evidence links is put in the
    canonical shard; no PDF or HTML parsing happens here.
    """

    if receipt.source_kind is not HistoricalSourceKind.FILINGS:
        raise HistoricalIngestionError(
            "FILING_DOCUMENT receipt must belong to the FILINGS source category: "
            + receipt.receipt_id
        )
    metadata = receipt.artifact_metadata
    filing_id = _required_metadata_text(metadata, "filing_id")
    listing_id = _required_metadata_text(metadata, "listing_id")
    market = _required_metadata_text(metadata, "market")
    source = _required_metadata_text(metadata, "source")
    title = _required_metadata_text(metadata, "title")
    document_type = _required_metadata_text(metadata, "document_type")
    published_raw = _required_metadata_text(metadata, "published_date")
    document_hash = _required_metadata_text(metadata, "document_sha256")
    document_size_raw = metadata.get("document_size")
    media_type = _required_metadata_text(metadata, "media_type")
    final_url = _required_metadata_text(metadata, "final_url", allow_none=True)
    source_uri = receipt.source_uri or final_url
    if source_uri is None:
        raise HistoricalIngestionError(
            "FILING_DOCUMENT receipt has no persisted source locator: " + receipt.receipt_id
        )
    if listing_id not in request.listing_ids:
        raise HistoricalIngestionError(
            "filing document listing lies outside request scope: " + receipt.receipt_id
        )
    target_market = batch.plan.target.listing_markets.get(listing_id)
    if target_market is not None and market != target_market.value:
        raise HistoricalIngestionError(
            "filing document market does not match target listing: " + receipt.receipt_id
        )
    if market not in {item.value for item in batch.plan.target.markets}:
        raise HistoricalIngestionError(
            "filing document market lies outside target: " + receipt.receipt_id
        )
    if document_hash != receipt.sha256:
        raise HistoricalIngestionError(
            "filing document metadata hash does not match raw receipt: " + receipt.receipt_id
        )
    if document_size_raw != receipt.byte_length:
        raise HistoricalIngestionError(
            "filing document metadata size does not match raw receipt: " + receipt.receipt_id
        )
    if receipt.content_type is not None and media_type != receipt.content_type:
        raise HistoricalIngestionError(
            "filing document metadata media type does not match raw receipt: "
            + receipt.receipt_id
        )
    try:
        published_at = date.fromisoformat(published_raw or "")
    except ValueError as exc:
        raise HistoricalIngestionError(
            "filing document published_date is not an ISO date: " + receipt.receipt_id
        ) from exc
    if not isinstance(document_size_raw, int) or isinstance(document_size_raw, bool):
        raise HistoricalIngestionError(
            "filing document document_size is not an integer: " + receipt.receipt_id
        )
    optional_metadata = {
        key: _required_metadata_text(metadata, key, allow_none=True)
        for key in ("source_document_id", "report_period")
    }
    try:
        filing_market = FilingMarket(market)
        filing_source = FilingSource(source)
        canonical_source_uri = validate_filing_document_url(filing_source, source_uri)
        canonical_locator = validate_filing_document_url(
            filing_source, final_url or source_uri
        )
        FilingRecord(
            filing_id=filing_id,
            listing_id=listing_id,
            market=filing_market,
            source=filing_source,
            title=title,
            document_type=document_type,
            published_date=published_at,
            url=canonical_source_uri,
            source_document_id=optional_metadata["source_document_id"],
            report_period=optional_metadata["report_period"],
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalIngestionError(
            "filing document metadata is not a valid official filing identity: "
            + receipt.receipt_id
        ) from exc
    artifact_id = filing_document_artifact_id(filing_id or "", document_hash or "")
    revision_identity = f"{filing_id}:{document_hash}"
    try:
        return HistoricalFilingDocumentRecord(
            artifact_id=artifact_id,
            filing_id=filing_id,
            listing_id=listing_id,
            market=market,
            source=source,
            title=title,
            document_type=document_type,
            published_at=published_at,
            # A source's exact historical availability timestamp is not
            # inferred from a publication date.  The local retrieval finish
            # is the conservative point-in-time boundary for this corpus.
            available_at=receipt.retrieval_finished_at,
            retrieved_at=receipt.retrieval_finished_at,
            source_uri=canonical_source_uri,
            document_locator=canonical_locator,
            source_document_id=optional_metadata["source_document_id"],
            report_period=optional_metadata["report_period"],
            document_hash=document_hash,
            document_size=document_size_raw,
            media_type=media_type,
            revision_identity=revision_identity,
            source_artifact_id=receipt.source_id,
            source_hash=batch.source_aggregate_hash(receipt.source_id),
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalIngestionError(
            "filing document metadata failed canonical validation: " + receipt.receipt_id
        ) from exc


class HistoricalIngestionCompiler:
    """Offline raw-to-shard compiler; it never owns a network or model client."""

    def __init__(
        self,
        *,
        raw_store: RawBlobStore,
        artifact_store: HistoricalArtifactStore,
        decoders: Mapping[tuple[str, ShardArtifactKind, str], HistoricalRawDecoder] | None = None,
    ) -> None:
        self.raw_store = raw_store
        self.artifact_store = artifact_store
        self._allow_generic_json_decoder = decoders is None
        self.decoders = dict(default_decoders() if decoders is None else decoders)

    def _decoder(self, receipt: RawArtifactReceiptV1) -> HistoricalRawDecoder:
        if receipt.artifact_kind is None or receipt.schema_version is None:
            raise HistoricalIngestionError("receipt has no canonical artifact schema")
        decoder = self.decoders.get(
            (receipt.adapter_id, receipt.artifact_kind, receipt.schema_version)
        )
        if (
            decoder is None
            and self._allow_generic_json_decoder
            and receipt.content_type in {"application/json", "text/json"}
        ):
            decoder = CanonicalJsonDecoder(receipt.artifact_kind, receipt.schema_version)
        if decoder is None:
            raise HistoricalIngestionError(
                "no decoder is registered for adapter/schema: "
                f"{receipt.adapter_id}/{receipt.artifact_kind.value}/{receipt.schema_version}"
            )
        return decoder

    def compile(self, batch: RawAcquisitionBatchManifestV1) -> HistoricalDatasetManifest:
        try:
            batch = RawAcquisitionBatchManifestV1.model_validate(
                batch.model_dump(mode="python", exclude_unset=True, warnings=False)
            )
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError("raw acquisition batch manifest is invalid") from exc
        plan = batch.plan
        requests = {request.request_id: request for request in plan.requests}
        sources = {source.source_id: source for source in plan.sources}
        for receipt in batch.receipts:
            request = requests.get(receipt.request_id)
            if request is None:
                raise HistoricalIngestionError(
                    "batch receipt references unknown request: " + receipt.receipt_id
                )
            source = sources.get(receipt.source_id)
            if source is None:
                raise HistoricalIngestionError(
                    "batch receipt references unknown source: " + receipt.receipt_id
                )
            if receipt.request_identity != request.request_identity:
                raise HistoricalIngestionError(
                    "batch receipt/request identity mismatch: " + receipt.receipt_id
                )
            if receipt.canonical_parameters != request.parameters:
                raise HistoricalIngestionError(
                    "batch receipt canonical parameters mismatch: " + receipt.receipt_id
                )
            if receipt.source_id != request.source_id or receipt.adapter_id != request.adapter_id:
                raise HistoricalIngestionError(
                    "batch receipt/request source identity mismatch: " + receipt.receipt_id
                )
            if receipt.source_kind is not request.source_kind:
                raise HistoricalIngestionError(
                    "batch receipt/request category mismatch: " + receipt.receipt_id
                )
            if receipt.license_evidence_uri != source.license_evidence_uri or (
                receipt.license_evidence_sha256 != source.license_evidence_sha256
            ):
                raise HistoricalIngestionError(
                    "batch receipt/source license evidence mismatch: " + receipt.receipt_id
                )
            if receipt.access_grant_reference != source.access_grant_reference:
                raise HistoricalIngestionError(
                    "batch receipt/source access grant mismatch: " + receipt.receipt_id
                )
            if receipt.storage_policy != plan.storage_policy:
                raise HistoricalIngestionError(
                    "batch receipt/plan storage policy mismatch: " + receipt.receipt_id
                )
            if receipt.artifact_role == "DATA" and (
                receipt.artifact_kind is not request.artifact_kind
                or receipt.schema_version != request.schema_version
            ):
                raise HistoricalIngestionError(
                    "batch data receipt schema does not match request: " + receipt.receipt_id
                )
        grouped: dict[tuple[str, ShardArtifactKind, str], list[BaseModel]] = defaultdict(list)
        for receipt in batch.receipts:
            body = self.raw_store.read(receipt.sha256, expected_length=receipt.byte_length)
            if receipt.artifact_role == "FILING_DOCUMENT":
                request = requests[receipt.request_id]
                row = _filing_document_row(receipt, batch, request)
                if row.published_at > request.end_date:
                    # A future filing must never disappear merely because the
                    # generic scope filter would otherwise omit it.  Keeping
                    # the failure explicit protects the point-in-time claim
                    # when an upstream response ignores its requested range.
                    raise HistoricalIngestionError(
                        "future filing lies outside acquisition request: "
                        + receipt.receipt_id
                    )
                if _row_in_request(request, ShardArtifactKind.FILING_DOCUMENT, row):
                    grouped[
                        (
                            receipt.source_id,
                            ShardArtifactKind.FILING_DOCUMENT,
                            receipt.schema_version or "filing-document-v1",
                        )
                    ].append(row)
                continue
            if receipt.artifact_role != "DATA":
                continue
            request = requests[receipt.request_id]
            decoder = self._decoder(receipt)
            decode_scoped = getattr(decoder, "decode_scoped", None)
            rows = (
                decode_scoped(receipt, body, request)
                if callable(decode_scoped)
                else decoder.decode(receipt, body)
            )
            source_hash = batch.source_aggregate_hash(receipt.source_id)
            for raw_row in rows:
                if receipt.artifact_kind is None:
                    raise HistoricalIngestionError("data receipt has no artifact kind")
                model_type = _MODEL_BY_KIND[receipt.artifact_kind]
                try:
                    row = (
                        raw_row
                        if isinstance(raw_row, model_type)
                        else model_type.model_validate(raw_row)
                    )
                    updates: dict[str, object] = {}
                    if hasattr(row, "source_hash"):
                        updates["source_hash"] = source_hash
                    if hasattr(row, "source_artifact_id"):
                        updates["source_artifact_id"] = receipt.source_id
                    if hasattr(row, "code_changes"):
                        updates["code_changes"] = [
                            item.model_copy(
                                update={
                                    "source_artifact_id": receipt.source_id,
                                    "source_hash": source_hash,
                                }
                            )
                            for item in row.code_changes
                        ]
                    row = row.model_copy(update=updates) if updates else row
                    row = model_type.model_validate(row)
                except (TypeError, ValueError) as exc:
                    raise HistoricalIngestionError(
                        "decoded row failed canonical validation: " + receipt.receipt_id
                    ) from exc
                if not _row_in_request(request, receipt.artifact_kind, row):
                    continue
                grouped[
                    (receipt.source_id, receipt.artifact_kind, receipt.schema_version or "")
                ].append(row)

        shards = []
        canonical_rows_by_kind: dict[ShardArtifactKind, list[BaseModel]] = defaultdict(list)
        observed_rows_by_source_kind: dict[
            HistoricalSourceKind, list[tuple[ShardArtifactKind, BaseModel]]
        ] = defaultdict(list)
        for (source_id, kind, schema_version), raw_rows in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1].value, item[0][2])
        ):
            by_natural_key: dict[tuple[object, ...], BaseModel] = {}
            for row in raw_rows:
                key = _natural_key(kind, row)
                previous = by_natural_key.get(key)
                if previous is not None:
                    if _semantic_payload(previous) != _semantic_payload(row):
                        raise HistoricalIngestionError(
                            "conflicting natural key in source batch: "
                            f"{source_id}/{kind.value}/{key}"
                        )
                    continue
                by_natural_key[key] = row
            rows = sorted(by_natural_key.values(), key=lambda item: _sort_key(kind, item))
            canonical_rows_by_kind[kind].extend(rows)
            observed_rows_by_source_kind[sources[source_id].source_kind].extend(
                (kind, row) for row in rows
            )
            dates = [_row_date(kind, row) for row in rows]
            valid_dates = [item for item in dates if item is not None]
            date_start = min(valid_dates, default=plan.target.start_date)
            date_end = max(valid_dates, default=plan.target.end_date)
            listing_scope = sorted(
                {
                    listing_id
                    for listing_id in (_row_listing(row) for row in rows)
                    if listing_id is not None
                }
                or set(plan.target.listing_ids)
            )
            shard_id = (
                "shard-"
                + hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "source_id": source_id,
                            "artifact_kind": kind.value,
                            "schema_version": schema_version,
                            "rows": [row.model_dump(mode="json", warnings=False) for row in rows],
                        }
                    )
                ).hexdigest()[:32]
            )
            shards.append(
                self.artifact_store.freeze_shard(
                    shard_id=shard_id,
                    artifact_kind=kind,
                    schema_version=schema_version,
                    date_start=date_start,
                    date_end=date_end,
                    listing_scope=listing_scope,
                    source_artifact_id=source_id,
                    rows=rows,
                )
            )

        if not shards:
            raise HistoricalIngestionError(
                "batch contains no decodable DATA or FILING_DOCUMENT artifact"
            )

        source_by_id = sources
        source_descriptors = []
        retrieved_by_source: dict[str, datetime] = {}
        for receipt in batch.receipts:
            previous = retrieved_by_source.get(receipt.source_id)
            if previous is None or receipt.retrieval_finished_at > previous:
                retrieved_by_source[receipt.source_id] = receipt.retrieval_finished_at
        for source_id in sorted({item.source_id for item in batch.receipts}):
            source = source_by_id[source_id]
            source_descriptors.append(
                {
                    "source_id": source.source_id,
                    "source_kind": source.source_kind,
                    "provider_id": source.provider_id,
                    "source_name": source.source_name,
                    "query_parameters": {
                        "plan_id": plan.plan_id,
                        "request_ids": sorted(
                            item.request_id
                            for item in batch.receipts
                            if item.source_id == source_id
                        ),
                    },
                    "retrieved_at": retrieved_by_source[source_id],
                    "source_version": source.source_version,
                    "coverage_start": source.coverage_start,
                    "coverage_end": source.coverage_end,
                    "coverage_listing_ids": source.coverage_listing_ids,
                    "content_sha256": batch.source_aggregate_hash(source_id),
                    "source_uri": source.source_uri,
                    "authority": source.authority,
                    "license_status": source.license_status,
                    "licensing_constraints": source.licensing_constraints,
                    "license_evidence_uri": source.license_evidence_uri,
                    "license_evidence_sha256": source.license_evidence_sha256,
                    "access_grant_reference": source.access_grant_reference,
                    "historical_capable": source.historical_capable,
                    "is_current_snapshot": source.is_current_snapshot,
                }
            )

        from .contracts import HistoricalSourceDescriptor

        descriptors = [
            HistoricalSourceDescriptor.model_validate(item) for item in source_descriptors
        ]
        coverage_reports = self._build_coverage_reports(
            plan,
            batch,
            observed_rows_by_source_kind,
            descriptors,
        )
        dataset_id = (
            "dataset-"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "target": plan.target.model_dump(mode="json", warnings=False),
                        "source_hashes": [item.content_sha256 for item in descriptors],
                        "shards": [item.content_sha256 for item in shards],
                    }
                )
            ).hexdigest()[:32]
        )
        return HistoricalDatasetManifest.build(
            dataset_id=dataset_id,
            dataset_version=plan.plan_version,
            target=plan.target,
            source_descriptors=descriptors,
            shards=shards,
            coverage_reports=coverage_reports,
            missing_data_summary={
                "raw_receipts": len(batch.receipts),
                "canonical_rows": sum(len(rows) for rows in canonical_rows_by_kind.values()),
            },
            limitations=[
                "compiled offline from an opt-in acquisition batch",
                *plan.notes,
            ],
        )

    def compile_with_replay_check(
        self,
        batch: RawAcquisitionBatchManifestV1,
    ) -> HistoricalDatasetManifest:
        """Compile twice offline and fail if any manifest/shard identity changes."""

        first = self.compile(batch)
        second = self.compile(batch)
        first_shards = [
            (
                item.shard_id,
                item.content_sha256,
                item.row_count,
                item.source_artifact_id,
            )
            for item in first.shards
        ]
        second_shards = [
            (
                item.shard_id,
                item.content_sha256,
                item.row_count,
                item.source_artifact_id,
            )
            for item in second.shards
        ]
        if first.content_sha256 != second.content_sha256 or first_shards != second_shards:
            raise HistoricalIngestionError(
                "OFFLINE_REPLAY_IDENTITY_MISMATCH: manifest or shard identity changed"
            )
        return first

    def _build_coverage_reports(
        self,
        plan: HistoricalAcquisitionPlanV1,
        batch: RawAcquisitionBatchManifestV1,
        rows_by_source_kind: Mapping[
            HistoricalSourceKind, Sequence[tuple[ShardArtifactKind, BaseModel]]
        ],
        descriptors: Sequence[BaseModel],
    ) -> list[HistoricalCoverageReport]:
        source_ids_by_kind: dict[HistoricalSourceKind, list[str]] = defaultdict(list)
        for source in plan.sources:
            if any(receipt.source_id == source.source_id for receipt in batch.receipts):
                source_ids_by_kind[source.source_kind].append(source.source_id)
        required = set(plan.target.required_source_kinds) | set(source_ids_by_kind)
        required |= set(HistoricalSourceKind)
        reports: list[HistoricalCoverageReport] = []
        for source_kind in sorted(required, key=lambda item: item.value):
            requests = [item for item in plan.requests if item.source_kind is source_kind]
            observed_by_listing: dict[str, set[date]] = defaultdict(set)
            expected: dict[str, list[date]] = {}
            basis = None
            for request in requests:
                if request.expected_sessions_by_listing:
                    for listing_id, values in request.expected_sessions_by_listing.items():
                        expected.setdefault(listing_id, []).extend(values)
                basis = basis or request.coverage_evidence_basis
            kind_rows = rows_by_source_kind.get(source_kind, ())
            for artifact_kind, row in kind_rows:
                listing_id = _row_listing(row)
                row_date = _row_date(artifact_kind, row)
                if (
                    source_kind is HistoricalSourceKind.BENCHMARK
                    and listing_id is None
                    and row_date is not None
                    and plan.target.start_date <= row_date <= plan.target.end_date
                ):
                    # Benchmark observations are global by contract and do
                    # not carry a listing_id. Attribute each observation to
                    # the listing scopes explicitly covered by benchmark
                    # requests so a complete index series is not reported as
                    # UNKNOWN merely because the row is not listing-shaped.
                    for request in requests:
                        if request.artifact_kind is artifact_kind:
                            for request_listing_id in request.listing_ids:
                                observed_by_listing[request_listing_id].add(row_date)
                    continue
                if (
                    listing_id is not None
                    and row_date is not None
                    and plan.target.start_date <= row_date <= plan.target.end_date
                ):
                    observed_by_listing[listing_id].add(row_date)
            expected_mapping: Mapping[str, Iterable[date]] | None = expected or None
            if expected:
                expected = {key: sorted(set(values)) for key, values in expected.items()}
            source_map = {
                source.source_id: source
                for source in descriptors
                if source.source_kind is source_kind
            }
            source_ids_by_listing = {
                listing_id: [
                    source_id
                    for source_id, source in source_map.items()
                    if listing_id in source.coverage_listing_ids
                ]
                for listing_id in plan.target.listing_ids
            }
            if basis is None:
                basis = {
                    HistoricalSourceKind.PRICES: CoverageEvidenceBasis.TRADING_SESSIONS,
                    HistoricalSourceKind.FX: CoverageEvidenceBasis.OBSERVATION_SESSIONS,
                    HistoricalSourceKind.BENCHMARK: CoverageEvidenceBasis.OBSERVATION_SESSIONS,
                }.get(source_kind)
            reports.append(
                build_coverage_report(
                    target=plan.target,
                    source_kind=source_kind,
                    expected_sessions_by_listing=expected_mapping,
                    observed_sessions_by_listing=observed_by_listing,
                    source_artifact_ids_by_listing=source_ids_by_listing,
                    report_id=f"coverage-{plan.plan_id}-{source_kind.value.lower()}",
                    evidence_basis=basis,
                )
            )
        return reports


def build_readiness_report(
    plan: HistoricalAcquisitionPlanV1,
    *,
    probe_reports: Sequence[SourceProbeReportV1] = (),
    batch: RawAcquisitionBatchManifestV1 | None = None,
    raw_store: RawBlobStore | None = None,
    validation_summary: Any | None = None,
    compiled_manifest: HistoricalDatasetManifest | None = None,
    network_used: bool = False,
    throttling_observed: bool = False,
    clock: Any | None = None,
) -> AcquisitionReadinessReportV1:
    """Produce explicit readiness claims and precise unresolved blockers."""

    blockers: list[str] = []
    warnings: list[str] = []
    if throttling_observed:
        warnings.append("THROTTLING_OBSERVED: provider responses required bounded pacing/retry")
    if batch is None:
        blockers.append("RAW_BATCH_MISSING: no acquisition batch is available")
    else:
        if batch.plan_id != plan.plan_id or batch.plan_sha256 != plan.content_sha256:
            blockers.append("RAW_BATCH_SCOPE_MISMATCH: " + batch.batch_id)
        receipt_request_ids = {receipt.request_id for receipt in batch.receipts}
        for request in plan.requests:
            if request.request_id not in receipt_request_ids:
                blockers.append("RAW_REQUEST_MISSING: " + request.request_id)
        for receipt in batch.receipts:
            if raw_store is None:
                blockers.append(
                    "RAW_STORE_UNVERIFIED: receipt bytes were not verified in this report"
                )
                break
            try:
                raw_store.read(receipt.sha256, expected_length=receipt.byte_length)
            except RawBlobError as exc:
                blockers.append(f"RAW_BLOB_INVALID: {receipt.artifact_id}: {exc}")
    for source in plan.sources:
        if source.license_evidence_uri is None or source.license_evidence_sha256 is None:
            blockers.append("SOURCE_TERMS_UNVERIFIED: " + source.source_id)
        if source.license_status is LicenseStatus.UNKNOWN:
            blockers.append("SOURCE_LICENSE_STATUS_UNVERIFIED: " + source.source_id)
        elif source.license_status is LicenseStatus.PROHIBITED:
            blockers.append("SOURCE_LICENSE_PROHIBITED: " + source.source_id)
        if (
            source.license_status is LicenseStatus.RESTRICTED_INTERNAL
            and not source.access_grant_reference
        ):
            blockers.append("ACCESS_GRANT_UNVERIFIED: " + source.source_id)
        if source.authority in {SourceAuthority.UNKNOWN, SourceAuthority.FIXTURE}:
            warnings.append("SOURCE_AUTHORITY_UNVERIFIED: " + source.source_id)
            blockers.append("SOURCE_AUTHORITY_UNVERIFIED: " + source.source_id)
        if source.is_current_snapshot:
            blockers.append("CURRENT_SNAPSHOT_UNUSABLE: " + source.source_id)
    requests_by_id = {request.request_id: request for request in plan.requests}
    sources_by_id = {source.source_id: source for source in plan.sources}
    scoped_probe_reports: list[SourceProbeReportV1] = []
    for report in probe_reports:
        request = requests_by_id.get(report.request_id)
        source = sources_by_id.get(report.source_id)
        scope_mismatch = (
            report.plan_id != plan.plan_id
            or request is None
            or source is None
            or report.source_id != request.source_id
            or report.adapter_id != request.adapter_id
            or report.source_kind is not request.source_kind
        )
        terms_mismatch = source is not None and (
            report.license_evidence_uri != source.license_evidence_uri
            or report.license_evidence_sha256 != source.license_evidence_sha256
            or report.access_grant_reference != source.access_grant_reference
        )
        if scope_mismatch:
            blockers.append("SOURCE_PROBE_SCOPE_MISMATCH: " + report.report_id)
            continue
        if terms_mismatch:
            blockers.append("SOURCE_PROBE_TERMS_MISMATCH: " + report.report_id)
            continue
        scoped_probe_reports.append(report)
    for report in scoped_probe_reports:
        warnings.extend(report.warnings)
        if report.status != ProbeStatus.PASS:
            blockers.extend(report.blockers or ["SOURCE_PROBE_FAILED: " + report.source_id])
        elif report.blockers:
            blockers.extend(report.blockers)
    qualified_historical_sources = {
        report.source_id
        for report in scoped_probe_reports
        if report.status == ProbeStatus.PASS and report.historical_capable
    }
    for source in plan.sources:
        if not source.historical_capable and source.source_id not in qualified_historical_sources:
            blockers.append("HISTORICAL_CAPABILITY_UNVERIFIED: " + source.source_id)
    target_h = {
        listing_id
        for listing_id in plan.target.listing_ids
        if _target_market(plan.target, listing_id) == "H"
    }
    if target_h:
        h_price_source_ids = {
            request.source_id
            for request in plan.requests
            if request.source_kind is HistoricalSourceKind.PRICES
            and target_h.intersection(request.listing_ids)
        }
        h_action_source_ids = {
            request.source_id
            for request in plan.requests
            if request.source_kind
            in {HistoricalSourceKind.PRICES, HistoricalSourceKind.CORPORATE_ACTIONS}
            and target_h.intersection(request.listing_ids)
        }
        h_terminal_source_ids = {
            request.source_id
            for request in plan.requests
            if request.source_kind
            in {
                HistoricalSourceKind.PRICES,
                HistoricalSourceKind.CORPORATE_ACTIONS,
                HistoricalSourceKind.LISTING_LIFECYCLE,
                HistoricalSourceKind.DELISTINGS,
            }
            and target_h.intersection(request.listing_ids)
        }
        h_terms_ids = {
            source.source_id
            for source in plan.sources
            if source.license_evidence_uri is not None
            and source.license_evidence_sha256 is not None
            and source.license_status
            in {LicenseStatus.OPEN_REDISTRIBUTABLE, LicenseStatus.RESTRICTED_INTERNAL}
            and (
                source.license_status is not LicenseStatus.RESTRICTED_INTERNAL
                or source.access_grant_reference is not None
            )
        }
        def qualified_h_listings(
            source_ids: set[str],
            source_kinds: set[HistoricalSourceKind],
            evidence_field: str | None = None,
        ) -> set[str]:
            covered: set[str] = set()
            for report in scoped_probe_reports:
                request = requests_by_id.get(report.request_id)
                request_h_listings = (
                    target_h
                    if request is None
                    else target_h.intersection(request.listing_ids)
                )
                if (
                    not request_h_listings
                    or report.source_id not in source_ids
                    or report.source_id not in h_terms_ids
                    or report.source_kind not in source_kinds
                    or (
                        evidence_field is not None
                        and getattr(report, evidence_field) != CoverageEvidenceStatus.CONFIRMED
                    )
                    or not _probe_has_h_scope(report, request_h_listings, plan.target)
                ):
                    continue
                covered.update(request_h_listings)
            return covered

        h_price_covered = qualified_h_listings(
            h_price_source_ids,
            {HistoricalSourceKind.PRICES},
        )
        h_action_covered = qualified_h_listings(
            h_action_source_ids,
            {HistoricalSourceKind.PRICES, HistoricalSourceKind.CORPORATE_ACTIONS},
            evidence_field="action_coverage",
        )
        h_terminal_covered = qualified_h_listings(
            h_terminal_source_ids,
            {
                HistoricalSourceKind.PRICES,
                HistoricalSourceKind.CORPORATE_ACTIONS,
                HistoricalSourceKind.LISTING_LIFECYCLE,
                HistoricalSourceKind.DELISTINGS,
            },
            evidence_field="terminal_coverage",
        )
        missing_h_evidence = []
        if not target_h.issubset(h_price_covered):
            missing_h_evidence.append("PRICE_HISTORY")
        if not target_h.issubset(h_action_covered):
            missing_h_evidence.append("CORPORATE_ACTIONS")
        if not target_h.issubset(h_terminal_covered):
            missing_h_evidence.append("TERMINAL_LIFECYCLE")
        if missing_h_evidence:
            blockers.append(
                "H_SOURCE_UNQUALIFIED: missing confirmed H-share evidence "
                + ",".join(missing_h_evidence)
                + "; price, action, terminal/lifecycle probes and permitted personal caching "
                "must be confirmed"
            )
    if plan.target.membership_claim == "HISTORICAL":
        membership_proven = any(
            report.source_kind is HistoricalSourceKind.UNIVERSE_MEMBERSHIP
            and _probe_covers_target(report, plan.target)
            for report in scoped_probe_reports
        )
        lifecycle_proven = any(
            report.source_kind
            in {
                HistoricalSourceKind.LISTING_LIFECYCLE,
                HistoricalSourceKind.DELISTINGS,
            }
            and _probe_covers_target(report, plan.target)
            for report in scoped_probe_reports
        )
        if not membership_proven or not lifecycle_proven:
            blockers.append(
                "HISTORICAL_MEMBERSHIP_UNVERIFIED: effective-dated membership source "
                "and lifecycle/code-change evidence are absent"
            )
    if not any(
        report.source_kind
        in {
            HistoricalSourceKind.LISTING_LIFECYCLE,
            HistoricalSourceKind.DELISTINGS,
        }
        and _probe_has_target_observation(report, plan.target)
        and report.terminal_coverage == CoverageEvidenceStatus.CONFIRMED
        for report in scoped_probe_reports
    ):
        blockers.append(
            "TERMINAL_COVERAGE_UNVERIFIED: delisted, acquired, cancelled, and suspended "
            "outcomes remain unresolved until a source probe proves retention"
        )
    validation_errors = (
        ()
        if validation_summary is None
        else getattr(validation_summary, "errors", ()) or ()
    )
    if compiled_manifest is not None:
        compiled_target = getattr(compiled_manifest, "target", None)
        if compiled_target is not None and getattr(compiled_target, "target_id", None) != (
            plan.target.target_id
        ):
            blockers.append("COMPILED_DATASET_SCOPE_MISMATCH: " + compiled_manifest.dataset_id)
    if validation_summary is not None and compiled_manifest is not None:
        summary_dataset_id = getattr(validation_summary, "dataset_id", None)
        if summary_dataset_id is not None and summary_dataset_id != compiled_manifest.dataset_id:
            blockers.append("VALIDATION_SCOPE_MISMATCH: " + str(summary_dataset_id))
    for error in validation_errors:
        blockers.append("DATASET_VALIDATION_ERROR: " + str(error))
    coverage_ready = True
    if validation_summary is not None:
        coverage_status = getattr(validation_summary, "coverage_status", {}) or {}
        for source_kind in plan.target.required_source_kinds:
            accepted_kinds = _readiness_scope_source_kinds(source_kind)
            for listing_id in plan.target.listing_ids:
                if not any(
                    coverage_status.get(f"{candidate.value}:{listing_id}") == "COMPLETE"
                    for candidate in accepted_kinds
                ):
                    coverage_ready = False
                    blockers.append(
                        "PERSONAL_COVERAGE_UNVERIFIED: "
                        f"{source_kind.value}:{listing_id}"
                    )
    production_eligible = bool(
        validation_summary is not None and getattr(validation_summary, "production_eligible", False)
        and not blockers
    )
    compiled_id = compiled_manifest.dataset_id if compiled_manifest is not None else None
    acquisition_ready = batch is not None and not any(
        blocker.startswith(
            (
                "RAW_",
                "SOURCE_TERMS_UNVERIFIED",
                "SOURCE_LICENSE_",
                "ACCESS_GRANT_UNVERIFIED",
            )
        )
        for blocker in blockers
    )
    personal_ready = bool(
        acquisition_ready
        and compiled_manifest is not None
        and validation_summary is not None
        and getattr(validation_summary, "valid", False)
        and coverage_ready
        and not blockers
        and (plan.target.end_date - plan.target.start_date).days >= 730
        and {"A", "H"}.issubset(
            {_target_market(plan.target, item) for item in plan.target.listing_ids}
        )
    )
    if production_eligible:
        readiness = ReadinessLevel.PRODUCTION_ELIGIBLE
    elif personal_ready:
        readiness = ReadinessLevel.PERSONAL_RESEARCH_READY
    elif acquisition_ready:
        readiness = ReadinessLevel.ACQUISITION_READY
    else:
        readiness = ReadinessLevel.NOT_READY
    report_id = "readiness-" + hashlib.sha256(plan.content_sha256.encode()).hexdigest()[:32]
    return AcquisitionReadinessReportV1.build(
        report_id=report_id,
        plan_id=plan.plan_id,
        generated_at=_utc_now(clock),
        network_used=network_used,
        readiness=readiness,
        acquisition_ready=acquisition_ready,
        personal_research_ready=personal_ready,
        production_eligible=production_eligible,
        probe_reports=list(probe_reports),
        batch_ids=[batch.batch_id] if batch is not None else [],
        compiled_dataset_id=compiled_id,
        blockers=sorted(set(blockers)),
        warnings=sorted(set(warnings)),
    )


def _readiness_scope_source_kinds(kind: HistoricalSourceKind) -> set[HistoricalSourceKind]:
    if kind is HistoricalSourceKind.LISTING_LIFECYCLE:
        return {HistoricalSourceKind.LISTING_LIFECYCLE, HistoricalSourceKind.DELISTINGS}
    return {kind}


def _target_market(target: HistoricalTargetScope, listing_id: str) -> str:
    """Resolve A/H from the target's listing IDs without guessing identifiers."""

    # A target may optionally provide a market selector in calendar_ids.  The
    # acquisition contract intentionally refuses to infer market from a code;
    # absent an explicit selector this remains unknown and fail-closed.
    market = target.listing_markets.get(listing_id)
    if market is not None:
        return market.value
    marker = target.calendar_ids.get(listing_id, "")
    if marker.startswith("A:"):
        return "A"
    if marker.startswith("H:"):
        return "H"
    return "UNKNOWN"


def _probe_covers_target(
    report: SourceProbeReportV1,
    target: HistoricalTargetScope,
) -> bool:
    """Require a successful, dated probe to cover every target listing."""

    return (
        report.status == ProbeStatus.PASS
        and report.historical_capable
        and set(target.listing_ids).issubset(set(report.observed_listing_ids))
        and report.observed_start is not None
        and report.observed_end is not None
        and report.observed_start <= target.start_date
        and report.observed_end >= target.end_date
    )


def _probe_has_h_scope(
    report: SourceProbeReportV1,
    listing_ids: set[str],
    target: HistoricalTargetScope,
) -> bool:
    """Require a successful, dated probe to cover every requested H listing."""

    return (
        report.status == ProbeStatus.PASS
        and not report.blockers
        and report.account_entitlement == AccountEntitlement.CONFIRMED
        and report.historical_capable
        and report.license_evidence_uri is not None
        and report.license_evidence_sha256 is not None
        and listing_ids.issubset(set(report.observed_listing_ids))
        and report.observed_start is not None
        and report.observed_end is not None
        and report.observed_start <= target.start_date
        and report.observed_end >= target.end_date
    )


def _probe_has_target_observation(
    report: SourceProbeReportV1,
    target: HistoricalTargetScope,
) -> bool:
    """Require at least one dated in-target observation for a coverage claim."""

    return (
        report.status == ProbeStatus.PASS
        and bool(set(report.observed_listing_ids).intersection(target.listing_ids))
        and report.observed_start is not None
        and report.observed_end is not None
        and report.observed_start <= target.end_date
        and report.observed_end >= target.start_date
    )


__all__ = [
    "ACQUISITION_CONTRACT_VERSION",
    "AccountEntitlement",
    "AcquisitionError",
    "AcquisitionReadinessReportV1",
    "AcquisitionResult",
    "CanonicalJsonDecoder",
    "ConfiguredHttpSourceAdapter",
    "CoverageEvidenceStatus",
    "CredentialKind",
    "CredentialReferenceV1",
    "CredentialResolver",
    "CredentialUnavailableError",
    "EnvironmentCredentialResolver",
    "HistoricalAcquisitionPlanV1",
    "HistoricalAcquisitionRequestV1",
    "HistoricalAcquisitionService",
    "HistoricalIngestionCompiler",
    "HistoricalIngestionError",
    "HistoricalRawDecoder",
    "HistoricalSourceAdapter",
    "HistoricalSourceSchemaError",
    "HistoricalSourceSpecV1",
    "HithinkDailyKParquetDecoder",
    "HithinkAdjustmentFactorParquetDecoder",
    "HithinkMarketDumpAdapter",
    "OfficialFilingDocumentAdapter",
    "MappingCredentialResolver",
    "NetworkDisabledError",
    "NetworkMode",
    "NetworkResponse",
    "NetworkTransport",
    "NetworkTransportError",
    "ProbeStatus",
    "RawAcquisitionBatchManifestV1",
    "RawArtifactReceiptV1",
    "RawBlobError",
    "RawBlobStore",
    "ReadinessLevel",
    "RawSourceAggregateV1",
    "ResilientNetworkTransport",
    "SourceProbeReportV1",
    "StoragePolicy",
    "UrllibNetworkTransport",
    "build_readiness_report",
    "default_decoders",
    "default_source_adapters",
]
