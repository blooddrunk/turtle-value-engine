"""Futu OpenD bounded H-share daily market-history adapter.

The Futu Python SDK is deliberately kept behind a lazy factory.  Importing
this module, importing :mod:`turtle_value_engine.historical`, and running the
offline compiler do not require the SDK or an OpenD process.

Futu's Python API returns a decoded SDK/DataFrame representation, not
guaranteed OpenD wire bytes.  The adapter therefore freezes a complete,
deterministic ``futu-opend-sdk-export-v1`` envelope in the existing raw CAS
boundary before the offline decoder projects rows into ``MARKET_BAR``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from turtle_value_engine.backtest import Market, MarketBar
from turtle_value_engine.providers.models import canonical_json_bytes

from .acquisition import (
    AccountEntitlement,
    AcquisitionError,
    CredentialResolver,
    CredentialUnavailableError,
    HistoricalAcquisitionRequestV1,
    HistoricalIngestionError,
    HistoricalSourceSchemaError,
    NetworkResponse,
    NetworkTransport,
    NetworkTransportError,
    ProbeStatus,
    RawArtifactReceiptV1,
    RawDownload,
    SourceProbeReportV1,
    _safe_uri,
    _utc_now,
)
from .contracts import ShardArtifactKind

FUTU_OPEND_ADAPTER_ID = "futu-opend-market-history"
FUTU_OPEND_ADAPTER_VERSION = "futu-opend-sdk-export-v1"
FUTU_OPEND_REPRESENTATION_ID = "futu-opend-sdk-export-v1"
FUTU_OPEND_SOURCE_URI = (
    "https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html"
)
FUTU_OPEND_TIMEZONE = "Asia/Shanghai"
FUTU_OPEND_SCHEMA_VERSION = "market-bar-v1"
FUTU_OPEND_DEFAULT_HOST = "127.0.0.1"
FUTU_OPEND_DEFAULT_PORT = 11111
FUTU_OPEND_DEFAULT_MAX_COUNT = 1_000
FUTU_OPEND_DEFAULT_MAX_PAGES = 1_024
FUTU_OPEND_MAX_RANGE_DAYS = 20 * 366 + 10
FUTU_OPEND_REQUIRED_COLUMNS = frozenset(
    {"code", "time_key", "open", "high", "low", "close", "volume", "turnover"}
)
_PROVIDER_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")

FUTU_OPEND_UNAVAILABLE = "FUTU_OPEND_UNAVAILABLE"
FUTU_SDK_UNAVAILABLE = "FUTU_SDK_UNAVAILABLE"
FUTU_SDK_INCOMPATIBLE = "FUTU_SDK_INCOMPATIBLE"
FUTU_HISTORY_QUOTA_EXHAUSTED = "FUTU_HISTORY_QUOTA_EXHAUSTED"
FUTU_ENTITLEMENT_DENIED = "FUTU_ENTITLEMENT_DENIED"
FUTU_HISTORY_REQUEST_FAILED = "FUTU_HISTORY_REQUEST_FAILED"
FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED = "FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED"
FUTU_NO_ROWS = "FUTU_NO_ROWS"
FUTU_COVERAGE_INSUFFICIENT = "FUTU_COVERAGE_INSUFFICIENT"
FUTU_SCHEMA_UNSUPPORTED = "FUTU_SCHEMA_UNSUPPORTED"


class FutuDiagnostic(StrEnum):
    """Stable classifications allowed at the Futu acquisition boundary."""

    OPEND_UNAVAILABLE = FUTU_OPEND_UNAVAILABLE
    SDK_UNAVAILABLE = FUTU_SDK_UNAVAILABLE
    SDK_INCOMPATIBLE = FUTU_SDK_INCOMPATIBLE
    HISTORY_QUOTA_EXHAUSTED = FUTU_HISTORY_QUOTA_EXHAUSTED
    ENTITLEMENT_DENIED = FUTU_ENTITLEMENT_DENIED
    HISTORY_REQUEST_FAILED = FUTU_HISTORY_REQUEST_FAILED


class FutuOpenDProviderError(AcquisitionError):
    """Bounded provider error whose class is safe to persist as a diagnostic."""

    def __init__(
        self,
        diagnostic: FutuDiagnostic | str,
        *,
        provider_code: str | int | None = None,
    ) -> None:
        self.diagnostic = str(diagnostic)
        self.provider_code = _safe_provider_code(provider_code)
        detail = self.diagnostic
        if self.provider_code is not None:
            detail += ": " + self.provider_code
        super().__init__(detail)


class FutuOpenDClient(Protocol):
    """Minimum client surface used by the adapter and offline fakes."""

    def request_history_kline(self, code: str, **kwargs: object) -> object:
        """Return the SDK's ``(ret, data, page_req_key)`` result."""

    def get_history_kl_quota(self, *, get_detail: bool = False) -> object:
        """Return the SDK's history-quota result when supported."""

    def close(self) -> object:
        """Release the OpenD connection."""


@dataclass(frozen=True, slots=True)
class FutuOpenDSession:
    """Client plus SDK constants supplied by a runtime-specific factory."""

    client: FutuOpenDClient
    k_day: object = "K_DAY"
    au_none: object = "NONE"
    fields_all: object = "ALL"
    ret_ok: object = 0
    sdk_version: str | None = None
    opend_version: str | None = None


