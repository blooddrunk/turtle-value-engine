"""Bounded BaoStock A-share lifecycle and trading-calendar acquisition.

BaoStock is kept behind a lazy SDK seam.  A live call is only reachable from
the opt-in historical acquisition service; importing this module and running
the offline compiler do not require the optional dependency or network access.
The SDK returns decoded result objects rather than stable wire bytes, so the
adapter freezes a complete ``baostock-sdk-export-v1`` envelope in the raw CAS
boundary before canonical rows are produced offline.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from turtle_value_engine.providers.models import canonical_json_bytes

from .acquisition import (
    AccountEntitlement,
    AcquisitionError,
    CredentialResolver,
    HistoricalAcquisitionRequestV1,
    HistoricalIngestionError,
    HistoricalRawDecoder,
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
from .contracts import (
    HistoricalListingLifecycle,
    HistoricalTerminalOutcome,
    HistoricalTradingSession,
    ShardArtifactKind,
)

BAOSTOCK_ADAPTER_ID = "baostock-a-share-lifecycle"
BAOSTOCK_ADAPTER_VERSION = "baostock-sdk-export-v1"
BAOSTOCK_REPRESENTATION_ID = "baostock-sdk-export-v1"
BAOSTOCK_PROVIDER_ID = "baostock"
BAOSTOCK_SOURCE_URI = "https://www.baostock.com"
BAOSTOCK_TIMEZONE = "Asia/Shanghai"
BAOSTOCK_LIFECYCLE_SCHEMA_VERSION = "historical-listing-lifecycle-v1"
BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION = "historical-trading-session-v1"

BAOSTOCK_SDK_UNAVAILABLE = "BAOSTOCK_SDK_UNAVAILABLE"
BAOSTOCK_SDK_INCOMPATIBLE = "BAOSTOCK_SDK_INCOMPATIBLE"
BAOSTOCK_LOGIN_FAILED = "BAOSTOCK_LOGIN_FAILED"
BAOSTOCK_QUERY_FAILED = "BAOSTOCK_QUERY_FAILED"
BAOSTOCK_NO_ROWS = "BAOSTOCK_NO_ROWS"
BAOSTOCK_COVERAGE_INSUFFICIENT = "BAOSTOCK_COVERAGE_INSUFFICIENT"
BAOSTOCK_SCHEMA_UNSUPPORTED = "BAOSTOCK_SCHEMA_UNSUPPORTED"
BAOSTOCK_A_SHARE_ONLY = "BAOSTOCK_A_SHARE_ONLY"

_A_SHARE_PATTERN = re.compile(r"^(SH|SZ|BJ)(\d{6})$")
_BAOSTOCK_CODE_PATTERN = re.compile(r"^(sh|sz|bj)\.\d{6}$")
_REQUIRED_CALENDAR_FIELDS = frozenset({"calendar_date", "is_trading_day"})
_REQUIRED_BASIC_FIELDS = frozenset(
    {"code", "code_name", "ipoDate", "outDate", "type", "status"}
)


class BaoStockProviderError(AcquisitionError):
    """Provider failure with a bounded, safe diagnostic classification."""

    def __init__(self, diagnostic: str, *, provider_code: object = None) -> None:
        self.diagnostic = diagnostic
        self.provider_code = _safe_provider_code(provider_code)
        detail = diagnostic if self.provider_code is None else f"{diagnostic}: {self.provider_code}"
        super().__init__(detail)


class BaoStockResult(Protocol):
    """Minimum BaoStock result surface used by the adapter and test fakes."""

    error_code: object
    error_msg: object
    fields: object

    def next(self) -> object:
        """Advance to the next provider row."""

    def get_row_data(self) -> object:
        """Return the current provider row."""


class BaoStockClient(Protocol):
    """Minimum SDK surface; the concrete module is imported lazily."""

    def login(self) -> object:
        """Open the provider session."""

    def logout(self) -> object:
        """Close the provider session."""

    def query_trade_dates(self, *, start_date: str, end_date: str) -> object:
        """Return calendar dates and trading-day flags."""

    def query_stock_basic(self, *, code: str) -> object:
        """Return listing/basic fields for one provider code."""


@dataclass(frozen=True, slots=True)
class BaoStockSession:
    """Client plus the SDK version observed by the live runtime."""

    client: BaoStockClient
    sdk_version: str | None = None


class BaoStockClientFactory(Protocol):
    """Injected factory seam for owner runtimes and deterministic fakes."""

    def __call__(self) -> BaoStockSession | BaoStockClient:
        """Create one short-lived BaoStock SDK session."""


class LazyBaoStockClientFactory:
    """Import ``baostock`` only when an explicitly allowed live call starts."""

    def __call__(self) -> BaoStockSession:
        try:
            import baostock  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BaoStockProviderError(BAOSTOCK_SDK_UNAVAILABLE) from exc
        version = getattr(baostock, "__version__", None)
        return BaoStockSession(
            client=baostock,
            sdk_version=version.strip() if isinstance(version, str) and version.strip() else None,
        )


@dataclass(frozen=True, slots=True)
class _BaoStockRequestDetails:
    listing_ids: tuple[str, ...]
    start_date: date
    end_date: date
    calendar_id: str
    timezone: str
    currency: str
    source_uri: str
    provider_codes: dict[str, str]
    economic_company_ids: dict[str, str]


@dataclass(frozen=True, slots=True)
class _BaoStockFetchResult:
    details: _BaoStockRequestDetails
    envelope: dict[str, object]
    body: bytes
    rows: list[BaseModel]


def _safe_provider_code(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text or len(text) > 64:
        return None
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]+", text) else None


def _json_safe(value: object, *, path: str) -> object:
    """Detach SDK scalar/container values without stringifying unknown data."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HistoricalSourceSchemaError(f"BaoStock {path} contains a non-finite value")
        return value
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise HistoricalSourceSchemaError(f"BaoStock {path} has a non-string key")
            result[key] = _json_safe(child, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_safe(child, path=f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            detached = item()
        except Exception as exc:
            raise HistoricalSourceSchemaError(f"BaoStock {path} has an unsupported scalar") from exc
        if detached is value:
            raise HistoricalSourceSchemaError(f"BaoStock {path} has an unsupported scalar")
        return _json_safe(detached, path=path)
    raise HistoricalSourceSchemaError(f"BaoStock {path} has an unsupported value")


def _result_value(result: object, name: str) -> object:
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def _check_result(result: object, *, operation: str) -> None:
    code = _result_value(result, "error_code")
    if code is None:
        raise HistoricalSourceSchemaError(f"BaoStock {operation} result has no error_code")
    if str(code).strip() != "0":
        diagnostic = BAOSTOCK_LOGIN_FAILED if operation == "login" else BAOSTOCK_QUERY_FAILED
        raise BaoStockProviderError(diagnostic, provider_code=code)


def _fields(result: object, *, operation: str) -> list[str]:
    raw_fields = _result_value(result, "fields")
    if isinstance(raw_fields, (str, bytes)) or not isinstance(raw_fields, Sequence):
        raise HistoricalSourceSchemaError(f"BaoStock {operation} result fields are unsupported")
    if any(not isinstance(item, str) for item in raw_fields):
        raise HistoricalSourceSchemaError(f"BaoStock {operation} result fields are not text")
    values = [item.strip() for item in raw_fields]
    if not values or any(not item for item in values) or len(values) != len(set(values)):
        raise HistoricalSourceSchemaError(f"BaoStock {operation} result fields are invalid")
    return values


def _row_from_provider(
    raw_row: object,
    fields: Sequence[str],
    *,
    operation: str,
    row_index: int,
) -> dict[str, object]:
    if isinstance(raw_row, Mapping):
        if any(not isinstance(key, str) for key in raw_row):
            raise HistoricalSourceSchemaError(f"BaoStock {operation} row has a non-string key")
        if set(raw_row) != set(fields):
            raise HistoricalSourceSchemaError(f"BaoStock {operation} row fields changed")
        values = {key: raw_row[key] for key in fields}
    elif isinstance(raw_row, (list, tuple)):
        if len(raw_row) != len(fields):
            raise HistoricalSourceSchemaError(f"BaoStock {operation} row length changed")
        values = dict(zip(fields, raw_row, strict=True))
    else:
        raise HistoricalSourceSchemaError(f"BaoStock {operation} row is not tabular")
    return {
        key: _json_safe(value, path=f"{operation}.rows[{row_index}].{key}")
        for key, value in values.items()
    }


def _provider_rows(result: object, *, operation: str) -> tuple[list[str], list[dict[str, object]]]:
    _check_result(result, operation=operation)
    fields = _fields(result, operation=operation)
    raw_rows = _result_value(result, "rows")
    rows: list[object]
    if raw_rows is not None:
        if isinstance(raw_rows, (str, bytes)) or not isinstance(raw_rows, Sequence):
            raise HistoricalSourceSchemaError(f"BaoStock {operation} rows are not a sequence")
        rows = list(raw_rows)
    else:
        advance = getattr(result, "next", None)
        get_row_data = getattr(result, "get_row_data", None)
        if not callable(advance) or not callable(get_row_data):
            raise HistoricalSourceSchemaError(f"BaoStock {operation} result is not iterable")
        rows = []
        for _ in range(1_000_001):
            try:
                has_row = bool(advance())
            except Exception as exc:
                raise BaoStockProviderError(BAOSTOCK_QUERY_FAILED) from exc
            if not has_row:
                break
            try:
                rows.append(get_row_data())
            except Exception as exc:
                raise BaoStockProviderError(BAOSTOCK_QUERY_FAILED) from exc
        else:
            raise HistoricalSourceSchemaError(f"BaoStock {operation} exceeded row bound")
    return fields, [
        _row_from_provider(row, fields, operation=operation, row_index=index)
        for index, row in enumerate(rows)
    ]


def _call_query(
    client: BaoStockClient,
    operation: str,
    **kwargs: str,
) -> tuple[list[str], list[dict[str, object]]]:
    method = getattr(client, operation, None)
    if not callable(method):
        raise BaoStockProviderError(BAOSTOCK_SDK_INCOMPATIBLE)
    try:
        result = method(**kwargs)
    except Exception as exc:
        raise BaoStockProviderError(BAOSTOCK_QUERY_FAILED) from exc
    return _provider_rows(result, operation=operation)


def _login(client: BaoStockClient) -> None:
    method = getattr(client, "login", None)
    if not callable(method):
        raise BaoStockProviderError(BAOSTOCK_SDK_INCOMPATIBLE)
    try:
        result = method()
    except Exception as exc:
        raise BaoStockProviderError(BAOSTOCK_LOGIN_FAILED) from exc
    _check_result(result, operation="login")


def _close(session: BaoStockSession | None) -> None:
    if session is None:
        return
    method = getattr(session.client, "logout", None)
    if callable(method):
        try:
            method()
        except Exception:
            # A provider close failure must not erase an already frozen body;
            # the receipt still records the exact successful query envelope.
            pass


def _canonical_listing_id(value: object) -> str:
    normalized = value.lower() if isinstance(value, str) and value == value.strip() else ""
    if not _BAOSTOCK_CODE_PATTERN.fullmatch(normalized):
        raise HistoricalSourceSchemaError("BaoStock code is not an explicit A-share provider code")
    market, number = normalized.split(".", 1)
    return market.upper() + number


def _provider_code(listing_id: str) -> str:
    match = _A_SHARE_PATTERN.fullmatch(listing_id)
    if match is None:
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_A_SHARE_ONLY}: BaoStock adapter requires canonical A-share listing IDs"
        )
    return f"{match.group(1).lower()}.{match.group(2)}"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} is not text")
    text = value
    if not text or any(ord(char) < 32 for char in text):
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} is empty or not printable")
    return text


