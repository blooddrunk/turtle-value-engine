"""Read-only AKShare acquisition and normalization for A/H market data.

The adapter deliberately keeps the optional ``akshare`` dependency lazy.  A
normal test run can import this module, inspect its capabilities and replay
cached records without installing AKShare or making a network request.

The adapter currently implements metadata, market observations, three narrow
financial-statement slices, A-share earnings-forecast and performance-report
raw slices, raw-only dividend event/snapshot, corporate-action and
ownership-pledge slices, and A-share share-capital raw slices. Upstream column
names are handled in this module and are never passed to the deterministic
calculation or gate code.
"""

from __future__ import annotations

import importlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from numbers import Integral, Real

from turtle_value_engine.models import (
    Company,
    ConfidenceLevel,
    DataQuality,
    Evidence,
    Fact,
    NormalizedCompanyInput,
    Source,
)
from turtle_value_engine.models.common import EvidenceDirection, EvidenceStrength, SourceType

from .base import StructuredDataProvider
from .cache import CacheKey, ProviderFetchResult, RawResponseCache, fetch_with_cache
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
    canonical_json_bytes,
)
from .normalization import deterministic_id

AKSHARE_ADAPTER_VERSION = "14"
AKSHARE_SOURCE_NAME = "AKShare"
AKSHARE_MAPPING_VERSION = "15"


class ListingMarket(StrEnum):
    """The two listing markets handled by this adapter."""

    A = "A"
    H = "H"


AKSHARE_CAPABILITIES = ProviderCapabilities(
    {
        DataCategory.COMPANY_METADATA,
        DataCategory.LISTING_METADATA,
        DataCategory.MARKET_QUOTE,
        DataCategory.MARKET_HISTORY,
        DataCategory.CASH_FLOW_STATEMENT,
        DataCategory.INCOME_STATEMENT,
        DataCategory.EARNINGS_FORECAST,
        DataCategory.PERFORMANCE_REPORT,
        DataCategory.BALANCE_SHEET,
        DataCategory.DIVIDENDS,
        DataCategory.CORPORATE_ACTIONS,
        DataCategory.SHARE_CAPITAL,
        DataCategory.OWNERSHIP_PLEDGE,
    }
)


_SOURCE_URIS = {
    "stock_info_a_code_name": "https://akshare.akfamily.xyz/data/stock/stock.html",
    "stock_zh_ah_name": "https://akshare.akfamily.xyz/data/stock/stock.html",
    "stock_zh_a_spot_em": "https://quote.eastmoney.com/center/gridlist.html#hs_a_board",
    "stock_zh_a_spot": "https://finance.sina.com.cn/realstock/company/",
    "stock_hk_spot_em": "http://quote.eastmoney.com/center/gridlist.html#hk_stocks",
    "stock_hk_spot": "http://stock.finance.sina.com.cn/hkstock/",
    "stock_zh_ah_spot_em": "https://quote.eastmoney.com/center/gridlist.html#ah_comparison",
    "stock_zh_a_hist": "https://quote.eastmoney.com/concept/",
    "stock_zh_a_daily": "https://finance.sina.com.cn/realstock/company/",
    "stock_hk_daily": "http://stock.finance.sina.com.cn/hkstock/",
    "stock_zh_ah_daily": "https://gu.qq.com/",
    "stock_hk_company_profile_em": "https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html",
    "stock_hk_security_profile_em": "https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html",
    "stock_cash_flow_sheet_by_report_em": "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index",
    "stock_profit_sheet_by_report_em": "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index",
    "stock_yjyg_em": "https://data.eastmoney.com/bbsj/202003/yjyg.html",
    "stock_yjbb_em": "https://data.eastmoney.com/bbsj/202003/yjbb.html",
    "stock_balance_sheet_by_report_em": "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index",
    "stock_zcfz_em": "https://data.eastmoney.com/bbsj/202003/zcfz.html",
    "stock_zcfz_bj_em": "https://data.eastmoney.com/bbsj/202003/zcfz.html",
    "stock_dividend_cninfo": "http://webapi.cninfo.com.cn/#/company",
    "stock_fhps_em": "https://data.eastmoney.com/yjfp/",
    "stock_hk_dividend_payout_em": "https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html",
    "stock_repurchase_em": "https://data.eastmoney.com/gphg/hglist.html",
    "stock_zh_a_gbjg_em": "https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html#/gbjg",
    "stock_share_change_cninfo": "https://webapi.cninfo.com.cn/#/apiDoc",
    "stock_allotment_cninfo": "https://webapi.cninfo.com.cn/#/dataBrowse",
    "stock_gpzy_pledge_ratio_em": "https://data.eastmoney.com/gpzy/pledgeRatio.aspx",
    "stock_financial_report_sina": "https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/",
    "stock_financial_hk_report_em": "https://emweb.securities.eastmoney.com/PC_HKF10/FinancialAnalysis/index",
}

_NO_ARGUMENT_ENDPOINTS = frozenset(
    {
        "stock_info_a_code_name",
        "stock_zh_ah_name",
        "stock_zh_a_spot_em",
        "stock_zh_a_spot",
        "stock_hk_spot_em",
        "stock_hk_spot",
        "stock_zh_ah_spot_em",
        "stock_repurchase_em",
    }
)

_ROW_SELECT_CATEGORIES = frozenset(
    {
        DataCategory.COMPANY_METADATA,
        DataCategory.LISTING_METADATA,
        DataCategory.MARKET_QUOTE,
    }
)

_HISTORY_PARAMETER_NAMES = frozenset(
    {
        "adjust",
        "end_date",
        "end_year",
        "period",
        "start_date",
        "start_year",
    }
)

_FINANCIAL_STATEMENT_PARAMETER_NAMES = frozenset({"indicator", "statement_date"})
_EARNINGS_FORECAST_PARAMETER_NAMES = frozenset({"date"})
_PERFORMANCE_REPORT_PARAMETER_NAMES = frozenset({"date"})

_DIVIDEND_SNAPSHOT_PARAMETER_NAMES = frozenset({"date"})
_SHARE_CAPITAL_PARAMETER_NAMES = frozenset({"start_date", "end_date"})
_SHARE_CHANGE_DEFAULT_START_DATE = "20091227"
_SHARE_CHANGE_DEFAULT_END_DATE = "20241021"

_CORPORATE_ACTION_PARAMETER_NAMES = frozenset({"start_date", "end_date"})
_OWNERSHIP_PLEDGE_PARAMETER_NAMES = frozenset({"date"})
_EARNINGS_FORECAST_START_DATE = date(2008, 12, 31)
_EARNINGS_FORECAST_QUARTER_ENDS = frozenset({(3, 31), (6, 30), (9, 30), (12, 31)})
_PERFORMANCE_REPORT_START_DATE = date(2010, 3, 31)
_PERFORMANCE_REPORT_QUARTER_ENDS = frozenset({(3, 31), (6, 30), (9, 30), (12, 31)})
_ALLOTMENT_DEFAULT_START_DATE = "19700101"
_ALLOTMENT_DEFAULT_END_DATE = "22220222"

_OFFICIAL_BALANCE_SHEET_ENDPOINTS = frozenset(
    {"stock_zcfz_em", "stock_zcfz_bj_em"}
)

_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S")
_MISSING_TEXT = frozenset({"", "-", "--", "—", "na", "n/a", "nan", "nat", "none", "null"})


@dataclass(frozen=True, slots=True)
class _ListingRef:
    market: ListingMarket
    code: str
    canonical_id: str


@dataclass(frozen=True, slots=True)
class _Endpoint:
    name: str
    function: Callable[..., object]
    source_uri: str