class LazyFutuOpenDClientFactory:
    """Import ``futu`` only when an explicitly opted-in live call is made."""

    def __call__(self, *, host: str, port: int) -> FutuOpenDSession:
        try:
            import futu  # type: ignore[import-not-found]
        except ImportError as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.SDK_UNAVAILABLE) from exc

        try:
            client = futu.OpenQuoteContext(host=host, port=port)
            session = FutuOpenDSession(
                client=client,
                k_day=futu.KLType.K_DAY,
                au_none=futu.AuType.NONE,
                fields_all=futu.KL_FIELD.ALL,
                ret_ok=getattr(futu, "RET_OK", 0),
                sdk_version=_safe_version(getattr(futu, "__version__", None)),
                opend_version=_safe_version(getattr(client, "opend_version", None)),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            _close_client_safely(locals().get("client"))
            raise FutuOpenDProviderError(FutuDiagnostic.SDK_INCOMPATIBLE) from exc
        except (ConnectionError, OSError, TimeoutError) as exc:
            _close_client_safely(locals().get("client"))
            raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
        except Exception as exc:  # SDK-specific connection exceptions vary by release.
            _close_client_safely(locals().get("client"))
            raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
        return session


class FutuOpenDRequestClientFactory(Protocol):
    """Injected factory seam for fake clients and controlled owner runners."""

    def __call__(self, *, host: str, port: int) -> FutuOpenDSession | FutuOpenDClient:
        """Create one short-lived OpenD quote context."""


@dataclass(frozen=True, slots=True)
class _FutuRequestDetails:
    source_uri: str
    listing_id: str
    futu_code: str
    start_date: date
    end_date: date
    currency: str
    timezone_name: str
    max_count: int
    max_pages: int
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class _FutuFetchResult:
    details: _FutuRequestDetails
    envelope: dict[str, object]
    body: bytes
    rows: list[dict[str, object]]
    quota: dict[str, object]
    diagnostics: list[str]
    sdk_version: str | None
    opend_version: str | None


@dataclass(frozen=True, slots=True)
class _FutuObservation:
    trading_date: date
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


def _safe_version(value: object) -> str | None:
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 128:
        return value.strip()
    return None


def _safe_provider_code(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text or len(text) > 64:
        return None
    if _PROVIDER_CODE_PATTERN.fullmatch(text) or (
        text.startswith("-") and text[1:].isdigit()
    ):
        return text
    return None


def _close_client_safely(client: object | None) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _opaque_identity(value: object) -> dict[str, object] | None:
    """Persist only a stable identity for an opaque SDK paging key."""

    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if not raw:
            return None
        return {
            "kind": "bytes",
            "byte_length": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise HistoricalSourceSchemaError("Futu page key is not finite")
        safe = canonical_json_bytes(value)
        return {
            "kind": type(value).__name__,
            "sha256": hashlib.sha256(safe).hexdigest(),
        }
    raise HistoricalSourceSchemaError("Futu page key has an unsupported representation")


def _json_safe(value: object, *, path: str = "value") -> object:
    """Detach provider values without stringifying unknown objects."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise HistoricalSourceSchemaError(f"Futu {path} contains a non-finite value")
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {
            "kind": "opaque-bytes",
            "byte_length": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise HistoricalSourceSchemaError(f"Futu {path} has a non-string object key")
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
            raise HistoricalSourceSchemaError(
                f"Futu {path} contains an unsupported scalar"
            ) from exc
        if detached is value:
            raise HistoricalSourceSchemaError(f"Futu {path} contains an unsupported scalar")
        return _json_safe(detached, path=path)
    raise HistoricalSourceSchemaError(f"Futu {path} contains an unsupported value")


def _column_name(value: object) -> str:
    if isinstance(value, str):
        name = value
    else:
        item = getattr(value, "item", None)
        if not callable(item):
            raise HistoricalSourceSchemaError("Futu response has a non-string column name")
        name = item()
    if not isinstance(name, str) or not name.strip():
        raise HistoricalSourceSchemaError("Futu response has an invalid column name")
    return name.strip()


def _frame_rows(data: object) -> tuple[list[str], list[dict[str, object]]]:
    """Export a pandas-like frame or an explicitly shaped fake frame."""

    raw_columns: object | None = None
    raw_rows: object
    if hasattr(data, "to_dict"):
        to_dict = getattr(data, "to_dict")
        if not callable(to_dict):
            raise HistoricalSourceSchemaError("Futu response to_dict is not callable")
        try:
            raw_rows = to_dict(orient="records")
        except TypeError as exc:
            raise HistoricalSourceSchemaError("Futu response is not a records DataFrame") from exc
        raw_columns = getattr(data, "columns", None)
    elif isinstance(data, Mapping) and "rows" in data:
        raw_rows = data.get("rows")
        raw_columns = data.get("columns")
    elif isinstance(data, list):
        raw_rows = data
    elif isinstance(data, Mapping):
        raw_rows = [data]
    else:
        raise HistoricalSourceSchemaError("Futu response data is not a supported table")

    if not isinstance(raw_rows, list):
        raise HistoricalSourceSchemaError("Futu response rows are not a list")
    if raw_columns is None:
        discovered: list[str] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, Mapping):
                raise HistoricalSourceSchemaError("Futu response row is not an object")
            for key in raw_row:
                name = _column_name(key)
                if name not in discovered:
                    discovered.append(name)
        columns = discovered
    else:
        if isinstance(raw_columns, (str, bytes)):
            raise HistoricalSourceSchemaError("Futu response columns are not a sequence")
        try:
            columns = [_column_name(value) for value in raw_columns]  # type: ignore[union-attr]
        except TypeError as exc:
            raise HistoricalSourceSchemaError("Futu response columns are not a sequence") from exc
    if len(columns) != len(set(columns)):
        raise HistoricalSourceSchemaError("Futu response contains duplicate columns")
    if not FUTU_OPEND_REQUIRED_COLUMNS.issubset(columns):
        raise HistoricalSourceSchemaError("Futu response is missing required daily-K columns")

    rows: list[dict[str, object]] = []
    for row_index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise HistoricalSourceSchemaError("Futu response row is not an object")
        detached: dict[str, object] = {}
        for raw_key, raw_value in raw_row.items():
            key = _column_name(raw_key)
            if key not in columns:
                raise HistoricalSourceSchemaError("Futu response row has an undeclared column")
            detached[key] = _json_safe(raw_value, path=f"rows[{row_index}].{key}")
        if not FUTU_OPEND_REQUIRED_COLUMNS.issubset(detached):
            raise HistoricalSourceSchemaError("Futu response row is missing required fields")
        rows.append(detached)
    return columns, rows


def _numeric(value: object, *, field_name: str, nonnegative: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise HistoricalIngestionError(f"Futu {field_name} is not numeric")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalIngestionError(f"Futu {field_name} is not numeric")
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoricalIngestionError(f"Futu {field_name} is not numeric") from exc
    if not math.isfinite(number):
        raise HistoricalIngestionError(f"Futu {field_name} is not finite")
    if nonnegative and number < 0:
        raise HistoricalIngestionError(f"Futu {field_name} is negative")
    return number


def _parse_time_key(value: object, *, timezone_name: str) -> tuple[date, datetime]:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalIngestionError("Futu time_key is not an explicit date/time string")
    zone = ZoneInfo(timezone_name)
    text = value.strip()
    try:
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            return parsed_date, datetime.combine(parsed_date, time(12), tzinfo=zone)
        iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(iso_text)
    except ValueError as exc:
        raise HistoricalIngestionError("Futu time_key is not a supported ISO date/time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=zone)
    else:
        parsed = parsed.astimezone(zone)
    return parsed.date(), parsed


def _unpack_result(result: object) -> tuple[object, object, object]:
    if not isinstance(result, (tuple, list)) or len(result) != 3:
        raise HistoricalSourceSchemaError("Futu history response is not a three-part result")
    return result[0], result[1], result[2]


def _parse_quota_result(result: object, *, ret_ok: object) -> dict[str, object] | None:
    if not isinstance(result, (tuple, list)) or len(result) < 2:
        return None
    ret = result[0]
    values: list[object]
    if len(result) == 2 and isinstance(result[1], Mapping):
        data = result[1]
        used = data.get("used_quota")
        remaining = data.get("remain_quota")
        details = data.get("detail_list")
    elif len(result) == 2 and isinstance(result[1], (tuple, list)):
        values = list(result[1])
        used = values[0] if len(values) > 0 else None
        remaining = values[1] if len(values) > 1 else None
        details = values[2:] if len(values) > 2 else []
    else:
        values = list(result[1:])
        used = values[0] if len(values) > 0 else None
        remaining = values[1] if len(values) > 1 else None
        details = values[2:] if len(values) > 2 else []
    if ret != ret_ok:
        return {
            "status": "UNKNOWN",
            "provider_code": _safe_provider_code(ret),
        }
    if isinstance(used, bool) or not isinstance(used, int):
        return None
    if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
        return None
    detail_count = len(details) if isinstance(details, (list, tuple)) else 0
    return {
        "status": "AVAILABLE",
        "used": used,
        "remaining": remaining,
        "detail_count": detail_count,
    }


def _schema_blocker() -> str:
    return FUTU_SCHEMA_UNSUPPORTED + ": required daily-K schema or semantics are unsupported"


def _diagnostic_for_exception(exc: Exception) -> str:
    if isinstance(exc, FutuOpenDProviderError):
        return exc.diagnostic
    if isinstance(exc, (NetworkTransportError, ConnectionError, OSError, TimeoutError)):
        return FUTU_OPEND_UNAVAILABLE
    return FUTU_HISTORY_REQUEST_FAILED


def _as_session(value: FutuOpenDSession | FutuOpenDClient) -> FutuOpenDSession:
    if isinstance(value, FutuOpenDSession):
        return value
    return FutuOpenDSession(client=value)


def _canonical_market_bar(
    row: Mapping[str, object],
    *,
    details: _FutuRequestDetails,
    source_hash: str,
) -> tuple[_FutuObservation, MarketBar]:
    returned_code = row.get("code")
    if not isinstance(returned_code, str) or returned_code != details.futu_code:
        raise HistoricalIngestionError("Futu response listing identity differs from the request")
    trading_date, timestamp = _parse_time_key(
        row.get("time_key"), timezone_name=details.timezone_name
    )
    open_price = _numeric(row.get("open"), field_name="open")
    high_price = _numeric(row.get("high"), field_name="high")
    low_price = _numeric(row.get("low"), field_name="low")
    close_price = _numeric(row.get("close"), field_name="close")
    volume = _numeric(row.get("volume"), field_name="volume", nonnegative=True)
    turnover = _numeric(row.get("turnover"), field_name="turnover", nonnegative=True)
    if min(open_price, high_price, low_price, close_price) <= 0:
        raise HistoricalIngestionError("Futu OHLC prices must be positive")
    if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
        raise HistoricalIngestionError("Futu OHLC range is inconsistent")
    observation = _FutuObservation(
        trading_date=trading_date,
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        turnover=turnover,
    )
    try:
        bar = MarketBar(
            bar_id=f"{details.listing_id}:{trading_date.isoformat()}",
            listing_id=details.listing_id,
            market=Market.H,
            trading_date=trading_date,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            amount=turnover,
            currency=details.currency,
            source_hash=source_hash,
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalIngestionError("Futu daily-K row failed canonical validation") from exc
    return observation, bar


def _envelope_request_matches(
    envelope: Mapping[str, object],
    *,
    details: _FutuRequestDetails,
) -> None:
    if envelope.get("contract") != "futu_opend_sdk_export_v1":
        raise HistoricalIngestionError("Futu provider envelope contract is unsupported")
    if envelope.get("representation_id") != FUTU_OPEND_REPRESENTATION_ID:
        raise HistoricalIngestionError("Futu provider envelope representation is unsupported")
    request = envelope.get("request")
    if not isinstance(request, Mapping):
        raise HistoricalIngestionError("Futu provider envelope has no request metadata")
    expected = {
        "listing_id": details.listing_id,
        "futu_code": details.futu_code,
        "canonical_market": Market.H.value,
        "currency": details.currency,
        "source_uri": details.source_uri,
        "start_date": details.start_date.isoformat(),
        "end_date": details.end_date.isoformat(),
        "kline_type": "K_DAY",
        "adjustment": "NONE",
        "timezone": details.timezone_name,
        "max_count": details.max_count,
        "opend_host": details.host,
        "opend_port": details.port,
    }
    for key, expected_value in expected.items():
        if request.get(key) != expected_value:
            raise HistoricalIngestionError("Futu provider envelope request identity changed")


def _observations_from_envelope(
    envelope: Mapping[str, object],
    *,
    details: _FutuRequestDetails,
    source_hash: str,
) -> tuple[list[_FutuObservation], list[MarketBar]]:
    _envelope_request_matches(envelope, details=details)
    pages = envelope.get("pages")
    if not isinstance(pages, list):
        raise HistoricalIngestionError("Futu provider envelope pages are not a list")
    observations: list[_FutuObservation] = []
    bars: list[MarketBar] = []
    seen_dates: set[date] = set()
    for expected_ordinal, page in enumerate(pages, start=1):
        if not isinstance(page, Mapping) or page.get("page_ordinal") != expected_ordinal:
            raise HistoricalIngestionError("Futu provider envelope page order is invalid")
        columns = page.get("columns")
        rows = page.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise HistoricalIngestionError("Futu provider envelope page schema is invalid")
        if len(columns) != len(set(columns)) or not FUTU_OPEND_REQUIRED_COLUMNS.issubset(columns):
            raise HistoricalIngestionError("Futu provider envelope required columns changed")
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                raise HistoricalIngestionError("Futu provider envelope row is not an object")
            observation, bar = _canonical_market_bar(
                raw_row,
                details=details,
                source_hash=source_hash,
            )
            if observation.trading_date in seen_dates:
                raise HistoricalIngestionError("Futu provider envelope contains duplicate dates")
            seen_dates.add(observation.trading_date)
            observations.append(observation)
            if details.start_date <= observation.trading_date <= details.end_date:
                bars.append(bar)
    return observations, bars


class FutuOpenDDailyKDecoder:
    """Decode a frozen Futu SDK export into unadjusted daily ``MarketBar`` rows."""

    adapter_id = FUTU_OPEND_ADAPTER_ID

    def __init__(self, schema_version: str = FUTU_OPEND_SCHEMA_VERSION) -> None:
        self.schema_version = schema_version

    @staticmethod
    def _validate_receipt(receipt: RawArtifactReceiptV1, schema_version: str) -> None:
        if receipt.adapter_id != FUTU_OPEND_ADAPTER_ID:
            raise HistoricalIngestionError("Futu decoder adapter identity mismatch")
        if receipt.artifact_kind is not ShardArtifactKind.MARKET_BAR:
            raise HistoricalIngestionError("Futu decoder requires MARKET_BAR")
        if receipt.schema_version != schema_version:
            raise HistoricalIngestionError("Futu decoder schema version is unrecognized")
        if receipt.artifact_metadata.get("representation") != FUTU_OPEND_REPRESENTATION_ID:
            raise HistoricalIngestionError("Futu receipt representation is not an SDK export")

    @staticmethod
    def _details_from_receipt(receipt: RawArtifactReceiptV1) -> _FutuRequestDetails:
        parameters = receipt.canonical_parameters
        listing_id = receipt.artifact_metadata.get("listing_id")
        if not isinstance(listing_id, str):
            raise HistoricalIngestionError("Futu receipt has no explicit listing identity")
        try:
            start_date = date.fromisoformat(str(receipt.artifact_metadata["start_date"]))
            end_date = date.fromisoformat(str(receipt.artifact_metadata["end_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalIngestionError("Futu receipt has no bounded date metadata") from exc
        details = _request_details_from_parameters(
            parameters,
            listing_id=listing_id,
            start_date=start_date,
            end_date=end_date,
        )
        if receipt.source_uri != details.source_uri:
            raise HistoricalIngestionError("Futu receipt source URI differs from request metadata")
        return details

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        self._validate_receipt(receipt, self.schema_version)
        details = self._details_from_receipt(receipt)
        try:
            envelope = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HistoricalIngestionError("Futu SDK export is not valid JSON") from exc
        if not isinstance(envelope, Mapping):
            raise HistoricalIngestionError("Futu SDK export is not an object")
        _, bars = _observations_from_envelope(
            envelope,
            details=details,
            source_hash=receipt.sha256,
        )
        return bars

    def decode_scoped(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
        request: HistoricalAcquisitionRequestV1,
    ) -> list[BaseModel]:
        self._validate_receipt(receipt, self.schema_version)
        details = _request_details(request)
        try:
            envelope = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HistoricalIngestionError("Futu SDK export is not valid JSON") from exc
        if not isinstance(envelope, Mapping):
            raise HistoricalIngestionError("Futu SDK export is not an object")
        _, bars = _observations_from_envelope(
            envelope,
            details=details,
            source_hash=receipt.sha256,
        )
        return bars


def _request_details_from_parameters(
    parameters: Mapping[str, object],
    *,
    listing_id: str,
    start_date: date,
    end_date: date,
) -> _FutuRequestDetails:
    if not listing_id.strip():
        raise HistoricalSourceSchemaError("Futu listing identity must be explicit")
    if end_date < start_date:
        raise HistoricalSourceSchemaError("Futu end date precedes start date")
    if (end_date - start_date).days > FUTU_OPEND_MAX_RANGE_DAYS:
        raise HistoricalSourceSchemaError("Futu request date range is not bounded")
    if parameters.get("canonical_market") != Market.H.value:
        raise HistoricalSourceSchemaError("Futu adapter requires canonical_market=H")
    if parameters.get("currency") != "HKD":
        raise HistoricalSourceSchemaError("Futu H market bars require currency=HKD")
    futu_code = parameters.get("futu_code")
    if not isinstance(futu_code, str) or not futu_code.strip() or any(
        char.isspace() for char in futu_code
    ):
        raise HistoricalSourceSchemaError(
            "Futu code must be explicitly supplied as futu_code; no FQGate identity is inferred"
        )
    kline_type = parameters.get("kline_type", parameters.get("ktype"))
    if kline_type != "K_DAY":
        raise HistoricalSourceSchemaError("Futu history request must explicitly use K_DAY")
    adjustment = parameters.get("adjustment", parameters.get("autype"))
    if adjustment != "NONE":
        raise HistoricalSourceSchemaError(
            "Futu history request must explicitly use unadjusted NONE"
        )
    timezone_name = parameters.get("timezone", FUTU_OPEND_TIMEZONE)
    if timezone_name != FUTU_OPEND_TIMEZONE:
        raise HistoricalSourceSchemaError(
            "Futu H daily history requires the documented Asia/Shanghai timezone"
        )
    max_count = parameters.get("max_count", FUTU_OPEND_DEFAULT_MAX_COUNT)
    if type(max_count) is not int or not 1 <= max_count <= FUTU_OPEND_DEFAULT_MAX_COUNT:
        raise HistoricalSourceSchemaError("Futu max_count must be between 1 and 1000")
    max_pages = parameters.get("max_pages", FUTU_OPEND_DEFAULT_MAX_PAGES)
    if type(max_pages) is not int or not 1 <= max_pages <= FUTU_OPEND_DEFAULT_MAX_PAGES:
        raise HistoricalSourceSchemaError("Futu max_pages is outside the bounded range")
    source_uri = parameters.get("source_uri", FUTU_OPEND_SOURCE_URI)
    if not isinstance(source_uri, str):
        raise HistoricalSourceSchemaError("Futu source_uri must be an explicit HTTP(S) URI")
    parsed = urlparse(source_uri)
    if parsed.query or parsed.fragment:
        raise HistoricalSourceSchemaError("Futu source_uri must not contain query or fragment")
    safe_source_uri = _safe_uri(source_uri)
    if safe_source_uri is None:
        raise HistoricalSourceSchemaError("Futu source_uri must be an absolute HTTP(S) URI")
    host = parameters.get("opend_host", FUTU_OPEND_DEFAULT_HOST)
    if not isinstance(host, str) or not host.strip():
        raise HistoricalSourceSchemaError("Futu OpenD host is invalid")
    normalized_host = host.strip()
    if normalized_host.lower() != "localhost":
        try:
            if not ipaddress.ip_address(normalized_host).is_loopback:
                raise HistoricalSourceSchemaError("Futu OpenD host must be local loopback")
        except ValueError as exc:
            raise HistoricalSourceSchemaError("Futu OpenD host must be local loopback") from exc
    port = parameters.get("opend_port", FUTU_OPEND_DEFAULT_PORT)
    if type(port) is not int or not 1 <= port <= 65_535:
        raise HistoricalSourceSchemaError("Futu OpenD port is invalid")
    return _FutuRequestDetails(
        source_uri=safe_source_uri,
        listing_id=listing_id,
        futu_code=futu_code.strip(),
        start_date=start_date,
        end_date=end_date,
        currency="HKD",
        timezone_name=FUTU_OPEND_TIMEZONE,
        max_count=max_count,
        max_pages=max_pages,
        host=normalized_host,
        port=port,
    )


def _request_details(request: HistoricalAcquisitionRequestV1) -> _FutuRequestDetails:
    if request.artifact_kind is not ShardArtifactKind.MARKET_BAR:
        raise HistoricalSourceSchemaError("Futu adapter requires MARKET_BAR requests")
    if request.source_kind.value != "PRICES":
        raise HistoricalSourceSchemaError("Futu adapter requires PRICES requests")
    if len(request.listing_ids) != 1:
        raise HistoricalSourceSchemaError("Futu history requests accept one listing")
    if request.credential_ref is not None:
        raise HistoricalSourceSchemaError(
            "Futu OpenD uses the owner-managed local session and does not accept credentials"
        )
    return _request_details_from_parameters(
        request.parameters,
        listing_id=request.listing_ids[0],
        start_date=request.start_date,
        end_date=request.end_date,
    )


class FutuOpenDMarketHistoryAdapter:
    """Opt-in Futu OpenD adapter for bounded, unadjusted H daily bars."""

    adapter_id = FUTU_OPEND_ADAPTER_ID
    adapter_version = FUTU_OPEND_ADAPTER_VERSION
    requires_live_credential = False

    def __init__(
        self,
        client_factory: FutuOpenDRequestClientFactory | Callable[..., object] | None = None,
    ) -> None:
        self._client_factory = client_factory or LazyFutuOpenDClientFactory()

    def _open_session(self, details: _FutuRequestDetails) -> FutuOpenDSession:
        try:
            value = self._client_factory(host=details.host, port=details.port)
        except FutuOpenDProviderError:
            raise
        except (ConnectionError, OSError, TimeoutError) as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.SDK_INCOMPATIBLE) from exc
        except Exception as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
        return _as_session(value)

    @staticmethod
    def _inspect_quota(session: FutuOpenDSession) -> tuple[dict[str, object], list[str]]:
        quota_method = getattr(session.client, "get_history_kl_quota", None)
        if not callable(quota_method):
            return {"status": "UNAVAILABLE"}, [FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED]
        try:
            result = quota_method(get_detail=True)
        except FutuOpenDProviderError as exc:
            if exc.diagnostic in {
                FUTU_OPEND_UNAVAILABLE,
                FUTU_SDK_INCOMPATIBLE,
                FUTU_ENTITLEMENT_DENIED,
            }:
                raise
            return {"status": "UNKNOWN"}, [FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED]
        except (ConnectionError, OSError, TimeoutError) as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
        except Exception:
            return {"status": "UNKNOWN"}, [FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED]
        parsed = _parse_quota_result(result, ret_ok=session.ret_ok)
        if parsed is None:
            return {"status": "UNKNOWN"}, [FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED]
        if parsed.get("status") != "AVAILABLE":
            return parsed, [FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED]
        remaining = parsed.get("remaining")
        if remaining == 0:
            raise FutuOpenDProviderError(FutuDiagnostic.HISTORY_QUOTA_EXHAUSTED)
        return parsed, []

    @staticmethod
    def _request_page(
        session: FutuOpenDSession,
        details: _FutuRequestDetails,
        page_key: object | None,
    ) -> tuple[object, object, object]:
        try:
            result = session.client.request_history_kline(
                details.futu_code,
                start=details.start_date.isoformat(),
                end=details.end_date.isoformat(),
                ktype=session.k_day,
                autype=session.au_none,
                fields=[session.fields_all],
                max_count=details.max_count,
                page_req_key=page_key,
                extended_time=False,
            )
            return _unpack_result(result)
        except FutuOpenDProviderError:
            raise
        except (ConnectionError, OSError, TimeoutError, NetworkTransportError) as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
        except (AttributeError, TypeError) as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.SDK_INCOMPATIBLE) from exc
        except HistoricalSourceSchemaError:
            raise
        except Exception as exc:
            raise FutuOpenDProviderError(FutuDiagnostic.HISTORY_REQUEST_FAILED) from exc

    def _fetch(self, request: HistoricalAcquisitionRequestV1) -> _FutuFetchResult:
        details = _request_details(request)
        session: FutuOpenDSession | None = None
        try:
            session = self._open_session(details)
            quota, quota_diagnostics = self._inspect_quota(session)
            pages: list[dict[str, object]] = []
            page_key: object | None = None
            seen_page_keys: set[str] = set()
            all_rows: list[dict[str, object]] = []
            columns_by_page: list[list[str]] = []
            for page_ordinal in range(1, details.max_pages + 1):
                page_key_in = _opaque_identity(page_key)
                ret, data, next_page_key = self._request_page(session, details, page_key)
                if ret != session.ret_ok:
                    raise FutuOpenDProviderError(
                        FutuDiagnostic.HISTORY_REQUEST_FAILED,
                        provider_code=ret if isinstance(ret, (str, int)) else None,
                    )
                columns, rows = _frame_rows(data)
                columns_by_page.append(columns)
                all_rows.extend(rows)
                page_key_out = _opaque_identity(next_page_key)
                page = {
                    "page_ordinal": page_ordinal,
                    "page_key_in": page_key_in,
                    "page_key_out": page_key_out,
                    "columns": columns,
                    "rows": rows,
                }
                pages.append(page)
                if page_key_out is None:
                    break
                identity = canonical_json_bytes(page_key_out).decode("utf-8")
                if identity in seen_page_keys:
                    raise HistoricalSourceSchemaError("Futu pagination key repeated")
                seen_page_keys.add(identity)
                page_key = next_page_key
            else:
                raise HistoricalSourceSchemaError("Futu pagination exceeded the bounded page limit")

            envelope: dict[str, object] = {
                "contract": "futu_opend_sdk_export_v1",
                "representation_id": FUTU_OPEND_REPRESENTATION_ID,
                "provider": {
                    "provider_id": "futu-opend",
                    "adapter_id": self.adapter_id,
                    "adapter_version": self.adapter_version,
                    "sdk_version": session.sdk_version,
                    "opend_version": session.opend_version,
                },
                "request": {
                    "listing_id": details.listing_id,
                    "futu_code": details.futu_code,
                    "canonical_market": Market.H.value,
                    "currency": details.currency,
                    "source_uri": details.source_uri,
                    "start_date": details.start_date.isoformat(),
                    "end_date": details.end_date.isoformat(),
                    "kline_type": "K_DAY",
                    "adjustment": "NONE",
                    "requested_fields": ["ALL"],
                    "max_count": details.max_count,
                    "timezone": details.timezone_name,
                    "opend_host": details.host,
                    "opend_port": details.port,
                    "extended_time": False,
                },
                "quota": quota,
                "diagnostics": quota_diagnostics,
                "pages": pages,
                "page_count": len(pages),
                "row_count": len(all_rows),
                "columns_by_page": columns_by_page,
            }
            body = canonical_json_bytes(envelope)
            # Validate the complete envelope before returning a successful
            # acquisition.  The compiler repeats this validation offline.
            _observations_from_envelope(
                envelope,
                details=details,
                source_hash=hashlib.sha256(body).hexdigest(),
            )
            return _FutuFetchResult(
                details=details,
                envelope=envelope,
                body=body,
                rows=all_rows,
                quota=quota,
                diagnostics=quota_diagnostics,
                sdk_version=session.sdk_version,
                opend_version=session.opend_version,
            )
        finally:
            if session is not None:
                try:
                    session.client.close()
                except (ConnectionError, OSError, TimeoutError) as exc:
                    raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc
                except Exception as exc:
                    raise FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE) from exc

    @staticmethod
    def _probe_report(
        request: HistoricalAcquisitionRequestV1,
        *,
        plan_id: str,
        status: ProbeStatus,
        started: datetime,
        finished: datetime,
        **values: object,
    ) -> SourceProbeReportV1:
        return SourceProbeReportV1.build(
            report_id=f"probe-{request.request_id}",
            plan_id=plan_id,
            request_id=request.request_id,
            source_id=request.source_id,
            adapter_id=FUTU_OPEND_ADAPTER_ID,
            adapter_version=FUTU_OPEND_ADAPTER_VERSION,
            source_kind=request.source_kind,
            status=status,
            started_at=started,
            finished_at=finished,
            **values,
        )

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
        except FutuOpenDProviderError as exc:
            raise AcquisitionError(_diagnostic_message(exc)) from exc
        except (HistoricalSourceSchemaError, HistoricalIngestionError) as exc:
            raise HistoricalSourceSchemaError(_schema_blocker()) from exc
        details = fetched.details
        metadata: dict[str, object] = {
            "representation": FUTU_OPEND_REPRESENTATION_ID,
            "provider_id": "futu-opend",
            "sdk_version": fetched.sdk_version,
            "opend_version": fetched.opend_version,
            "listing_id": details.listing_id,
            "futu_code": details.futu_code,
            "canonical_market": Market.H.value,
            "currency": details.currency,
            "opend_host": details.host,
            "opend_port": details.port,
            "start_date": details.start_date.isoformat(),
            "end_date": details.end_date.isoformat(),
            "kline_type": "K_DAY",
            "adjustment": "NONE",
            "page_count": fetched.envelope["page_count"],
            "row_count": fetched.envelope["row_count"],
            "quota_status": fetched.quota.get("status"),
            "quota_remaining": fetched.quota.get("remaining"),
        }
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
                artifact_metadata=metadata,
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
        started = _utc_now(clock)
        try:
            details = _request_details(request)
            fetched = self._fetch(request)
            finished = _utc_now(clock)
            source_hash = hashlib.sha256(fetched.body).hexdigest()
            observations, bars = _observations_from_envelope(
                fetched.envelope,
                details=details,
                source_hash=source_hash,
            )
        except (HistoricalSourceSchemaError, HistoricalIngestionError):
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[_schema_blocker()],
            )
        except CredentialUnavailableError:
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.BLOCKED,
                started=started,
                finished=finished,
                blockers=[FUTU_OPEND_UNAVAILABLE],
            )
        except FutuOpenDProviderError as exc:
            finished = _utc_now(clock)
            diagnostic = exc.diagnostic
            status = (
                ProbeStatus.BLOCKED
                if diagnostic
                in {FUTU_OPEND_UNAVAILABLE, FUTU_SDK_UNAVAILABLE, FUTU_SDK_INCOMPATIBLE}
                else ProbeStatus.FAILED
            )
            entitlement = (
                AccountEntitlement.DENIED
                if diagnostic == FUTU_ENTITLEMENT_DENIED
                else AccountEntitlement.UNKNOWN
            )
            blocker = _diagnostic_message(exc)
            return self._probe_report(
                request,
                plan_id=plan_id,
                status=status,
                started=started,
                finished=finished,
                account_entitlement=entitlement,
                blockers=[blocker],
            )
        except Exception:
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[FUTU_HISTORY_REQUEST_FAILED],
            )

        common = {
            "http_status": 200,
            "content_type": "application/json",
            "content_length": len(fetched.body),
            "response_sha256": hashlib.sha256(fetched.body).hexdigest(),
            "source_uri": details.source_uri,
        }
        if not bars:
            blocker = (
                FUTU_NO_ROWS
                if not observations
                else FUTU_COVERAGE_INSUFFICIENT
            )
            return self._probe_report(
                request,
                plan_id=plan_id,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                account_entitlement=AccountEntitlement.UNKNOWN,
                blockers=[blocker],
                **common,
            )
        observed_dates = {bar.trading_date for bar in bars}
        blockers: list[str] = []
        if min(observed_dates) > request.start_date or max(observed_dates) < request.end_date:
            blockers.append(FUTU_COVERAGE_INSUFFICIENT)
        for _listing_id, expected_sessions in (request.expected_sessions_by_listing or {}).items():
            if set(expected_sessions) - observed_dates:
                blockers.append(FUTU_COVERAGE_INSUFFICIENT + ": expected sessions are missing")
        status = ProbeStatus.PASS if not blockers else ProbeStatus.FAILED
        warnings = [
            "FUTU_UNADJUSTED_DAILY_ONLY: adjustment is fixed to NONE",
            "FUTU_SDK_EXPORT_NOT_RAW_OPEND_WIRE: provider envelope is a decoded SDK export",
            "FUTU_H_IDENTITY_OPERATOR_SUPPLIED: futu_code is never inferred from FQGate fields",
            "FUTU_NO_ACTION_OR_TERMINAL_EVIDENCE: this adapter only proves market bars",
            *fetched.diagnostics,
        ]
        return self._probe_report(
            request,
            plan_id=plan_id,
            status=status,
            started=started,
            finished=finished,
            account_entitlement=AccountEntitlement.CONFIRMED,
            observed_start=min(observed_dates),
            observed_end=max(observed_dates),
            observed_listing_ids=[request.listing_ids[0]],
            historical_capable=not blockers,
            terminal_coverage="UNKNOWN",
            action_coverage="UNKNOWN",
            blockers=blockers,
            warnings=warnings,
            **common,
        )


def _diagnostic_message(error: FutuOpenDProviderError) -> str:
    if error.provider_code is None:
        return error.diagnostic
    return f"{error.diagnostic}: provider code {error.provider_code}"


# Descriptive alias for callers that use the provider's historical role name.
FutuOpenDHistoricalMarketAdapter = FutuOpenDMarketHistoryAdapter
FutuOpenDMarketBarDecoder = FutuOpenDDailyKDecoder


__all__ = [
    "FUTU_COVERAGE_INSUFFICIENT",
    "FUTU_ENTITLEMENT_DENIED",
    "FUTU_HISTORY_QUOTA_CHECK_UNCLASSIFIED",
    "FUTU_HISTORY_QUOTA_EXHAUSTED",
    "FUTU_HISTORY_REQUEST_FAILED",
    "FUTU_NO_ROWS",
    "FUTU_OPEND_ADAPTER_ID",
    "FUTU_OPEND_ADAPTER_VERSION",
    "FUTU_OPEND_REPRESENTATION_ID",
    "FUTU_OPEND_SOURCE_URI",
    "FUTU_OPEND_UNAVAILABLE",
    "FUTU_SCHEMA_UNSUPPORTED",
    "FUTU_SDK_INCOMPATIBLE",
    "FUTU_SDK_UNAVAILABLE",
    "FutuDiagnostic",
    "FutuOpenDClient",
    "FutuOpenDClientFactory",
    "FutuOpenDDailyKDecoder",
    "FutuOpenDHistoricalMarketAdapter",
    "FutuOpenDMarketBarDecoder",
    "FutuOpenDMarketHistoryAdapter",
    "FutuOpenDProviderError",
    "FutuOpenDRequestClientFactory",
    "FutuOpenDSession",
    "LazyFutuOpenDClientFactory",
]

# Compatibility name for callers that expect the shorter factory label.
FutuOpenDClientFactory = LazyFutuOpenDClientFactory
