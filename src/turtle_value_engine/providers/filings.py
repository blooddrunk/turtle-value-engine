"""Injectable discovery of official A/H filing metadata.

This module deliberately stops at discovery.  A source client returns
metadata for official announcements or reports; it does not download a
document, parse its contents, create evidence, or propose an adjustment.
The provider turns that metadata into a replayable ``RawProviderRecord`` so
the existing cache remains the byte-level provenance boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from re import fullmatch
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .base import StructuredDataProvider
from .cache import ProviderFetchResult, RawResponseCache, fetch_with_cache
from .errors import (
    ProviderCapabilityError,
    ProviderError,
    ProviderNormalizationError,
    ProviderRequestError,
    ProviderResponseError,
)
from .models import (
    DataCategory,
    JSONValue,
    ProviderCapabilities,
    ProviderIdentity,
    ProviderRequest,
    RawProviderRecord,
)
from .normalization import deterministic_id

FILING_DISCOVERY_ADAPTER_VERSION = "filing-discovery-v1"
FILING_DISCOVERY_SOURCE_NAME = "Official filing sources"

_FILING_DISCOVERY_PROVIDER_ID = "official-filing-discovery"
_FILING_DISCOVERY_CONTRACT = "filing_discovery_v1"
_MAX_DISCOVERY_RESULTS = 100
_LISTING_ID_PATTERN = r"^(?:(?:SH|SZ|BJ)\d{6}|HK\d{5})$"
_FILINGS_ORDER = "published_date_desc,filing_id_asc"
_QUERY_PARAMETER_NAMES = frozenset(
    {
        "source",
        "published_from",
        "published_to",
        "document_type",
        "limit",
        "as_of",
    }
)


class FilingMarket(StrEnum):
    """Market derived from the engine's canonical listing identifier."""

    A = "A"
    H = "H"


class FilingSource(StrEnum):
    """Official source boundary allowed by the Phase 3 discovery contract."""

    CNINFO = "CNINFO"
    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    A_COMPANY_ANNOUNCEMENT = "A_COMPANY_ANNOUNCEMENT"
    HKEXNEWS = "HKEXNEWS"
    H_COMPANY_REPORT = "H_COMPANY_REPORT"
    H_COMPANY_ANNOUNCEMENT = "H_COMPANY_ANNOUNCEMENT"


_A_SOURCES = frozenset(
    {
        FilingSource.CNINFO,
        FilingSource.SSE,
        FilingSource.SZSE,
        FilingSource.BSE,
        FilingSource.A_COMPANY_ANNOUNCEMENT,
    }
)
_H_SOURCES = frozenset(
    {
        FilingSource.HKEXNEWS,
        FilingSource.H_COMPANY_REPORT,
        FilingSource.H_COMPANY_ANNOUNCEMENT,
    }
)
_COMPANY_SOURCES = frozenset(
    {
        FilingSource.A_COMPANY_ANNOUNCEMENT,
        FilingSource.H_COMPANY_REPORT,
        FilingSource.H_COMPANY_ANNOUNCEMENT,
    }
)
_EXCHANGE_PREFIXES = {
    FilingSource.SSE: "SH",
    FilingSource.SZSE: "SZ",
    FilingSource.BSE: "BJ",
}
_OFFICIAL_HOST_SUFFIXES = {
    FilingSource.CNINFO: ("cninfo.com.cn",),
    FilingSource.SSE: ("sse.com.cn",),
    FilingSource.SZSE: ("szse.cn",),
    FilingSource.BSE: ("bse.cn",),
    FilingSource.HKEXNEWS: ("hkexnews.hk",),
}


def _market_for_listing(listing_id: str) -> FilingMarket:
    if fullmatch(r"(?:SH|SZ|BJ)\d{6}", listing_id):
        return FilingMarket.A
    if fullmatch(r"HK\d{5}", listing_id):
        return FilingMarket.H
    raise ValueError(f"unsupported canonical listing id: {listing_id!r}")