def _parse_date(value: object, *, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, str):
        return value
    if not isinstance(value, str) or len(value) != 10 or value != value.strip():
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} is not an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} is not an ISO date") from exc


def _optional_date(value: object, *, field_name: str) -> date | None:
    if value is None or value == "":
        return None
    return _parse_date(value, field_name=field_name)


def _provider_flag(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return value == 1
    if isinstance(value, str) and value in {"0", "1"}:
        return value == "1"
    raise HistoricalSourceSchemaError(f"BaoStock {field_name} is not a strict 0/1 flag")


def _provider_type(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} is not a stock type")
    if isinstance(value, int) and value == 1:
        return value
    if isinstance(value, str) and value == "1":
        return 1
    raise HistoricalSourceSchemaError(f"BaoStock {field_name} is not the stock type")


def _mapping_parameter(
    parameters: Mapping[str, object],
    names: tuple[str, ...],
    *,
    listing_ids: Sequence[str],
    field_name: str,
) -> dict[str, str]:
    raw: object = None
    for name in names:
        if name in parameters:
            raw = parameters[name]
            break
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} must be an object")
    if not set(raw).issubset(set(listing_ids)):
        raise HistoricalSourceSchemaError(f"BaoStock {field_name} contains an unknown listing")
    result: dict[str, str] = {}
    for listing_id, value in raw.items():
        if not isinstance(listing_id, str):
            raise HistoricalSourceSchemaError(f"BaoStock {field_name} has an invalid listing")
        result[listing_id] = _required_text(value, field_name=field_name)
    return result


