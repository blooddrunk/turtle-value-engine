"""Provider-neutral structured-data and raw-response cache foundations."""

from .base import StructuredDataNormalizer, StructuredDataProvider
from .cache import (
    CacheKey,
    FilesystemRawResponseCache,
    ProviderFetchResult,
    RawResponseCache,
    deterministic_cache_key,
    fetch_with_cache,
)
from .errors import (
    CacheCorruptionError,
    CacheError,
    CacheMissError,
    CacheWriteError,
    ProviderCapabilityError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
)
from .models import (
    DataCategory,
    JSONScalar,
    JSONValue,
    ProviderCapabilities,
    ProviderIdentity,
    ProviderRequest,
    RawProviderRecord,
    RetrievalMode,
    canonical_json_bytes,
)
from .normalization import deterministic_id

__all__ = [
    "CacheCorruptionError",
    "CacheError",
    "CacheKey",
    "CacheMissError",
    "CacheWriteError",
    "DataCategory",
    "FilesystemRawResponseCache",
    "JSONScalar",
    "JSONValue",
    "ProviderCapabilities",
    "ProviderCapabilityError",
    "ProviderError",
    "ProviderFetchResult",
    "ProviderIdentity",
    "ProviderRequest",
    "ProviderRequestError",
    "ProviderResponseError",
    "RawProviderRecord",
    "RawResponseCache",
    "RetrievalMode",
    "StructuredDataNormalizer",
    "StructuredDataProvider",
    "canonical_json_bytes",
    "deterministic_cache_key",
    "deterministic_id",
    "fetch_with_cache",
]
