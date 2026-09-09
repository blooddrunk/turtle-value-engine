"""Small interfaces for structured provider adapters and normalization."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

from turtle_value_engine.models import Company, NormalizedCompanyInput

from .errors import (
    ProviderCapabilityError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
)
from .models import (
    DataCategory,
    ProviderCapabilities,
    ProviderIdentity,
    ProviderRequest,
    RawProviderRecord,
)


class StructuredDataProvider(ABC):
    """Base contract for an adapter that acquires opaque structured records.

    Implementations provide only ``fetch_raw``.  They do not calculate CDC,
    net cash, Through Return, valuation or gates.  The base class performs the
    capability and response-identity checks common to every provider.
    """

    @property
    @abstractmethod
    def identity(self) -> ProviderIdentity:
        """Return the stable provider and source version metadata."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return the categories this adapter can acquire."""

    @abstractmethod
    def fetch_raw(self, request: ProviderRequest) -> RawProviderRecord:
        """Acquire one raw record; no normalization or financial math belongs here."""

    def fetch(self, request: ProviderRequest) -> RawProviderRecord:
        """Validate a request boundary and return one provider record."""

        if not isinstance(request, ProviderRequest):
            raise TypeError("request must be a ProviderRequest")
        if not self.capabilities.supports(request.category):
            categories = ", ".join(self.capabilities.as_values()) or "none"
            raise ProviderCapabilityError(
                f"provider {self.identity.provider_id!r} does not support "
                f"{request.category.value!r}; advertised categories: {categories}",
                provider=self.identity,
                request=request,
            )
        try:
            record = self.fetch_raw(request)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderRequestError(
                f"provider {self.identity.provider_id!r} failed to fetch "
                f"{request.category.value!r} for {request.entity_id!r}",
                provider=self.identity,
                request=request,
            ) from exc

        if not isinstance(record, RawProviderRecord):
            raise ProviderResponseError(
                "provider returned something other than RawProviderRecord",
                provider=self.identity,
                request=request,
            )
        if record.provider != self.identity or record.request != request:
            raise ProviderResponseError(
                "provider response identity does not match the request boundary",
                provider=self.identity,
                request=request,
            )
        return record

    def fetch_category(
        self,
        category: DataCategory | str,
        entity_id: str,
        parameters: Mapping[str, object] | None = None,
    ) -> RawProviderRecord:
        """Convenience entry point for independently fetching one category."""

        return self.fetch(
            ProviderRequest(
                category=category,
                entity_id=entity_id,
                parameters={} if parameters is None else parameters,
            )
        )


class StructuredDataNormalizer(Protocol):
    """Normalization boundary returning the existing input model.

    A concrete normalizer maps provider-specific raw payloads to canonical
    ``Fact``/``Evidence`` objects and ``DataQuality`` inside
    ``NormalizedCompanyInput``.  This intentionally introduces no second
    analysis model and is not implemented by the provider foundation.
    """

    def normalize(
        self,
        records: Sequence[RawProviderRecord],
        *,
        analysis_id: str,
        as_of: date,
        profile_id: str,
        company: Company,
    ) -> NormalizedCompanyInput:
        """Map raw records into the frozen normalized-input contract."""

        ...
