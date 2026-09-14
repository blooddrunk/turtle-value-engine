"""Provider-backed preparation for the frozen normalized-input contract.

Preparation owns canonical listing/as-of request handling, provider priority,
cache replay and normalization.  It ends at ``NormalizedCompanyInput``; the
calculation pipeline remains a separate offline boundary and is never called
from a provider adapter.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from typing import TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from turtle_value_engine.models import Company, NormalizedCompanyInput
from turtle_value_engine.providers.akshare import (
    AKShareNormalizer,
    normalize_listing_id,
)
from turtle_value_engine.providers.base import (
    StructuredDataNormalizer,
    StructuredDataProvider,
)
from turtle_value_engine.providers.cache import (
    ProviderFetchResult,
    RawResponseCache,
    fetch_with_cache,
)
from turtle_value_engine.providers.errors import CacheError, ProviderError
from turtle_value_engine.providers.models import (
    DataCategory,
    ProviderRequest,
    RawProviderRecord,
    RetrievalMode,
)
from turtle_value_engine.providers.normalization import deterministic_id

DEFAULT_PREPARATION_CATEGORIES: tuple[DataCategory, ...] = (
    DataCategory.COMPANY_METADATA,
    DataCategory.LISTING_METADATA,
    DataCategory.MARKET_QUOTE,
    DataCategory.CASH_FLOW_STATEMENT,
    DataCategory.INCOME_STATEMENT,
    DataCategory.BALANCE_SHEET,
)

# Provider statements usually report cash paid as a negative signed amount;
# the frozen CDC input contract uses positive outflow magnitudes.  This is a
# boundary normalization, not a change to CDC arithmetic or to the raw cache.
_SIGNED_CASH_OUTFLOW_FIELDS = frozenset(
    {
        "cash_interest_paid_total",
        "cash_interest_in_cfo",
        "cash_interest_outside_cfo",
        "ppe_purchase_cash",
        "intangible_purchase_cash",
        "other_operating_long_term_asset_cash",
        "lease_principal_outside_cfo",
        "capitalized_development_cash_outside_capex",
        "acquisition_cash",
        "strategic_investment_cash",
    }
)

_DATE_TOKEN_RE = re.compile(r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{8})(?!\d)")
_POINT_IN_TIME_KEYS = frozenset(
    {
        "announcement_date",
        "date",
        "end_date",
        "observation_date",
        "observation_end_datetime",
        "observation_start_datetime",
        "publication_date",
        "published_at",
        "published_date",
        "report_date",
        "report_period",
        "requested_date",
        "start_date",
        "statement_date",
    }
)


class PreparationError(ValueError):
    """Base error for the provider-to-normalized-input boundary."""


class PreparationAcquisitionError(PreparationError):
    """Raised when one required provider/cache request cannot be completed."""


class PreparationNormalizationError(PreparationError):
    """Raised when raw acquisition cannot produce the frozen input contract."""


class AcquisitionRequest(BaseModel):
    """Stable preparation request independent of any provider's field names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    listing_id: str = Field(min_length=1)
    as_of: date
    provider: str = Field(default="akshare", min_length=1)
    provider_priority: tuple[str, ...] = Field(default_factory=tuple)
    provider_by_category: dict[str, str] = Field(default_factory=dict)
    categories: tuple[DataCategory, ...] = DEFAULT_PREPARATION_CATEGORIES
    category_parameters: dict[str, dict[str, object]] = Field(default_factory=dict)
    analysis_id: str | None = Field(default=None, min_length=1)
    profile_id: str = Field(default="strict-v1", min_length=1)
    company: Company | None = None

    @field_validator("listing_id", mode="before")
    @classmethod
    def canonicalize_listing_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("listing_id must be a string")
        try:
            return normalize_listing_id(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid A/H listing_id: {value!r}") from exc

    @field_validator("provider", "profile_id")
    @classmethod
    def non_blank_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider/profile_id must not be blank")
        return normalized

    @field_validator("provider_priority")
    @classmethod
    def unique_provider_priority(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("provider_priority entries must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("provider_priority must not contain duplicates")
        return value

    @field_validator("categories")
    @classmethod
    def unique_categories(cls, value: tuple[DataCategory, ...]) -> tuple[DataCategory, ...]:
        if not value:
            raise ValueError("at least one preparation category is required")
        if len(value) != len(set(value)):
            raise ValueError("preparation categories must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_category_configuration(self) -> AcquisitionRequest:
        known_categories = {category.value for category in self.categories}
        unknown_parameters = sorted(set(self.category_parameters) - known_categories)
        if unknown_parameters:
            raise ValueError(
                "category_parameters contains categories not selected for acquisition: "
                + ", ".join(unknown_parameters)
            )
        unknown_providers = sorted(set(self.provider_by_category) - known_categories)
        if unknown_providers:
            raise ValueError(
                "provider_by_category contains categories not selected for acquisition: "
                + ", ".join(unknown_providers)
            )
        if self.company is not None and self.company.primary_listing != self.listing_id:
            raise ValueError("company.primary_listing must match the canonical listing_id")
        return self

    @property
    def resolved_analysis_id(self) -> str:
        """Return a deterministic analysis identity when the caller omitted one."""

        return self.analysis_id or deterministic_id(
            "analysis",
            self.provider,
            self.listing_id,
            self.as_of.isoformat(),
            self.profile_id,
        )


@dataclass(frozen=True, slots=True)
class AcquisitionFetch:
    """One cache-aware category fetch and its replay mode."""

    request: ProviderRequest
    provider_id: str
    record: RawProviderRecord
    mode: RetrievalMode


@dataclass(frozen=True, slots=True)
class AcquisitionBundle:
    """All opaque records used to build one normalized input."""

    request: AcquisitionRequest
    fetches: tuple[AcquisitionFetch, ...]

    @property
    def records(self) -> tuple[RawProviderRecord, ...]:
        return tuple(fetch.record for fetch in self.fetches)

    @property
    def retrieval_modes(self) -> tuple[RetrievalMode, ...]:
        return tuple(fetch.mode for fetch in self.fetches)

    @property
    def replayable(self) -> bool:
        return all(mode is not RetrievalMode.LIVE for mode in self.retrieval_modes)

    def by_category(self, category: DataCategory | str) -> RawProviderRecord:
        """Return the one acquired record for a selected category."""

        normalized = DataCategory(category)
        matches = [fetch.record for fetch in self.fetches if fetch.request.category is normalized]
        if len(matches) != 1:
            raise PreparationError(
                f"expected exactly one acquired record for {normalized.value!r}, "
                f"found {len(matches)}"
            )
        return matches[0]


ProviderCollection: TypeAlias = StructuredDataProvider | Mapping[str, StructuredDataProvider]
CompanyResolver: TypeAlias = Callable[[AcquisitionBundle], Company]


def _provider_mapping(
    provider: ProviderCollection,
) -> dict[str, StructuredDataProvider]:
    if isinstance(provider, Mapping):
        providers = dict(provider)
    else:
        providers = {provider.identity.provider_id: provider}
    if not providers:
        raise TypeError("at least one structured data provider is required")
    if any(not isinstance(key, str) or not key.strip() for key in providers):
        raise TypeError("provider mapping keys must be non-blank strings")
    if any(not isinstance(value, StructuredDataProvider) for value in providers.values()):
        raise TypeError("provider mapping values must be StructuredDataProvider instances")
    return providers


class NormalizedCompanyInputBuilder:
    """Orchestrate provider acquisition, cache replay and normalization."""

    def __init__(
        self,
        provider: ProviderCollection,
        cache: RawResponseCache,
        *,
        normalizer: StructuredDataNormalizer | None = None,
        company_resolver: CompanyResolver | None = None,
    ) -> None:
        # Runtime-checkable Protocols are intentionally avoided by the
        # repository's cache interface; validating the two required methods
        # keeps injected test doubles simple and explicit.
        if not callable(getattr(cache, "read", None)) or not callable(
            getattr(cache, "write", None)
        ):
            raise TypeError("cache must implement read() and write()")
        self._providers = _provider_mapping(provider)
        self._cache = cache
        self._normalizer = normalizer
        self._company_resolver = company_resolver

    def _select_provider(
        self,
        request: AcquisitionRequest,
        category: DataCategory,
    ) -> StructuredDataProvider:
        requested = request.provider_by_category.get(category.value, request.provider)
        candidate_ids = [requested, *request.provider_priority, *sorted(self._providers)]
        seen: set[str] = set()
        for provider_id in candidate_ids:
            if provider_id in seen:
                continue
            seen.add(provider_id)
            provider = self._providers.get(provider_id)
            if provider is not None and provider.capabilities.supports(category):
                return provider
        advertised = "; ".join(
            f"{provider_id}="
            f"{','.join(item.value for item in provider.capabilities.supported_categories)}"
            for provider_id, provider in sorted(self._providers.items())
        )
        raise PreparationAcquisitionError(
            f"no configured provider supports {category.value!r}; requested={requested!r}; "
            f"available={advertised or 'none'}"
        )

    @staticmethod
    def _validate_as_of(record: RawProviderRecord, as_of: date) -> None:
        retrieved_date = record.retrieved_at.astimezone(UTC).date()
        if retrieved_date > as_of:
            raise PreparationAcquisitionError(
                f"provider record for {record.request.category.value!r} was retrieved on "
                f"{retrieved_date.isoformat()}, after as_of {as_of.isoformat()}"
            )
        for source, values in (
            ("request parameters", record.request.parameters),
            ("response metadata", record.response_metadata),
        ):
            for key, value in values.items():
                if key not in _POINT_IN_TIME_KEYS:
                    continue
                observed_date = _date_token(value)
                if observed_date is not None and observed_date > as_of:
                    raise PreparationAcquisitionError(
                        f"{source} {key!r}={value!r} for "
                        f"{record.request.category.value!r} is after "
                        f"as_of {as_of.isoformat()}"
                    )

    def acquire(
        self,
        request: AcquisitionRequest,
        *,
        offline: bool = False,
        max_age: timedelta | None = None,
        allow_stale: bool = False,
    ) -> AcquisitionBundle:
        """Acquire all selected categories through the existing raw cache."""

        if not isinstance(request, AcquisitionRequest):
            raise TypeError("request must be an AcquisitionRequest")
        fetches: list[AcquisitionFetch] = []
        for category in request.categories:
            provider = self._select_provider(request, category)
            parameters = request.category_parameters.get(category.value, {})
            try:
                provider_request = ProviderRequest(
                    category=category,
                    entity_id=request.listing_id,
                    parameters=parameters,
                )
                result: ProviderFetchResult = fetch_with_cache(
                    provider,
                    provider_request,
                    self._cache,
                    offline=offline,
                    max_age=max_age,
                    allow_stale=allow_stale,
                )
            except (ProviderError, CacheError, OSError, TypeError, ValueError) as exc:
                raise PreparationAcquisitionError(
                    f"cannot acquire {category.value!r} for {request.listing_id}: {exc}"
                ) from exc
            self._validate_as_of(result.record, request.as_of)
            fetches.append(
                AcquisitionFetch(
                    request=provider_request,
                    provider_id=provider.identity.provider_id,
                    record=result.record,
                    mode=result.mode,
                )
            )
        return AcquisitionBundle(request=request, fetches=tuple(fetches))

    def _resolve_company(
        self,
        bundle: AcquisitionBundle,
        company: Company | None,
    ) -> Company:
        resolved = company or bundle.request.company
        if resolved is None and self._company_resolver is not None:
            resolved = self._company_resolver(bundle)
        if resolved is None:
            raise PreparationNormalizationError(
                "company context is required: provide Company with explicit name, sector "
                "and reporting_currency (the preparation layer does not guess them)"
            )
        if not isinstance(resolved, Company):
            raise PreparationNormalizationError(
                "company resolver must return a validated Company"
            )
        if resolved.primary_listing != bundle.request.listing_id:
            raise PreparationNormalizationError(
                "company.primary_listing does not match the canonical acquisition listing"
            )
        return resolved

    def normalize(
        self,
        bundle: AcquisitionBundle,
        *,
        company: Company | None = None,
    ) -> NormalizedCompanyInput:
        """Normalize an acquired bundle without invoking deterministic analysis."""

        if not isinstance(bundle, AcquisitionBundle):
            raise TypeError("bundle must be an AcquisitionBundle")
        active_normalizer = self._normalizer
        if active_normalizer is None:
            provider_ids = {record.provider.provider_id.lower() for record in bundle.records}
            if provider_ids != {"akshare"}:
                raise PreparationNormalizationError(
                    "a non-AKShare acquisition requires an injected normalizer"
                )
            active_normalizer = AKShareNormalizer()
        active_company = self._resolve_company(bundle, company)
        try:
            normalized = active_normalizer.normalize(
                bundle.records,
                analysis_id=bundle.request.resolved_analysis_id,
                as_of=bundle.request.as_of,
                profile_id=bundle.request.profile_id,
                company=active_company,
            )
        except (ValidationError, ProviderError, ValueError, TypeError) as exc:
            raise PreparationNormalizationError(
                f"cannot normalize acquisition bundle for {bundle.request.listing_id}: {exc}"
            ) from exc
        if normalized.as_of != bundle.request.as_of:
            raise PreparationNormalizationError("normalizer changed the requested as_of date")
        if normalized.company.primary_listing != bundle.request.listing_id:
            raise PreparationNormalizationError(
                "normalizer returned a company for a different primary listing"
            )
        prepared = _canonicalize_preparation_values(normalized)
        _validate_normalized_fact_keys(prepared)
        _validate_normalized_point_in_time(prepared, bundle.request.as_of)
        return prepared

    def prepare(
        self,
        request: AcquisitionRequest,
        *,
        company: Company | None = None,
        offline: bool = False,
        max_age: timedelta | None = None,
        allow_stale: bool = False,
    ) -> tuple[AcquisitionBundle, NormalizedCompanyInput]:
        """Acquire and normalize one request; calculations remain caller-owned."""

        bundle = self.acquire(
            request,
            offline=offline,
            max_age=max_age,
            allow_stale=allow_stale,
        )
        return bundle, self.normalize(bundle, company=company)

    # ``build`` is intentionally an alias: it reads naturally at callers that
    # already have a fetched bundle and keeps the contract name explicit.
    build = normalize


ProviderPreparationOrchestrator = NormalizedCompanyInputBuilder


def prepare_normalized_input(
    request: AcquisitionRequest,
    provider: ProviderCollection,
    cache: RawResponseCache,
    *,
    company: Company | None = None,
    normalizer: StructuredDataNormalizer | None = None,
    company_resolver: CompanyResolver | None = None,
    offline: bool = False,
    max_age: timedelta | None = None,
    allow_stale: bool = False,
) -> NormalizedCompanyInput:
    """Convenience API for the complete provider/cache/normalizer path."""

    builder = NormalizedCompanyInputBuilder(
        provider,
        cache,
        normalizer=normalizer,
        company_resolver=company_resolver,
    )
    _bundle, normalized = builder.prepare(
        request,
        company=company,
        offline=offline,
        max_age=max_age,
        allow_stale=allow_stale,
    )
    return normalized


__all__ = [
    "AcquisitionBundle",
    "AcquisitionFetch",
    "AcquisitionRequest",
    "DEFAULT_PREPARATION_CATEGORIES",
    "NormalizedCompanyInputBuilder",
    "PreparationAcquisitionError",
    "PreparationError",
    "PreparationNormalizationError",
    "ProviderPreparationOrchestrator",
    "prepare_normalized_input",
]


def _canonicalize_preparation_values(
    normalized: NormalizedCompanyInput,
) -> NormalizedCompanyInput:
    """Normalize signed provider-reported cash-paid lines to input magnitudes."""

    changed = False
    facts = []
    for fact in normalized.facts:
        if (
            fact.field in _SIGNED_CASH_OUTFLOW_FIELDS
            and isinstance(fact.value, (int, float))
            and not isinstance(fact.value, bool)
            and fact.value < 0
        ):
            payload = fact.model_dump(mode="python", warnings=False)
            payload["value"] = abs(fact.value)
            facts.append(type(fact).model_validate(payload))
            changed = True
        else:
            facts.append(fact)
    if not changed:
        return normalized
    flags = list(normalized.flags)
    if "PREPARATION_SIGN_NORMALIZED_CASH_OUTFLOW" not in flags:
        flags.append("PREPARATION_SIGN_NORMALIZED_CASH_OUTFLOW")
    payload = normalized.model_dump(mode="python", warnings=False)
    payload.update({"facts": facts, "flags": flags})
    return NormalizedCompanyInput.model_validate(payload)


def _date_token(value: object) -> date | None:
    """Parse a supported ISO or compact date token from provider metadata."""

    if not isinstance(value, str):
        return None
    match = _DATE_TOKEN_RE.search(value)
    if match is None:
        return None
    token = match.group(0)
    try:
        return date.fromisoformat(token) if "-" in token else date(
            int(token[:4]), int(token[4:6]), int(token[6:8])
        )
    except ValueError:
        return None


def _validate_normalized_fact_keys(normalized: NormalizedCompanyInput) -> None:
    """Reject duplicate field/period facts before they reach calculations."""

    seen: set[tuple[str, str]] = set()
    for fact in normalized.facts:
        key = (fact.field, fact.period)
        if key in seen:
            raise PreparationNormalizationError(
                f"normalized input contains duplicate fact {fact.field!r}/{fact.period!r}"
            )
        seen.add(key)


def _validate_normalized_point_in_time(
    normalized: NormalizedCompanyInput,
    as_of: date,
) -> None:
    """Reject future-dated normalized facts and explicit provider snapshots."""

    for fact in normalized.facts:
        fact_date = _date_token(fact.period)
        if fact_date is not None and fact_date > as_of:
            raise PreparationNormalizationError(
                f"normalized fact {fact.field!r}/{fact.period!r} is after "
                f"as_of {as_of.isoformat()}"
            )

    for evidence in normalized.evidence_index:
        published_date = evidence.source.published_date
        if published_date is not None and published_date > as_of:
            raise PreparationNormalizationError(
                f"evidence publication date {published_date.isoformat()} is after "
                f"as_of {as_of.isoformat()}"
            )
