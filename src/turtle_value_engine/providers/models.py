"""Provider-neutral models for structured data acquisition.

The provider layer deliberately treats a response payload as opaque JSON.  A
provider adapter may know the upstream column names, but those names stop at
``RawProviderRecord`` and never become inputs to the calculation modules.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _copy_json_value(value: object, *, path: str = "value") -> JSONValue:
    """Validate and copy one JSON-compatible value without coercion."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, JSONValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} object keys must be strings")
            copied[key] = _copy_json_value(child, path=f"{path}.{key}")
        return copied
    if isinstance(value, list):
        return [
            _copy_json_value(child, path=f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    raise TypeError(f"{path} must be JSON-compatible")


def copy_json_object(value: Mapping[str, object], *, path: str = "value") -> dict[str, JSONValue]:
    """Return a validated detached copy of a JSON object."""

    copied = _copy_json_value(value, path=path)
    if not isinstance(copied, dict):
        raise TypeError(f"{path} must be a JSON object")
    return copied


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON data canonically for stable IDs and cache keys."""

    import json

    normalized = _copy_json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class DataCategory(StrEnum):
    """Independent structured-data categories a provider may expose."""

    COMPANY_METADATA = "company_metadata"
    LISTING_METADATA = "listing_metadata"
    RISK_WARNING_STATUS = "risk_warning_status"
    TRADING_SUSPENSIONS = "trading_suspensions"
    MARKET_QUOTE = "market_quote"
    MARKET_HISTORY = "market_history"
    INCOME_STATEMENT = "income_statement"
    EARNINGS_FORECAST = "earnings_forecast"
    EARNINGS_QUICK_REPORT = "earnings_quick_report"
    PERFORMANCE_REPORT = "performance_report"
    BUSINESS_COMPOSITION = "business_composition"
    FINANCIAL_ABSTRACT = "financial_abstract"
    FINANCIAL_INDICATORS = "financial_indicators"
    GOODWILL_IMPAIRMENT = "goodwill_impairment"
    ESG_RATINGS = "esg_ratings"
    MARGIN_TRADING = "margin_trading"
    LATEST_INDICATORS = "latest_indicators"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW_STATEMENT = "cash_flow_statement"
    DIVIDENDS = "dividends"
    DISCLOSURE_NOTICES = "disclosure_notices"
    SHARE_CAPITAL = "share_capital"
    CORPORATE_ACTIONS = "corporate_actions"
    OWNERSHIP_PLEDGE = "ownership_pledge"
    INSIDER_SHARE_CHANGES = "insider_share_changes"
    SHAREHOLDER_HOLDINGS = "shareholder_holdings"


class RetrievalMode(StrEnum):
    """How a raw record was obtained by the cache-aware boundary."""

    LIVE = "LIVE"
    CACHE_REPLAY = "CACHE_REPLAY"
    STALE_CACHE_REPLAY = "STALE_CACHE_REPLAY"


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """Versioned identity for an adapter and its upstream source."""

    provider_id: str
    provider_version: str
    source_name: str

    def __post_init__(self) -> None:
        for name in ("provider_id", "provider_version", "source_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if any(char in self.provider_id for char in "/\\"):
            raise ValueError("provider_id must not contain path separators")
        if any(ord(char) < 32 for char in self.provider_id):
            raise ValueError("provider_id must not contain control characters")

    def as_dict(self) -> dict[str, str]:
        """Return the identity in the shape persisted in a cache envelope."""

        return {
            "id": self.provider_id,
            "version": self.provider_version,
            "source_name": self.source_name,
        }


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Canonical request identity shared by providers and the cache."""

    category: DataCategory
    entity_id: str
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            category = DataCategory(self.category)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported data category: {self.category!r}") from exc
        object.__setattr__(self, "category", category)

        if not isinstance(self.entity_id, str) or not self.entity_id.strip():
            raise ValueError("entity_id must be a non-empty string")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a JSON object")
        object.__setattr__(self, "parameters", copy_json_object(self.parameters, path="parameters"))

    def as_dict(self) -> dict[str, JSONValue]:
        """Return the complete request identity for persistence and hashing."""

        return {
            "category": self.category.value,
            "entity_id": self.entity_id,
            "parameters": copy_json_object(self.parameters, path="parameters"),
        }


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Explicit capability advertisement for one provider adapter."""

    supported_categories: frozenset[DataCategory] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        categories = self.supported_categories
        if isinstance(categories, str):
            categories = (categories,)
        try:
            normalized = frozenset(DataCategory(category) for category in categories)
        except (TypeError, ValueError) as exc:
            raise ValueError("supported_categories contains an unknown data category") from exc
        object.__setattr__(self, "supported_categories", normalized)

    def supports(self, category: DataCategory | str) -> bool:
        """Return whether the provider can acquire the requested category."""

        try:
            normalized = DataCategory(category)
        except (TypeError, ValueError):
            return False
        return normalized in self.supported_categories

    def as_values(self) -> tuple[str, ...]:
        """Return categories in deterministic display order."""

        return tuple(sorted(category.value for category in self.supported_categories))


@dataclass(frozen=True, slots=True)
class RawProviderRecord:
    """An opaque provider response plus the provenance needed to replay it."""

    provider: ProviderIdentity
    request: ProviderRequest
    retrieved_at: datetime
    raw_payload: JSONValue
    source_uri: str | None = None
    response_metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderIdentity):
            raise TypeError("provider must be a ProviderIdentity")
        if not isinstance(self.request, ProviderRequest):
            raise TypeError("request must be a ProviderRequest")
        if not isinstance(self.retrieved_at, datetime):
            raise TypeError("retrieved_at must be a datetime")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        object.__setattr__(
            self,
            "retrieved_at",
            self.retrieved_at.astimezone(UTC),
        )
        object.__setattr__(self, "raw_payload", _copy_json_value(self.raw_payload))
        if self.source_uri is not None and not isinstance(self.source_uri, str):
            raise TypeError("source_uri must be a string or null")
        if not isinstance(self.response_metadata, Mapping):
            raise TypeError("response_metadata must be a JSON object")
        object.__setattr__(
            self,
            "response_metadata",
            copy_json_object(self.response_metadata, path="response_metadata"),
        )