def _details_from_values(
    *,
    listing_ids: Sequence[str],
    start_date: date,
    end_date: date,
    parameters: Mapping[str, object],
) -> _BaoStockRequestDetails:
    if not listing_ids or any(not isinstance(item, str) for item in listing_ids):
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_A_SHARE_ONLY}: BaoStock listing IDs must be text"
        )
    normalized_listing_ids = tuple(sorted(listing_ids))
    if len(normalized_listing_ids) != len(set(normalized_listing_ids)):
        raise HistoricalSourceSchemaError("BaoStock listing IDs contain duplicates")
    if any(_A_SHARE_PATTERN.fullmatch(item) is None for item in normalized_listing_ids):
        raise HistoricalSourceSchemaError(
            f"{BAOSTOCK_A_SHARE_ONLY}: BaoStock adapter requires canonical A-share listing IDs"
        )
    if end_date < start_date:
        raise HistoricalSourceSchemaError("BaoStock request end_date must not precede start_date")
    calendar_id = _required_text(parameters.get("calendar_id"), field_name="calendar_id")
    timezone = parameters.get("timezone", BAOSTOCK_TIMEZONE)
    timezone = _required_text(timezone, field_name="timezone")
    try:
        ZoneInfo(timezone)
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise HistoricalSourceSchemaError(
            "BaoStock timezone is not an installed IANA zone"
        ) from exc
    currency = parameters.get("currency", "CNY")
    currency = _required_text(currency, field_name="currency").upper()
    if currency != "CNY" or len(currency) != 3:
        raise HistoricalSourceSchemaError("BaoStock A-share currency must be CNY")
    source_uri = parameters.get("source_uri", BAOSTOCK_SOURCE_URI)
    try:
        source_uri = _safe_uri(_required_text(source_uri, field_name="source_uri"))
    except (TypeError, ValueError) as exc:
        raise HistoricalSourceSchemaError("BaoStock source URI is invalid") from exc
    if source_uri is None:
        raise HistoricalSourceSchemaError("BaoStock source URI is missing")
    explicit_codes = _mapping_parameter(
        parameters,
        ("baostock_codes_by_listing", "provider_codes_by_listing"),
        listing_ids=normalized_listing_ids,
        field_name="provider_codes_by_listing",
    )
    provider_codes = {
        listing_id: explicit_codes.get(listing_id, _provider_code(listing_id))
        for listing_id in normalized_listing_ids
    }
    for listing_id, provider_code in provider_codes.items():
        if _canonical_listing_id(provider_code) != listing_id:
            raise HistoricalSourceSchemaError(
                f"BaoStock provider code does not match listing: {listing_id}"
            )
    explicit_economic_ids = _mapping_parameter(
        parameters,
        ("economic_company_id_by_listing", "economic_company_ids"),
        listing_ids=normalized_listing_ids,
        field_name="economic_company_id_by_listing",
    )
    economic_company_ids = {
        # This is a source-local A listing surrogate, not an asserted A/H
        # economic-company mapping.  The limitation is retained in reports.
        listing_id: explicit_economic_ids.get(listing_id, f"A:{listing_id}")
        for listing_id in normalized_listing_ids
    }
    return _BaoStockRequestDetails(
        listing_ids=normalized_listing_ids,
        start_date=start_date,
        end_date=end_date,
        calendar_id=calendar_id,
        timezone=timezone,
        currency=currency,
        source_uri=source_uri,
        provider_codes=provider_codes,
        economic_company_ids=economic_company_ids,
    )


