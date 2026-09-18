"""Optional S3-compatible transport for the historical artifact mirror.

The S3 adapter is deliberately narrower than a general object-store client. It
only addresses explicit mirror keys and keeps the local
``HistoricalArtifactStore`` as the authoritative deterministic CAS. The SDK is
loaded lazily so offline users and tests do not need a cloud dependency.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .acquisition import (
    CredentialReferenceV1,
    CredentialResolver,
    CredentialUnavailableError,
    EnvironmentCredentialResolver,
    NetworkDisabledError,
)
from .contracts import _validate_mirror_object_key
from .mirror import (
    ArtifactObjectConflictError,
    ArtifactObjectMetadata,
    ArtifactObjectMissingError,
    ArtifactObjectSecurityError,
    HistoricalArtifactMirrorError,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_MISSING_ERROR_CODES = {
    "404",
    "notfound",
    "nosuchkey",
    "nosuchobject",
}
_BUCKET_MISSING_ERROR_CODES = {"nosuchbucket"}
_PERMISSION_ERROR_CODES = {
    "401",
    "403",
    "accessdenied",
    "accountproblem",
    "allaccessdisabled",
    "authorizationheadermalformed",
    "expiredtoken",
    "forbidden",
    "invalidaccesskeyid",
    "invalidtoken",
    "signaturedoesnotmatch",
    "unauthorized",
}
_PRECONDITION_ERROR_CODES = {
    "409",
    "412",
    "conditionalrequestconflict",
    "preconditionfailed",
}


class ArtifactObjectConfigurationError(ArtifactObjectSecurityError):
    """Raised when remote backend configuration is unsafe or incomplete."""


class ArtifactObjectRemoteError(HistoricalArtifactMirrorError):
    """Base class for sanitized S3-compatible transport failures."""


class ArtifactObjectPermissionError(ArtifactObjectRemoteError):
    """Raised when the remote service rejects authorization or permission."""


class ArtifactObjectTransportError(ArtifactObjectRemoteError):
    """Raised for remote transport and service failures other than missing data."""


class _RawS3CallError(Exception):
    """Internal wrapper that keeps a provider exception out of public messages."""

    def __init__(self, operation: str, original: Exception) -> None:
        super().__init__(operation)
        self.operation = operation
        self.original = original


@dataclass(frozen=True, slots=True, repr=False)
class _ResolvedCredentials:
    access_key_id: str | None
    secret_access_key: str | None
    session_token: str | None


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip("[]").lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _safe_endpoint_url(value: str) -> str:
    if value != value.strip() or not value:
        raise ValueError("S3 endpoint URL must be a non-empty URL without surrounding whitespace")
    try:
        parsed = urlparse(value)
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError("S3 endpoint URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("S3 endpoint URL must use http or https and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("S3 endpoint URL must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise ValueError("S3 endpoint URL must not contain query or fragment data")
    normalized_path = parsed.path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            normalized_path,
            "",
            "",
            "",
        )
    )


class S3CompatibleArtifactStoreConfig(BaseModel):
    """Non-secret runtime configuration for one S3-compatible bucket."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    contract: Literal["s3_compatible_artifact_store_config_v1"] = (
        "s3_compatible_artifact_store_config_v1"
    )
    endpoint_url: StrictStr = Field(min_length=1)
    bucket: StrictStr = Field(min_length=1)
    region: StrictStr = Field(default="auto", min_length=1)
    key_prefix: StrictStr = ""
    addressing_style: Literal["auto", "virtual", "path"] = "auto"
    access_key_ref: CredentialReferenceV1 | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "access_key_ref",
            "access_key",
            "access_key_credential_ref",
            "access_key_credential",
        ),
    )
    secret_key_ref: CredentialReferenceV1 | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "secret_key_ref",
            "secret_key",
            "secret_key_credential_ref",
            "secret_key_credential",
        ),
    )
    session_token_ref: CredentialReferenceV1 | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "session_token_ref",
            "session_token",
            "session_token_credential_ref",
            "session_token_credential",
        ),
    )
    allow_insecure_local_endpoint: StrictBool = False

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, value: str) -> str:
        return _safe_endpoint_url(value)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        if value != value.strip() or any(character.isspace() for character in value):
            raise ValueError("S3 bucket must not contain whitespace")
        if "/" in value or "\\" in value or any(ord(character) < 32 for character in value):
            raise ValueError("S3 bucket must be a single safe name")
        return value

    @field_validator("key_prefix")
    @classmethod
    def validate_key_prefix(cls, value: str) -> str:
        if not value:
            return ""
        if value.startswith("/") or "\\" in value:
            raise ValueError("S3 key prefix must be a relative POSIX path")
        normalized = value.rstrip("/")
        if not normalized:
            raise ValueError("S3 key prefix must not be only separators")
        try:
            return _validate_mirror_object_key(normalized)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid S3 key prefix: {exc}") from exc

    @model_validator(mode="after")
    def validate_security(self) -> S3CompatibleArtifactStoreConfig:
        parsed = urlparse(self.endpoint_url)
        if parsed.scheme == "http":
            if not self.allow_insecure_local_endpoint or not _is_loopback_host(
                parsed.hostname or ""
            ):
                raise ValueError(
                    "non-loopback S3 endpoints must use HTTPS; explicitly configured local "
                    "loopback endpoints may use HTTP"
                )
        return self