def _source_allowed(market: FilingMarket, source: FilingSource) -> bool:
    return source in (_A_SOURCES if market is FilingMarket.A else _H_SOURCES)


def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(normalized == suffix or normalized.endswith(f".{suffix}") for suffix in suffixes)


def _canonical_http_url(value: AnyHttpUrl | str) -> str:
    """Normalize only URL identity details that cannot change document meaning."""

    parsed = urlsplit(str(value))
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("filing URL must have a host and must not contain userinfo")
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = hostname + port
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _validate_source_collection_url(source: FilingSource, value: str) -> str:
    canonical = _canonical_http_url(value)
    parsed = urlsplit(canonical)
    if source in _COMPANY_SOURCES:
        if parsed.scheme != "https":
            raise ValueError(f"{source.value} source URI must use HTTPS")
    else:
        suffixes = _OFFICIAL_HOST_SUFFIXES[source]
        if not _host_matches(parsed.hostname or "", suffixes):
            raise ValueError(f"{source.value} source URI must use an official host")
    return canonical


def _validate_document_url(source: FilingSource, value: AnyHttpUrl | str) -> str:
    canonical = _canonical_http_url(value)
    parsed = urlsplit(canonical)
    if source in _COMPANY_SOURCES:
        if parsed.scheme != "https":
            raise ValueError(f"{source.value} filing URL must use HTTPS")
    else:
        suffixes = _OFFICIAL_HOST_SUFFIXES[source]
        if not _host_matches(parsed.hostname or "", suffixes):
            raise ValueError(f"{source.value} filing URL must use an official host")
    return canonical


def filing_id_for(
    *,
    listing_id: str,
    market: FilingMarket,
    source: FilingSource,
    source_document_id: str | None,
    url: AnyHttpUrl | str,
) -> str:
    """Return a stable ID from source identity, never retrieval time or row position."""

    identity_kind = "source_document_id" if source_document_id else "url"
    identity_value = source_document_id if source_document_id else _canonical_http_url(url)
    return deterministic_id(
        "filing",
        market.value,
        listing_id,
        source.value,
        identity_kind,
        identity_value,
    )