def _request_details(request: HistoricalAcquisitionRequestV1) -> _BaoStockRequestDetails:
    if request.adapter_id != BAOSTOCK_ADAPTER_ID:
        raise HistoricalSourceSchemaError("BaoStock request adapter identity mismatch")
    if request.source_kind.value != "LISTING_LIFECYCLE":
        raise HistoricalSourceSchemaError("BaoStock adapter only serves lifecycle source rows")
    if request.artifact_kind is ShardArtifactKind.LISTING_LIFECYCLE:
        expected_schema = BAOSTOCK_LIFECYCLE_SCHEMA_VERSION
    elif request.artifact_kind is ShardArtifactKind.TRADING_SESSION:
        expected_schema = BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION
    else:
        raise HistoricalSourceSchemaError(
            "BaoStock adapter only serves lifecycle or calendar shards"
        )
    if request.schema_version != expected_schema:
        raise HistoricalSourceSchemaError("BaoStock schema version is unrecognized")
    return _details_from_values(
        listing_ids=request.listing_ids,
        start_date=request.start_date,
        end_date=request.end_date,
        parameters=request.parameters,
    )


def _required_fields(fields: Sequence[str], *, operation: str) -> None:
    required = (
        _REQUIRED_BASIC_FIELDS
        if operation == "query_stock_basic"
        else _REQUIRED_CALENDAR_FIELDS
    )
    if len(fields) != len(required) or set(fields) != required:
        raise HistoricalSourceSchemaError(
            f"BaoStock {operation} fields are unsupported or changed"
        )


