"""Bounded BaoStock A-share daily price-reference acquisition.

This module is deliberately separate from the M3 lifecycle/calendar adapter.
It uses the same lazy SDK and private raw-CAS boundary, but has its own
adapter identity, request semantics and offline decoder.  BaoStock is a
sampled reference source here; it is not promoted to the bulk canonical
A-share price source.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from turtle_value_engine.backtest import MarketBar
from turtle_value_engine.backtest.contracts import PriceBasis
from turtle_value_engine.providers.models import canonical_json_bytes

from .acquisition import (
    AccountEntitlement,
    AcquisitionError,
    CredentialResolver,
    HistoricalAcquisitionRequestV1,
    HistoricalIngestionError,
    HistoricalSourceSchemaError,
    NetworkResponse,
    NetworkTransport,
    ProbeStatus,
    RawArtifactReceiptV1,
    RawDownload,
    SourceProbeReportV1,
    _safe_uri,
    _utc_now,
)
from .baostock import (
    BAOSTOCK_PROVIDER_ID,
    BAOSTOCK_SOURCE_URI,
    BAOSTOCK_TIMEZONE,
    BaoStockClientFactory,
    BaoStockProviderError,
    BaoStockSession,
    _call_query,
    _canonical_listing_id,
    _close,
    _login,
    _mapping_parameter,
    _parse_date,
    _provider_code,
    _required_text,
    _row_from_provider,
)
from .contracts import HistoricalSourceKind, ShardArtifactKind

BAOSTOCK_PRICE_ADAPTER_ID = "baostock-a-share-price-reference"
BAOSTOCK_PRICE_ADAPTER_VERSION = "baostock-sdk-price-export-v1"
BAOSTOCK_PRICE_REPRESENTATION_ID = "baostock-sdk-price-export-v1"
BAOSTOCK_PRICE_SCHEMA_VERSION = "market-bar-v1"
BAOSTOCK_PRICE_OPERATION = "query_history_k_data_plus"
BAOSTOCK_PRICE_FREQUENCY = "d"
BAOSTOCK_PRICE_ADJUSTFLAG = "3"
BAOSTOCK_PRICE_BASIS = "UNADJUSTED"
BAOSTOCK_PRICE_FIELDS = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adjustflag",
)

BAOSTOCK_PRICE_NO_ROWS = "BAOSTOCK_PRICE_NO_ROWS"
BAOSTOCK_PRICE_A_SHARE_ONLY = "BAOSTOCK_PRICE_A_SHARE_ONLY"
BAOSTOCK_PRICE_SCHEMA_UNSUPPORTED = "BAOSTOCK_PRICE_SCHEMA_UNSUPPORTED"
BAOSTOCK_PRICE_ADJUSTED_REJECTED = "BAOSTOCK_PRICE_ADJUSTED_REJECTED"
BAOSTOCK_PRICE_COVERAGE_INSUFFICIENT = "BAOSTOCK_PRICE_COVERAGE_INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class _BaoStockPriceRequestDetails:
    listing_ids: tuple[str, ...]
    start_date: date
    end_date: date
    provider_codes: dict[str, str]
    frequency: str
    adjustflag: str
    fields: tuple[str, ...]
    timezone: str
    currency: str
    source_uri: str


@dataclass(frozen=True, slots=True)
class _BaoStockPriceFetchResult:
    details: _BaoStockPriceRequestDetails
    envelope: dict[str, object]
    body: bytes
    rows: list[MarketBar]


def _price_request_details(request: HistoricalAcquisitionRequestV1) -> _BaoStockPriceRequestDetails:
    if request.adapter_id != BAOSTOCK_PRICE_ADAPTER_ID:
        raise HistoricalSourceSchemaError("BaoStock price request adapter identity mismatch")
    if request.source_kind is not HistoricalSourceKind.PRICES:
        raise HistoricalSourceSchemaError("BaoStock price adapter only serves PRICES rows")
    if request.artifact_kind is not ShardArtifactKind.MARKET_BAR:
        raise HistoricalSourceSchemaError("BaoStock price adapter requires MARKET_BAR")
    if request.schema_version != BAOSTOCK_PRICE_SCHEMA_VERSION:
        raise HistoricalSourceSchemaError("BaoStock price schema version is unrecognized")
    if not request.listing_ids or any(not isinstance(item, str) for item in request.listing_ids):
        raise HistoricalSourceSchemaError(f"{BAOSTOCK_PRICE_A_SHARE_ONLY}: invalid listing IDs")
    listing_ids = tuple(sorted(request.listing_ids))
    if len(listing_ids) != len(set(listing_ids)):
        raise HistoricalSourceSchemaError("BaoStock price listing IDs contain duplicates")
    if any(not re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", item) for item in listing_ids):
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_PRICE_A_SHARE_ONLY}: BaoStock price reference requires A-share IDs"
        )
    if request.end_date < request.start_date:
        raise HistoricalSourceSchemaError(
            "BaoStock price request end_date must not precede start_date"
        )

    parameters = request.parameters
    if "frequency" not in parameters:
        raise HistoricalSourceSchemaError("BaoStock price request must declare daily frequency")
    frequency = parameters["frequency"]
    if not isinstance(frequency, str) or frequency != BAOSTOCK_PRICE_FREQUENCY:
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_PRICE_SCHEMA_UNSUPPORTED}: frequency must be 'd'"
        )
    if "adjustflag" not in parameters:
        raise HistoricalSourceSchemaError(
            "BaoStock price request must declare unadjusted adjustflag='3'"
        )
    adjustflag = parameters["adjustflag"]
    if isinstance(adjustflag, bool) or str(adjustflag) != BAOSTOCK_PRICE_ADJUSTFLAG:
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_PRICE_ADJUSTED_REJECTED}: only adjustflag='3' is supported"
        )
    if "price_basis" in parameters and parameters["price_basis"] != BAOSTOCK_PRICE_BASIS:
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_PRICE_ADJUSTED_REJECTED}: only UNADJUSTED is supported"
        )

    raw_fields = parameters.get("fields")
    if raw_fields is None:
        fields = BAOSTOCK_PRICE_FIELDS
    elif isinstance(raw_fields, str):
        fields = tuple(item.strip() for item in raw_fields.split(","))
    elif isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (bytes, bytearray)):
        fields = tuple(raw_fields)
    else:
        raise HistoricalSourceSchemaError("BaoStock price fields are invalid")
    if fields != BAOSTOCK_PRICE_FIELDS:
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_PRICE_SCHEMA_UNSUPPORTED}: price fields changed"
        )

    timezone = parameters.get("timezone", BAOSTOCK_TIMEZONE)
    timezone = _required_text(timezone, field_name="timezone")
    try:
        ZoneInfo(timezone)
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise HistoricalSourceSchemaError(
            "BaoStock price timezone is not an installed IANA zone"
        ) from exc
    currency = parameters.get("currency", "CNY")
    currency = _required_text(currency, field_name="currency")
    if currency != "CNY":
        raise HistoricalSourceSchemaError("BaoStock price reference requires CNY")
    source_uri = parameters.get("source_uri", BAOSTOCK_SOURCE_URI)
    source_uri = _required_text(source_uri, field_name="source_uri")
    try:
        source_uri = _safe_uri(source_uri)
    except (TypeError, ValueError) as exc:
        raise HistoricalSourceSchemaError("BaoStock price source URI is invalid") from exc
    if source_uri is None:
        raise HistoricalSourceSchemaError("BaoStock price source URI is missing")

    explicit_codes = _mapping_parameter(
        parameters,
        ("baostock_codes_by_listing", "provider_codes_by_listing"),
        listing_ids=listing_ids,
        field_name="provider_codes_by_listing",
    )
    provider_codes = {
        listing_id: explicit_codes.get(listing_id, _provider_code(listing_id))
        for listing_id in listing_ids
    }
    for listing_id, provider_code in provider_codes.items():
        if _canonical_listing_id(provider_code) != listing_id:
            raise HistoricalSourceSchemaError(
                f"BaoStock provider code does not match listing: {listing_id}"
            )
    return _BaoStockPriceRequestDetails(
        listing_ids=listing_ids,
        start_date=request.start_date,
        end_date=request.end_date,
        provider_codes=provider_codes,
        frequency=frequency,
        adjustflag=BAOSTOCK_PRICE_ADJUSTFLAG,
        fields=fields,
        timezone=timezone,
        currency=currency,
        source_uri=source_uri,
    )


def _strict_number(value: object, *, field_name: str, positive: bool = False) -> float:
    if isinstance(value, bool) or value is None:
        raise HistoricalIngestionError(f"BaoStock price {field_name} is not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoricalIngestionError(f"BaoStock price {field_name} is not numeric") from exc
    if not math.isfinite(number) or (positive and number <= 0) or number < 0:
        raise HistoricalIngestionError(f"BaoStock price {field_name} is invalid")
    return number


def _strict_adjustflag(value: object) -> None:
    if isinstance(value, bool) or str(value) != BAOSTOCK_PRICE_ADJUSTFLAG:
        raise HistoricalIngestionError(
            f"{BAOSTOCK_PRICE_ADJUSTED_REJECTED}: row is not unadjusted"
        )


def _required_price_fields(fields: Sequence[str]) -> None:
    if tuple(fields) != BAOSTOCK_PRICE_FIELDS:
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_PRICE_SCHEMA_UNSUPPORTED}: provider fields changed"
        )


def _load_envelope(raw_bytes: bytes) -> dict[str, object]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalIngestionError("BaoStock price raw envelope is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HistoricalIngestionError("BaoStock price raw envelope is not an object")
    return payload


def _details_from_envelope(
    envelope: Mapping[str, object],
    receipt: RawArtifactReceiptV1,
) -> _BaoStockPriceRequestDetails:
    provider = envelope.get("provider")
    if not isinstance(provider, Mapping):
        raise HistoricalIngestionError("BaoStock price envelope provider identity is invalid")
    if (
        provider.get("provider_id") != BAOSTOCK_PROVIDER_ID
        or provider.get("adapter_id") != receipt.adapter_id
        or provider.get("adapter_version") != receipt.adapter_version
    ):
        raise HistoricalIngestionError("BaoStock price envelope provider identity mismatch")
    request = envelope.get("request")
    if not isinstance(request, Mapping):
        raise HistoricalIngestionError("BaoStock price envelope request is invalid")
    listing_ids = request.get("listing_ids")
    if isinstance(listing_ids, (str, bytes)) or not isinstance(listing_ids, Sequence):
        raise HistoricalIngestionError("BaoStock price envelope listing_ids are invalid")
    try:
        proxy = HistoricalAcquisitionRequestV1(
            request_id=receipt.request_id,
            source_id=receipt.source_id,
            adapter_id=receipt.adapter_id,
            source_kind=receipt.source_kind,
            artifact_kind=receipt.artifact_kind,
            schema_version=receipt.schema_version,
            listing_ids=list(listing_ids),
            start_date=_parse_date(request.get("start_date"), field_name="start_date"),
            end_date=_parse_date(request.get("end_date"), field_name="end_date"),
            parameters=receipt.canonical_parameters,
        )
        details = _price_request_details(proxy)
    except (TypeError, ValueError, HistoricalSourceSchemaError) as exc:
        raise HistoricalIngestionError("BaoStock price envelope request is invalid") from exc
    if request.get("request_identity") != receipt.request_identity:
        raise HistoricalIngestionError("BaoStock price envelope/request identity mismatch")
    expected = {
        "listing_ids": list(details.listing_ids),
        "provider_codes": details.provider_codes,
        "start_date": details.start_date.isoformat(),
        "end_date": details.end_date.isoformat(),
        "frequency": details.frequency,
        "adjustflag": details.adjustflag,
        "fields": list(details.fields),
        "price_basis": BAOSTOCK_PRICE_BASIS,
        "timezone": details.timezone,
        "currency": details.currency,
        "source_uri": details.source_uri,
    }
    if any(request.get(key) != value for key, value in expected.items()):
        raise HistoricalIngestionError("BaoStock price envelope request parameters mismatch")
    return details


def _canonical_rows_from_envelope(
    envelope: Mapping[str, object],
    *,
    details: _BaoStockPriceRequestDetails,
    source_artifact_id: str,
    source_hash: str,
) -> list[MarketBar]:
    if envelope.get("contract") != "baostock_sdk_export_v1":
        raise HistoricalIngestionError("BaoStock price envelope contract is unsupported")
    if envelope.get("representation_id") != BAOSTOCK_PRICE_REPRESENTATION_ID:
        raise HistoricalIngestionError("BaoStock price envelope representation is unsupported")
    if envelope.get("operation") != BAOSTOCK_PRICE_OPERATION:
        raise HistoricalIngestionError("BaoStock price envelope operation is unsupported")
    raw_fields = envelope.get("fields")
    if isinstance(raw_fields, (str, bytes)) or not isinstance(raw_fields, Sequence):
        raise HistoricalIngestionError("BaoStock price envelope fields are invalid")
    fields = list(raw_fields)
    _required_price_fields(fields)
    raw_rows = envelope.get("rows")
    if not isinstance(raw_rows, list):
        raise HistoricalIngestionError("BaoStock price envelope rows are invalid")
    row_count = envelope.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count != len(raw_rows):
        raise HistoricalIngestionError("BaoStock price envelope row_count is invalid")
    if not raw_rows:
        raise HistoricalIngestionError(f"{BAOSTOCK_PRICE_NO_ROWS}: BaoStock returned no price rows")

    result: list[MarketBar] = []
    seen: set[tuple[str, date]] = set()
    for index, raw_row in enumerate(raw_rows):
        row = _row_from_provider(
            raw_row,
            fields,
            operation=BAOSTOCK_PRICE_OPERATION,
            row_index=index,
        )
        listing_id = _canonical_listing_id(row.get("code"))
        if listing_id not in details.listing_ids:
            raise HistoricalIngestionError(
                "BaoStock price response contains an unrequested listing"
            )
        trading_date = _parse_date(row.get("date"), field_name="date")
        if not details.start_date <= trading_date <= details.end_date:
            raise HistoricalIngestionError("BaoStock price row lies outside request range")
        _strict_adjustflag(row.get("adjustflag"))
        key = (listing_id, trading_date)
        if key in seen:
            raise HistoricalIngestionError("duplicate BaoStock price natural key")
        seen.add(key)
        try:
            result.append(
                MarketBar(
                    bar_id=f"{listing_id}:{trading_date.isoformat()}",
                    listing_id=listing_id,
                    market="A",
                    trading_date=trading_date,
                    open=_strict_number(row.get("open"), field_name="open", positive=True),
                    high=_strict_number(row.get("high"), field_name="high", positive=True),
                    low=_strict_number(row.get("low"), field_name="low", positive=True),
                    close=_strict_number(row.get("close"), field_name="close", positive=True),
                    volume=_strict_number(row.get("volume"), field_name="volume"),
                    amount=_strict_number(row.get("amount"), field_name="amount"),
                    currency=details.currency,
                    price_basis=PriceBasis.UNADJUSTED,
                    source_hash=source_hash,
                )
            )
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError(
                "BaoStock price row failed canonical validation"
            ) from exc
    return sorted(result, key=lambda row: (row.listing_id, row.trading_date))


class BaoStockAsharePriceReferenceDecoder:
    """Decode frozen BaoStock daily price-reference envelopes offline."""

    adapter_id = BAOSTOCK_PRICE_ADAPTER_ID

    def _validate_receipt(self, receipt: RawArtifactReceiptV1) -> None:
        if receipt.adapter_id != BAOSTOCK_PRICE_ADAPTER_ID:
            raise HistoricalIngestionError("BaoStock price decoder adapter identity mismatch")
        if receipt.artifact_kind is not ShardArtifactKind.MARKET_BAR:
            raise HistoricalIngestionError("BaoStock price decoder requires MARKET_BAR")
        if receipt.schema_version != BAOSTOCK_PRICE_SCHEMA_VERSION:
            raise HistoricalIngestionError("BaoStock price schema version is unrecognized")

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        self._validate_receipt(receipt)
        envelope = _load_envelope(raw_bytes)
        details = _details_from_envelope(envelope, receipt)
        return _canonical_rows_from_envelope(
            envelope,
            details=details,
            source_artifact_id=receipt.source_id,
            source_hash=receipt.sha256,
        )

    def decode_scoped(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
        request: HistoricalAcquisitionRequestV1,
    ) -> list[BaseModel]:
        self._validate_receipt(receipt)
        details = _price_request_details(request)
        envelope = _load_envelope(raw_bytes)
        envelope_details = _details_from_envelope(envelope, receipt)
        if request.request_identity != receipt.request_identity or envelope_details != details:
            raise HistoricalIngestionError("BaoStock price envelope/request scope mismatch")
        return _canonical_rows_from_envelope(
            envelope,
            details=details,
            source_artifact_id=receipt.source_id,
            source_hash=receipt.sha256,
        )


class BaoStockAsharePriceReferenceAdapter:
    """Acquire a fixed A-share daily, unadjusted price-reference sample."""

    adapter_id = BAOSTOCK_PRICE_ADAPTER_ID
    adapter_version = BAOSTOCK_PRICE_ADAPTER_VERSION
    requires_live_credential = False
    provider_id = BAOSTOCK_PROVIDER_ID
    source_name = "BaoStock sampled A-share daily price reference"

    def __init__(
        self,
        client_factory: BaoStockClientFactory | Callable[[], object] | None = None,
    ) -> None:
        self.client_factory = client_factory

    @staticmethod
    def _session(value: object) -> BaoStockSession:
        if isinstance(value, BaoStockSession):
            return value
        if all(callable(getattr(value, name, None)) for name in ("login", "logout")):
            return BaoStockSession(client=value)  # type: ignore[arg-type]
        raise BaoStockProviderError("BAOSTOCK_SDK_INCOMPATIBLE")

    def _make_session(self) -> BaoStockSession:
        if self.client_factory is None:
            from .baostock import LazyBaoStockClientFactory

            factory: Callable[[], object] = LazyBaoStockClientFactory()
        else:
            factory = self.client_factory
        try:
            return self._session(factory())
        except BaoStockProviderError:
            raise
        except Exception as exc:
            raise BaoStockProviderError("BAOSTOCK_SDK_INCOMPATIBLE") from exc

    def _fetch(self, request: HistoricalAcquisitionRequestV1) -> _BaoStockPriceFetchResult:
        details = _price_request_details(request)
        session: BaoStockSession | None = None
        try:
            session = self._make_session()
            _login(session.client)
            fields: list[str] | None = None
            rows: list[dict[str, object]] = []
            for listing_id in details.listing_ids:
                query_fields, query_rows = _call_query(
                    session.client,
                    BAOSTOCK_PRICE_OPERATION,
                    code=details.provider_codes[listing_id],
                    fields=",".join(details.fields),
                    start_date=details.start_date.isoformat(),
                    end_date=details.end_date.isoformat(),
                    frequency=details.frequency,
                    adjustflag=details.adjustflag,
                )
                _required_price_fields(query_fields)
                if fields is None:
                    fields = query_fields
                elif fields != query_fields:
                    raise HistoricalSourceSchemaError(
                        "BaoStock price fields changed between queries"
                    )
                rows.extend(query_rows)
            if not rows:
                raise BaoStockProviderError(BAOSTOCK_PRICE_NO_ROWS)
            assert fields is not None
            rows = sorted(
                rows,
                key=lambda row: (str(row.get("code", "")), str(row.get("date", ""))),
            )
            envelope: dict[str, object] = {
                "contract": "baostock_sdk_export_v1",
                "representation_id": BAOSTOCK_PRICE_REPRESENTATION_ID,
                "provider": {
                    "provider_id": BAOSTOCK_PROVIDER_ID,
                    "adapter_id": self.adapter_id,
                    "adapter_version": self.adapter_version,
                    "sdk_version": session.sdk_version,
                },
                "request": {
                    "request_identity": request.request_identity,
                    "listing_ids": list(details.listing_ids),
                    "provider_codes": details.provider_codes,
                    "start_date": details.start_date.isoformat(),
                    "end_date": details.end_date.isoformat(),
                    "frequency": details.frequency,
                    "adjustflag": details.adjustflag,
                    "fields": list(details.fields),
                    "price_basis": BAOSTOCK_PRICE_BASIS,
                    "timezone": details.timezone,
                    "currency": details.currency,
                    "source_uri": details.source_uri,
                },
                "operation": BAOSTOCK_PRICE_OPERATION,
                "fields": fields,
                "rows": rows,
                "row_count": len(rows),
            }
            body = canonical_json_bytes(envelope)
            canonical_rows = _canonical_rows_from_envelope(
                envelope,
                details=details,
                source_artifact_id=request.source_id,
                source_hash=hashlib.sha256(body).hexdigest(),
            )
            return _BaoStockPriceFetchResult(
                details=details,
                envelope=envelope,
                body=body,
                rows=canonical_rows,
            )
        finally:
            _close(session)

    def acquire(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> list[RawDownload]:
        del transport, credentials
        try:
            fetched = self._fetch(request)
        except BaoStockProviderError as exc:
            raise AcquisitionError(str(exc)) from exc
        except (HistoricalSourceSchemaError, HistoricalIngestionError) as exc:
            raise HistoricalSourceSchemaError(str(exc)) from exc
        details = fetched.details
        response = NetworkResponse(
            status_code=200,
            headers={
                "content-type": "application/json",
                "content-length": str(len(fetched.body)),
            },
            body=fetched.body,
            url=details.source_uri,
        )
        return [
            RawDownload(
                body=fetched.body,
                response=response,
                source_uri=details.source_uri,
                artifact_kind=request.artifact_kind,
                schema_version=request.schema_version,
                artifact_metadata={
                    "representation": BAOSTOCK_PRICE_REPRESENTATION_ID,
                    "provider_id": BAOSTOCK_PROVIDER_ID,
                    "operation": BAOSTOCK_PRICE_OPERATION,
                    "listing_ids": list(details.listing_ids),
                    "provider_codes": details.provider_codes,
                    "frequency": details.frequency,
                    "adjustflag": details.adjustflag,
                    "price_basis": BAOSTOCK_PRICE_BASIS,
                    "currency": details.currency,
                    "start_date": details.start_date.isoformat(),
                    "end_date": details.end_date.isoformat(),
                    "row_count": len(fetched.envelope["rows"]),
                },
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
        del transport, credentials
        started = _utc_now(clock)
        try:
            fetched = self._fetch(request)
        except BaoStockProviderError as exc:
            finished = _utc_now(clock)
            status = (
                ProbeStatus.BLOCKED
                if exc.diagnostic in {"BAOSTOCK_SDK_UNAVAILABLE", "BAOSTOCK_SDK_INCOMPATIBLE"}
                else ProbeStatus.FAILED
            )
            return _price_probe_report(
                request,
                plan_id=plan_id,
                status=status,
                started=started,
                finished=finished,
                blockers=[str(exc)],
            )
        except (HistoricalSourceSchemaError, HistoricalIngestionError) as exc:
            finished = _utc_now(clock)
            return _price_probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[str(exc)],
            )

        finished = _utc_now(clock)
        details = fetched.details
        blockers: list[str] = []
        if request.expected_sessions_by_listing:
            observed = {(row.listing_id, row.trading_date) for row in fetched.rows}
            expected = {
                (listing_id, session_date)
                for listing_id, values in request.expected_sessions_by_listing.items()
                for session_date in values
            }
            if expected - observed:
                blockers.append(BAOSTOCK_PRICE_COVERAGE_INSUFFICIENT)
        observed_dates = [row.trading_date for row in fetched.rows]
        return _price_probe_report(
            request,
            plan_id=plan_id,
            status=ProbeStatus.PASS if not blockers else ProbeStatus.FAILED,
            started=started,
            finished=finished,
            http_status=200,
            content_type="application/json",
            content_length=len(fetched.body),
            response_sha256=hashlib.sha256(fetched.body).hexdigest(),
            source_uri=details.source_uri,
            observed_start=min(observed_dates) if observed_dates else None,
            observed_end=max(observed_dates) if observed_dates else None,
            observed_listing_ids=list(details.listing_ids),
            account_entitlement=AccountEntitlement.CONFIRMED,
            historical_capable=not blockers,
            action_coverage="UNKNOWN",
            blockers=blockers,
            warnings=[
                "BAOSTOCK_SDK_EXPORT_NOT_RAW_WIRE: provider result is a decoded SDK envelope",
                "BAOSTOCK_SAMPLED_REFERENCE_ONLY: this adapter is not a bulk canonical source",
                "BAOSTOCK_NO_SUSPENSION_INFERENCE: missing price rows remain missing",
            ],
        )


def _price_probe_report(
    request: HistoricalAcquisitionRequestV1,
    *,
    plan_id: str,
    status: ProbeStatus,
    started: object,
    finished: object,
    **values: object,
) -> SourceProbeReportV1:
    return SourceProbeReportV1.build(
        report_id=f"probe-{request.request_id}",
        plan_id=plan_id,
        request_id=request.request_id,
        source_id=request.source_id,
        adapter_id=BAOSTOCK_PRICE_ADAPTER_ID,
        adapter_version=BAOSTOCK_PRICE_ADAPTER_VERSION,
        source_kind=request.source_kind,
        status=status,
        started_at=started,
        finished_at=finished,
        **values,
    )


# Descriptive aliases for the additive sampled-reference role.
BaoStockPriceReferenceAdapter = BaoStockAsharePriceReferenceAdapter
BaoStockPriceReferenceDecoder = BaoStockAsharePriceReferenceDecoder
BaoStockMarketHistoryAdapter = BaoStockAsharePriceReferenceAdapter


__all__ = [
    "BAOSTOCK_PRICE_ADAPTER_ID",
    "BAOSTOCK_PRICE_ADAPTER_VERSION",
    "BAOSTOCK_PRICE_ADJUSTED_REJECTED",
    "BAOSTOCK_PRICE_ADJUSTFLAG",
    "BAOSTOCK_PRICE_A_SHARE_ONLY",
    "BAOSTOCK_PRICE_BASIS",
    "BAOSTOCK_PRICE_COVERAGE_INSUFFICIENT",
    "BAOSTOCK_PRICE_FIELDS",
    "BAOSTOCK_PRICE_FREQUENCY",
    "BAOSTOCK_PRICE_NO_ROWS",
    "BAOSTOCK_PRICE_OPERATION",
    "BAOSTOCK_PRICE_REPRESENTATION_ID",
    "BAOSTOCK_PRICE_SCHEMA_UNSUPPORTED",
    "BAOSTOCK_PRICE_SCHEMA_VERSION",
    "BaoStockAsharePriceReferenceAdapter",
    "BaoStockAsharePriceReferenceDecoder",
    "BaoStockMarketHistoryAdapter",
    "BaoStockPriceReferenceAdapter",
    "BaoStockPriceReferenceDecoder",
]