def _config_from_input(
    config: S3CompatibleArtifactStoreConfig | Mapping[str, object],
) -> S3CompatibleArtifactStoreConfig:
    if isinstance(config, S3CompatibleArtifactStoreConfig):
        return config
    try:
        return S3CompatibleArtifactStoreConfig.model_validate(config)
    except (TypeError, ValueError, ValidationError):
        # Do not expose Pydantic's input_value rendering: an operator may have
        # accidentally placed a secret in a rejected config file.
        raise ArtifactObjectConfigurationError(
            "invalid S3-compatible artifact-store configuration"
        ) from None


def _response_details(exc: Exception) -> tuple[str | None, int | None]:
    """Extract only bounded, non-secret error identifiers from SDK errors."""

    response = getattr(exc, "response", None)
    error: Mapping[str, object] = {}
    metadata: Mapping[str, object] = {}
    if isinstance(response, Mapping):
        raw_error = response.get("Error")
        raw_metadata = response.get("ResponseMetadata")
        if isinstance(raw_error, Mapping):
            error = raw_error
        if isinstance(raw_metadata, Mapping):
            metadata = raw_metadata
    raw_code: object = error.get("Code") or getattr(exc, "code", None)
    if raw_code is None:
        raw_code = getattr(exc, "error_code", None)
    code = str(raw_code) if raw_code is not None else None
    if code is not None and not _SAFE_ERROR_CODE_PATTERN.fullmatch(code):
        code = "remote_error"
    raw_status: object = metadata.get("HTTPStatusCode")
    if raw_status is None:
        raw_status = getattr(exc, "status_code", None)
    if raw_status is None:
        raw_status = getattr(exc, "status", None)
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None
    if status is not None and not 100 <= status <= 599:
        status = None
    return code, status


def _error_class(code: str | None, status: int | None) -> str:
    normalized_code = (code or "").lower()
    if normalized_code in _PERMISSION_ERROR_CODES or status in {401, 403}:
        return "permission"
    if normalized_code in _PRECONDITION_ERROR_CODES or status in {409, 412}:
        return "precondition"
    if normalized_code in _MISSING_ERROR_CODES or (
        status == 404 and normalized_code not in _BUCKET_MISSING_ERROR_CODES
    ):
        return "missing"
    return "transport"


def _failure_message(operation: str, code: str | None, status: int | None) -> str:
    suffix: list[str] = []
    if code is not None:
        suffix.append(f"code={code}")
    if status is not None:
        suffix.append(f"status={status}")
    detail = f" ({', '.join(suffix)})" if suffix else ""
    return f"remote S3-compatible {operation} failed{detail}"