def _canonical_rows_from_envelope(
    envelope: Mapping[str, object],
    *,
    details: _BaoStockRequestDetails,
    artifact_kind: ShardArtifactKind,
    source_artifact_id: str,
    source_hash: str,
) -> list[BaseModel]:
    expected_operation = (
        "query_stock_basic"
        if artifact_kind is ShardArtifactKind.LISTING_LIFECYCLE
        else "query_trade_dates"
    )
    if envelope.get("contract") != "baostock_sdk_export_v1":
        raise HistoricalIngestionError("BaoStock envelope contract is unsupported")
    if envelope.get("representation_id") != BAOSTOCK_REPRESENTATION_ID:
        raise HistoricalIngestionError("BaoStock envelope representation is unsupported")
    if envelope.get("operation") != expected_operation:
        raise HistoricalIngestionError("BaoStock envelope operation does not match artifact kind")
    raw_fields = envelope.get("fields")
    raw_rows = envelope.get("rows")
    if isinstance(raw_fields, (str, bytes)) or not isinstance(raw_fields, Sequence):
        raise HistoricalIngestionError("BaoStock envelope fields are invalid")
    if any(not isinstance(item, str) for item in raw_fields):
        raise HistoricalIngestionError("BaoStock envelope fields are not text")
    fields = list(raw_fields)
    _required_fields(fields, operation=expected_operation)
    if not isinstance(raw_rows, list):
        raise HistoricalIngestionError("BaoStock envelope rows are invalid")
    row_count = envelope.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count != len(raw_rows):
        raise HistoricalIngestionError("BaoStock envelope row_count is invalid")
    rows = [
        _row_from_provider(
            row,
            fields,
            operation=expected_operation,
            row_index=index,
        )
        for index, row in enumerate(raw_rows)
    ]
    if not rows:
        raise HistoricalIngestionError(f"{BAOSTOCK_NO_ROWS}: BaoStock returned no rows")
    if artifact_kind is ShardArtifactKind.TRADING_SESSION:
        return _calendar_rows(
            rows,
            details=details,
            source_artifact_id=source_artifact_id,
            source_hash=source_hash,
        )
    return _lifecycle_rows(
        rows,
        details=details,
        source_artifact_id=source_artifact_id,
        source_hash=source_hash,
    )


def _lifecycle_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    details: _BaoStockRequestDetails,
    source_artifact_id: str,
    source_hash: str,
) -> list[HistoricalListingLifecycle]:
    result: list[HistoricalListingLifecycle] = []
    seen: set[str] = set()
    for row in rows:
        listing_id = _canonical_listing_id(row.get("code"))
        if listing_id not in details.listing_ids:
            raise HistoricalIngestionError("BaoStock response contains an unrequested listing")
        if listing_id in seen:
            raise HistoricalIngestionError("BaoStock response contains duplicate listing basics")
        seen.add(listing_id)
        _required_text(row.get("code_name"), field_name="code_name")
        _provider_type(row.get("type"), field_name="type")
        listed = _provider_flag(row.get("status"), field_name="status")
        listing_date = _parse_date(row.get("ipoDate"), field_name="ipoDate")
        terminal_date = _optional_date(row.get("outDate"), field_name="outDate")
        if listed and terminal_date is not None:
            raise HistoricalIngestionError("BaoStock listed row has an outDate")
        if not listed and terminal_date is None:
            raise HistoricalIngestionError(
                f"{BAOSTOCK_SCHEMA_UNSUPPORTED}: delisted row has no terminal date"
            )
        outcome = HistoricalTerminalOutcome.ACTIVE if listed else HistoricalTerminalOutcome.DELISTED
        try:
            result.append(
                HistoricalListingLifecycle(
                    listing_id=listing_id,
                    economic_company_id=details.economic_company_ids[listing_id],
                    market="A",
                    currency=details.currency,
                    listing_date=listing_date,
                    terminal_date=terminal_date,
                    terminal_outcome=outcome,
                    trading_calendar=details.calendar_id,
                    timezone=details.timezone,
                    historical_codes=[details.provider_codes[listing_id]],
                    source_artifact_id=source_artifact_id,
                    source_hash=source_hash,
                )
            )
        except (TypeError, ValueError) as exc:
            raise HistoricalIngestionError(
                "BaoStock lifecycle row failed canonical validation"
            ) from exc
    if seen != set(details.listing_ids):
        raise HistoricalIngestionError(
            f"{BAOSTOCK_COVERAGE_INSUFFICIENT}: listing basics are incomplete"
        )
    return sorted(result, key=lambda row: row.listing_id)


def _calendar_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    details: _BaoStockRequestDetails,
    source_artifact_id: str,
    source_hash: str,
) -> list[HistoricalTradingSession]:
    parsed: dict[date, bool] = {}
    for row in rows:
        session_date = _parse_date(row.get("calendar_date"), field_name="calendar_date")
        if not details.start_date <= session_date <= details.end_date:
            raise HistoricalIngestionError("BaoStock calendar row lies outside request range")
        if session_date in parsed:
            raise HistoricalIngestionError("BaoStock calendar contains duplicate dates")
        parsed[session_date] = _provider_flag(
            row.get("is_trading_day"),
            field_name="is_trading_day",
        )
    expected_dates = {
        details.start_date + timedelta(days=offset)
        for offset in range((details.end_date - details.start_date).days + 1)
    }
    if set(parsed) != expected_dates:
        raise HistoricalIngestionError(
            f"{BAOSTOCK_COVERAGE_INSUFFICIENT}: calendar does not cover every requested date"
        )
    result = [
        HistoricalTradingSession(
            session_id=f"{listing_id}:{details.calendar_id}:{session_date.isoformat()}",
            listing_id=listing_id,
            calendar_id=details.calendar_id,
            session_date=session_date,
            is_trading_day=is_trading_day,
            timezone=details.timezone,
            source_artifact_id=source_artifact_id,
            source_hash=source_hash,
        )
        for listing_id in details.listing_ids
        for session_date, is_trading_day in sorted(parsed.items())
    ]
    return result


