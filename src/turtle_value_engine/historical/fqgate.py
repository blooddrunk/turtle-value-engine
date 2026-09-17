"""FQGate historical daily-K adapters for local and remote endpoints.

FQGate is intentionally integrated as a small HTTP source adapter.  This
module does not import the FQGate agent/plugin project and does not make any
claim about an account's market entitlement or historical retention.

The public FQGate client/UI currently documents the following daily-K fields:

* ``1``: time;
* ``7``, ``8``, ``9``, ``11``: open, high, low, close;
* ``13``: volume;
* ``19``: amount.

Only the unadjusted daily shape is accepted here.  An operator must provide
the actual FQGate ``market`` and ``code`` values in the acquisition plan.  In
particular, no H-share market identifier is inferred by this adapter.  The
legacy local adapter remains available alongside the explicit endpoint-
topology adapter; no remote bridge route or authentication contract is
inferred by this module.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from turtle_value_engine.backtest import Market, MarketBar
from turtle_value_engine.historical.contracts import ShardArtifactKind
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
    _credential_value,
    _safe_uri,
    _utc_now,
)

_FQGATE_ENDPOINT_PATH = "/v1/market/history/klines"
_FQGATE_LEGACY_ADAPTER_ID = "fqgate-local-market-history"
_FQGATE_DEPLOYMENT_NEUTRAL_ADAPTER_ID = "fqgate-market-history"
_FQGATE_RESPONSE_CONTRACT = "fqgate-envelope-v1"
_FQGATE_ALLOWED_ENVELOPE_KEYS = frozenset({"code", "message", "data", "warnings"})
_FQGATE_ALLOWED_DATA_KEYS = frozenset(
    {
        "business_type",
        "data_state",
        "format",
        "instance",
        "record_count",
        "records",
        "row_count",
        "segment_count",
    }
)
_FQGATE_FIELD_KEYS = frozenset({"1", "7", "8", "9", "11", "13", "19"})
_FQGATE_LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
_FQGATE_PROVIDER_ERROR_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")

FQGATE_LOCAL_GATEWAY_UNREACHABLE = "FQGATE_LOCAL_GATEWAY_UNREACHABLE"
FQGATE_REMOTE_ENDPOINT_UNREACHABLE = "FQGATE_REMOTE_ENDPOINT_UNREACHABLE"
FQGATE_REMOTE_AUTH_DENIED = "FQGATE_REMOTE_AUTH_DENIED"
FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED = "FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED"
REMOTE_BRIDGE_LIVE_UNPROVEN = "REMOTE_BRIDGE_LIVE_UNPROVEN"
FQGATE_H_ROUTE_UNVERIFIED = "FQGATE_H_ROUTE_UNVERIFIED"
# These two prefixes are reserved for independently established provider
# semantics; this repository currently has no such evidence and emits neither.
FQGATE_H_ROUTE_REJECTED = "FQGATE_H_ROUTE_REJECTED"
FQGATE_HTTP_504_UNCLASSIFIED = "FQGATE_HTTP_504_UNCLASSIFIED"
FQGATE_UPSTREAM_TIMEOUT_CONFIRMED = "FQGATE_UPSTREAM_TIMEOUT_CONFIRMED"
FQGATE_ENTITLEMENT_DENIED = "FQGATE_ENTITLEMENT_DENIED"
FQGATE_PROVIDER_ERROR_CODE = "FQGATE_PROVIDER_ERROR_CODE"
FQGATE_PROVIDER_ERROR_UNCLASSIFIED = "FQGATE_PROVIDER_ERROR_UNCLASSIFIED"
HISTORICAL_NO_ROWS = "HISTORICAL_NO_ROWS"
HISTORICAL_COVERAGE_INSUFFICIENT = "HISTORICAL_COVERAGE_INSUFFICIENT"
SOURCE_SCHEMA_UNSUPPORTED = "SOURCE_SCHEMA_UNSUPPORTED"


class FQGateEndpointKind(StrEnum):
    """Explicit deployment topology for one FQGate historical request."""

    LOCAL_DIRECT = "LOCAL_DIRECT"
    REMOTE_BRIDGE = "REMOTE_BRIDGE"


class _FQGateShapeError(ValueError):
    """Internal parser error that is converted at the acquisition boundary."""


@dataclass(frozen=True, slots=True)
class _FQGateRequestDetails:
    source_uri: str
    endpoint_kind: FQGateEndpointKind
    response_contract: str
    market: str
    code: str
    canonical_market: Market
    currency: str
    count: int | None


@dataclass(frozen=True, slots=True)
class _FQGateObservation:
    trading_date: date
    timestamp: date | datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    amount: float | None


def _shape_error(message: str) -> _FQGateShapeError:
    return _FQGateShapeError("FQGate response shape is unsupported: " + message)


def _safe_provider_error_code(raw_bytes: bytes) -> str | None:
    """Extract only a bounded scalar error code from a provider response.

    FQGate's public client forwards the top-level ``code`` value (with an
    ``api_error`` fallback) from an HTTP error body, but does not define a
    closed set of meanings for those codes.
    Keep the code as a diagnostic only; never retain the accompanying message
    or details, which may contain arbitrary provider or session information.
    """

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw_code = payload.get("code")
    if raw_code is None:
        raw_code = payload.get("api_error")
    if isinstance(raw_code, bool) or not isinstance(raw_code, (int, str)):
        return None
    code = str(raw_code).strip()
    if isinstance(raw_code, int):
        return code if code and len(code) <= 64 else None
    if not code or not (
        _FQGATE_PROVIDER_ERROR_CODE_PATTERN.fullmatch(code)
        or (code.startswith("-") and code[1:].isdigit() and len(code) <= 64)
    ):
        return None
    return code


def _structured_error_code(raw_bytes: bytes) -> str | None:
    """Return a non-success top-level provider code when one is explicit."""

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or not (
        "code" in payload or "api_error" in payload
    ):
        return None
    if type(payload.get("code")) is int and payload.get("code") == 0:
        return None
    return _safe_provider_error_code(raw_bytes)


def _provider_error_code_blocker(raw_bytes: bytes) -> str | None:
    code = _safe_provider_error_code(raw_bytes)
    return f"{FQGATE_PROVIDER_ERROR_CODE}: {code}" if code is not None else None


def _http_error_blockers(
    response: NetworkResponse,
    *,
    endpoint_kind: FQGateEndpointKind,
) -> list[str]:
    """Classify only the HTTP facts that are independently observable.

    A response received through ``REMOTE_BRIDGE`` is not evidence that the
    response was generated by FQGate.  In particular, an edge/bridge 401 or
    403 must not be promoted to an FQGate entitlement denial, and a remote
    5xx must not be presented as a provider failure.  The legacy local path
    keeps the M2-A classification unchanged.
    """

    if endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE:
        if response.status_code in {401, 403}:
            return [f"{FQGATE_REMOTE_AUTH_DENIED}: HTTP {response.status_code}"]
        return [
            f"{FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED}: HTTP {response.status_code}"
        ]

    if response.status_code in {401, 403}:
        blockers = [f"{FQGATE_ENTITLEMENT_DENIED}: HTTP {response.status_code}"]
    elif response.status_code == 504:
        # A gateway status alone does not identify the failing upstream.  In
        # particular, do not turn the current H 504 into an upstream-timeout
        # claim merely because 504 is commonly used for that purpose.
        blockers = [f"{FQGATE_HTTP_504_UNCLASSIFIED}: HTTP 504"]
    else:
        blockers = [f"FQGATE_HTTP_ERROR_UNCLASSIFIED: HTTP {response.status_code}"]
    provider_code = _provider_error_code_blocker(response.body)
    if provider_code is not None:
        blockers.append(provider_code)
        blockers.append(
            f"{FQGATE_PROVIDER_ERROR_UNCLASSIFIED}: provider code semantics are not established"
        )
    return blockers


def _provider_error_blockers(raw_bytes: bytes) -> list[str] | None:
    """Classify an explicit error envelope without assigning unproven meaning."""

    code = _structured_error_code(raw_bytes)
    if code is None:
        return None
    return [
        f"{FQGATE_PROVIDER_ERROR_CODE}: {code}",
        f"{FQGATE_PROVIDER_ERROR_UNCLASSIFIED}: provider code semantics are not established",
    ]


def _h_route_is_unverified(request: HistoricalAcquisitionRequestV1) -> bool:
    """Detect only an absent/template H route; never derive a replacement route."""

    parameters = request.parameters
    if parameters.get("canonical_market") != Market.H.value:
        return False
    for key in ("market", "code"):
        value = parameters.get(key)
        if not isinstance(value, str) or not value.strip():
            return True
        stripped = value.strip()
        if stripped.startswith("<") and stripped.endswith(">"):
            return True
    return False


def _schema_blocker(exc: Exception) -> str:
    """Keep local parser diagnostics bounded and free of response text."""

    detail = str(exc).strip().replace("\n", " ")[:256]
    return f"{SOURCE_SCHEMA_UNSUPPORTED}: {detail}" if detail else SOURCE_SCHEMA_UNSUPPORTED


def _unwrap_field(value: object, *, field_id: str) -> object:
    if not isinstance(value, Mapping):
        return value
    if "value" not in value:
        raise _shape_error(f"field {field_id} has no value")
    if any(key not in {"type", "value"} for key in value):
        raise _shape_error(f"field {field_id} contains unknown keys")
    if "type" in value and not isinstance(value["type"], str):
        raise _shape_error(f"field {field_id} type is not a string")
    return value["value"]


def _field(record: Mapping[str, object], field_id: str, *, required: bool) -> object | None:
    if field_id not in record:
        if required:
            raise _shape_error(f"record is missing field {field_id}")
        return None
    value = _unwrap_field(record[field_id], field_id=field_id)
    if value is None and required:
        raise _shape_error(f"record field {field_id} is null")
    return value


def _number(value: object, *, field_id: str, required: bool) -> float | None:
    if value is None:
        if required:
            raise _shape_error(f"record field {field_id} is null")
        return None
    if isinstance(value, bool):
        raise _shape_error(f"record field {field_id} is boolean")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.replace(",", "").strip()
        if not text:
            raise _shape_error(f"record field {field_id} is empty")
        try:
            number = float(text)
        except ValueError as exc:
            raise _shape_error(f"record field {field_id} is not numeric") from exc
    else:
        raise _shape_error(f"record field {field_id} is not numeric")
    if not math.isfinite(number):
        raise _shape_error(f"record field {field_id} is not finite")
    return number


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_FQGATE_LOCAL_ZONE)
    return value.astimezone(_FQGATE_LOCAL_ZONE)


def _date_only(value: date) -> tuple[date, date | datetime]:
    # The public FQGate UI treats a date-only daily value as local noon.  Keep
    # that deterministic timestamp marker while leaving session boundaries
    # unset because the response does not provide them.
    return value, datetime.combine(value, time(12), tzinfo=_FQGATE_LOCAL_ZONE)


def _parse_time(value: object) -> tuple[date, date | datetime]:
    if isinstance(value, bool) or value is None:
        raise _shape_error("field 1 is not a supported date/time value")

    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise _shape_error("field 1 is not finite")
        text = str(int(numeric)) if numeric.is_integer() else str(numeric)
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise _shape_error("field 1 is not a supported date/time value")

    compact = re.sub(r"[-/: T]", "", text)
    if re.fullmatch(r"\d{8}", compact):
        try:
            return _date_only(date.fromisoformat(
                f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
            ))
        except ValueError as exc:
            raise _shape_error("field 1 contains an invalid calendar date") from exc
    if re.fullmatch(r"\d{12}", compact) or re.fullmatch(r"\d{14}", compact):
        try:
            parsed = datetime.strptime(
                compact,
                "%Y%m%d%H%M" if len(compact) == 12 else "%Y%m%d%H%M%S",
            )
        except ValueError as exc:
            raise _shape_error("field 1 contains an invalid local date/time") from exc
        parsed = _local_datetime(parsed)
        return parsed.date(), parsed

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed_iso = datetime.fromisoformat(iso_text)
    except ValueError:
        parsed_iso = None
    if parsed_iso is not None:
        parsed_iso = _local_datetime(parsed_iso)
        return parsed_iso.date(), parsed_iso

    try:
        numeric = float(text)
    except ValueError as exc:
        raise _shape_error("field 1 is not a supported date/time value") from exc
    if not math.isfinite(numeric):
        raise _shape_error("field 1 is not finite")
    if numeric > 10_000_000_000:
        numeric /= 1_000
    if numeric <= 100_000_000:
        raise _shape_error("field 1 is not a supported Unix timestamp")
    try:
        parsed_timestamp = datetime.fromtimestamp(numeric, tz=_FQGATE_LOCAL_ZONE)
    except (OverflowError, OSError, ValueError) as exc:
        raise _shape_error("field 1 contains an invalid Unix timestamp") from exc
    return parsed_timestamp.date(), parsed_timestamp


def _record_values(records: object) -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []

    def visit(value: object) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, Mapping):
            raise _shape_error("records must contain arrays and field records")
        if not value or not all(
            isinstance(key, str) and re.fullmatch(r"\d+", key) for key in value
        ):
            raise _shape_error("a record must contain only numeric field IDs")
        if not any(key in value for key in _FQGATE_FIELD_KEYS):
            raise _shape_error("a record contains no supported K-line field")
        result.append(value)

    if not isinstance(records, list):
        raise _shape_error("data.records must be an array")
    visit(records)
    return result


def _parse_envelope(raw_bytes: bytes) -> list[Mapping[str, object]]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _shape_error("body is not UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise _shape_error("envelope must be an object")
    if set(payload) - _FQGATE_ALLOWED_ENVELOPE_KEYS:
        raise _shape_error("envelope contains unknown keys")
    if type(payload.get("code")) is not int or payload.get("code") != 0:
        raise _shape_error("envelope code is not zero")
    if not isinstance(payload.get("message"), str):
        raise _shape_error("envelope message is not a string")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise _shape_error("envelope data is not an object")
    if set(data) - _FQGATE_ALLOWED_DATA_KEYS or "records" not in data:
        raise _shape_error("data does not contain the supported records shape")
    return _record_values(data["records"])


def _endpoint_kind_from_parameters(
    parameters: Mapping[str, object],
    *,
    legacy_compatibility: bool,
) -> FQGateEndpointKind:
    raw_endpoint_kind = parameters.get("endpoint_kind")
    if raw_endpoint_kind is None and legacy_compatibility:
        return FQGateEndpointKind.LOCAL_DIRECT
    if not isinstance(raw_endpoint_kind, str):
        raise HistoricalSourceSchemaError(
            "FQGate request requires an explicit endpoint_kind of LOCAL_DIRECT or "
            "REMOTE_BRIDGE"
        )
    try:
        return FQGateEndpointKind(raw_endpoint_kind)
    except ValueError as exc:
        raise HistoricalSourceSchemaError(
            "FQGate endpoint_kind must be LOCAL_DIRECT or REMOTE_BRIDGE"
        ) from exc


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _endpoint_uri(
    raw_source_uri: object,
    *,
    endpoint_kind: FQGateEndpointKind,
    legacy_compatibility: bool = False,
) -> str:
    if not isinstance(raw_source_uri, str) or not raw_source_uri.strip():
        raise HistoricalSourceSchemaError(
            "FQGate request requires an explicit source_uri endpoint"
        )
    if any(char.isspace() for char in raw_source_uri):
        raise HistoricalSourceSchemaError("FQGate source_uri must not contain whitespace")
    source_uri = raw_source_uri
    parsed_uri = urlparse(source_uri)
    try:
        hostname = parsed_uri.hostname
        parsed_uri.port
    except ValueError as exc:
        raise HistoricalSourceSchemaError("FQGate source_uri has an invalid host or port") from exc
    if (
        parsed_uri.scheme not in {"http", "https"}
        or not parsed_uri.netloc
        or hostname is None
        or parsed_uri.username is not None
        or parsed_uri.password is not None
        or parsed_uri.query
        or parsed_uri.fragment
    ):
        raise HistoricalSourceSchemaError(
            "FQGate source_uri must be an absolute credential-free HTTP(S) endpoint"
        )
    if endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE:
        if parsed_uri.scheme != "https":
            raise HistoricalSourceSchemaError(
                "REMOTE_BRIDGE FQGate source_uri must use explicit HTTPS"
            )
        if parsed_uri.path in {"", "/"}:
            raise HistoricalSourceSchemaError(
                "REMOTE_BRIDGE FQGate source_uri must contain an explicit operation path"
            )
    else:
        if not legacy_compatibility and not _is_loopback_host(hostname):
            raise HistoricalSourceSchemaError(
                "LOCAL_DIRECT FQGate source_uri must target a loopback host"
            )
        if parsed_uri.path.rstrip("/") != _FQGATE_ENDPOINT_PATH:
            raise HistoricalSourceSchemaError(
                "LOCAL_DIRECT FQGate source_uri must end in " + _FQGATE_ENDPOINT_PATH
            )
    safe_source_uri = _safe_uri(source_uri)
    if safe_source_uri is None:
        raise HistoricalSourceSchemaError("FQGate source_uri is invalid")
    return safe_source_uri


def _details_from_parameters(
    parameters: Mapping[str, object],
    *,
    request: HistoricalAcquisitionRequestV1 | None = None,
    adapter_id: str | None = None,
) -> _FQGateRequestDetails:
    legacy_compatibility = adapter_id in {None, _FQGATE_LEGACY_ADAPTER_ID}
    endpoint_kind = _endpoint_kind_from_parameters(
        parameters,
        legacy_compatibility=legacy_compatibility,
    )
    if (
        adapter_id == _FQGATE_LEGACY_ADAPTER_ID
        and endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE
    ):
        raise HistoricalSourceSchemaError(
            "legacy fqgate-local-market-history requests cannot use REMOTE_BRIDGE"
        )
    response_contract = parameters.get("response_contract")
    if response_contract is None:
        if endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE:
            raise HistoricalSourceSchemaError(
                "REMOTE_BRIDGE FQGate requests require the supported response_contract"
            )
        response_contract = _FQGATE_RESPONSE_CONTRACT
    if response_contract != _FQGATE_RESPONSE_CONTRACT:
        raise HistoricalSourceSchemaError(
            "FQGate response_contract is not supported: " + str(response_contract)
        )
    if parameters.get("adjust", "") != "":
        raise HistoricalSourceSchemaError(
            "FQGate adapter supports only unadjusted bars (adjust='')"
        )
    if parameters.get("interval", "day") != "day":
        raise HistoricalSourceSchemaError(
            "FQGate adapter supports only daily bars (interval='day')"
        )
    if request is not None:
        if request.artifact_kind.value != "MARKET_BAR":
            raise HistoricalSourceSchemaError("FQGate adapter requires MARKET_BAR requests")
        if request.source_kind.value != "PRICES":
            raise HistoricalSourceSchemaError("FQGate adapter requires PRICES requests")
        if len(request.listing_ids) != 1:
            raise HistoricalSourceSchemaError(
                "FQGate history endpoint accepts exactly one listing per request"
            )
        if endpoint_kind is FQGateEndpointKind.LOCAL_DIRECT and request.credential_ref is not None:
            raise HistoricalSourceSchemaError(
                "LOCAL_DIRECT FQGate API uses its running session and does not accept credentials"
            )

    safe_source_uri = _endpoint_uri(
        parameters.get("source_uri"),
        endpoint_kind=endpoint_kind,
        legacy_compatibility=legacy_compatibility,
    )

    market = parameters.get("market")
    code = parameters.get("code")
    canonical_market = parameters.get("canonical_market")
    currency = parameters.get("currency")
    if not isinstance(market, str) or not market.strip() or any(char.isspace() for char in market):
        raise HistoricalSourceSchemaError("FQGate market must be an explicit non-empty value")
    if not isinstance(code, str) or not code.strip() or any(char.isspace() for char in code):
        raise HistoricalSourceSchemaError("FQGate code must be an explicit non-empty value")
    if canonical_market not in {Market.A.value, Market.H.value}:
        raise HistoricalSourceSchemaError(
            "FQGate canonical_market must be explicitly declared as A or H"
        )
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise HistoricalSourceSchemaError(
            "FQGate currency must be an explicit three-letter uppercase code"
        )
    count = parameters.get("count")
    if count is not None:
        if type(count) is not int or count <= 0:
            raise HistoricalSourceSchemaError("FQGate count must be a positive integer")
        if request is not None:
            raise HistoricalSourceSchemaError(
                "FQGate historical acquisition uses date-range mode; omit count because "
                "the API does not allow count with start_date/end_date"
            )
    return _FQGateRequestDetails(
        source_uri=safe_source_uri,
        endpoint_kind=endpoint_kind,
        response_contract=response_contract,
        market=market,
        code=code,
        canonical_market=Market(canonical_market),
        currency=currency,
        count=count,
    )


def _details_for_request(request: HistoricalAcquisitionRequestV1) -> _FQGateRequestDetails:
    return _details_from_parameters(
        request.parameters,
        request=request,
        adapter_id=request.adapter_id,
    )


def _payload_for_request(
    request: HistoricalAcquisitionRequestV1,
    details: _FQGateRequestDetails,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "market": details.market,
        "code": details.code,
        "start_date": request.start_date.strftime("%Y%m%d"),
        "end_date": request.end_date.strftime("%Y%m%d"),
        "adjust": "",
        "interval": "day",
    }
    return payload


def _observations(
    raw_bytes: bytes,
    details: _FQGateRequestDetails,
    *,
    allow_empty: bool = False,
) -> list[_FQGateObservation]:
    try:
        records = _parse_envelope(raw_bytes)
    except _FQGateShapeError as exc:
        raise HistoricalIngestionError(str(exc)) from exc
    observations: list[_FQGateObservation] = []
    try:
        for record in records:
            raw_time = _field(record, "1", required=True)
            trading_date, timestamp = _parse_time(raw_time)
            values = {
                field_id: _number(
                    _field(record, field_id, required=True),
                    field_id=field_id,
                    required=True,
                )
                for field_id in ("7", "8", "9", "11")
            }
            volume = _number(
                _field(record, "13", required=False),
                field_id="13",
                required=False,
            )
            amount = _number(
                _field(record, "19", required=False),
                field_id="19",
                required=False,
            )
            assert all(value is not None for value in values.values())
            observations.append(
                _FQGateObservation(
                    trading_date=trading_date,
                    timestamp=timestamp,
                    open=values["7"],
                    high=values["8"],
                    low=values["9"],
                    close=values["11"],
                    volume=volume,
                    amount=amount,
                )
            )
    except _FQGateShapeError as exc:
        raise HistoricalIngestionError(str(exc)) from exc
    if not observations and not allow_empty:
        raise HistoricalIngestionError("FQGate response contains no daily K-line records")
    return observations


def _listing_id_from_receipt(receipt: RawArtifactReceiptV1) -> str:
    value = receipt.artifact_metadata.get("listing_id")
    if not isinstance(value, str) or not value.strip():
        raise HistoricalIngestionError("FQGate receipt has no listing identity")
    return value


def _market_bar(
    observation: _FQGateObservation,
    *,
    listing_id: str,
    details: _FQGateRequestDetails,
    source_hash: str,
) -> MarketBar:
    try:
        return MarketBar(
            bar_id=f"{listing_id}:{observation.trading_date.isoformat()}",
            listing_id=listing_id,
            market=details.canonical_market,
            trading_date=observation.trading_date,
            timestamp=observation.timestamp,
            open=observation.open,
            high=observation.high,
            low=observation.low,
            close=observation.close,
            volume=observation.volume,
            amount=observation.amount,
            currency=details.currency,
            source_hash=source_hash,
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalIngestionError(
            "FQGate daily K-line row failed canonical validation"
        ) from exc


class FQGateDailyKDecoder:
    """Decode the verified FQGate unadjusted daily-K envelope."""

    adapter_id = _FQGATE_LEGACY_ADAPTER_ID
    supported_adapter_ids = frozenset(
        {_FQGATE_LEGACY_ADAPTER_ID, _FQGATE_DEPLOYMENT_NEUTRAL_ADAPTER_ID}
    )

    def __init__(self, schema_version: str = "market-bar-v1") -> None:
        self.schema_version = schema_version

    def _validate_receipt(self, receipt: RawArtifactReceiptV1) -> None:
        if receipt.adapter_id not in self.supported_adapter_ids:
            raise HistoricalIngestionError("FQGate decoder adapter identity mismatch")
        if receipt.artifact_kind is not ShardArtifactKind.MARKET_BAR:
            raise HistoricalIngestionError("FQGate decoder requires MARKET_BAR")
        if receipt.schema_version != self.schema_version:
            raise HistoricalIngestionError("FQGate daily-K schema version is unrecognized")

    def decode(self, receipt: RawArtifactReceiptV1, raw_bytes: bytes) -> list[BaseModel]:
        self._validate_receipt(receipt)
        try:
            details = _details_from_parameters(
                receipt.canonical_parameters,
                adapter_id=receipt.adapter_id,
            )
        except HistoricalSourceSchemaError as exc:
            raise HistoricalIngestionError(str(exc)) from exc
        observations = _observations(raw_bytes, details)
        listing_id = _listing_id_from_receipt(receipt)
        return [
            _market_bar(
                observation,
                listing_id=listing_id,
                details=details,
                source_hash=receipt.sha256,
            )
            for observation in observations
        ]

    def decode_scoped(
        self,
        receipt: RawArtifactReceiptV1,
        raw_bytes: bytes,
        request: HistoricalAcquisitionRequestV1,
    ) -> list[BaseModel]:
        self._validate_receipt(receipt)
        try:
            details = _details_for_request(request)
        except HistoricalSourceSchemaError as exc:
            raise HistoricalIngestionError(str(exc)) from exc
        observations = _observations(raw_bytes, details)
        listing_id = request.listing_ids[0]
        return [
            _market_bar(
                observation,
                listing_id=listing_id,
                details=details,
                source_hash=receipt.sha256,
            )
            for observation in observations
            if request.start_date <= observation.trading_date <= request.end_date
        ]


class _FQGateMarketHistoryAdapterBase:
    """Shared acquisition behavior for legacy and endpoint-neutral identities."""

    adapter_id: str
    adapter_version: str
    requires_live_credential: bool
    legacy_compatibility: bool

    def requires_live_credential_for(
        self,
        request: HistoricalAcquisitionRequestV1,
    ) -> bool:
        """Expose request-sensitive credential needs to the live preflight."""

        return (
            request.parameters.get("endpoint_kind") == FQGateEndpointKind.REMOTE_BRIDGE.value
            and request.credential_ref is not None
        )

    @staticmethod
    def _headers(
        request: HistoricalAcquisitionRequestV1,
        details: _FQGateRequestDetails,
        credentials: CredentialResolver,
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "turtle-value-engine/fqgate-market-history-v1",
        }
        if details.endpoint_kind is not FQGateEndpointKind.REMOTE_BRIDGE:
            return headers

        value = _credential_value(request, credentials)
        if value is None:
            return headers
        if not value:
            raise CredentialUnavailableError(
                "required remote bridge credential is unavailable: "
                + (request.credential_ref.reference_id if request.credential_ref else "unknown")
            )
        if "\r" in value or "\n" in value:
            raise CredentialUnavailableError("remote bridge credential contains invalid characters")
        header = request.parameters.get("credential_header", "Authorization")
        scheme = request.parameters.get("credential_scheme")
        if not isinstance(header, str) or not re.fullmatch(r"[A-Za-z0-9-]+", header):
            raise HistoricalSourceSchemaError("credential header name is invalid")
        if scheme is not None and not isinstance(scheme, str):
            raise HistoricalSourceSchemaError("credential scheme is invalid")
        if isinstance(scheme, str) and ("\r" in scheme or "\n" in scheme):
            raise HistoricalSourceSchemaError("credential scheme is invalid")
        headers[header] = f"{scheme} {value}" if scheme else value
        return headers

    def _request(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> tuple[NetworkResponse, _FQGateRequestDetails]:
        details = _details_for_request(request)
        if (
            details.endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE
            and self._transport_allows_redirects(transport)
        ):
            raise NetworkTransportError(
                "authenticated REMOTE_BRIDGE transport must reject redirects"
            )
        body = canonical_json_bytes(_payload_for_request(request, details))
        response = transport.request(
            "POST",
            details.source_uri,
            headers=self._headers(request, details, credentials),
            body=body,
        )
        if (
            details.endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE
            and response.url != details.source_uri
        ):
            # This also protects injected transports which report that they
            # followed a redirect.  The built-in urllib transport rejects
            # redirects before a second request is made.
            raise NetworkTransportError("FQGate endpoint redirects are not allowed")
        return response, details

    @staticmethod
    def _transport_allows_redirects(transport: NetworkTransport) -> bool:
        """Detect an explicit opt-in on the built-in transport chain.

        Unknown injected transports are allowed for deterministic tests; they
        still have to report a changed final URL for the response to be
        accepted.  The standard transport chain is guarded before credentials
        are sent when a caller explicitly enables redirects.
        """

        current: object | None = transport
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if getattr(current, "allow_redirects", False) is True:
                return True
            current = getattr(current, "inner", None)
        return False

    def _raw_download(
        self,
        request: HistoricalAcquisitionRequestV1,
        response: NetworkResponse,
        details: _FQGateRequestDetails,
    ) -> RawDownload:
        artifact_metadata: dict[str, object] = {
            "response_schema": details.response_contract,
            "listing_id": request.listing_ids[0],
            "canonical_market": details.canonical_market.value,
            "fqgate_market": details.market,
            "fqgate_code": details.code,
            "interval": "day",
            "adjust": "",
        }
        if request.adapter_id != _FQGATE_LEGACY_ADAPTER_ID:
            artifact_metadata.update(
                {
                    "endpoint_kind": details.endpoint_kind.value,
                }
            )
        return RawDownload(
            body=response.body,
            response=response,
            source_uri=details.source_uri,
            artifact_kind=request.artifact_kind,
            schema_version=request.schema_version,
            artifact_metadata=artifact_metadata,
        )

    @staticmethod
    def _probe_report(
        request: HistoricalAcquisitionRequestV1,
        *,
        plan_id: str,
        adapter_id: str,
        adapter_version: str,
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
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            source_kind=request.source_kind,
            status=status,
            started_at=started,
            finished_at=finished,
            **values,
        )

    @staticmethod
    def _endpoint_kind_hint(request: HistoricalAcquisitionRequestV1) -> FQGateEndpointKind:
        return (
            FQGateEndpointKind.REMOTE_BRIDGE
            if request.parameters.get("endpoint_kind") == FQGateEndpointKind.REMOTE_BRIDGE.value
            else FQGateEndpointKind.LOCAL_DIRECT
        )

    @staticmethod
    def _connection_blocker(endpoint_kind: FQGateEndpointKind) -> str:
        if endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE:
            return (
                f"{FQGATE_REMOTE_ENDPOINT_UNREACHABLE}: "
                "FQGate remote endpoint connection failed"
            )
        return f"{FQGATE_LOCAL_GATEWAY_UNREACHABLE}: FQGate local HTTP connection failed"

    def acquire(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
    ) -> list[RawDownload]:
        try:
            response, details = self._request(
                request,
                transport=transport,
                credentials=credentials,
            )
        except (NetworkTransportError, TimeoutError, OSError) as exc:
            raise AcquisitionError(
                self._connection_blocker(self._endpoint_kind_hint(request))
            ) from exc
        if not 200 <= response.status_code <= 299:
            raise AcquisitionError(
                "; ".join(
                    _http_error_blockers(response, endpoint_kind=details.endpoint_kind)
                )
            )
        return [self._raw_download(request, response, details)]

    def probe(
        self,
        request: HistoricalAcquisitionRequestV1,
        *,
        transport: NetworkTransport,
        credentials: CredentialResolver,
        plan_id: str,
        clock: object,
    ) -> SourceProbeReportV1:
        started = _utc_now(clock)
        try:
            response, details = self._request(
                request,
                transport=transport,
                credentials=credentials,
            )
        except CredentialUnavailableError as exc:
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.BLOCKED,
                started=started,
                finished=finished,
                account_entitlement=AccountEntitlement.UNKNOWN,
                blockers=["CREDENTIAL_UNAVAILABLE: " + str(exc)],
            )
        except (NetworkTransportError, TimeoutError, OSError):
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[self._connection_blocker(self._endpoint_kind_hint(request))],
            )
        except HistoricalSourceSchemaError as exc:
            finished = _utc_now(clock)
            if _h_route_is_unverified(request):
                status = ProbeStatus.BLOCKED
                blockers = [
                    f"{FQGATE_H_ROUTE_UNVERIFIED}: an explicit H market/code pair was not supplied"
                ]
            else:
                status = ProbeStatus.FAILED
                blockers = [_schema_blocker(exc)]
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=status,
                started=started,
                finished=finished,
                blockers=blockers,
            )
        except AcquisitionError:
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                blockers=[self._connection_blocker(self._endpoint_kind_hint(request))],
            )

        common = {
            "http_status": response.status_code,
            "content_type": response.content_type,
            "content_length": len(response.body),
            "response_sha256": hashlib.sha256(response.body).hexdigest(),
            "source_uri": details.source_uri,
        }
        if not 200 <= response.status_code <= 299:
            finished = _utc_now(clock)
            blockers = _http_error_blockers(response, endpoint_kind=details.endpoint_kind)
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                account_entitlement=(
                    AccountEntitlement.DENIED
                    if (
                        details.endpoint_kind is FQGateEndpointKind.LOCAL_DIRECT
                        and response.status_code in {401, 403}
                    )
                    else AccountEntitlement.UNKNOWN
                ),
                blockers=blockers,
                **common,
            )

        provider_error_blockers = _provider_error_blockers(response.body)
        if provider_error_blockers is not None:
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                account_entitlement=AccountEntitlement.UNKNOWN,
                blockers=provider_error_blockers,
                **common,
            )

        try:
            observations = _observations(response.body, details, allow_empty=True)
        except (HistoricalIngestionError, HistoricalSourceSchemaError) as exc:
            finished = _utc_now(clock)
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                account_entitlement=(
                    AccountEntitlement.CONFIRMED
                    if details.endpoint_kind is FQGateEndpointKind.LOCAL_DIRECT
                    else AccountEntitlement.UNKNOWN
                ),
                blockers=[_schema_blocker(exc)],
                **common,
            )

        finished = _utc_now(clock)
        if not observations:
            return self._probe_report(
                request,
                plan_id=plan_id,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                status=ProbeStatus.FAILED,
                started=started,
                finished=finished,
                account_entitlement=AccountEntitlement.UNKNOWN,
                blockers=[
                    f"{HISTORICAL_NO_ROWS}: FQGate returned no usable daily observations"
                ],
                **common,
            )

        observed_dates = {item.trading_date for item in observations}
        observed_start = min(observed_dates) if observed_dates else None
        observed_end = max(observed_dates) if observed_dates else None
        blockers: list[str] = []
        if observed_start is None or observed_end is None:
            blockers.append(f"{HISTORICAL_NO_ROWS}: FQGate returned no usable daily observations")
        else:
            if observed_start > request.start_date or observed_end < request.end_date:
                blockers.append(
                    f"{HISTORICAL_COVERAGE_INSUFFICIENT}: FQGate response does not cover the "
                    "requested date range"
                )
            for listing_id, expected_sessions in (
                request.expected_sessions_by_listing or {}
            ).items():
                if set(expected_sessions) - observed_dates:
                    blockers.append(
                        f"{HISTORICAL_COVERAGE_INSUFFICIENT}: expected FQGate sessions are "
                        "missing: "
                        + listing_id
                    )
        warnings = [
            "FQGATE_UNADJUSTED_DAILY_ONLY: adjustment and interval are fixed to "
            "adjust='' and interval='day'",
            "FQGATE_NO_ACTION_OR_TERMINAL_EVIDENCE: this adapter only proves market bars",
            "FQGATE_MARKET_ROUTING_IS_OPERATOR_SUPPLIED: no H-share market identifier "
            "is inferred",
        ]
        if self.adapter_id != _FQGATE_LEGACY_ADAPTER_ID:
            warnings.append(f"FQGATE_ENDPOINT_KIND: {details.endpoint_kind.value}")
        if details.endpoint_kind is FQGateEndpointKind.REMOTE_BRIDGE:
            warnings.append(
                f"{REMOTE_BRIDGE_LIVE_UNPROVEN}: fqgate-remote-bridge has not published "
                "a stable Phase 4 machine market-history contract"
            )
        return self._probe_report(
            request,
            plan_id=plan_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            status=ProbeStatus.PASS,
            started=started,
            finished=finished,
            account_entitlement=AccountEntitlement.CONFIRMED,
            observed_start=observed_start,
            observed_end=observed_end,
            observed_listing_ids=request.listing_ids if observations else [],
            historical_capable=not blockers and bool(observations),
            action_coverage="UNKNOWN",
            terminal_coverage="UNKNOWN",
            blockers=blockers,
            warnings=warnings,
            **common,
        )


class FQGateMarketHistoryAdapter(_FQGateMarketHistoryAdapterBase):
    """Legacy local FQGate adapter retained for v1 plans and receipts."""

    adapter_id = _FQGATE_LEGACY_ADAPTER_ID
    adapter_version = "1"
    requires_live_credential = False
    legacy_compatibility = True


class FQGateDeploymentNeutralMarketHistoryAdapter(_FQGateMarketHistoryAdapterBase):
    """Endpoint-neutral FQGate adapter for explicit local or remote requests."""

    adapter_id = _FQGATE_DEPLOYMENT_NEUTRAL_ADAPTER_ID
    adapter_version = "2"
    requires_live_credential = True
    legacy_compatibility = False


# Descriptive aliases make the transport boundary discoverable without making
# callers depend on a particular internal class name.
FQGateMarketHistoryEndpointAdapter = FQGateDeploymentNeutralMarketHistoryAdapter
FQGateEndpointTransportAdapter = FQGateDeploymentNeutralMarketHistoryAdapter


__all__ = [
    "FQGateDailyKDecoder",
    "FQGateDeploymentNeutralMarketHistoryAdapter",
    "FQGateEndpointKind",
    "FQGateEndpointTransportAdapter",
    "FQGateMarketHistoryAdapter",
    "FQGateMarketHistoryEndpointAdapter",
    "FQGATE_ENTITLEMENT_DENIED",
    "FQGATE_H_ROUTE_REJECTED",
    "FQGATE_H_ROUTE_UNVERIFIED",
    "FQGATE_HTTP_504_UNCLASSIFIED",
    "FQGATE_LOCAL_GATEWAY_UNREACHABLE",
    "FQGATE_PROVIDER_ERROR_CODE",
    "FQGATE_PROVIDER_ERROR_UNCLASSIFIED",
    "FQGATE_REMOTE_AUTH_DENIED",
    "FQGATE_REMOTE_ENDPOINT_UNREACHABLE",
    "FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED",
    "FQGATE_UPSTREAM_TIMEOUT_CONFIRMED",
    "HISTORICAL_COVERAGE_INSUFFICIENT",
    "HISTORICAL_NO_ROWS",
    "REMOTE_BRIDGE_LIVE_UNPROVEN",
    "SOURCE_SCHEMA_UNSUPPORTED",
]
