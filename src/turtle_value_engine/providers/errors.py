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


class CacheError(RuntimeError):
    """Base error for local raw-response cache operations."""


class CacheMissError(CacheError):
    """Raised when an explicitly requested offline replay is unavailable."""


class CacheCorruptionError(CacheError):
    """Raised when a cache file is not a valid complete current envelope."""


class CacheWriteError(CacheError):
    """Raised when an atomic cache write cannot be committed."""