def _envelope_request(envelope: Mapping[str, object]) -> Mapping[str, object]:
    request = envelope.get("request")
    if not isinstance(request, Mapping):
        raise HistoricalIngestionError("BaoStock envelope request is invalid")
    return request


def _details_from_envelope(
    envelope: Mapping[str, object],
    receipt: RawArtifactReceiptV1,
) -> _BaoStockRequestDetails:
    provider = envelope.get("provider")
    if not isinstance(provider, Mapping):
        raise HistoricalIngestionError("BaoStock envelope provider identity is invalid")
    if (
        provider.get("provider_id") != BAOSTOCK_PROVIDER_ID
        or provider.get("adapter_id") != receipt.adapter_id
        or provider.get("adapter_version") != receipt.adapter_version
    ):
        raise HistoricalIngestionError("BaoStock envelope provider identity mismatch")
    request = _envelope_request(envelope)
    listing_ids = request.get("listing_ids")
    if isinstance(listing_ids, (str, bytes)) or not isinstance(listing_ids, Sequence):
        raise HistoricalIngestionError("BaoStock envelope listing_ids are invalid")
    if any(not isinstance(item, str) for item in listing_ids):
        raise HistoricalIngestionError("BaoStock envelope listing_ids are not text")
    start_date = _parse_date(request.get("start_date"), field_name="start_date")
    end_date = _parse_date(request.get("end_date"), field_name="end_date")
    try:
        details = _details_from_values(
            listing_ids=list(listing_ids),
            start_date=start_date,
            end_date=end_date,
            parameters=receipt.canonical_parameters,
        )
    except HistoricalSourceSchemaError as exc:
        raise HistoricalIngestionError(str(exc)) from exc
    if request.get("request_identity") != receipt.request_identity:
        raise HistoricalIngestionError("BaoStock envelope/request identity mismatch")
    if (
        request.get("listing_ids") != list(details.listing_ids)
        or request.get("provider_codes") != details.provider_codes
        or request.get("start_date") != details.start_date.isoformat()
        or request.get("end_date") != details.end_date.isoformat()
        or request.get("calendar_id") != details.calendar_id
        or request.get("timezone") != details.timezone
        or request.get("currency") != details.currency
        or request.get("source_uri") != details.source_uri
    ):
        raise HistoricalIngestionError("BaoStock envelope request parameters mismatch")
    return details