class AKShareProvider(StructuredDataProvider):
    """Acquire opaque, read-only AKShare records for one A/H listing.

    ``client`` is injectable so deterministic tests can provide a tiny fake
    object.  When omitted, importing ``akshare`` is deferred until the first
    actual fetch.  No adapter method mutates an upstream resource.
    """

    def __init__(
        self,
        client: object | None = None,
        *,
        provider_version: str = AKSHARE_ADAPTER_VERSION,
        source_name: str = AKSHARE_SOURCE_NAME,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._identity = ProviderIdentity(
            provider_id="akshare",
            provider_version=provider_version,
            source_name=source_name,
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def identity(self) -> ProviderIdentity:
        """Return the stable adapter/source identity used by the cache."""

        return self._identity

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the exact categories implemented by this adapter slice."""

        return AKSHARE_CAPABILITIES

    def fetch_raw(self, request: ProviderRequest) -> RawProviderRecord:
        """Fetch one opaque record and retain provider fields only in its payload."""

        if not isinstance(request, ProviderRequest):
            raise TypeError("request must be a ProviderRequest")
        if not self.capabilities.supports(request.category):
            raise ProviderCapabilityError(
                f"AKShare adapter does not support {request.category.value!r}",
                provider=self.identity,
                request=request,
            )

        listing = _parse_listing_id(request.entity_id, provider=self.identity, request=request)
        if request.category is DataCategory.SHARE_CAPITAL and listing.market is not ListingMarket.A:
            raise ProviderRequestError(
                "the AKShare share-capital endpoint supports A-share listings only",
                provider=self.identity,
                request=request,
                retryable=False,
            )
        if (
            request.category is DataCategory.CORPORATE_ACTIONS
            and listing.market is not ListingMarket.A
        ):
            raise ProviderRequestError(
                "the AKShare corporate-action endpoint supports A-share listings only",
                provider=self.identity,
                request=request,
                retryable=False,
            )
        if (
            request.category is DataCategory.OWNERSHIP_PLEDGE
            and listing.market is not ListingMarket.A
        ):
            raise ProviderRequestError(
                "the AKShare ownership-pledge endpoint supports A-share listings only",
                provider=self.identity,
                request=request,
                retryable=False,
            )
        if (
            request.category is DataCategory.EARNINGS_FORECAST
            and listing.market is not ListingMarket.A
        ):
            raise ProviderRequestError(
                "the AKShare earnings-forecast endpoint supports A-share listings only",
                provider=self.identity,
                request=request,
                retryable=False,
            )
        if (
            request.category is DataCategory.PERFORMANCE_REPORT
            and listing.market is not ListingMarket.A
        ):
            raise ProviderRequestError(
                "the AKShare performance-report endpoint supports A-share listings only",
                provider=self.identity,
                request=request,
                retryable=False,
            )
        client = self._load_client(request)
        endpoint = self._resolve_endpoint(client, listing, request.category, request)
        kwargs = self._endpoint_kwargs(endpoint.name, listing, request)

        try:
            upstream_response = endpoint.function(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderRequestError(
                f"AKShare endpoint {endpoint.name!r} failed for {request.entity_id!r}",
                provider=self.identity,
                request=request,
                retryable=_is_probably_retryable(exc),
            ) from exc

        try:
            payload = _to_json_value(upstream_response)
        except ProviderResponseError as exc:
            raise ProviderResponseError(
                f"AKShare endpoint {endpoint.name!r} returned a non-JSON response: {exc}",
                provider=self.identity,
                request=request,
            ) from exc

        response_metadata: dict[str, JSONValue] = {
            "endpoint": endpoint.name,
            "market": listing.market.value,
            "listing_code": listing.code,
            "raw_response_type": type(upstream_response).__name__,
        }
        library_version = getattr(client, "__version__", None)
        if isinstance(library_version, str) and library_version:
            response_metadata["library_version"] = library_version

        if request.category in _ROW_SELECT_CATEGORIES:
            rows = _table_rows(payload, provider=self.identity, request=request)
            selected = _select_listing_row(
                rows,
                listing,
                provider=self.identity,
                request=request,
            )
            payload = selected
            response_metadata["upstream_row_count"] = len(rows)
            response_metadata["entity_row_selected"] = True
        elif request.category is DataCategory.MARKET_HISTORY:
            rows = _table_rows(payload, provider=self.identity, request=request)
            response_metadata["upstream_row_count"] = len(rows)
            if listing.market is ListingMarket.H and _has_history_range(request.parameters):
                response_metadata["range_filtering"] = "normalizer"
        elif (
            request.category is DataCategory.BALANCE_SHEET
            and endpoint.name in _OFFICIAL_BALANCE_SHEET_ENDPOINTS
        ):
            rows = _table_rows(payload, provider=self.identity, request=request)
            selected = _select_listing_row(
                rows,
                listing,
                provider=self.identity,
                request=request,
            )
            payload = selected
            response_metadata["upstream_row_count"] = len(rows)
            response_metadata["entity_row_selected"] = True
            response_metadata["statement_date"] = _parse_statement_date_parameter(
                request.parameters["statement_date"],
                request=request,
            ).isoformat()
        elif request.category is DataCategory.DIVIDENDS:
            rows = _table_rows(payload, provider=self.identity, request=request)
            if endpoint.name == "stock_fhps_em":
                _validate_dividend_snapshot_provider_rows(
                    rows,
                    listing,
                    provider=self.identity,
                    request=request,
                )
                selected = _select_listing_rows(
                    rows,
                    listing,
                    provider=self.identity,
                    request=request,
                    row_label="dividend-snapshot",
                )
                payload = selected
                requested_date = _parse_dividend_snapshot_date_parameter(
                    kwargs["date"],
                    request=request,
                )
                response_metadata["upstream_row_count"] = len(rows)
                response_metadata["entity_row_count"] = len(selected)
                response_metadata["entity_rows_selected"] = True
                response_metadata["listing_scoped_request"] = False
                response_metadata["row_filtering"] = "provider"
                response_metadata["requested_date"] = kwargs["date"]
                response_metadata["report_period"] = requested_date.isoformat()
            else:
                response_metadata["upstream_row_count"] = len(rows)
        elif request.category is DataCategory.SHARE_CAPITAL:
            rows = _table_rows(payload, provider=self.identity, request=request)
            if endpoint.name == "stock_share_change_cninfo":
                _validate_share_capital_provider_rows(
                    rows,
                    listing,
                    provider=self.identity,
                    request=request,
                )
                response_metadata["start_date"] = kwargs["start_date"]
                response_metadata["end_date"] = kwargs["end_date"]
                response_metadata["range_filtering"] = "provider"
            response_metadata["upstream_row_count"] = len(rows)
            response_metadata["listing_scoped_request"] = True
        elif request.category is DataCategory.CORPORATE_ACTIONS:
            rows = _table_rows(payload, provider=self.identity, request=request)
            if endpoint.name == "stock_repurchase_em":
                selected = _select_listing_rows(
                    rows,
                    listing,
                    provider=self.identity,
                    request=request,
                )
                payload = selected
                response_metadata["upstream_row_count"] = len(rows)
                response_metadata["entity_row_count"] = len(selected)
                response_metadata["entity_rows_selected"] = True
                response_metadata["listing_scoped_request"] = False
                response_metadata["row_filtering"] = "provider"
            elif endpoint.name == "stock_allotment_cninfo":
                _validate_corporate_action_provider_rows(
                    rows,
                    listing,
                    provider=self.identity,
                    request=request,
                )
                response_metadata["upstream_row_count"] = len(rows)
                response_metadata["listing_scoped_request"] = True
                response_metadata["action_type"] = "rights_issue"
                response_metadata["start_date"] = kwargs["start_date"]
                response_metadata["end_date"] = kwargs["end_date"]
        elif request.category is DataCategory.OWNERSHIP_PLEDGE:
            rows = _table_rows(payload, provider=self.identity, request=request)
            requested_date = _parse_pledge_date_parameter(
                kwargs["date"],
                request=request,
            )
            _validate_ownership_pledge_provider_rows(
                rows,
                listing,
                requested_date=requested_date,
                provider=self.identity,
                request=request,
            )
            selected = _select_listing_rows(
                rows,
                listing,
                provider=self.identity,
                request=request,
                row_label="ownership-pledge",
            )
            if len(selected) > 1:
                raise ProviderResponseError(
                    f"AKShare returned ambiguous ownership-pledge rows for "
                    f"{request.entity_id!r}",
                    provider=self.identity,
                    request=request,
                )
            payload = selected
            response_metadata["upstream_row_count"] = len(rows)
            response_metadata["entity_row_count"] = len(selected)
            response_metadata["entity_rows_selected"] = True
            response_metadata["listing_scoped_request"] = False
            response_metadata["row_filtering"] = "provider"
            response_metadata["requested_date"] = kwargs["date"]
            response_metadata["observation_date"] = requested_date.isoformat()
        elif request.category is DataCategory.EARNINGS_FORECAST:
            rows = _table_rows(payload, provider=self.identity, request=request)
            requested_date = _parse_earnings_forecast_date_parameter(
                kwargs["date"],
                request=request,
            )
            _validate_earnings_forecast_provider_rows(
                rows,
                listing,
                report_period=requested_date,
                provider=self.identity,
                request=request,
            )
            selected = _select_listing_rows(
                rows,
                listing,
                provider=self.identity,
                request=request,
                row_label="earnings-forecast",
            )
            payload = selected
            response_metadata["upstream_row_count"] = len(rows)
            response_metadata["entity_row_count"] = len(selected)
            response_metadata["entity_rows_selected"] = True
            response_metadata["listing_scoped_request"] = False
            response_metadata["row_filtering"] = "provider"
            response_metadata["requested_date"] = kwargs["date"]
            response_metadata["report_period"] = requested_date.isoformat()
        elif request.category is DataCategory.PERFORMANCE_REPORT:
            rows = _table_rows(payload, provider=self.identity, request=request)
            requested_date = _parse_performance_report_date_parameter(
                kwargs["date"],
                request=request,
            )
            _validate_performance_report_provider_rows(
                rows,
                listing,
                provider=self.identity,
                request=request,
            )
            selected = _select_listing_rows(
                rows,
                listing,
                provider=self.identity,
                request=request,
                row_label="performance-report",
            )
            payload = selected
            response_metadata["upstream_row_count"] = len(rows)
            response_metadata["entity_row_count"] = len(selected)
            response_metadata["entity_rows_selected"] = True
            response_metadata["listing_scoped_request"] = False
            response_metadata["row_filtering"] = "provider"
            response_metadata["requested_date"] = kwargs["date"]
            response_metadata["report_period"] = requested_date.isoformat()

        try:
            retrieved_at = self._clock()
        except Exception as exc:
            raise ProviderResponseError(
                "AKShare retrieval clock failed",
                provider=self.identity,
                request=request,
            ) from exc
        if not isinstance(retrieved_at, datetime):
            raise ProviderResponseError(
                "AKShare retrieval clock must return a datetime",
                provider=self.identity,
                request=request,
            )

        return RawProviderRecord(
            provider=self.identity,
            request=request,
            retrieved_at=retrieved_at,
            raw_payload=payload,
            source_uri=endpoint.source_uri,
            response_metadata=response_metadata,
        )

    def _load_client(self, request: ProviderRequest) -> object:
        if self._client is not None:
            return self._client
        try:
            self._client = importlib.import_module("akshare")
        except ImportError as exc:
            raise ProviderRequestError(
                "AKShare is an optional dependency; install the akshare extra before live fetches",
                provider=self.identity,
                request=request,
                retryable=False,
            ) from exc
        return self._client

    def _resolve_endpoint(
        self,
        client: object,
        listing: _ListingRef,
        category: DataCategory,
        request: ProviderRequest,
    ) -> _Endpoint:
        candidates = _endpoint_candidates(
            listing,
            category,
            statement_date_requested="statement_date" in request.parameters,
            corporate_action_date_requested=any(
                name in request.parameters for name in ("start_date", "end_date")
            ),
            share_capital_date_requested=any(
                name in request.parameters for name in ("start_date", "end_date")
            ),
            dividend_snapshot_date_requested="date" in request.parameters,
        )
        for name in candidates:
            function = getattr(client, name, None)
            if callable(function):
                return _Endpoint(
                    name=name,
                    function=function,
                    source_uri=_SOURCE_URIS.get(name, "https://akshare.akfamily.xyz/data/stock/stock.html"),
                )
        names = ", ".join(candidates)
        raise ProviderRequestError(
            f"AKShare client does not expose a supported endpoint for "
            f"{category.value!r}; tried: {names}",
            provider=self.identity,
            request=request,
            retryable=False,
        )

    def _endpoint_kwargs(
        self,
        endpoint_name: str,
        listing: _ListingRef,
        request: ProviderRequest,
    ) -> dict[str, object]:
        try:
            if request.category is DataCategory.MARKET_HISTORY:
                return _history_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.CASH_FLOW_STATEMENT:
                return _cash_flow_statement_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.INCOME_STATEMENT:
                return _income_statement_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.BALANCE_SHEET:
                return _balance_sheet_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.EARNINGS_FORECAST:
                return _earnings_forecast_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.PERFORMANCE_REPORT:
                return _performance_report_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.DIVIDENDS:
                return _dividends_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.SHARE_CAPITAL:
                return _share_capital_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.CORPORATE_ACTIONS:
                return _corporate_action_kwargs(endpoint_name, listing, request)
            if request.category is DataCategory.OWNERSHIP_PLEDGE:
                return _ownership_pledge_kwargs(endpoint_name, listing, request)
            if endpoint_name in _NO_ARGUMENT_ENDPOINTS:
                _reject_unexpected_parameters(request)
                return {}
            _reject_unexpected_parameters(request)
            return {"symbol": listing.code}
        except ProviderRequestError as exc:
            if exc.provider is not None:
                raise
            raise ProviderRequestError(
                str(exc),
                provider=self.identity,
                request=request,
                retryable=exc.retryable,
            ) from exc


# The spelling used in the roadmap is kept as a compatibility alias.
AkShareProvider = AKShareProvider
AKShareAdapter = AKShareProvider


def fetch_akshare_with_cache(
    provider: AKShareProvider,
    request: ProviderRequest,
    cache: RawResponseCache,
    *,
    offline: bool = False,
    max_age: timedelta | None = None,
    allow_stale: bool = False,
) -> ProviderFetchResult:
    """Use the provider-neutral cache helper with an AKShare provider."""

    return fetch_with_cache(
        provider,
        request,
        cache,
        offline=offline,
        max_age=max_age,
        allow_stale=allow_stale,
    )


class AKShareNormalizer:
    """Map the supported AKShare records to the existing input contract.

    The caller supplies the required ``Company`` identity.  Metadata can
    enrich nullable context fields but cannot invent a sector or reporting
    currency.  Quote/history observations become canonical extension facts;
    they do not become metrics, gates, valuation inputs or a second model.
    """

    mapping_version = AKSHARE_MAPPING_VERSION

    def __init__(self, *, confidence: float = 0.8) -> None:
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be finite and between 0 and 1")
        self.confidence = float(confidence)

    def normalize(
        self,
        records: Sequence[RawProviderRecord],
        *,
        analysis_id: str,
        as_of: date,
        profile_id: str,
        company: Company,
    ) -> NormalizedCompanyInput:
        """Return one schema-valid normalized input from AKShare raw records."""

        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise TypeError("records must be a sequence of RawProviderRecord")
        if not records:
            raise ProviderNormalizationError("at least one raw record is required")
        if not isinstance(company, Company):
            raise TypeError("company must be a Company")

        ordered_records = _deduplicate_and_sort_records(records)
        facts: list[Fact] = []
        evidence_index: list[Evidence] = []
        fact_keys: set[tuple[str, str]] = set()
        missing_fields: set[str] = set()
        coverage_total = 0
        coverage_present = 0
        metadata_context: dict[str, str] = {}
        normalizer_flags: set[str] = set()

        def add_fact(
            record: RawProviderRecord,
            evidence: Evidence,
            *,
            field: str,
            value: object,
            period: str,
            currency: str | None = None,
            unit: str | None = None,
            count_coverage: bool = True,
        ) -> None:
            nonlocal coverage_present, coverage_total
            if count_coverage:
                coverage_total += 1
                if value is not None:
                    coverage_present += 1
            key = (field, period)
            if key in fact_keys:
                raise ProviderNormalizationError(
                    f"ambiguous duplicate mapping for field={field!r}, period={period!r}"
                )
            fact_keys.add(key)
            facts.append(
                Fact(
                    id=deterministic_id(
                        "fact",
                        self.mapping_version,
                        record.provider.provider_id,
                        record.provider.provider_version,
                        record.request.as_dict(),
                        field,
                        period,
                    ),
                    field=field,
                    value=value,
                    unit=unit,
                    currency=currency,
                    period=period,
                    source_evidence_ids=[evidence.id],
                    confidence=self.confidence,
                )
            )

        for record in ordered_records:
            if record.provider.provider_id.lower() != "akshare":
                raise ProviderNormalizationError(
                    f"AKShare normalizer cannot consume provider {record.provider.provider_id!r}"
                )
            evidence = _evidence_for_record(record, confidence=self.confidence)
            evidence_index.append(evidence)
            listing = _parse_listing_id(record.request.entity_id)
            rows = _table_rows(record.raw_payload)
            primary = _same_listing(listing.canonical_id, company.primary_listing)
            as_of_period = _listing_period(as_of, listing, primary=primary)

            if record.request.category is DataCategory.COMPANY_METADATA:
                row = _single_normalization_row(rows, record)
                context = _map_company_metadata(row)
                if primary:
                    metadata_context.update(
                        {key: value for key, value in context.items() if value is not None}
                    )
                for field, aliases in _COMPANY_METADATA_FIELDS.items():
                    found, raw_value = _lookup(row, aliases)
                    if found:
                        value = _text_value(raw_value)
                        add_fact(
                            record,
                            evidence,
                            field=field,
                            value=value,
                            period=as_of_period,
                            count_coverage=False,
                        )
            elif record.request.category is DataCategory.LISTING_METADATA:
                row = _single_normalization_row(rows, record)
                for field, aliases in _LISTING_METADATA_FIELDS.items():
                    found, raw_value = _lookup(row, aliases)
                    if found:
                        value = _text_value(raw_value)
                        add_fact(
                            record,
                            evidence,
                            field=field,
                            value=value,
                            period=as_of_period,
                            count_coverage=False,
                        )
                listing_date = _metadata_date(row)
                if listing_date is not None:
                    if listing_date > as_of:
                        raise ProviderNormalizationError(
                            f"listing date {listing_date.isoformat()} is after analysis date "
                            f"{as_of.isoformat()}"
                        )
                    add_fact(
                        record,
                        evidence,
                        field="listing_years",
                        value=(as_of - listing_date).days / 365.25,
                        period=as_of_period,
                        unit="years",
                        count_coverage=False,
                    )
            elif record.request.category is DataCategory.MARKET_QUOTE:
                row = _single_normalization_row(rows, record)
                field = "current_price" if primary else "listing_current_price"
                found, raw_value = _lookup(row, _QUOTE_PRICE_FIELDS)
                value = _number_value(raw_value, field=field) if found else None
                add_fact(
                    record,
                    evidence,
                    field=field,
                    value=value,
                    period=as_of_period,
                    currency=_currency_for(listing.market),
                    unit="price_per_share",
                )
                if value is None and primary:
                    missing_fields.add("current_price")
                timestamp_found, timestamp_value = _lookup(row, _QUOTE_TIME_FIELDS)
                if timestamp_found:
                    add_fact(
                        record,
                        evidence,
                        field="market_quote_timestamp",
                        value=_text_value(timestamp_value),
                        period=as_of_period,
                        count_coverage=False,
                    )
            elif record.request.category is DataCategory.MARKET_HISTORY:
                history_result = _map_history(
                    record,
                    evidence,
                    rows,
                    listing,
                    as_of=as_of,
                    primary=primary,
                    add_fact=add_fact,
                )
                if history_result[0] == 0:
                    missing_fields.add("market_history")
                if history_result[1] == 0:
                    missing_fields.add("historical_close")
            elif record.request.category is DataCategory.CASH_FLOW_STATEMENT:
                cash_flow_result = _map_cash_flow_statement(
                    record,
                    evidence,
                    rows,
                    listing,
                    primary=primary,
                    add_fact=add_fact,
                )
                if cash_flow_result[0] == 0:
                    missing_fields.add("cash_flow_statement")
                if cash_flow_result[1] == 0:
                    missing_fields.add("reported_cfo")
            elif record.request.category is DataCategory.INCOME_STATEMENT:
                income_result = _map_income_statement(
                    record,
                    evidence,
                    rows,
                    listing,
                    primary=primary,
                    add_fact=add_fact,
                )
                if income_result[0] == 0:
                    missing_fields.add("income_statement")
                if income_result[1]["parent_net_profit"] == 0:
                    missing_fields.add("parent_net_profit")
                if income_result[1]["consolidated_net_profit"] == 0:
                    missing_fields.add("consolidated_net_profit")
            elif record.request.category is DataCategory.BALANCE_SHEET:
                balance_sheet_result = _map_balance_sheet(
                    record,
                    evidence,
                    rows,
                    listing,
                    primary=primary,
                    add_fact=add_fact,
                )
                if balance_sheet_result[0] == 0:
                    missing_fields.add("balance_sheet")
                for field in _BALANCE_SHEET_CRITICAL_FIELDS:
                    if balance_sheet_result[1][field] == 0:
                        missing_fields.add(field)
            elif record.request.category is DataCategory.EARNINGS_FORECAST:
                if listing.market is not ListingMarket.A:
                    raise ProviderNormalizationError(
                        "AKShare earnings-forecast raw slice supports A-share listings only"
                    )
                try:
                    report_period = _parse_earnings_forecast_date_parameter(
                        record.request.parameters.get("date"),
                        request=record.request,
                    )
                except ProviderRequestError as exc:
                    raise ProviderNormalizationError(str(exc)) from exc
                _validate_earnings_forecast_normalizer_rows(
                    rows,
                    listing,
                    report_period=report_period,
                )
                # Forecast ranges and announcement dates are estimates and
                # publication metadata, not reported parent/consolidated
                # profit for the requested statement period.
                missing_fields.update({"parent_net_profit", "consolidated_net_profit"})
                normalizer_flags.add("AKSHARE_EARNINGS_FORECAST_RAW_ONLY")
            elif record.request.category is DataCategory.PERFORMANCE_REPORT:
                if listing.market is not ListingMarket.A:
                    raise ProviderNormalizationError(
                        "AKShare performance-report raw slice supports A-share listings only"
                    )
                try:
                    _parse_performance_report_date_parameter(
                        record.request.parameters.get("date"),
                        request=record.request,
                    )
                except ProviderRequestError as exc:
                    raise ProviderNormalizationError(str(exc)) from exc
                _validate_performance_report_normalizer_rows(rows, listing)
                # The report headline does not identify parent versus
                # consolidated profit, and operating cash flow is reported
                # per share rather than as the accepted total CFO fact.
                missing_fields.update(
                    {"parent_net_profit", "consolidated_net_profit", "reported_cfo"}
                )
                normalizer_flags.add("AKSHARE_PERFORMANCE_REPORT_RAW_ONLY")
            elif record.request.category is DataCategory.DIVIDENDS:
                endpoint_name = record.response_metadata.get("endpoint")
                if endpoint_name == "stock_fhps_em":
                    if listing.market is not ListingMarket.A:
                        raise ProviderNormalizationError(
                            "AKShare dividend-snapshot raw slice supports A-share listings only"
                        )
                    try:
                        _parse_dividend_snapshot_date_parameter(
                            record.request.parameters.get("date"),
                            request=record.request,
                        )
                    except ProviderRequestError as exc:
                        raise ProviderNormalizationError(str(exc)) from exc
                    _validate_dividend_snapshot_normalizer_rows(rows, listing)
                    normalizer_flags.add("AKSHARE_DIVIDEND_SNAPSHOT_RAW_ONLY")
                # The upstream endpoints expose event plans and dates, not a
                # normalized cash amount with a settled entity/period basis.
                # Keep the raw record and evidence available without treating
                # a per-share plan, ratio or fiscal-year label as ordinary cash.
                missing_fields.add("ordinary_dividend_cash")
            elif record.request.category is DataCategory.CORPORATE_ACTIONS:
                if listing.market is not ListingMarket.A:
                    raise ProviderNormalizationError(
                        "AKShare corporate-action raw slices support A-share listings only"
                    )
                endpoint_name = record.response_metadata.get("endpoint")
                if endpoint_name == "stock_allotment_cninfo":
                    _validate_corporate_action_normalizer_rows(rows, listing)
                    missing_fields.add("share_issuance_cash")
                    normalizer_flags.add("AKSHARE_ALLOTMENT_RAW_ONLY")
                else:
                    _validate_corporate_action_rows(rows, listing)
                    # The endpoint combines planned and completed repurchase
                    # fields and exposes an announcement/update date rather
                    # than one settled cash-flow period. Retain the record and
                    # evidence, but do not turn it into annual buyback cash or
                    # a recurrence claim.
                    missing_fields.add("buyback_cash")
                    normalizer_flags.add("AKSHARE_CORPORATE_ACTIONS_RAW_ONLY")
            elif record.request.category is DataCategory.SHARE_CAPITAL:
                if listing.market is not ListingMarket.A:
                    raise ProviderNormalizationError(
                        "AKShare share-capital raw slice supports A-share listings only"
                    )
                if record.response_metadata.get("endpoint") == "stock_share_change_cninfo":
                    _validate_share_capital_normalizer_rows(rows, listing)
                    normalizer_flags.add("AKSHARE_SHARE_CAPITAL_CHANGE_RAW_ONLY")
                else:
                    normalizer_flags.add("AKSHARE_SHARE_CAPITAL_RAW_ONLY")
                missing_fields.add("normalized_diluted_economic_shares")
            elif record.request.category is DataCategory.OWNERSHIP_PLEDGE:
                if listing.market is not ListingMarket.A:
                    raise ProviderNormalizationError(
                        "AKShare ownership-pledge raw slice supports A-share listings only"
                    )
                try:
                    requested_date = _parse_pledge_date_parameter(
                        record.request.parameters.get("date"),
                        request=record.request,
                    )
                except ProviderRequestError as exc:
                    raise ProviderNormalizationError(str(exc)) from exc
                _validate_ownership_pledge_rows(
                    rows,
                    listing,
                    observation_date=requested_date,
                )
                # A dated pledge ratio is a screening signal only. It does not
                # establish governance severity, controlling-shareholder
                # identity, cash accessibility or a strict-v1 debt/cash fact.
                missing_fields.add("governance_risk_level")
                normalizer_flags.add("AKSHARE_OWNERSHIP_PLEDGE_RAW_ONLY")
            else:
                raise ProviderNormalizationError(
                    f"unsupported AKShare normalization category: {record.request.category.value}"
                )

        normalized_company = _enrich_company(company, metadata_context)
        coverage = coverage_present / coverage_total if coverage_total else 0.0
        quality = (
            ConfidenceLevel.LOW
            if missing_fields or not facts
            else ConfidenceLevel.MEDIUM
        )
        notes = (
            "AKShare structured records were normalized as structured observations. "
            "Cash-flow mapping is limited to explicitly reported operating cash flow "
            "and acquisition cash; income-statement mapping is limited to explicit "
            "parent and consolidated net profit; balance-sheet mapping is limited "
            "to explicit cash, equity and interest-bearing-debt totals. Earnings "
            "forecast records remain raw structured evidence because forecast "
            "ranges and announcement dates are not reported profit. Performance "
            "report records remain raw structured evidence because their headline "
            "net profit has no admitted parent/consolidated basis and their operating "
            "cash flow is per share. Dividend "
            "and corporate-action records remain raw structured evidence until "
            "ordinary/special status, cash amount, action outcome, amount unit "
            "and period basis are explicit. Ownership-pledge records remain raw "
            "structured evidence until the affected holder, governance context "
            "and point-in-time interpretation are established. Filing "
            "classifications and economic adjustments remain unresolved until a "
            "later provider/filing workflow."
        )
        if "AKSHARE_CORPORATE_ACTIONS_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share repurchase endpoint is retained as raw "
                "evidence only: planned versus completed amounts and announcement "
                "dates do not establish a settled annual buyback-cash fact."
            )
        if "AKSHARE_SHARE_CAPITAL_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share share-capital history is retained as raw "
                "evidence only: its change-date, unit and diluted economic scope "
                "are not sufficient for a canonical share-count fact."
            )
        if "AKSHARE_SHARE_CAPITAL_CHANGE_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share company share-change response is retained "
                "as raw evidence only: its change/announcement dates, numeric share "
                "holdings and change reasons do not establish a canonical period, "
                "unit or diluted economic share scope."
            )
        if "AKSHARE_ALLOTMENT_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share rights-issue response is retained as raw "
                "evidence only: its action dates, planned/actual outcome, amount "
                "units and share-class scope are not sufficient for a canonical "
                "issuance or dilution fact."
            )
        if "AKSHARE_OWNERSHIP_PLEDGE_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share ownership-pledge snapshot is retained as "
                "raw evidence only: its ratio and observation date do not identify "
                "a controlling holder or establish a governance-risk conclusion, "
                "pledged cash amount or debt-equivalent fact."
            )
        if "AKSHARE_DIVIDEND_SNAPSHOT_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share dividend-distribution snapshot is retained "
                "as raw evidence only: its report-date ratios, distribution status "
                "and announcement/record/ex-rights dates do not establish settled "
                "ordinary dividend cash or a canonical payout ratio."
            )
        if "AKSHARE_EARNINGS_FORECAST_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share earnings-forecast response is retained as "
                "raw evidence only: forecast ranges, forecast type and announcement "
                "dates do not establish reported parent or consolidated net profit "
                "for the requested report period."
            )
        if "AKSHARE_PERFORMANCE_REPORT_RAW_ONLY" in normalizer_flags:
            notes += (
                " The documented A-share performance-report response is retained as "
                "raw evidence only: its headline net profit has no admitted "
                "parent/consolidated basis, and its operating cash flow is per share "
                "rather than a canonical reported CFO total."
            )
        return NormalizedCompanyInput(
            schema_version="1.0.0",
            analysis_id=analysis_id,
            as_of=as_of,
            profile_id=profile_id,
            company=normalized_company,
            data_quality=DataQuality(
                confidence=quality,
                evidence_coverage=coverage,
                critical_missing_fields=sorted(missing_fields),
                notes=notes,
            ),
            facts=facts,
            evidence_index=evidence_index,
            adjustments=[],
            flags=sorted(normalizer_flags),
        )


AkShareNormalizer = AKShareNormalizer


def normalize_akshare_records(
    records: Sequence[RawProviderRecord],
    *,
    analysis_id: str,
    as_of: date,
    profile_id: str,
    company: Company,
    confidence: float = 0.8,
) -> NormalizedCompanyInput:
    """Convenience wrapper around :class:`AKShareNormalizer`."""

    return AKShareNormalizer(confidence=confidence).normalize(
        records,
        analysis_id=analysis_id,
        as_of=as_of,
        profile_id=profile_id,
        company=company,
    )


_COMPANY_METADATA_FIELDS = {
    "company_name": ("公司名称", "name", "名称", "company_name"),
    "company_english_name": ("英文名称", "english_name", "company_english_name"),
    "company_registration_region": ("注册地", "country_or_region", "registration_region"),
    "company_incorporation_date": ("公司成立日期", "成立日期", "incorporation_date"),
    "company_industry": ("所属行业", "industry", "company_industry"),
    "fiscal_year_end": ("年结日", "财年结日", "fiscal_year_end"),
}

_LISTING_METADATA_FIELDS = {
    "listing_code": ("证券代码", "代码", "股票代码", "code", "symbol"),
    "listing_name": ("证券简称", "名称", "股票简称", "name"),
    "listing_date": ("上市日期", "上市日", "listing_date"),
    "listing_exchange": ("交易所", "exchange"),
    "listing_board": ("板块", "board"),
    "listing_security_type": ("证券类型", "security_type"),
    "listing_isin": ("ISIN（国际证券识别编码）", "ISIN", "isin"),
    "listing_hk_connect": ("是否沪港通标的", "是否深港通标的", "hk_connect"),
}

_QUOTE_PRICE_FIELDS = (
    "最新价",
    "最新价-HKD",
    "最新价-RMB",
    "latest_price",
    "current_price",
    "price",
)
_QUOTE_TIME_FIELDS = ("时间", "日期", "date", "datetime", "timestamp")

_HISTORY_FIELDS = {
    "historical_open": (("开盘", "open"), "price_per_share"),
    "historical_high": (("最高", "high"), "price_per_share"),
    "historical_low": (("最低", "low"), "price_per_share"),
    "historical_close": (("收盘", "close", "latest", "最新价"), "price_per_share"),
    "historical_volume": (("成交量", "volume"), None),
    "historical_turnover": (("成交额", "amount", "turnover"), "currency_amount"),
    "historical_change_percent": (("涨跌幅", "change_percent", "pct_change"), "percent"),
}


def _endpoint_candidates(
    listing: _ListingRef,
    category: DataCategory,
    *,
    statement_date_requested: bool = False,
    corporate_action_date_requested: bool = False,
    share_capital_date_requested: bool = False,
    dividend_snapshot_date_requested: bool = False,
) -> tuple[str, ...]:
    market = listing.market
    if category is DataCategory.COMPANY_METADATA:
        if market is ListingMarket.A:
            return ("stock_info_a_code_name", "stock_zh_ah_name")
        return ("stock_hk_company_profile_em", "stock_zh_ah_name", "stock_hk_spot_em")
    if category is DataCategory.LISTING_METADATA:
        if market is ListingMarket.A:
            return ("stock_info_a_code_name", "stock_zh_ah_name")
        return ("stock_hk_security_profile_em", "stock_zh_ah_name", "stock_hk_spot_em")
    if category is DataCategory.MARKET_QUOTE:
        if market is ListingMarket.A:
            return ("stock_zh_a_spot_em", "stock_zh_a_spot")
        return ("stock_hk_spot_em", "stock_hk_spot")
    if category is DataCategory.MARKET_HISTORY:
        if market is ListingMarket.A:
            return ("stock_zh_a_hist", "stock_zh_a_daily")
        return ("stock_hk_daily", "stock_zh_ah_daily")
    if category is DataCategory.CASH_FLOW_STATEMENT:
        if market is ListingMarket.A:
            return ("stock_cash_flow_sheet_by_report_em", "stock_financial_report_sina")
        return ("stock_financial_hk_report_em",)
    if category is DataCategory.INCOME_STATEMENT:
        if market is ListingMarket.A:
            return ("stock_profit_sheet_by_report_em", "stock_financial_report_sina")
        return ("stock_financial_hk_report_em",)
    if category is DataCategory.EARNINGS_FORECAST:
        if market is ListingMarket.A:
            return ("stock_yjyg_em",)
        return ()
    if category is DataCategory.PERFORMANCE_REPORT:
        if market is ListingMarket.A:
            return ("stock_yjbb_em",)
        return ()
    if category is DataCategory.BALANCE_SHEET:
        if market is ListingMarket.A:
            if listing.canonical_id.startswith("BJ"):
                aggregate_endpoint = "stock_zcfz_bj_em"
            else:
                aggregate_endpoint = "stock_zcfz_em"
            detailed_endpoint = "stock_balance_sheet_by_report_em"
            if statement_date_requested:
                return (
                    aggregate_endpoint,
                    detailed_endpoint,
                    "stock_financial_report_sina",
                )
            return (
                detailed_endpoint,
                aggregate_endpoint,
                "stock_financial_report_sina",
            )
        return ("stock_financial_hk_report_em",)
    if category is DataCategory.DIVIDENDS:
        if market is ListingMarket.A:
            if dividend_snapshot_date_requested:
                return ("stock_fhps_em",)
            return ("stock_dividend_cninfo",)
        return ("stock_hk_dividend_payout_em",)
    if category is DataCategory.CORPORATE_ACTIONS:
        if corporate_action_date_requested:
            return ("stock_allotment_cninfo",)
        return ("stock_repurchase_em",)
    if category is DataCategory.SHARE_CAPITAL:
        if share_capital_date_requested:
            return ("stock_share_change_cninfo",)
        return ("stock_zh_a_gbjg_em",)
    if category is DataCategory.OWNERSHIP_PLEDGE:
        if market is ListingMarket.A:
            return ("stock_gpzy_pledge_ratio_em",)
        return ()
    raise ProviderCapabilityError(f"AKShare adapter does not support {category.value!r}")


def _cash_flow_statement_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    return _financial_statement_kwargs(
        endpoint_name,
        listing,
        request,
        statement_symbol="现金流量表",
        statement_label="cash-flow",
    )


def _income_statement_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    return _financial_statement_kwargs(
        endpoint_name,
        listing,
        request,
        statement_symbol="利润表",
        statement_label="income statement",
    )


def _balance_sheet_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    return _financial_statement_kwargs(
        endpoint_name,
        listing,
        request,
        statement_symbol="资产负债表",
        statement_label="balance sheet",
    )


def _earnings_forecast_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    if endpoint_name != "stock_yjyg_em":
        raise ProviderRequestError(
            f"unsupported AKShare earnings-forecast endpoint {endpoint_name!r}",
            request=request,
            retryable=False,
        )
    if listing.market is not ListingMarket.A:
        raise ProviderRequestError(
            "the AKShare earnings-forecast endpoint supports A-share listings only",
            request=request,
            retryable=False,
        )
    unknown = sorted(set(request.parameters) - _EARNINGS_FORECAST_PARAMETER_NAMES)
    if unknown:
        raise ProviderRequestError(
            "unsupported AKShare earnings-forecast parameter(s): " + ", ".join(unknown),
            request=request,
            retryable=False,
        )
    if "date" not in request.parameters:
        raise ProviderRequestError(
            "the AKShare earnings-forecast endpoint requires date (YYYYMMDD)",
            request=request,
            retryable=False,
        )
    report_date = _parse_earnings_forecast_date_parameter(
        request.parameters["date"],
        request=request,
    )
    return {"date": report_date.strftime("%Y%m%d")}


def _performance_report_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    if endpoint_name != "stock_yjbb_em":
        raise ProviderRequestError(
            f"unsupported AKShare performance-report endpoint {endpoint_name!r}",
            request=request,
            retryable=False,
        )
    if listing.market is not ListingMarket.A:
        raise ProviderRequestError(
            "the AKShare performance-report endpoint supports A-share listings only",
            request=request,
            retryable=False,
        )
    unknown = sorted(set(request.parameters) - _PERFORMANCE_REPORT_PARAMETER_NAMES)
    if unknown:
        raise ProviderRequestError(
            "unsupported AKShare performance-report parameter(s): " + ", ".join(unknown),
            request=request,
            retryable=False,
        )
    if "date" not in request.parameters:
        raise ProviderRequestError(
            "the AKShare performance-report endpoint requires date (YYYYMMDD)",
            request=request,
            retryable=False,
        )
    report_date = _parse_performance_report_date_parameter(
        request.parameters["date"],
        request=request,
    )
    return {"date": report_date.strftime("%Y%m%d")}


def _dividends_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    if endpoint_name == "stock_fhps_em":
        if listing.market is not ListingMarket.A:
            raise ProviderRequestError(
                "the AKShare dividend-snapshot endpoint supports A-share listings only",
                request=request,
                retryable=False,
            )
        unknown = sorted(set(request.parameters) - _DIVIDEND_SNAPSHOT_PARAMETER_NAMES)
        if unknown:
            raise ProviderRequestError(
                "unsupported AKShare dividend-snapshot parameter(s): "
                + ", ".join(unknown),
                request=request,
                retryable=False,
            )
        if "date" not in request.parameters:
            raise ProviderRequestError(
                "the AKShare dividend-snapshot endpoint requires date (YYYYMMDD)",
                request=request,
                retryable=False,
            )
        report_date = _parse_dividend_snapshot_date_parameter(
            request.parameters["date"],
            request=request,
        )
        return {"date": report_date.strftime("%Y%m%d")}
    if endpoint_name == "stock_dividend_cninfo":
        if listing.market is not ListingMarket.A:
            raise ProviderRequestError(
                "the AKShare A-share dividend endpoint supports A-share listings only",
                request=request,
                retryable=False,
            )
        _reject_unexpected_parameters(request)
        return {"symbol": listing.code}
    if endpoint_name == "stock_hk_dividend_payout_em":
        if listing.market is not ListingMarket.H:
            raise ProviderRequestError(
                "the AKShare H-share dividend endpoint supports H-share listings only",
                request=request,
                retryable=False,
            )
        _reject_unexpected_parameters(request)
        return {"symbol": listing.code}
    raise ProviderRequestError(
        f"unsupported AKShare dividends endpoint {endpoint_name!r}",
        request=request,
        retryable=False,
    )


def _share_capital_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    if endpoint_name == "stock_share_change_cninfo":
        if listing.market is not ListingMarket.A:
            raise ProviderRequestError(
                "the AKShare share-capital endpoint supports A-share listings only",
                request=request,
                retryable=False,
            )
        unknown = sorted(set(request.parameters) - _SHARE_CAPITAL_PARAMETER_NAMES)
        if unknown:
            raise ProviderRequestError(
                "unsupported AKShare share-capital parameter(s): " + ", ".join(unknown),
                request=request,
                retryable=False,
            )
        start_date, start_value = _share_change_date_parameter(
            request.parameters.get("start_date", _SHARE_CHANGE_DEFAULT_START_DATE),
            name="start_date",
            request=request,
        )
        end_date, end_value = _share_change_date_parameter(
            request.parameters.get("end_date", _SHARE_CHANGE_DEFAULT_END_DATE),
            name="end_date",
            request=request,
        )
        if start_value > end_value:
            raise ProviderRequestError(
                "share-capital start_date must not be after end_date",
                request=request,
                retryable=False,
            )
        return {
            "symbol": listing.code,
            "start_date": start_date,
            "end_date": end_date,
        }
    if endpoint_name != "stock_zh_a_gbjg_em":
        raise ProviderRequestError(
            f"unsupported AKShare share-capital endpoint {endpoint_name!r}",
            request=request,
            retryable=False,
        )
    if listing.market is not ListingMarket.A:
        raise ProviderRequestError(
            "the AKShare share-capital endpoint supports A-share listings only",
            request=request,
            retryable=False,
        )
    _reject_unexpected_parameters(request)
    return {"symbol": listing.code}


def _ownership_pledge_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    if endpoint_name != "stock_gpzy_pledge_ratio_em":
        raise ProviderRequestError(
            f"unsupported AKShare ownership-pledge endpoint {endpoint_name!r}",
            request=request,
            retryable=False,
        )
    if listing.market is not ListingMarket.A:
        raise ProviderRequestError(
            "the AKShare ownership-pledge endpoint supports A-share listings only",
            request=request,
            retryable=False,
        )
    unknown = sorted(set(request.parameters) - _OWNERSHIP_PLEDGE_PARAMETER_NAMES)
    if unknown:
        raise ProviderRequestError(
            "unsupported AKShare ownership-pledge parameter(s): " + ", ".join(unknown),
            request=request,
            retryable=False,
        )
    if "date" not in request.parameters:
        raise ProviderRequestError(
            "the AKShare ownership-pledge endpoint requires date (YYYYMMDD)",
            request=request,
            retryable=False,
        )
    raw_date = request.parameters["date"]
    _parse_pledge_date_parameter(raw_date, request=request)
    return {"date": raw_date}


def _corporate_action_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    if endpoint_name == "stock_repurchase_em":
        _reject_unexpected_parameters(request)
        return {}
    if endpoint_name != "stock_allotment_cninfo":
        raise ProviderRequestError(
            f"unsupported AKShare corporate-action endpoint {endpoint_name!r}",
            request=request,
            retryable=False,
        )
    if listing.market is not ListingMarket.A:
        raise ProviderRequestError(
            "the AKShare rights-issue endpoint supports A-share listings only",
            request=request,
            retryable=False,
        )
    unknown = sorted(set(request.parameters) - _CORPORATE_ACTION_PARAMETER_NAMES)
    if unknown:
        raise ProviderRequestError(
            "unsupported AKShare corporate-action parameter(s): " + ", ".join(unknown),
            request=request,
            retryable=False,
        )
    start_date, start_value = _allotment_date_parameter(
        request.parameters.get("start_date", _ALLOTMENT_DEFAULT_START_DATE),
        name="start_date",
        request=request,
    )
    end_date, end_value = _allotment_date_parameter(
        request.parameters.get("end_date", _ALLOTMENT_DEFAULT_END_DATE),
        name="end_date",
        request=request,
    )
    if start_value is not None and end_value is not None and start_value > end_value:
        raise ProviderRequestError(
            "corporate-action start_date must not be after end_date",
            request=request,
            retryable=False,
        )
    return {"symbol": listing.code, "start_date": start_date, "end_date": end_date}


def _allotment_date_parameter(
    raw_value: object,
    *,
    name: str,
    request: ProviderRequest,
) -> tuple[str, date | None]:
    if not isinstance(raw_value, str) or not re.fullmatch(r"\d{8}", raw_value):
        raise ProviderRequestError(
            f"corporate-action {name} must be YYYYMMDD",
            request=request,
            retryable=False,
        )
    if raw_value == _ALLOTMENT_DEFAULT_END_DATE:
        return raw_value, None
    try:
        parsed = datetime.strptime(raw_value, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderRequestError(
            f"corporate-action {name} must be a valid YYYYMMDD date",
            request=request,
            retryable=False,
        ) from exc
    return raw_value, parsed


def _share_change_date_parameter(
    raw_value: object,
    *,
    name: str,
    request: ProviderRequest,
) -> tuple[str, date]:
    if not isinstance(raw_value, str) or not re.fullmatch(r"\d{8}", raw_value):
        raise ProviderRequestError(
            f"share-capital {name} must be YYYYMMDD",
            request=request,
            retryable=False,
        )
    try:
        parsed = datetime.strptime(raw_value, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderRequestError(
            f"share-capital {name} must be a valid YYYYMMDD date",
            request=request,
            retryable=False,
        ) from exc
    return raw_value, parsed


def _parse_pledge_date_parameter(
    raw_value: object,
    *,
    request: ProviderRequest,
) -> date:
    if not isinstance(raw_value, str) or not re.fullmatch(r"\d{8}", raw_value):
        raise ProviderRequestError(
            "ownership-pledge date must be YYYYMMDD",
            request=request,
            retryable=False,
        )
    try:
        return datetime.strptime(raw_value, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderRequestError(
            "ownership-pledge date must be a valid YYYYMMDD date",
            request=request,
            retryable=False,
        ) from exc


def _parse_dividend_snapshot_date_parameter(
    raw_value: object,
    *,
    request: ProviderRequest,
) -> date:
    if not isinstance(raw_value, str) or not re.fullmatch(r"\d{8}", raw_value):
        raise ProviderRequestError(
            "dividend-snapshot date must be YYYYMMDD",
            request=request,
            retryable=False,
        )
    try:
        parsed = datetime.strptime(raw_value, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderRequestError(
            "dividend-snapshot date must be a valid YYYYMMDD date",
            request=request,
            retryable=False,
        ) from exc
    if parsed < date(1990, 12, 31):
        raise ProviderRequestError(
            "dividend-snapshot date must be on or after 19901231",
            request=request,
            retryable=False,
        )
    if (parsed.month, parsed.day) not in {(6, 30), (12, 31)}:
        raise ProviderRequestError(
            "dividend-snapshot date must be a June 30 or December 31 report date",
            request=request,
            retryable=False,
        )
    return parsed


def _parse_earnings_forecast_date_parameter(
    raw_value: object,
    *,
    request: ProviderRequest | None = None,
) -> date:
    if not isinstance(raw_value, str) or not re.fullmatch(r"\d{8}", raw_value):
        raise ProviderRequestError(
            "earnings-forecast date must be YYYYMMDD",
            request=request,
            retryable=False,
        )
    try:
        parsed = datetime.strptime(raw_value, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderRequestError(
            "earnings-forecast date must be a valid YYYYMMDD date",
            request=request,
            retryable=False,
        ) from exc
    if parsed < _EARNINGS_FORECAST_START_DATE:
        raise ProviderRequestError(
            "earnings-forecast date must be on or after 20081231",
            request=request,
            retryable=False,
        )
    if (parsed.month, parsed.day) not in _EARNINGS_FORECAST_QUARTER_ENDS:
        raise ProviderRequestError(
            "earnings-forecast date must be an exact quarter-end report date",
            request=request,
            retryable=False,
        )
    return parsed


def _parse_performance_report_date_parameter(
    raw_value: object,
    *,
    request: ProviderRequest | None = None,
) -> date:
    if not isinstance(raw_value, str) or not re.fullmatch(r"\d{8}", raw_value):
        raise ProviderRequestError(
            "performance-report date must be YYYYMMDD",
            request=request,
            retryable=False,
        )
    try:
        parsed = datetime.strptime(raw_value, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderRequestError(
            "performance-report date must be a valid YYYYMMDD date",
            request=request,
            retryable=False,
        ) from exc
    if parsed < _PERFORMANCE_REPORT_START_DATE:
        raise ProviderRequestError(
            "performance-report date must be on or after 20100331",
            request=request,
            retryable=False,
        )
    if (parsed.month, parsed.day) not in _PERFORMANCE_REPORT_QUARTER_ENDS:
        raise ProviderRequestError(
            "performance-report date must be an exact quarter-end report date",
            request=request,
            retryable=False,
        )
    return parsed


def _financial_statement_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
    *,
    statement_symbol: str,
    statement_label: str,
) -> dict[str, object]:
    unknown = sorted(set(request.parameters) - _FINANCIAL_STATEMENT_PARAMETER_NAMES)
    if unknown:
        raise ProviderRequestError(
            f"unsupported AKShare {statement_label} parameter(s): " + ", ".join(unknown),
            request=request,
            retryable=False,
        )
    if endpoint_name in _OFFICIAL_BALANCE_SHEET_ENDPOINTS:
        if "indicator" in request.parameters:
            raise ProviderRequestError(
                f"the A-share aggregate {statement_label} endpoint does not accept indicator",
                request=request,
                retryable=False,
            )
        if "statement_date" not in request.parameters:
            raise ProviderRequestError(
                f"the A-share aggregate {statement_label} endpoint requires "
                "statement_date (YYYY-MM-DD or YYYYMMDD)",
                request=request,
                retryable=False,
            )
        statement_date = _parse_statement_date_parameter(
            request.parameters["statement_date"],
            request=request,
        )
        return {"date": statement_date.strftime("%Y%m%d")}
    indicator = str(request.parameters.get("indicator", "annual")).lower()
    indicators = {
        "annual": "年度",
        "yearly": "年度",
        "reporting": "报告期",
        "report": "报告期",
        "年度": "年度",
        "报告期": "报告期",
    }
    if indicator not in indicators:
        raise ProviderRequestError(
            f"{statement_label} indicator must be annual or reporting",
            request=request,
            retryable=False,
        )
    if endpoint_name == "stock_cash_flow_sheet_by_report_em":
        if "statement_date" in request.parameters:
            raise ProviderRequestError(
                f"the A-share report-period {statement_label} endpoint does not "
                "accept statement_date",
                request=request,
                retryable=False,
            )
        if "indicator" in request.parameters:
            raise ProviderRequestError(
                f"the A-share report-period {statement_label} endpoint does not accept indicator",
                request=request,
                retryable=False,
            )
        return {"symbol": listing.canonical_id}
    if endpoint_name == "stock_profit_sheet_by_report_em":
        if "statement_date" in request.parameters:
            raise ProviderRequestError(
                f"the A-share report-period {statement_label} endpoint does not "
                "accept statement_date",
                request=request,
                retryable=False,
            )
        if "indicator" in request.parameters:
            raise ProviderRequestError(
                f"the A-share report-period {statement_label} endpoint does not accept indicator",
                request=request,
                retryable=False,
            )
        return {"symbol": listing.canonical_id}
    if endpoint_name == "stock_balance_sheet_by_report_em":
        if "statement_date" in request.parameters:
            raise ProviderRequestError(
                f"the A-share report-period {statement_label} endpoint does not "
                "accept statement_date",
                request=request,
                retryable=False,
            )
        if "indicator" in request.parameters:
            raise ProviderRequestError(
                f"the A-share report-period {statement_label} endpoint does not accept indicator",
                request=request,
                retryable=False,
            )
        return {"symbol": listing.canonical_id}
    if endpoint_name == "stock_financial_report_sina":
        if "statement_date" in request.parameters:
            raise ProviderRequestError(
                f"the Sina {statement_label} endpoint does not accept statement_date",
                request=request,
                retryable=False,
            )
        if listing.market is not ListingMarket.A:
            raise ProviderRequestError(
                "the Sina financial-report endpoint supports A-share listings only",
                request=request,
                retryable=False,
            )
        return {"stock": listing.canonical_id.lower(), "symbol": statement_symbol}
    if endpoint_name == "stock_financial_hk_report_em":
        if "statement_date" in request.parameters:
            raise ProviderRequestError(
                f"the H-share {statement_label} endpoint does not accept statement_date",
                request=request,
                retryable=False,
            )
        return {
            "stock": listing.code,
            "symbol": statement_symbol,
            "indicator": indicators[indicator],
        }
    raise ProviderRequestError(
        f"unsupported AKShare {statement_label} endpoint {endpoint_name!r}",
        request=request,
        retryable=False,
    )


def _parse_listing_id(
    entity_id: str,
    *,
    provider: ProviderIdentity | None = None,
    request: ProviderRequest | None = None,
) -> _ListingRef:
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ProviderRequestError(
            "entity_id must identify an A or H listing",
            provider=provider,
            request=request,
            retryable=False,
        )
    value = re.sub(r"\s+", "", entity_id).upper()

    match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", value)
    if match:
        exchange, code = match.groups()
        return _ListingRef(ListingMarket.A, code, exchange + code)
    match = re.fullmatch(r"HK(\d{1,5})", value)
    if match:
        code = match.group(1).zfill(5)
        return _ListingRef(ListingMarket.H, code, "HK" + code)
    match = re.fullmatch(r"A[:.]?(\d{6})", value)
    if match:
        code = match.group(1)
        return _ListingRef(ListingMarket.A, code, _inferred_a_prefix(code) + code)
    match = re.fullmatch(r"H[:.]?(\d{1,5})", value)
    if match:
        code = match.group(1).zfill(5)
        return _ListingRef(ListingMarket.H, code, "HK" + code)
    match = re.fullmatch(r"(\d{6})\.(SH|SS|SZ|BJ)", value)
    if match:
        code, exchange = match.groups()
        exchange = "SH" if exchange == "SS" else exchange
        return _ListingRef(ListingMarket.A, code, exchange + code)
    match = re.fullmatch(r"(\d{1,5})\.HK", value)
    if match:
        code = match.group(1).zfill(5)
        return _ListingRef(ListingMarket.H, code, "HK" + code)
    if re.fullmatch(r"\d{6}", value):
        return _ListingRef(ListingMarket.A, value, _inferred_a_prefix(value) + value)
    if re.fullmatch(r"\d{1,5}", value):
        code = value.zfill(5)
        return _ListingRef(ListingMarket.H, code, "HK" + code)

    raise ProviderRequestError(
        f"unsupported A/H listing identifier: {entity_id!r}",
        provider=provider,
        request=request,
        retryable=False,
    )


def _inferred_a_prefix(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def _same_listing(canonical_id: str, other: str) -> bool:
    try:
        return canonical_id == _parse_listing_id(other).canonical_id
    except ProviderError:
        return canonical_id == str(other).strip().upper()


def _canonical_row_code(value: object, market: ListingMarket) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        text = str(int(numeric)) if numeric.is_integer() else str(numeric)
    else:
        text = str(value).strip().upper()
    if text.lower() in _MISSING_TEXT:
        return None
    digits = re.findall(r"\d+", text)
    if not digits:
        return None
    code = "".join(digits)
    if market is ListingMarket.A:
        if len(code) > 6:
            code = code[-6:]
        return code.zfill(6)
    if len(code) > 5:
        code = code[-5:]
    return code.zfill(5)


def _row_code(row: Mapping[str, JSONValue], market: ListingMarket) -> str | None:
    if market is ListingMarket.A:
        keys = (
            "A股代码",
            "股票代码",
            "证券代码",
            "SECURITY_CODE",
            "code",
            "symbol",
            "代码",
        )
    else:
        keys = (
            "H股代码",
            "SECURITY_CODE",
            "证券代码",
            "股票代码",
            "code",
            "symbol",
            "代码",
        )
    for key in keys:
        if key in row:
            code = _canonical_row_code(row[key], market)
            if code is not None:
                return code
    return None


def _to_json_value(value: object, *, path: str = "response") -> JSONValue:
    """Convert pandas/numpy-like results to strict JSON without zero-filling."""

    if value is None:
        return None
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    if isinstance(value, (str, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, Real) and not isinstance(value, bool):
        numeric = float(value)
        if math.isnan(numeric):
            return None
        if not math.isfinite(numeric):
            raise ProviderResponseError(f"{path} contains infinity")
        return numeric
    if isinstance(value, Mapping):
        converted: dict[str, JSONValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ProviderResponseError(f"{path} has a non-string object key")
            converted[key] = _to_json_value(child, path=f"{path}.{key}")
        return converted
    if isinstance(value, (list, tuple)):
        return [_to_json_value(child, path=f"{path}[{index}]") for index, child in enumerate(value)]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            tabular = to_dict(orient="records")
        except TypeError:
            try:
                tabular = to_dict("records")
            except Exception as exc:
                raise ProviderResponseError(f"{path} could not be converted to records") from exc
        return _to_json_value(tabular, path=path)

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _to_json_value(item(), path=path)
        except Exception as exc:
            if isinstance(exc, ProviderResponseError):
                raise
            raise ProviderResponseError(f"{path} contains an unsupported scalar") from exc
    raise ProviderResponseError(f"{path} has unsupported type {type(value).__name__}")


def _table_rows(
    payload: JSONValue,
    *,
    provider: ProviderIdentity | None = None,
    request: ProviderRequest | None = None,
) -> list[dict[str, JSONValue]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, list):
            payload = data
        else:
            return [dict(payload)]
    if not isinstance(payload, list):
        raise ProviderResponseError(
            "tabular AKShare response must be an object, array or null",
            provider=provider,
            request=request,
        )
    rows: list[dict[str, JSONValue]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ProviderResponseError(
                f"AKShare tabular response row {index} is not an object",
                provider=provider,
                request=request,
            )
        rows.append(dict(item))
    return rows


def _select_listing_row(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> dict[str, JSONValue]:
    matches = [row for row in rows if _row_code(row, listing.market) == listing.code]
    if len(matches) == 1:
        return dict(matches[0])
    if len(matches) > 1:
        raise ProviderResponseError(
            f"AKShare returned ambiguous rows for {request.entity_id!r}",
            provider=provider,
            request=request,
        )
    if len(rows) == 1 and _row_code(rows[0], listing.market) is None:
        return dict(rows[0])
    raise ProviderResponseError(
        f"AKShare returned no row for {request.entity_id!r}",
        provider=provider,
        request=request,
    )


def _select_listing_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    provider: ProviderIdentity,
    request: ProviderRequest,
    row_label: str = "corporate-action",
) -> list[dict[str, JSONValue]]:
    """Filter a universe response without discarding matching history rows."""

    if any(_row_code(row, listing.market) is None for row in rows):
        raise ProviderResponseError(
            f"AKShare returned a {row_label} row without a listing code for "
            f"{request.entity_id!r}",
            provider=provider,
            request=request,
        )
    return [dict(row) for row in rows if _row_code(row, listing.market) == listing.code]


def _validate_corporate_action_provider_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> None:
    """Reject explicitly cross-listed rows before storing raw evidence."""

    for row in rows:
        row_code = _row_code(row, listing.market)
        if row_code is not None and row_code != listing.code:
            raise ProviderResponseError(
                f"AKShare returned corporate-action row entity {row_code!r} for "
                f"requested listing {listing.canonical_id!r}",
                provider=provider,
                request=request,
            )


def _validate_dividend_snapshot_provider_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> None:
    """Reject an A-share distribution universe row without an explicit code."""

    for row in rows:
        if _row_code(row, ListingMarket.A) is None:
            raise ProviderResponseError(
                f"AKShare returned a dividend-snapshot row without a listing code for "
                f"{listing.canonical_id!r}",
                provider=provider,
                request=request,
            )


def _validate_earnings_forecast_provider_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    report_period: date,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> None:
    """Validate an earnings-forecast universe before filtering its rows."""

    for row in rows:
        if _row_code(row, ListingMarket.A) is None:
            raise ProviderResponseError(
                f"AKShare returned an earnings-forecast row without a listing code for "
                f"{request.entity_id!r}",
                provider=provider,
                request=request,
            )
        found, raw_period = _lookup(row, _EARNINGS_FORECAST_PERIOD_FIELDS)
        if not found or raw_period is None or _text_value(raw_period) in _MISSING_TEXT:
            continue
        row_period = _parse_date_value(raw_period)
        if row_period is None:
            raise ProviderResponseError(
                f"AKShare returned an earnings-forecast row with an invalid report date "
                f"for {request.entity_id!r}",
                provider=provider,
                request=request,
            )
        if row_period != report_period:
            raise ProviderResponseError(
                f"AKShare returned earnings-forecast row period {row_period.isoformat()!r}; "
                f"requested {report_period.isoformat()!r}",
                provider=provider,
                request=request,
            )


def _validate_performance_report_provider_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> None:
    """Validate a performance-report universe before filtering its rows."""

    for row in rows:
        if _row_code(row, ListingMarket.A) is None:
            raise ProviderResponseError(
                f"AKShare returned a performance-report row without a listing code for "
                f"{request.entity_id!r}",
                provider=provider,
                request=request,
            )


def _validate_share_capital_provider_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> None:
    """Reject explicitly cross-listed rows before storing share-change evidence."""

    for row in rows:
        row_code = _row_code(row, ListingMarket.A)
        if row_code is not None and row_code != listing.code:
            raise ProviderResponseError(
                f"AKShare returned share-capital row entity {row_code!r} for "
                f"requested listing {listing.canonical_id!r}",
                provider=provider,
                request=request,
            )


def _validate_corporate_action_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
) -> None:
    """Keep replayed corporate-action payloads bound to their request entity."""

    for row in rows:
        row_code = _row_code(row, listing.market)
        if row_code is None:
            raise ProviderNormalizationError(
                "corporate-action row has no explicit listing code"
            )
        if row_code != listing.code:
            raise ProviderNormalizationError(
                f"corporate-action row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )


def _validate_corporate_action_normalizer_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
) -> None:
    """Keep manually supplied raw records inside the requested listing boundary."""

    for row in rows:
        row_code = _row_code(row, listing.market)
        if row_code is not None and row_code != listing.code:
            raise ProviderNormalizationError(
                f"corporate-action row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )


def _validate_dividend_snapshot_normalizer_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
) -> None:
    """Keep replayed dividend-distribution rows inside the requested listing."""

    for row in rows:
        row_code = _row_code(row, ListingMarket.A)
        if row_code is None:
            raise ProviderNormalizationError(
                "dividend-snapshot row has no explicit listing code"
            )
        if row_code != listing.code:
            raise ProviderNormalizationError(
                f"dividend-snapshot row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )


def _validate_earnings_forecast_normalizer_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    report_period: date,
) -> None:
    """Keep replayed earnings-forecast rows inside the requested listing/period."""

    for row in rows:
        row_code = _row_code(row, ListingMarket.A)
        if row_code is None:
            raise ProviderNormalizationError(
                "earnings-forecast row has no explicit listing code"
            )
        if row_code != listing.code:
            raise ProviderNormalizationError(
                f"earnings-forecast row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )
        found, raw_period = _lookup(row, _EARNINGS_FORECAST_PERIOD_FIELDS)
        if not found or raw_period is None or _text_value(raw_period) in _MISSING_TEXT:
            continue
        row_date = _parse_date_value(raw_period)
        if row_date is None:
            raise ProviderNormalizationError(
                "earnings-forecast row has an invalid report date"
            )
        if row_date != report_period:
            raise ProviderNormalizationError(
                f"earnings-forecast row period {row_date.isoformat()!r} does not match "
                f"requested report period {report_period.isoformat()!r}"
            )


def _validate_performance_report_normalizer_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
) -> None:
    """Keep replayed performance-report rows inside the requested listing."""

    for row in rows:
        row_code = _row_code(row, ListingMarket.A)
        if row_code is None:
            raise ProviderNormalizationError(
                "performance-report row has no explicit listing code"
            )
        if row_code != listing.code:
            raise ProviderNormalizationError(
                f"performance-report row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )


def _validate_share_capital_normalizer_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
) -> None:
    """Keep replayed share-change payloads inside the requested listing boundary."""

    for row in rows:
        row_code = _row_code(row, ListingMarket.A)
        if row_code is not None and row_code != listing.code:
            raise ProviderNormalizationError(
                f"share-capital row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )


def _validate_ownership_pledge_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    observation_date: date,
) -> None:
    """Keep replayed pledge snapshots bound to the requested A-share listing."""

    for row in rows:
        row_code = _row_code(row, listing.market)
        if row_code is None:
            raise ProviderNormalizationError(
                "ownership-pledge row has no explicit listing code"
            )
        if row_code != listing.code:
            raise ProviderNormalizationError(
                f"ownership-pledge row entity {row_code!r} does not match "
                f"requested listing {listing.canonical_id!r}"
            )
        row_date = _observation_date(row)
        if row_date is None:
            raise ProviderNormalizationError(
                "ownership-pledge row has no exact observation date"
            )
        if row_date != observation_date:
            raise ProviderNormalizationError(
                f"ownership-pledge row date {row_date.isoformat()!r} does not match "
                f"requested observation date {observation_date.isoformat()!r}"
            )


def _validate_ownership_pledge_provider_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    requested_date: date,
    provider: ProviderIdentity,
    request: ProviderRequest,
) -> None:
    """Validate a universe snapshot before filtering it into raw evidence."""

    for row in rows:
        row_code = _row_code(row, listing.market)
        if row_code is None:
            raise ProviderResponseError(
                f"AKShare returned an ownership-pledge row without a listing code for "
                f"{request.entity_id!r}",
                provider=provider,
                request=request,
            )
        row_date = _observation_date(row)
        if row_date is None:
            raise ProviderResponseError(
                f"AKShare returned an ownership-pledge row without an observation date for "
                f"{request.entity_id!r}",
                provider=provider,
                request=request,
            )
        if row_date != requested_date:
            raise ProviderResponseError(
                f"AKShare returned ownership-pledge row date {row_date.isoformat()!r}; "
                f"requested {requested_date.isoformat()!r}",
                provider=provider,
                request=request,
            )


def _history_kwargs(
    endpoint_name: str,
    listing: _ListingRef,
    request: ProviderRequest,
) -> dict[str, object]:
    parameters = dict(request.parameters)
    unknown = sorted(set(parameters) - _HISTORY_PARAMETER_NAMES)
    if unknown:
        raise ProviderRequestError(
            "unsupported AKShare history parameter(s): " + ", ".join(unknown),
            request=request,
            retryable=False,
        )
    period = str(parameters.get("period", "daily")).lower()
    adjust = str(parameters.get("adjust", ""))
    if period not in {"daily", "weekly", "monthly"}:
        raise ProviderRequestError(
            "history period must be daily, weekly or monthly",
            request=request,
            retryable=False,
        )
    if adjust not in {"", "qfq", "hfq"}:
        raise ProviderRequestError(
            "history adjust must be '', 'qfq' or 'hfq'",
            request=request,
            retryable=False,
        )
    if listing.market is ListingMarket.H and period != "daily":
        raise ProviderRequestError(
            "the AKShare H-share history endpoint supports daily observations only",
            request=request,
            retryable=False,
        )

    start_text, start_date = _date_parameter(parameters, "start_date", "start_year")
    end_text, end_date = _date_parameter(parameters, "end_date", "end_year")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ProviderRequestError(
            "history start_date must not be after end_date",
            request=request,
            retryable=False,
        )

    if endpoint_name == "stock_hk_daily":
        return {"symbol": listing.code, "adjust": adjust}
    if endpoint_name == "stock_zh_ah_daily":
        kwargs: dict[str, object] = {"symbol": listing.code, "adjust": adjust}
        if start_date is not None:
            kwargs["start_year"] = str(start_date.year)
        if end_date is not None:
            kwargs["end_year"] = str(end_date.year)
        return kwargs

    if endpoint_name == "stock_zh_a_daily":
        kwargs = {
            "symbol": listing.canonical_id[:2].lower() + listing.code,
            "adjust": adjust,
        }
        if start_text is not None:
            kwargs["start_date"] = start_text
        if end_text is not None:
            kwargs["end_date"] = end_text
        return kwargs

    kwargs = {"symbol": listing.code, "period": period, "adjust": adjust}
    if start_text is not None:
        kwargs["start_date"] = start_text
    if end_text is not None:
        kwargs["end_date"] = end_text
    return kwargs


def _date_parameter(
    parameters: Mapping[str, JSONValue],
    date_name: str,
    year_name: str,
) -> tuple[str | None, date | None]:
    raw = parameters.get(date_name)
    if raw is None:
        raw = parameters.get(year_name)
        if raw is not None:
            text = str(raw)
            if not re.fullmatch(r"\d{4}", text):
                raise ProviderRequestError(
                    f"{year_name} must be a four-digit year", retryable=False
                )
            text = text + ("0101" if date_name == "start_date" else "1231")
        else:
            return None, None
    else:
        text = str(raw)
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
            return parsed.strftime("%Y%m%d"), parsed
        except ValueError:
            continue
    raise ProviderRequestError(f"{date_name} must be YYYY-MM-DD or YYYYMMDD", retryable=False)


def _reject_unexpected_parameters(request: ProviderRequest) -> None:
    if request.parameters:
        names = ", ".join(sorted(request.parameters))
        raise ProviderRequestError(
            f"{request.category.value} does not accept request parameters: {names}",
            request=request,
            retryable=False,
        )


def _has_history_range(parameters: Mapping[str, JSONValue]) -> bool:
    return any(name in parameters for name in ("start_date", "end_date", "start_year", "end_year"))


def _is_probably_retryable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "timeout",
            "timed out",
            "temporarily",
            "rate limit",
            "too many requests",
            "quota",
            "connection",
            "503",
            "502",
            "504",
        )
    )


def _deduplicate_and_sort_records(
    records: Sequence[RawProviderRecord],
) -> list[RawProviderRecord]:
    unique: dict[bytes, RawProviderRecord] = {}
    payloads: dict[bytes, bytes] = {}
    for record in records:
        if not isinstance(record, RawProviderRecord):
            raise TypeError("records must contain RawProviderRecord values")
        identity = canonical_json_bytes(
            {
                "provider": record.provider.as_dict(),
                "request": record.request.as_dict(),
                "retrieved_at": record.retrieved_at.isoformat(),
            }
        )
        payload = canonical_json_bytes(record.raw_payload)
        if identity in unique:
            if payloads[identity] != payload:
                raise ProviderNormalizationError(
                    "raw records with the same request and retrieval timestamp disagree"
                )
            continue
        unique[identity] = record
        payloads[identity] = payload
    return sorted(
        unique.values(),
        key=lambda record: (
            record.request.category.value,
            record.request.entity_id,
            record.retrieved_at.isoformat(),
            canonical_json_bytes(record.raw_payload),
        ),
    )


def _evidence_for_record(record: RawProviderRecord, *, confidence: float) -> Evidence:
    cache_key = CacheKey.from_record(record)
    locator = (
        f"category={record.request.category.value}; entity={record.request.entity_id}; "
        f"parameters={canonical_json_bytes(record.request.parameters).decode('utf-8')}"
    )
    return Evidence(
        id=deterministic_id(
            "evidence",
            record.provider.provider_id,
            record.provider.provider_version,
            record.request.as_dict(),
            record.retrieved_at.isoformat(),
        ),
        direction=EvidenceDirection.CONTEXT,
        strength=EvidenceStrength.E1,
        statement=(
            f"AKShare returned {record.request.category.value} data for "
            f"{record.request.entity_id}."
        ),
        source=Source(
            type=SourceType.STRUCTURED_DATA_VENDOR,
            title=(
                f"{record.provider.source_name} structured data "
                f"({record.provider.provider_version})"
            ),
            issuer=record.provider.source_name,
            url=record.source_uri,
            document_id=cache_key.digest,
            locator=locator,
        ),
        confidence=confidence,
        notes=(
            f"Retrieved at {record.retrieved_at.isoformat()}; raw response is replayable "
            "through the provider cache."
        ),
    )


def _single_normalization_row(
    rows: Sequence[Mapping[str, JSONValue]], record: RawProviderRecord
) -> Mapping[str, JSONValue]:
    if len(rows) != 1:
        raise ProviderNormalizationError(
            f"{record.request.category.value} must contain exactly one selected row; "
            f"got {len(rows)}"
        )
    return rows[0]


def _lookup(
    row: Mapping[str, JSONValue], aliases: Sequence[str]
) -> tuple[bool, JSONValue | None]:
    for alias in aliases:
        if alias in row:
            return True, row[alias]
    return False, None


def _text_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (date, datetime)):
        text = value.isoformat()
    else:
        text = str(value).strip()
    return None if text.lower() in _MISSING_TEXT else text


def _number_value(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ProviderNormalizationError(f"{field} cannot be boolean")
    if isinstance(value, Real):
        numeric = float(value)
    else:
        text = str(value).strip()
        if text.lower() in _MISSING_TEXT:
            return None
        text = text.replace(",", "").rstrip("%")
        try:
            numeric = float(text)
        except ValueError as exc:
            raise ProviderNormalizationError(
                f"{field} value {value!r} is not numeric or null"
            ) from exc
    if math.isnan(numeric):
        return None
    if not math.isfinite(numeric):
        raise ProviderNormalizationError(f"{field} cannot be infinite")
    return numeric


def _currency_for(market: ListingMarket) -> str:
    return "CNY" if market is ListingMarket.A else "HKD"


def _listing_period(as_of: date, listing: _ListingRef, *, primary: bool) -> str:
    base = f"AS_OF_{as_of.isoformat()}"
    return base if primary else f"{base}:{listing.canonical_id}"


def _map_company_metadata(row: Mapping[str, JSONValue]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for field, aliases in _COMPANY_METADATA_FIELDS.items():
        found, value = _lookup(row, aliases)
        if found:
            result[field] = _text_value(value)
    return result


def _enrich_company(company: Company, context: Mapping[str, str]) -> Company:
    updates: dict[str, str] = {}
    if company.legal_name is None and context.get("company_name"):
        updates["legal_name"] = context["company_name"]
    if company.industry is None and context.get("company_industry"):
        updates["industry"] = context["company_industry"]
    if company.country_or_region is None and context.get("company_registration_region"):
        updates["country_or_region"] = context["company_registration_region"]
    if company.fiscal_year_end is None and context.get("fiscal_year_end"):
        updates["fiscal_year_end"] = context["fiscal_year_end"]
    return company.model_copy(update=updates) if updates else company


_CASH_FLOW_FIELDS = {
    "reported_cfo": (
        "经营活动产生的现金流量净额",
        "经营活动现金流量净额",
        "经营活动产生的现金流量净额(元)",
        "经营活动现金流量净额(元)",
        "NETCASH_OPERATE",
        "NETCASH_OPERATE_CONTINUOUS",
        "OPERATE_CASH_FLOW",
    ),
    "acquisition_cash": (
        "取得子公司及其他营业单位支付的现金净额",
        "取得子公司及其他营业单位支付的现金",
        "CASH_PAID_FOR_ACQUISITION",
    ),
}

_INCOME_STATEMENT_FIELDS = {
    "parent_net_profit": (
        "归属于母公司所有者的净利润",
        "归属于母公司股东的净利润",
        "归属于母公司所有者的净利润(元)",
        "归属于母公司股东的净利润(元)",
        "归母净利润",
        "PARENT_NETPROFIT",
        "PARENT_NET_PROFIT",
        "NET_PROFIT_ATTRIBUTABLE_TO_PARENT",
        "NET_PROFIT_ATTRIBUTABLE_TO_OWNERS",
        "PROFIT_ATTRIBUTABLE_TO_EQUITY_HOLDERS_OF_THE_COMPANY",
        "PROFIT_ATTRIBUTABLE_TO_OWNERS_OF_THE_COMPANY",
        "Profit attributable to equity holders of the Company",
        "Profit attributable to owners of the Company",
        "Profit attributable to owners of the parent",
        "股东应占溢利",
        "股东应占溢利（亏损）",
        "股东应占利润",
        "本公司拥有人应占溢利",
        "本公司拥有人应占利润",
        "母公司拥有人应占溢利",
    ),
    "consolidated_net_profit": (
        "净利润",
        "净利润(元)",
        "净利润（元）",
        "NETPROFIT",
        "NET_PROFIT",
        "PROFIT_FOR_THE_PERIOD",
        "PROFIT_FOR_THE_YEAR",
        "PROFIT_FOR_THE_PERIOD (LOSS)",
        "PROFIT_FOR_THE_YEAR (LOSS)",
        "Profit for the period",
        "Profit for the year",
        "Profit (loss) for the period",
        "Profit (loss) for the year",
        "Net profit",
        "Net income",
        "除税后溢利",
        "除税后利润",
        "本年度溢利",
        "本年度利润",
        "年内溢利",
        "年内利润",
        "期内溢利",
        "期内利润",
    ),
}

_BALANCE_SHEET_FIELDS = {
    "book_cash": (
        "货币资金",
        "货币资金(元)",
        "资产-货币资金",
        "现金及现金等价物",
        "现金及现金等价物(元)",
        "MONETARYFUNDS",
        "CASH_AND_CASH_EQUIVALENTS",
        "CASH_CASH_EQUIVALENTS",
        "CASH_AND_BANK_BALANCES",
        "Cash and cash equivalents",
        "Cash and bank balances",
    ),
    "reported_interest_bearing_debt": (
        "有息负债合计",
        "有息负债",
        "有息债务合计",
        "有息债务",
        "带息负债合计",
        "带息负债",
        "TOTAL_INTEREST_BEARING_DEBT",
        "INTEREST_BEARING_DEBT",
        "TOTAL_INTEREST_BEARING_LIABILITIES",
        "INTEREST_BEARING_LIABILITIES",
        "Total interest-bearing debt",
        "Interest-bearing debt",
        "Total interest bearing debt",
        "Interest bearing debt",
    ),
    "parent_equity": (
        "归属于母公司所有者权益合计",
        "归属于母公司股东权益合计",
        "归属于母公司所有者权益",
        "归属于母公司股东权益",
        "归属于母公司所有者权益（或股东权益）合计",
        "归属于母公司所有者权益(或股东权益)合计",
        "归属于母公司股东的权益合计",
        "TOTAL_PARENT_EQUITY",
        "PARENT_EQUITY",
        "TOTAL_EQUITY_ATTRIBUTABLE_TO_OWNERS_OF_THE_PARENT",
        "EQUITY_ATTRIBUTABLE_TO_OWNERS_OF_THE_PARENT",
        "EQUITY_ATTRIBUTABLE_TO_OWNERS_OF_THE_COMPANY",
        "Total equity attributable to owners of the Company",
        "Equity attributable to owners of the Company",
        "Total equity attributable to owners of the parent",
        "Equity attributable to owners of the parent",
        "Total equity attributable to equity holders of the Company",
    ),
    "total_equity": (
        "所有者权益合计",
        "所有者权益(或股东权益)合计",
        "所有者权益（或股东权益）合计",
        "股东权益合计",
        "所有者权益",
        "TOTAL_EQUITY",
        "TOTAL_OWNER_EQUITY",
        "TOTAL_SHAREHOLDER_EQUITY",
        "Total equity",
        "Total shareholders' equity",
    ),
}

_BALANCE_SHEET_CRITICAL_FIELDS = tuple(_BALANCE_SHEET_FIELDS)

_STATEMENT_PERIOD_FIELDS = (
    "报告日",
    "报告日期",
    "报告期",
    "REPORT_DATE",
    "STD_REPORT_DATE",
    "STD_REPORT_DATE_NAME",
)
_EARNINGS_FORECAST_PERIOD_FIELDS = (
    "报告日期",
    "报告期",
    "REPORT_DATE",
    "report_date",
)
_STATEMENT_CURRENCY_FIELDS = ("币种", "CURRENCY", "CURRENCY_NAME")
_LONG_STATEMENT_ITEM_FIELDS = ("STD_ITEM_NAME", "项目名称", "科目名称", "ITEM_NAME")
_LONG_STATEMENT_VALUE_FIELDS = ("AMOUNT", "金额", "VALUE", "ITEM_VALUE")


def _map_cash_flow_statement(
    record: RawProviderRecord,
    evidence: Evidence,
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    primary: bool,
    add_fact: Callable[..., None],
) -> tuple[int, int]:
    """Map only unambiguous reported cash-flow lines from A/H statement shapes."""

    mapped_periods, counts = _map_financial_statement(
        record,
        evidence,
        rows,
        listing,
        primary=primary,
        add_fact=add_fact,
        field_aliases=_CASH_FLOW_FIELDS,
        statement_label="cash-flow",
        pivot_long=_pivot_long_cash_flow_rows,
    )
    return mapped_periods, counts["reported_cfo"]


def _map_income_statement(
    record: RawProviderRecord,
    evidence: Evidence,
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    primary: bool,
    add_fact: Callable[..., None],
) -> tuple[int, dict[str, int]]:
    """Map only explicit consolidated and parent-attributable net profit."""

    return _map_financial_statement(
        record,
        evidence,
        rows,
        listing,
        primary=primary,
        add_fact=add_fact,
        field_aliases=_INCOME_STATEMENT_FIELDS,
        statement_label="income",
        pivot_long=_pivot_long_income_statement_rows,
    )


def _map_balance_sheet(
    record: RawProviderRecord,
    evidence: Evidence,
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    primary: bool,
    add_fact: Callable[..., None],
) -> tuple[int, dict[str, int]]:
    """Map only explicit cash, equity and interest-bearing-debt totals."""

    return _map_financial_statement(
        record,
        evidence,
        rows,
        listing,
        primary=primary,
        add_fact=add_fact,
        field_aliases=_BALANCE_SHEET_FIELDS,
        statement_label="balance-sheet",
        pivot_long=_pivot_long_balance_sheet_rows,
    )


def _map_financial_statement(
    record: RawProviderRecord,
    evidence: Evidence,
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    primary: bool,
    add_fact: Callable[..., None],
    field_aliases: Mapping[str, Sequence[str]],
    statement_label: str,
    pivot_long: Callable[
        [Sequence[Mapping[str, JSONValue]], RawProviderRecord],
        list[tuple[dict[str, JSONValue], Mapping[str, JSONValue]]],
    ],
) -> tuple[int, dict[str, int]]:
    if not rows:
        return 0, {field: 0 for field in field_aliases}
    for row in rows:
        _validate_statement_entity(row, listing, statement_label=statement_label)
    statement_currencies = _statement_currencies_by_period(
        rows,
        record=record,
        statement_label=statement_label,
    )
    is_long = any(
        _lookup(row, _LONG_STATEMENT_ITEM_FIELDS)[0]
        or _lookup(row, _LONG_STATEMENT_VALUE_FIELDS)[0]
        for row in rows
    )
    period_rows = pivot_long(rows, record) if is_long else [(row, row) for row in rows]

    mapped_periods = 0
    field_counts = {field: 0 for field in field_aliases}
    seen_periods: set[str] = set()
    for period_row, _ in period_rows:
        statement_date = _statement_date(period_row, record=record)
        if statement_date is None:
            raise ProviderNormalizationError(
                f"{statement_label} statement row for {record.request.entity_id!r} "
                "has no exact report date"
            )
        period = statement_date.isoformat()
        if not primary:
            period = f"{listing.canonical_id}:{period}"
        if period in seen_periods:
            raise ProviderNormalizationError(
                f"ambiguous duplicate {statement_label} statement period {period!r}"
            )
        seen_periods.add(period)
        currency = statement_currencies.get(statement_date.isoformat())
        found_any = False
        for field, aliases in field_aliases.items():
            found, raw_value = _lookup(period_row, (field, *aliases))
            if not found:
                continue
            value = _number_value(raw_value, field=field)
            add_fact(
                record,
                evidence,
                field=field,
                value=value,
                period=period,
                currency=currency,
                unit="reported_currency_amount",
            )
            found_any = True
            if value is not None:
                field_counts[field] += 1
        if found_any:
            mapped_periods += 1
    return mapped_periods, field_counts


def _validate_statement_entity(
    row: Mapping[str, JSONValue],
    listing: _ListingRef,
    *,
    statement_label: str,
) -> None:
    """Reject an explicit statement row code that is not the requested listing.

    Some statement endpoints return rows without a security-code column because
    the request itself is listing-scoped. Those rows remain valid. When the
    upstream does provide a code, however, silently trusting the endpoint would
    allow a mixed-entity payload to cross the raw-to-fact boundary.
    """

    row_code = _row_code(row, listing.market)
    if row_code is not None and row_code != listing.code:
        raise ProviderNormalizationError(
            f"{statement_label} statement row entity {row_code!r} does not match "
            f"requested listing {listing.canonical_id!r}"
        )


def _pivot_long_cash_flow_rows(
    rows: Sequence[Mapping[str, JSONValue]], record: RawProviderRecord
) -> list[tuple[dict[str, JSONValue], Mapping[str, JSONValue]]]:
    return _pivot_long_statement_rows(
        rows,
        record,
        field_aliases=_CASH_FLOW_FIELDS,
        statement_label="cash-flow",
    )


def _pivot_long_income_statement_rows(
    rows: Sequence[Mapping[str, JSONValue]], record: RawProviderRecord
) -> list[tuple[dict[str, JSONValue], Mapping[str, JSONValue]]]:
    return _pivot_long_statement_rows(
        rows,
        record,
        field_aliases=_INCOME_STATEMENT_FIELDS,
        statement_label="income",
    )


def _pivot_long_balance_sheet_rows(
    rows: Sequence[Mapping[str, JSONValue]], record: RawProviderRecord
) -> list[tuple[dict[str, JSONValue], Mapping[str, JSONValue]]]:
    return _pivot_long_statement_rows(
        rows,
        record,
        field_aliases=_BALANCE_SHEET_FIELDS,
        statement_label="balance-sheet",
    )


def _pivot_long_statement_rows(
    rows: Sequence[Mapping[str, JSONValue]],
    record: RawProviderRecord,
    *,
    field_aliases: Mapping[str, Sequence[str]],
    statement_label: str,
) -> list[tuple[dict[str, JSONValue], Mapping[str, JSONValue]]]:
    grouped: dict[str, dict[str, JSONValue]] = {}
    seen_items: dict[str, set[str]] = {}
    source_rows: dict[str, Mapping[str, JSONValue]] = {}
    normalized_aliases = {
        field: {field, *(alias.strip().upper() for alias in aliases)}
        for field, aliases in field_aliases.items()
    }
    for row in rows:
        statement_date = _statement_date(row, record=record)
        if statement_date is None:
            raise ProviderNormalizationError(
                f"{statement_label} statement row for {record.request.entity_id!r} "
                "has no exact report date"
            )
        item_found, item = _lookup(row, _LONG_STATEMENT_ITEM_FIELDS)
        value_found, value = _lookup(row, _LONG_STATEMENT_VALUE_FIELDS)
        if not item_found or not value_found or _text_value(item) is None:
            raise ProviderNormalizationError(
                f"long {statement_label} statement rows require a non-empty item name "
                "and amount"
            )
        period = statement_date.isoformat()
        item_name = _text_value(item)
        assert item_name is not None
        normalized_item = item_name.strip().upper()
        target = grouped.setdefault(period, {})
        period_items = seen_items.setdefault(period, set())
        if normalized_item in period_items:
            raise ProviderNormalizationError(
                f"ambiguous duplicate {statement_label} item {item_name!r} for {period!r}"
            )
        period_items.add(normalized_item)
        for field, aliases in normalized_aliases.items():
            if normalized_item in aliases:
                if field in target:
                    raise ProviderNormalizationError(
                        f"ambiguous duplicate {statement_label} field {field!r} "
                        f"for {period!r}"
                    )
                target[field] = value
        for field in _STATEMENT_CURRENCY_FIELDS:
            if field in row:
                target[field] = row[field]
        source_rows.setdefault(period, row)
    return [
        (dict({"报告日": period}, **values), source_rows[period])
        for period, values in sorted(grouped.items())
    ]


def _parse_date_value(raw_value: object) -> date | None:
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    if raw_value is None or isinstance(raw_value, bool):
        return None
    text = str(raw_value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    return None


def _parse_statement_date_parameter(
    raw_value: object,
    *,
    request: ProviderRequest | None = None,
) -> date:
    statement_date = _parse_date_value(raw_value)
    if statement_date is None or statement_date.strftime("%m%d") not in {
        "0331",
        "0630",
        "0930",
        "1231",
    }:
        raise ProviderRequestError(
            "statement_date must be an exact quarter-end date "
            "(YYYY-MM-DD or YYYYMMDD)",
            request=request,
            retryable=False,
        )
    return statement_date


def _statement_date(
    row: Mapping[str, JSONValue],
    *,
    record: RawProviderRecord | None = None,
) -> date | None:
    found, raw_value = _lookup(row, _STATEMENT_PERIOD_FIELDS)
    if found:
        return _parse_date_value(raw_value)
    if record is not None:
        fallback = record.response_metadata.get("statement_date")
        if fallback is None:
            fallback = record.request.parameters.get("statement_date")
        return _parse_date_value(fallback)
    return None


def _statement_currency_metadata(
    row: Mapping[str, JSONValue],
    *,
    statement_label: str,
) -> tuple[bool, str | None]:
    """Read explicit statement currency metadata without inferring it.

    A listing market is not a reliable substitute for the reporting currency:
    an H-share issuer may report in CNY, and an A-share issuer may disclose a
    different presentation currency.  Only an explicit three-letter code is
    safe to place in ``Fact.currency``.  Multiple provider aliases on one row
    must also agree instead of being resolved by alias order.
    """

    found = False
    candidates: set[str] = set()
    for field in _STATEMENT_CURRENCY_FIELDS:
        if field not in row:
            continue
        found = True
        raw_value = row[field]
        value = _text_value(raw_value)
        if value is None:
            continue
        if not re.fullmatch(r"[A-Za-z]{3}", value):
            raise ProviderNormalizationError(
                f"{statement_label} statement currency {raw_value!r} is not "
                "an explicit three-letter code"
            )
        candidates.add(value.upper())

    if len(candidates) > 1:
        values = ", ".join(sorted(candidates))
        raise ProviderNormalizationError(
            f"conflicting {statement_label} statement currency metadata: {values}"
        )
    return found, next(iter(candidates), None)


def _statement_currencies_by_period(
    rows: Sequence[Mapping[str, JSONValue]],
    *,
    record: RawProviderRecord,
    statement_label: str,
) -> dict[str, str | None]:
    """Collect order-independent explicit currencies for statement periods."""

    currencies: dict[str, str | None] = {}
    for row in rows:
        statement_date = _statement_date(row, record=record)
        if statement_date is None:
            raise ProviderNormalizationError(
                f"{statement_label} statement row for {record.request.entity_id!r} "
                "has no exact report date"
            )
        found, currency = _statement_currency_metadata(row, statement_label=statement_label)
        if not found:
            continue
        period = statement_date.isoformat()
        previous = currencies.get(period)
        if previous is not None and currency is not None and previous != currency:
            raise ProviderNormalizationError(
                f"conflicting {statement_label} statement currency metadata for "
                f"{period!r}: {previous!r} vs {currency!r}"
            )
        if previous is None or currency is not None:
            currencies[period] = currency
    return currencies


def _map_history(
    record: RawProviderRecord,
    evidence: Evidence,
    rows: Sequence[Mapping[str, JSONValue]],
    listing: _ListingRef,
    *,
    as_of: date,
    primary: bool,
    add_fact: Callable[..., None],
) -> tuple[int, int]:
    start_date, end_date = _normalizer_history_range(record.request.parameters)
    ordered: list[tuple[date, Mapping[str, JSONValue]]] = []
    for row in rows:
        observation_date = _observation_date(row)
        if observation_date is None:
            raise ProviderNormalizationError(
                f"market history row for {record.request.entity_id!r} has no date"
            )
        if start_date is not None and observation_date < start_date:
            continue
        if end_date is not None and observation_date > end_date:
            continue
        ordered.append((observation_date, row))
    ordered.sort(key=lambda item: item[0])
    seen_dates: set[date] = set()
    row_count = 0
    close_count = 0
    for observation_date, row in ordered:
        if observation_date in seen_dates:
            raise ProviderNormalizationError(
                f"ambiguous duplicate market history date {observation_date.isoformat()} "
                f"for {record.request.entity_id!r}"
            )
        seen_dates.add(observation_date)
        row_count += 1
        period = observation_date.isoformat()
        if not primary:
            period = f"{listing.canonical_id}:{period}"
        for field, (aliases, unit) in _HISTORY_FIELDS.items():
            found, raw_value = _lookup(row, aliases)
            if not found and field != "historical_close":
                continue
            value = _number_value(raw_value, field=field) if found else None
            if field == "historical_close" and value is not None:
                close_count += 1
            field_currency = (
                _currency_for(listing.market)
                if field
                in {
                    "historical_open",
                    "historical_high",
                    "historical_low",
                    "historical_close",
                    "historical_turnover",
                }
                else None
            )
            field_unit = unit
            if field == "historical_volume":
                field_unit = "lots" if listing.market is ListingMarket.A else "shares"
            add_fact(
                record,
                evidence,
                field=field,
                value=value,
                period=period,
                currency=field_currency,
                unit=field_unit,
            )
    return row_count, close_count


def _observation_date(row: Mapping[str, JSONValue]) -> date | None:
    found, raw_value = _lookup(row, ("日期", "交易日期", "date", "时间", "datetime"))
    if not found or raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    text = str(raw_value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if match:
        return date.fromisoformat(match.group(1))
    return None


def _metadata_date(row: Mapping[str, JSONValue]) -> date | None:
    found, raw_value = _lookup(row, ("上市日期", "上市日", "listing_date"))
    if not found or raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    text = str(raw_value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if match:
        return date.fromisoformat(match.group(1))
    raise ProviderNormalizationError(f"listing_date value {raw_value!r} is not a date")


def _normalizer_history_range(
    parameters: Mapping[str, JSONValue],
) -> tuple[date | None, date | None]:
    _, start_date = _date_parameter(parameters, "start_date", "start_year")
    _, end_date = _date_parameter(parameters, "end_date", "end_year")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ProviderNormalizationError("market history range is inverted")
    return start_date, end_date


def normalize_listing_id(entity_id: str) -> str:
    """Return the adapter's canonical ``SH/SZ/BJ`` or ``HK`` listing ID."""

    return _parse_listing_id(entity_id).canonical_id


__all__ = [
    "AKSHARE_ADAPTER_VERSION",
    "AKSHARE_CAPABILITIES",
    "AKSHARE_MAPPING_VERSION",
    "AKSHARE_SOURCE_NAME",
    "AKShareNormalizer",
    "AKShareAdapter",
    "AKShareProvider",
    "AkShareNormalizer",
    "AkShareProvider",
    "ListingMarket",
    "fetch_akshare_with_cache",
    "normalize_akshare_records",
    "normalize_listing_id",
]
