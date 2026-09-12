"""Errors at the provider and raw-response cache boundaries."""

from .models import ProviderIdentity, ProviderRequest


class ProviderError(RuntimeError):
    """Base error for an isolated structured-data provider request."""

    def __init__(
        self,
        message: str,
        *,
        provider: ProviderIdentity | str | None = None,
        request: ProviderRequest | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.request = request
        self.retryable = retryable


class ProviderCapabilityError(ProviderError):
    """Raised when an adapter does not advertise a requested category."""


class ProviderRequestError(ProviderError):
    """Raised when a provider cannot complete a request."""


class ProviderResponseError(ProviderError):
    """Raised when an adapter returns an invalid or mismatched raw record."""


class ProviderNormalizationError(ValueError):
    """Raised when a provider payload cannot be mapped unambiguously."""


class CacheError(RuntimeError):
    """Base error for local raw-response cache operations."""


class CacheMissError(CacheError):
    """Raised when an explicitly requested offline replay is unavailable."""


class CacheCorruptionError(CacheError):
    """Raised when a cache file is not a valid complete current envelope."""


class CacheWriteError(CacheError):
    """Raised when an atomic cache write cannot be committed."""


class FilingDocumentError(ProviderError):
    """Base error for an isolated official filing document retrieval."""


class FilingDocumentRequestError(FilingDocumentError):
    """Raised when a document request or injected transport fails."""


class FilingDocumentResponseError(FilingDocumentError):
    """Raised when a document response violates the byte/provenance contract."""


class FilingExtractionError(ProviderError):
    """Base error for bounded official filing text extraction."""


class FilingExtractionRequestError(FilingExtractionError):
    """Raised when an extraction request or document is unsupported."""


class FilingExtractionResponseError(FilingExtractionError):
    """Raised when an injected parser returns malformed or mismatched text."""


class EvidenceStoreError(CacheError):
    """Base error for deterministic local filing-evidence storage."""


class EvidenceStoreMissError(EvidenceStoreError):
    """Raised when an explicitly requested evidence replay is unavailable."""


class EvidenceStoreCorruptionError(EvidenceStoreError):
    """Raised when a persisted evidence record fails integrity validation."""


class EvidenceStoreConflictError(EvidenceStoreError):
    """Raised when an evidence ID already represents different content."""


class EvidenceStoreRequestError(EvidenceStoreError):
    """Raised when an evidence request is outside the store contract."""


class EvidenceStoreWriteError(EvidenceStoreError):
    """Raised when an evidence record cannot be atomically persisted."""