class S3CompatibleArtifactObjectStore:
    """Immutable exact-byte ``ArtifactObjectStore`` over an S3-style client.

    ``client`` is an injected SDK-compatible object for tests and controlled
    runners. When omitted, boto3 is imported only after network authorization
    and credential resolution succeed.
    """

    def __init__(
        self,
        config: S3CompatibleArtifactStoreConfig | Mapping[str, object] | None = None,
        *,
        endpoint_url: str | None = None,
        bucket: str | None = None,
        region: str = "auto",
        key_prefix: str = "",
        addressing_style: Literal["auto", "virtual", "path"] = "auto",
        access_key_ref: CredentialReferenceV1 | None = None,
        secret_key_ref: CredentialReferenceV1 | None = None,
        session_token_ref: CredentialReferenceV1 | None = None,
        allow_insecure_local_endpoint: bool = False,
        client: Any | None = None,
        credentials: CredentialResolver | None = None,
        network_allowed: bool = False,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if client is not None and client_factory is not None:
            raise ArtifactObjectConfigurationError(
                "provide either an injected S3 client or a client factory, not both"
            )
        if config is None:
            if endpoint_url is None or bucket is None:
                raise ArtifactObjectConfigurationError(
                    "S3-compatible backend requires endpoint_url and bucket"
                )
            config = {
                "endpoint_url": endpoint_url,
                "bucket": bucket,
                "region": region,
                "key_prefix": key_prefix,
                "addressing_style": addressing_style,
                "access_key_ref": access_key_ref,
                "secret_key_ref": secret_key_ref,
                "session_token_ref": session_token_ref,
                "allow_insecure_local_endpoint": allow_insecure_local_endpoint,
            }
        elif endpoint_url is not None or bucket is not None:
            raise ArtifactObjectConfigurationError(
                "do not combine a typed S3 configuration with direct endpoint arguments"
            )
        self.config = _config_from_input(config)
        self._client = client
        self._client_factory = client_factory
        self._credentials = (
            EnvironmentCredentialResolver() if credentials is None else credentials
        )
        self._network_allowed = network_allowed
        self._resolved_credentials: _ResolvedCredentials | None = None
        self._prepared = False

    @property
    def client(self) -> Any | None:
        """Return the injected/lazily-created client for controlled inspection."""

        return self._client

    def put_if_absent(self, key: str, content: bytes) -> ArtifactObjectMetadata:
        safe_key = self._safe_key(key)
        if not isinstance(content, bytes):
            raise TypeError("mirror object content must be bytes")
        expected_hash = hashlib.sha256(content).hexdigest()
        remote_key = self._remote_key(safe_key)

        existing = self._head_or_missing(safe_key, remote_key)
        if existing is not None:
            existing_bytes = self._get_remote_bytes(safe_key, remote_key)
            if existing_bytes != content:
                raise ArtifactObjectConflictError(
                    f"mirror object contains conflicting content: {safe_key}"
                )
            return ArtifactObjectMetadata(safe_key, len(existing_bytes), expected_hash)

        try:
            self._call_raw(
                "put_object",
                Bucket=self.config.bucket,
                Key=remote_key,
                Body=content,
                Metadata={"tve-sha256": expected_hash},
                IfNoneMatch="*",
            )
        except _RawS3CallError as failure:
            code, status = _response_details(failure.original)
            if _error_class(code, status) == "precondition":
                # Another writer won the conditional create. Read the winner
                # and preserve immutable/idempotent semantics without trusting
                # ETag or assuming the winner's metadata is present.
                winner = self._get_remote_bytes(safe_key, remote_key)
                if winner != content:
                    raise ArtifactObjectConflictError(
                        f"mirror object contains conflicting content: {safe_key}"
                    ) from None
                return ArtifactObjectMetadata(safe_key, len(winner), expected_hash)
            raise self._normalize_failure("put_object", failure.original, code, status) from None
        return ArtifactObjectMetadata(safe_key, len(content), expected_hash)

    def get(self, key: str) -> bytes:
        safe_key = self._safe_key(key)
        return self._get_remote_bytes(safe_key, self._remote_key(safe_key))

    def stat(self, key: str) -> ArtifactObjectMetadata:
        safe_key = self._safe_key(key)
        remote_key = self._remote_key(safe_key)
        try:
            response = self._call_raw(
                "head_object",
                Bucket=self.config.bucket,
                Key=remote_key,
            )
        except _RawS3CallError as failure:
            code, status = _response_details(failure.original)
            if _error_class(code, status) == "missing":
                raise ArtifactObjectMissingError(
                    f"remote mirror object is missing: {safe_key}"
                ) from None
            raise self._normalize_failure("head_object", failure.original, code, status) from None

        byte_length = self._content_length(response)
        content_sha256 = self._metadata_sha256(response)
        return ArtifactObjectMetadata(
            key=safe_key,
            byte_length=byte_length,
            content_sha256=content_sha256,
        )

    def put_exact(self, key: str, content: bytes) -> ArtifactObjectMetadata:
        return self.put_if_absent(key, content)

    def read_exact(self, key: str) -> bytes:
        return self.get(key)

    def inspect(self, key: str) -> ArtifactObjectMetadata:
        return self.stat(key)

    def _safe_key(self, key: str) -> str:
        try:
            return _validate_mirror_object_key(key)
        except (TypeError, ValueError) as exc:
            raise ArtifactObjectSecurityError(str(exc)) from None

    def _remote_key(self, safe_key: str) -> str:
        if self.config.key_prefix:
            return f"{self.config.key_prefix}/{safe_key}"
        return safe_key

    def _prepare_remote(self) -> None:
        if self._prepared:
            return
        if self._network_allowed is not True:
            raise NetworkDisabledError(
                "network is denied; pass --network=allow for an explicit artifact mirror operation"
            )
        resolved = self._resolve_credentials()
        if self._client is None:
            if resolved.access_key_id is None or resolved.secret_access_key is None:
                raise CredentialUnavailableError(
                    "S3-compatible backend requires resolved access and secret credentials"
                )
            self._client = self._create_client(resolved)
        self._resolved_credentials = resolved
        self._prepared = True

    def _resolve_credentials(self) -> _ResolvedCredentials:
        access_ref = self.config.access_key_ref
        secret_ref = self.config.secret_key_ref
        if access_ref is None or secret_ref is None:
            raise CredentialUnavailableError(
                "S3-compatible backend requires access and secret credential references"
            )

        access = self._resolve_one(access_ref)
        secret = self._resolve_one(secret_ref)
        session = self._resolve_one(self.config.session_token_ref)
        if (access is None) != (secret is None):
            raise CredentialUnavailableError(
                "S3-compatible access and secret credentials must resolve together"
            )
        return _ResolvedCredentials(access, secret, session)

    def _resolve_one(self, reference: CredentialReferenceV1 | None) -> str | None:
        if reference is None or reference.kind == "NONE":
            return None
        try:
            value = self._credentials.resolve(reference)
        except Exception:
            raise CredentialUnavailableError(
                "credential resolver failed for reference: " + reference.reference_id
            ) from None
        if value is not None and not isinstance(value, str):
            raise CredentialUnavailableError(
                "credential resolver returned an invalid value for reference: "
                + reference.reference_id
            )
        if not value and reference.required:
            raise CredentialUnavailableError(
                "required credential is unavailable for reference: " + reference.reference_id
            )
        return value or None

    def _create_client(self, resolved: _ResolvedCredentials) -> Any:
        kwargs: dict[str, object] = {
            "service_name": "s3",
            "endpoint_url": self.config.endpoint_url,
            "region_name": self.config.region,
            "aws_access_key_id": resolved.access_key_id,
            "aws_secret_access_key": resolved.secret_access_key,
        }
        if resolved.session_token is not None:
            kwargs["aws_session_token"] = resolved.session_token
        if self._client_factory is not None:
            kwargs["addressing_style"] = self.config.addressing_style
            try:
                return self._client_factory(**kwargs)
            except Exception:
                raise ArtifactObjectRemoteError(
                    "unable to initialize the S3-compatible client"
                ) from None
        if self.config.addressing_style != "auto":
            try:
                from botocore.config import Config
            except ImportError:
                raise ArtifactObjectConfigurationError(
                    "the optional S3 SDK is unavailable"
                ) from None
            kwargs["config"] = Config(
                s3={"addressing_style": self.config.addressing_style}
            )
        try:
            import boto3
        except ImportError:
            raise ArtifactObjectConfigurationError(
                "the optional S3 SDK is unavailable; install the s3 extra"
            ) from None
        try:
            return boto3.client(**kwargs)
        except Exception:
            raise ArtifactObjectRemoteError(
                "unable to initialize the S3-compatible client"
            ) from None

    def _call_raw(self, operation: str, **kwargs: object) -> object:
        self._prepare_remote()
        try:
            method = getattr(self._client, operation)
            return method(**kwargs)
        except Exception as exc:
            raise _RawS3CallError(operation, exc) from None

    def _head_or_missing(self, safe_key: str, remote_key: str) -> object | None:
        try:
            return self._call_raw(
                "head_object",
                Bucket=self.config.bucket,
                Key=remote_key,
            )
        except _RawS3CallError as failure:
            code, status = _response_details(failure.original)
            if _error_class(code, status) == "missing":
                return None
            raise self._normalize_failure("head_object", failure.original, code, status) from None

    def _get_remote_bytes(self, safe_key: str, remote_key: str) -> bytes:
        try:
            response = self._call_raw(
                "get_object",
                Bucket=self.config.bucket,
                Key=remote_key,
            )
        except _RawS3CallError as failure:
            code, status = _response_details(failure.original)
            if _error_class(code, status) == "missing":
                raise ArtifactObjectMissingError(
                    f"remote mirror object is missing: {safe_key}"
                ) from None
            raise self._normalize_failure("get_object", failure.original, code, status) from None

        body = (
            response.get("Body")
            if isinstance(response, Mapping)
            else getattr(response, "Body", None)
        )
        if body is None:
            raise ArtifactObjectTransportError(
                "remote S3-compatible get_object response has no body"
            )
        try:
            content = body.read() if callable(getattr(body, "read", None)) else body
            if isinstance(content, bytearray):
                content = bytes(content)
            if not isinstance(content, bytes):
                raise TypeError
        except Exception:
            raise ArtifactObjectTransportError(
                "remote S3-compatible get_object response body is invalid"
            ) from None
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        if isinstance(response, Mapping) and response.get("ContentLength") is not None:
            try:
                declared_length = int(response["ContentLength"])
            except (TypeError, ValueError):
                raise ArtifactObjectTransportError(
                    "remote S3-compatible get_object response length is invalid"
                ) from None
            if declared_length != len(content):
                raise ArtifactObjectTransportError(
                    "remote S3-compatible get_object response length mismatches its body"
                )
        return content

    def _content_length(self, response: object) -> int:
        raw_length = response.get("ContentLength") if isinstance(response, Mapping) else None
        if raw_length is None:
            raw_length = getattr(response, "content_length", None)
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise ArtifactObjectTransportError(
                "remote S3-compatible head_object response has invalid content length"
            ) from None
        if length < 0:
            raise ArtifactObjectTransportError(
                "remote S3-compatible head_object response has invalid content length"
            )
        return length

    def _metadata_sha256(self, response: object) -> str | None:
        metadata = response.get("Metadata") if isinstance(response, Mapping) else None
        if not isinstance(metadata, Mapping):
            return None
        for raw_key, raw_value in metadata.items():
            if str(raw_key).lower() != "tve-sha256":
                continue
            candidate = str(raw_value).lower()
            return candidate if _SHA256_PATTERN.fullmatch(candidate) else None
        return None

    @staticmethod
    def _normalize_failure(
        operation: str,
        original: Exception,
        code: str | None,
        status: int | None,
    ) -> ArtifactObjectRemoteError:
        category = _error_class(code, status)
        if category == "permission":
            return ArtifactObjectPermissionError(
                f"remote S3-compatible permission denied during {operation}"
            )
        if category == "missing":
            return ArtifactObjectMissingError(
                f"remote S3-compatible object is missing during {operation}"
            )
        return ArtifactObjectTransportError(_failure_message(operation, code, status))


S3ArtifactObjectStore = S3CompatibleArtifactObjectStore
S3ArtifactStoreConfig = S3CompatibleArtifactStoreConfig
S3ArtifactObjectStoreConfig = S3CompatibleArtifactStoreConfig
S3CompatibleArtifactObjectStoreConfig = S3CompatibleArtifactStoreConfig


__all__ = [
    "ArtifactObjectConfigurationError",
    "ArtifactObjectPermissionError",
    "ArtifactObjectRemoteError",
    "ArtifactObjectTransportError",
    "S3ArtifactObjectStore",
    "S3ArtifactObjectStoreConfig",
    "S3ArtifactStoreConfig",
    "S3CompatibleArtifactObjectStore",
    "S3CompatibleArtifactObjectStoreConfig",
    "S3CompatibleArtifactStoreConfig",
]