class FilingDiscoveryQuery(BaseModel):
    """Strict, cache-keyed query for one listing and one official source."""

    model_config = ConfigDict(extra="forbid")

    listing_id: StrictStr = Field(pattern=_LISTING_ID_PATTERN)
    source: FilingSource
    published_from: date | None = None
    published_to: date | None = None
    document_type: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    limit: StrictInt = Field(default=50, ge=1, le=_MAX_DISCOVERY_RESULTS)
    as_of: date | None = None

    @field_validator("published_from", "published_to", "as_of", mode="before")
    @classmethod
    def _validate_date_input(cls, value: object) -> object:
        if value is None or isinstance(value, date) and not isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("date parameters must be ISO YYYY-MM-DD strings")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date parameters must be ISO YYYY-MM-DD strings") from exc

    @field_validator("document_type")
    @classmethod
    def _validate_document_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("document_type must not be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_scope(self) -> FilingDiscoveryQuery:
        market = _market_for_listing(self.listing_id)
        if not _source_allowed(market, self.source):
            raise ValueError(
                f"{self.source.value} is not an allowed source for {market.value}-share listings"
            )
        exchange_prefix = _EXCHANGE_PREFIXES.get(self.source)
        if exchange_prefix is not None and not self.listing_id.startswith(exchange_prefix):
            raise ValueError(
                f"{self.source.value} requires a {exchange_prefix}-prefixed A-share listing"
            )
        if self.published_from and self.published_to and self.published_from > self.published_to:
            raise ValueError("published_from must not be after published_to")
        if self.as_of and self.published_from and self.published_from > self.as_of:
            raise ValueError("published_from must not be after as_of")
        if self.as_of and self.published_to and self.published_to > self.as_of:
            raise ValueError("published_to must not be after as_of")
        return self

    @property
    def market(self) -> FilingMarket:
        """Return the market derived from ``listing_id``."""

        return _market_for_listing(self.listing_id)

    def as_parameters(self) -> dict[str, JSONValue]:
        """Return normalized request parameters used in replay metadata."""

        parameters: dict[str, JSONValue] = {
            "source": self.source.value,
            "limit": self.limit,
        }
        for name in ("published_from", "published_to", "document_type", "as_of"):
            value = getattr(self, name)
            if value is not None:
                parameters[name] = value.isoformat() if isinstance(value, date) else value
        return parameters

    def to_provider_request(self) -> ProviderRequest:
        """Build the generic request consumed by the cache-aware provider boundary."""

        return ProviderRequest(
            category=DataCategory.FILING_DISCOVERY,
            entity_id=self.listing_id,
            parameters=self.as_parameters(),
        )

    @classmethod
    def from_provider_request(cls, request: ProviderRequest) -> FilingDiscoveryQuery:
        """Parse one generic request and turn validation failures into provider errors."""

        if request.category is not DataCategory.FILING_DISCOVERY:
            raise ProviderCapabilityError(
                "filing discovery requires the filing_discovery category", request=request
            )
        unexpected = set(request.parameters) - _QUERY_PARAMETER_NAMES
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ProviderRequestError(
                f"filing discovery does not accept request parameters: {names}",
                request=request,
                retryable=False,
            )
        if "source" not in request.parameters:
            raise ProviderRequestError(
                "filing discovery requires a source parameter",
                request=request,
                retryable=False,
            )
        try:
            return cls(listing_id=request.entity_id, **dict(request.parameters))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProviderRequestError(
                f"invalid filing-discovery request: {exc}", request=request, retryable=False
            ) from exc


class FilingDescriptor(BaseModel):
    """Metadata returned by an injected source client before canonical ID binding."""

    model_config = ConfigDict(extra="forbid")

    title: StrictStr = Field(min_length=1, max_length=500)
    document_type: StrictStr = Field(min_length=1, max_length=128)
    published_date: date
    url: AnyHttpUrl
    source_document_id: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    report_period: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    issuer_name: StrictStr | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("title", "document_type", "source_document_id", "report_period", "issuer_name")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("filing metadata text must not be blank")
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("filing metadata text must not contain control characters")
        return normalized

    @field_validator("published_date", mode="before")
    @classmethod
    def _validate_published_date(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise ValueError("published_date must be an ISO YYYY-MM-DD date")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("published_date must be an ISO YYYY-MM-DD date") from exc


class FilingRecord(BaseModel):
    """One discovered official filing with deterministic provenance identity."""

    model_config = ConfigDict(extra="forbid")

    filing_id: StrictStr = Field(pattern=r"^filing-[0-9a-f]{24}$")
    listing_id: StrictStr = Field(pattern=_LISTING_ID_PATTERN)
    market: FilingMarket
    source: FilingSource
    title: StrictStr = Field(min_length=1, max_length=500)
    document_type: StrictStr = Field(min_length=1, max_length=128)
    published_date: date
    url: AnyHttpUrl
    source_document_id: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    report_period: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    issuer_name: StrictStr | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("title", "document_type", "source_document_id", "report_period", "issuer_name")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        return FilingDescriptor._normalize_text(value)

    @model_validator(mode="after")
    def _validate_identity(self) -> FilingRecord:
        expected_market = _market_for_listing(self.listing_id)
        if self.market is not expected_market:
            raise ValueError("filing market does not match listing_id")
        if not _source_allowed(self.market, self.source):
            raise ValueError("filing source is not allowed for listing market")
        exchange_prefix = _EXCHANGE_PREFIXES.get(self.source)
        if exchange_prefix is not None and not self.listing_id.startswith(exchange_prefix):
            raise ValueError("filing exchange source does not match listing prefix")
        _validate_document_url(self.source, self.url)
        expected_id = filing_id_for(
            listing_id=self.listing_id,
            market=self.market,
            source=self.source,
            source_document_id=self.source_document_id,
            url=self.url,
        )
        if self.filing_id != expected_id:
            raise ValueError("filing_id does not match deterministic source identity")
        return self


class FilingDiscoveryResult(BaseModel):
    """Canonical metadata-only payload stored in a raw cache record."""

    model_config = ConfigDict(extra="forbid")

    listing_id: StrictStr = Field(pattern=_LISTING_ID_PATTERN)
    market: FilingMarket
    source: FilingSource
    source_uri: AnyHttpUrl
    filings: list[FilingRecord] = Field(default_factory=list, max_length=_MAX_DISCOVERY_RESULTS)

    @model_validator(mode="after")
    def _validate_result(self) -> FilingDiscoveryResult:
        expected_market = _market_for_listing(self.listing_id)
        if self.market is not expected_market:
            raise ValueError("discovery market does not match listing_id")
        if not _source_allowed(self.market, self.source):
            raise ValueError("discovery source is not allowed for listing market")
        _validate_source_collection_url(self.source, str(self.source_uri))
        ids = [filing.filing_id for filing in self.filings]
        if len(ids) != len(set(ids)):
            raise ValueError("discovery result contains duplicate filing_id values")
        urls = [_canonical_http_url(filing.url) for filing in self.filings]
        if len(urls) != len(set(urls)):
            raise ValueError("discovery result contains duplicate filing URLs")
        if any(
            filing.listing_id != self.listing_id
            or filing.market is not self.market
            or filing.source is not self.source
            for filing in self.filings
        ):
            raise ValueError("discovery filing scope does not match result scope")
        expected_order = sorted(
            self.filings,
            key=lambda filing: (-filing.published_date.toordinal(), filing.filing_id),
        )
        if self.filings != expected_order:
            raise ValueError(f"discovery filings must use {_FILINGS_ORDER} ordering")
        return self


@dataclass(frozen=True, slots=True)
class FilingDiscoverySourceClient:
    """One deterministic/injectable official-source discovery implementation."""

    source: FilingSource
    source_uri: str
    discover: Callable[[FilingDiscoveryQuery], Iterable[FilingDescriptor | Mapping[str, object]]]

    def __post_init__(self) -> None:
        try:
            source = FilingSource(self.source)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported filing source: {self.source!r}") from exc
        object.__setattr__(self, "source", source)
        if not isinstance(self.source_uri, str) or not self.source_uri.strip():
            raise ValueError("source_uri must be a non-empty string")
        object.__setattr__(
            self,
            "source_uri",
            _validate_source_collection_url(source, self.source_uri),
        )
        if not callable(self.discover):
            raise TypeError("discover must be callable")


class OfficialFilingDiscoveryProvider(StructuredDataProvider):
    """Acquire official filing metadata through source clients supplied by the caller."""

    def __init__(
        self,
        clients: Mapping[FilingSource | str, FilingDiscoverySourceClient],
        *,
        provider_version: str = FILING_DISCOVERY_ADAPTER_VERSION,
        source_name: str = FILING_DISCOVERY_SOURCE_NAME,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        normalized: dict[FilingSource, FilingDiscoverySourceClient] = {}
        for source, client in clients.items():
            try:
                normalized_source = FilingSource(source)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unsupported filing source: {source!r}") from exc
            if not isinstance(client, FilingDiscoverySourceClient):
                raise TypeError("clients must contain FilingDiscoverySourceClient values")
            if client.source is not normalized_source:
                raise ValueError("client source does not match its mapping key")
            normalized[normalized_source] = client
        self._clients = normalized
        self._identity = ProviderIdentity(
            provider_id=_FILING_DISCOVERY_PROVIDER_ID,
            provider_version=provider_version,
            source_name=source_name,
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def identity(self) -> ProviderIdentity:
        """Return the stable provider identity used by the generic cache."""

        return self._identity

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Advertise only the one Phase 3 discovery category."""

        return ProviderCapabilities({DataCategory.FILING_DISCOVERY})

    def fetch_raw(self, request: ProviderRequest) -> RawProviderRecord:
        """Fetch, validate and serialize one metadata-only discovery result."""

        if not isinstance(request, ProviderRequest):
            raise TypeError("request must be a ProviderRequest")
        if request.category is not DataCategory.FILING_DISCOVERY:
            raise ProviderCapabilityError(
                "official filing discovery supports only filing_discovery",
                provider=self.identity,
                request=request,
            )
        query = FilingDiscoveryQuery.from_provider_request(request)
        client = self._clients.get(query.source)
        if client is None:
            raise ProviderRequestError(
                f"no injected filing source client configured for {query.source.value}",
                provider=self.identity,
                request=request,
                retryable=False,
            )
        try:
            discovered = client.discover(query)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderRequestError(
                f"official {query.source.value} filing discovery failed",
                provider=self.identity,
                request=request,
                retryable=False,
            ) from exc
        if isinstance(discovered, (str, bytes, bytearray, Mapping)):
            raise ProviderResponseError(
                "filing source client must return an iterable of filing metadata",
                provider=self.identity,
                request=request,
            )
        try:
            descriptors = [FilingDescriptor.model_validate(item) for item in discovered]
        except (TypeError, ValidationError) as exc:
            raise ProviderResponseError(
                f"invalid {query.source.value} filing discovery metadata: {exc}",
                provider=self.identity,
                request=request,
            ) from exc
        if len(descriptors) > query.limit:
            raise ProviderResponseError(
                "filing source returned "
                f"{len(descriptors)} rows over requested limit {query.limit}",
                provider=self.identity,
                request=request,
            )

        records: list[FilingRecord] = []
        try:
            for descriptor in descriptors:
                if query.published_from and descriptor.published_date < query.published_from:
                    raise ValueError("filing published_date is before published_from")
                if query.published_to and descriptor.published_date > query.published_to:
                    raise ValueError("filing published_date is after published_to")
                if query.as_of and descriptor.published_date > query.as_of:
                    raise ValueError("filing published_date is after as_of")
                if query.document_type and descriptor.document_type != query.document_type:
                    raise ValueError("filing document_type does not match requested document_type")
                _validate_document_url(query.source, descriptor.url)
                records.append(
                    FilingRecord(
                        filing_id=filing_id_for(
                            listing_id=query.listing_id,
                            market=query.market,
                            source=query.source,
                            source_document_id=descriptor.source_document_id,
                            url=descriptor.url,
                        ),
                        listing_id=query.listing_id,
                        market=query.market,
                        source=query.source,
                        title=descriptor.title,
                        document_type=descriptor.document_type,
                        published_date=descriptor.published_date,
                        url=_canonical_http_url(descriptor.url),
                        source_document_id=descriptor.source_document_id,
                        report_period=descriptor.report_period,
                        issuer_name=descriptor.issuer_name,
                    )
                )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProviderResponseError(
                f"invalid {query.source.value} filing discovery result: {exc}",
                provider=self.identity,
                request=request,
            ) from exc
        try:
            result = FilingDiscoveryResult(
                listing_id=query.listing_id,
                market=query.market,
                source=query.source,
                source_uri=client.source_uri,
                filings=sorted(
                    records,
                    key=lambda filing: (-filing.published_date.toordinal(), filing.filing_id),
                ),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProviderResponseError(
                f"invalid filing discovery result scope: {exc}",
                provider=self.identity,
                request=request,
            ) from exc
        filing_ids = [filing.filing_id for filing in result.filings]
        metadata: dict[str, JSONValue] = {
            "contract": _FILING_DISCOVERY_CONTRACT,
            "metadata_only": True,
            "download_performed": False,
            "listing_id": query.listing_id,
            "market": query.market.value,
            "source": query.source.value,
            "source_uri": client.source_uri,
            "query": query.as_parameters(),
            "ordering": _FILINGS_ORDER,
            "result_count": len(result.filings),
            "filing_ids": filing_ids,
            "source_document_ids": [
                filing.source_document_id
                for filing in result.filings
                if filing.source_document_id is not None
            ],
        }
        return RawProviderRecord(
            provider=self.identity,
            request=request,
            retrieved_at=self._clock(),
            raw_payload=result.model_dump(mode="json"),
            source_uri=client.source_uri,
            response_metadata=metadata,
        )


def parse_filing_discovery_record(record: RawProviderRecord) -> FilingDiscoveryResult:
    """Validate a live or replayed raw record before downstream filing use."""

    if not isinstance(record, RawProviderRecord):
        raise TypeError("record must be a RawProviderRecord")
    if record.request.category is not DataCategory.FILING_DISCOVERY:
        raise ProviderNormalizationError("record is not a filing-discovery response")
    if record.provider.provider_id != _FILING_DISCOVERY_PROVIDER_ID:
        raise ProviderNormalizationError("record provider is not official filing discovery")
    try:
        query = FilingDiscoveryQuery.from_provider_request(record.request)
        result = FilingDiscoveryResult.model_validate(record.raw_payload)
    except (ProviderError, TypeError, ValueError, ValidationError) as exc:
        raise ProviderNormalizationError(f"invalid filing-discovery record: {exc}") from exc
    if result.listing_id != query.listing_id:
        raise ProviderNormalizationError(
            "filing-discovery result listing_id does not match request"
        )
    if result.market is not query.market or result.source is not query.source:
        raise ProviderNormalizationError("filing-discovery result scope does not match request")
    if len(result.filings) > query.limit:
        raise ProviderNormalizationError("replayed filing result exceeds requested limit")
    if record.source_uri != str(result.source_uri):
        raise ProviderNormalizationError("filing-discovery source_uri does not match payload")
    for filing in result.filings:
        if query.published_from and filing.published_date < query.published_from:
            raise ProviderNormalizationError("replayed filing is before published_from")
        if query.published_to and filing.published_date > query.published_to:
            raise ProviderNormalizationError("replayed filing is after published_to")
        if query.as_of and filing.published_date > query.as_of:
            raise ProviderNormalizationError("replayed filing is after as_of")
        if query.document_type and filing.document_type != query.document_type:
            raise ProviderNormalizationError("replayed filing document_type does not match request")
    expected_metadata: dict[str, JSONValue] = {
        "contract": _FILING_DISCOVERY_CONTRACT,
        "metadata_only": True,
        "download_performed": False,
        "listing_id": query.listing_id,
        "market": query.market.value,
        "source": query.source.value,
        "source_uri": record.source_uri,
        "query": query.as_parameters(),
        "ordering": _FILINGS_ORDER,
        "result_count": len(result.filings),
        "filing_ids": [filing.filing_id for filing in result.filings],
        "source_document_ids": [
            filing.source_document_id
            for filing in result.filings
            if filing.source_document_id is not None
        ],
    }
    if dict(record.response_metadata) != expected_metadata:
        raise ProviderNormalizationError("filing-discovery replay metadata does not match payload")
    return result


def fetch_filing_discovery_with_cache(
    provider: OfficialFilingDiscoveryProvider,
    request: ProviderRequest,
    cache: RawResponseCache,
    *,
    offline: bool = False,
    max_age: timedelta | None = None,
    allow_stale: bool = False,
) -> ProviderFetchResult:
    """Use the shared cache boundary for live discovery or explicit replay."""

    return fetch_with_cache(
        provider,
        request,
        cache,
        offline=offline,
        max_age=max_age,
        allow_stale=allow_stale,
    )


__all__ = [
    "FILING_DISCOVERY_ADAPTER_VERSION",
    "FILING_DISCOVERY_SOURCE_NAME",
    "FilingDescriptor",
    "FilingDiscoveryQuery",
    "FilingDiscoveryResult",
    "FilingDiscoverySourceClient",
    "FilingMarket",
    "FilingRecord",
    "FilingSource",
    "OfficialFilingDiscoveryProvider",
    "fetch_filing_discovery_with_cache",
    "filing_id_for",
    "parse_filing_discovery_record",
]