class BaoStockAshareLifecycleDecoder:
    """Decode BaoStock lifecycle/basic envelopes into source-aware rows."""

    adapter_id = BAOSTOCK_ADAPTER_ID

    def _validate_receipt(self, receipt: RawArtifactReceiptV1) -> None:
        if receipt.adapter_id != BAOSTOCK_ADAPTER_ID:
            raise HistoricalIngestionError("BaoStock decoder adapter identity mismatch")
        if receipt.artifact_kind is not ShardArtifactKind.LISTING_LIFECYCLE:
            raise HistoricalIngestionError("BaoStock lifecycle decoder requires LISTING_LIFECYCLE")
        if receipt.schema_version != BAOSTOCK_LIFECYCLE_SCHEMA_VERSION:
            raise HistoricalIngestionError("BaoStock lifecycle schema version is unrecognized")

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        self._validate_receipt(receipt)
        envelope = _load_envelope(raw_bytes)
        details = _details_from_envelope(envelope, receipt)
        return _canonical_rows_from_envelope(
            envelope,
            details=details,
            artifact_kind=ShardArtifactKind.LISTING_LIFECYCLE,
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
        details = _request_details(request)
        envelope = _load_envelope(raw_bytes)
        envelope_details = _details_from_envelope(envelope, receipt)
        if request.request_identity != receipt.request_identity or envelope_details != details:
            raise HistoricalIngestionError("BaoStock envelope/request scope mismatch")
        rows = _canonical_rows_from_envelope(
            envelope,
            details=details,
            artifact_kind=ShardArtifactKind.LISTING_LIFECYCLE,
            source_artifact_id=receipt.source_id,
            source_hash=receipt.sha256,
        )
        return [row for row in rows if row.listing_id in request.listing_ids]


class BaoStockTradingSessionDecoder:
    """Decode BaoStock trade-date envelopes into explicit calendar rows."""

    adapter_id = BAOSTOCK_ADAPTER_ID

    def _validate_receipt(self, receipt: RawArtifactReceiptV1) -> None:
        if receipt.adapter_id != BAOSTOCK_ADAPTER_ID:
            raise HistoricalIngestionError("BaoStock decoder adapter identity mismatch")
        if receipt.artifact_kind is not ShardArtifactKind.TRADING_SESSION:
            raise HistoricalIngestionError("BaoStock calendar decoder requires TRADING_SESSION")
        if receipt.schema_version != BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION:
            raise HistoricalIngestionError("BaoStock calendar schema version is unrecognized")

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        self._validate_receipt(receipt)
        envelope = _load_envelope(raw_bytes)
        details = _details_from_envelope(envelope, receipt)
        return _canonical_rows_from_envelope(
            envelope,
            details=details,
            artifact_kind=ShardArtifactKind.TRADING_SESSION,
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
        details = _request_details(request)
        envelope = _load_envelope(raw_bytes)
        envelope_details = _details_from_envelope(envelope, receipt)
        if request.request_identity != receipt.request_identity or envelope_details != details:
            raise HistoricalIngestionError("BaoStock envelope/request scope mismatch")
        rows = _canonical_rows_from_envelope(
            envelope,
            details=details,
            artifact_kind=ShardArtifactKind.TRADING_SESSION,
            source_artifact_id=receipt.source_id,
            source_hash=receipt.sha256,
        )
        return [
            row
            for row in rows
            if request.start_date <= row.session_date <= request.end_date
            and row.listing_id in request.listing_ids
        ]


def _load_envelope(raw_bytes: bytes) -> dict[str, object]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalIngestionError("BaoStock raw envelope is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HistoricalIngestionError("BaoStock raw envelope is not an object")
    return payload


class BaoStockAshareLifecycleAdapter:
    """Acquire A-share listing basics and an explicit trade-date calendar."""

    adapter_id = BAOSTOCK_ADAPTER_ID
    adapter_version = BAOSTOCK_ADAPTER_VERSION
    requires_live_credential = False
    provider_id = BAOSTOCK_PROVIDER_ID
    source_name = "BaoStock A-share lifecycle and trading calendar"

    def __init__(
        self,
        client_factory: BaoStockClientFactory | Callable[[], object] | None = None,
    ) -> None:
        self.client_factory = client_factory or LazyBaoStockClientFactory()

    @staticmethod
    def _session(value: object) -> BaoStockSession:
        if isinstance(value, BaoStockSession):
            return value
        if all(callable(getattr(value, name, None)) for name in ("login", "logout")):
            return BaoStockSession(client=value)  # type: ignore[arg-type]
        raise BaoStockProviderError(BAOSTOCK_SDK_INCOMPATIBLE)

    def _fetch(self, request: HistoricalAcquisitionRequestV1) -> _BaoStockFetchResult:
        details = _request_details(request)
        session: BaoStockSession | None = None
        try:
            try:
                session = self._session(self.client_factory())
            except BaoStockProviderError:
                raise
            except Exception as exc:
                raise BaoStockProviderError(BAOSTOCK_SDK_INCOMPATIBLE) from exc
            _login(session.client)
            if request.artifact_kind is ShardArtifactKind.LISTING_LIFECYCLE:
                operation = "query_stock_basic"
                fields: list[str] | None = None
                rows: list[dict[str, object]] = []
                for listing_id in details.listing_ids:
                    query_fields, query_rows = _call_query(
                        session.client,
                        operation,
                        code=details.provider_codes[listing_id],
                    )
                    _required_fields(query_fields, operation=operation)
                    if fields is None:
                        fields = query_fields
                    elif fields != query_fields:
                        raise HistoricalSourceSchemaError(
                            "BaoStock basic fields changed between queries"
                        )
                    rows.extend(query_rows)
                if not rows:
                    raise BaoStockProviderError(BAOSTOCK_NO_ROWS)
            else:
                operation = "query_trade_dates"
                fields, rows = _call_query(
                    session.client,
                    operation,
                    start_date=details.start_date.isoformat(),
                    end_date=details.end_date.isoformat(),
                )
                _required_fields(fields, operation=operation)
                if not rows:
                    raise BaoStockProviderError(BAOSTOCK_NO_ROWS)
            assert fields is not None
            rows = sorted(
                rows,
                key=(
                    (lambda row: str(row.get("code", "")))
                    if operation == "query_stock_basic"
                    else (lambda row: str(row.get("calendar_date", "")))
                ),
            )
            envelope: dict[str, object] = {
                "contract": "baostock_sdk_export_v1",
                "representation_id": BAOSTOCK_REPRESENTATION_ID,
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
                    "calendar_id": details.calendar_id,
                    "timezone": details.timezone,
                    "currency": details.currency,
                    "source_uri": details.source_uri,
                },
                "operation": operation,
                "fields": fields,
                "rows": rows,
                "row_count": len(rows),
            }
            body = canonical_json_bytes(envelope)
            canonical_rows = _canonical_rows_from_envelope(
                envelope,
                details=details,
                artifact_kind=request.artifact_kind,
                source_artifact_id=request.source_id,
                source_hash=hashlib.sha256(body).hexdigest(),
            )
            return _BaoStockFetchResult(
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
                    "representation": BAOSTOCK_REPRESENTATION_ID,
                    "provider_id": BAOSTOCK_PROVIDER_ID,
                    "operation": fetched.envelope["operation"],
                    "listing_ids": list(details.listing_ids),
                    "provider_codes": details.provider_codes,
                    "calendar_id": details.calendar_id,
                    "timezone": details.timezone,
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
            finished = _utc_now(clock)
        except BaoStockProviderError as exc:
            finished = _utc_now(clock)
            status = (
                ProbeStatus.BLOCKED
                if exc.diagnostic in {BAOSTOCK_SDK_UNAVAILABLE, BAOSTOCK_SDK_INCOMPATIBLE}
                else ProbeStatus.FAILED
            )
            return _probe_report(
                request,
                plan_id=plan_id,
                status=status,
                started=started,
                finished=finished,
                blockers=[str(exc)],
            )
        except (HistoricalSourceSchemaError, HistoricalIngestionError) as exc:
            finished = _utc_now(clock)
            return _probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[str(exc)],
            )
        except Exception:
            finished = _utc_now(clock)
            return _probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[BAOSTOCK_QUERY_FAILED],
            )

        details = fetched.details
        blockers: list[str] = []
        if request.artifact_kind is ShardArtifactKind.TRADING_SESSION:
            observed_dates = {row.session_date for row in fetched.rows}
            expected = {
                value
                for values in (request.expected_sessions_by_listing or {}).values()
                for value in values
            }
            if expected - observed_dates:
                blockers.append(BAOSTOCK_COVERAGE_INSUFFICIENT)
        else:
            observed_listing_ids = {row.listing_id for row in fetched.rows}
            if observed_listing_ids != set(details.listing_ids):
                blockers.append(BAOSTOCK_COVERAGE_INSUFFICIENT)
            observed_dates = {
                value
                for row in fetched.rows
                for value in (row.listing_date, row.terminal_date)
                if value is not None
            }
        status = ProbeStatus.PASS if not blockers else ProbeStatus.FAILED
        return _probe_report(
            request,
            plan_id=plan_id,
            status=status,
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
            terminal_coverage="UNVERIFIED",
            action_coverage="UNKNOWN",
            blockers=blockers,
            warnings=[
                "BAOSTOCK_SDK_EXPORT_NOT_RAW_WIRE: provider result is a decoded SDK envelope",
                "BAOSTOCK_BASIC_CURRENT_SNAPSHOT: stock_basic does not prove PIT "
                "membership or code history",
                "BAOSTOCK_TERMINAL_COVERAGE_UNVERIFIED: observed outDate does not "
                "prove complete delisted retention",
                "BAOSTOCK_NO_SUSPENSION_INFERENCE: missing price rows must not be "
                "treated as suspension",
                "BAOSTOCK_LOCAL_ECONOMIC_ID_SURROGATE: default A identity is not "
                "an A/H company mapping",
            ],
        )


def _probe_report(
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
        adapter_id=BAOSTOCK_ADAPTER_ID,
        adapter_version=BAOSTOCK_ADAPTER_VERSION,
        source_kind=request.source_kind,
        status=status,
        started_at=started,
        finished_at=finished,
        **values,
    )


# Descriptive aliases keep the provider role discoverable without adding a
# second adapter identity or a second wire contract.
BaoStockLifecycleAdapter = BaoStockAshareLifecycleAdapter
BaoStockHistoricalAdapter = BaoStockAshareLifecycleAdapter
BaoStockMarketHistoryAdapter = BaoStockAshareLifecycleAdapter
BaoStockLifecycleDecoder = BaoStockAshareLifecycleDecoder


__all__ = [
    "BAOSTOCK_ADAPTER_ID",
    "BAOSTOCK_ADAPTER_VERSION",
    "BAOSTOCK_A_SHARE_ONLY",
    "BAOSTOCK_COVERAGE_INSUFFICIENT",
    "BAOSTOCK_LIFECYCLE_SCHEMA_VERSION",
    "BAOSTOCK_LOGIN_FAILED",
    "BAOSTOCK_NO_ROWS",
    "BAOSTOCK_PROVIDER_ID",
    "BAOSTOCK_QUERY_FAILED",
    "BAOSTOCK_REPRESENTATION_ID",
    "BAOSTOCK_SCHEMA_UNSUPPORTED",
    "BAOSTOCK_SDK_INCOMPATIBLE",
    "BAOSTOCK_SDK_UNAVAILABLE",
    "BAOSTOCK_SOURCE_URI",
    "BAOSTOCK_TIMEZONE",
    "BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION",
    "BaoStockAshareLifecycleAdapter",
    "BaoStockAshareLifecycleDecoder",
    "BaoStockClient",
    "BaoStockClientFactory",
    "BaoStockHistoricalAdapter",
    "BaoStockLifecycleAdapter",
    "BaoStockLifecycleDecoder",
    "BaoStockMarketHistoryAdapter",
    "BaoStockProviderError",
    "BaoStockResult",
    "BaoStockSession",
    "BaoStockTradingSessionDecoder",
    "HistoricalRawDecoder",
    "LazyBaoStockClientFactory",
]
