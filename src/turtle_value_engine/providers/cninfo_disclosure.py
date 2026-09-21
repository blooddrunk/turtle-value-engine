"""Bounded CNINFO official-disclosure discovery client (Phase 6-B).

This module implements the injected ``FilingDiscoverySourceClient`` contract
from ``providers.filings`` against CNINFO's public, unauthenticated,
metadata-only announcement search.  It is the Phase 6-B first live source
slice and deliberately narrow:

- exactly one official host family (``www.cninfo.com.cn``), HTTPS only;
- no credential, cookie or session is read, stored or logged;
- two bounded POST requests per listing (org-id lookup + one query page);
- a hard timeout and a hard response byte bound on every request;
- one query page only; a truncated result (more matching records than the
  requested limit) fails closed instead of silently dropping rows;
- no document is ever downloaded; only announcement metadata is returned.

Verified contract (bounded live probes, 2026-09-21, evidence recorded in
``docs/status/phase-6-b-2026-09-21.md``):

- ``POST /new/information/topSearch/detailOfQuery`` with
  ``keyWord=<code>&maxSecNum=5&maxListNum=5`` returns ``keyBoardList`` rows
  carrying ``code``, ``orgId``, ``category`` (e.g. ``A股``) and ``plate``;
- ``POST /new/hisAnnouncement/query`` with the form below returns
  ``announcements`` (nullable list) where each row carries
  ``announcementId``, ``announcementTitle``, ``announcementType``
  (``||``-joined CNINFO taxonomy codes; the last element is the document
  class leaf), ``announcementTime`` (UTC epoch milliseconds),
  ``adjunctUrl`` (``finalpage/<YYYY-MM-DD>/<id>.PDF``), ``secCode``,
  ``secName`` and ``orgId``, plus ``totalRecordNum``.

Timestamp honesty: scheduled A-share disclosures are stamped at Beijing
midnight (date-granular evidence), while corrected re-releases carry a real
time of day.  Because a genuine midnight publication cannot be distinguished
from date-only normalization, the client derives only ``published_date``
(Beijing calendar date of ``announcementTime``) and never claims sub-day
precision.  ``announcementTime`` itself is not propagated.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from .errors import ProviderResponseError
from .filings import (
    FilingDescriptor,
    FilingDiscoveryQuery,
    FilingDiscoverySourceClient,
    FilingSource,
    validate_filing_document_url,
)

CNINFO_DISCLOSURE_ADAPTER_VERSION = "cninfo-disclosure-v1"
CNINFO_ORG_SEARCH_URI = "https://www.cninfo.com.cn/new/information/topSearch/detailOfQuery"
CNINFO_ANNOUNCEMENT_QUERY_URI = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_DOCUMENT_HOST = "https://static.cninfo.com.cn"

_BEIJING_TZ = timezone(timedelta(hours=8))
_MAX_PAGE_SIZE = 30
_ORG_SEARCH_MAX_RESULTS = 5
_LISTING_PATTERN = re.compile(r"^(SH|SZ)(\d{6})$")
_PLATE_BY_PREFIX = {"SH": "sse", "SZ": "szse"}
_ADJUNCT_URL_PATTERN = re.compile(r"^finalpage/\d{4}-\d{2}-\d{2}/[A-Za-z0-9._-]+\.PDF$")
# Live evidence (2026-09-21): taxonomy segments are 4-8 digit codes, e.g.
# "01010503||010113||010301" (annual report) or "01010903||010112||0129"
# (audit report).  Classification uses only the final (leaf) segment.
_ANNOUNCEMENT_TYPE_PATTERN = re.compile(r"^\d{4,8}(\|\|\d{4,8})*$")
_DEFAULT_USER_AGENT = "turtle-value-engine-monitoring/1.0 (bounded metadata-only)"


class CninfoTransportError(RuntimeError):
    """Raised when a bounded transport request cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class CninfoHttpResponse:
    """One bounded HTTP response (status plus already size-capped body)."""

    status: int
    body: bytes


class CninfoHttpTransport(Protocol):
    """Injectable POST-form transport used by deterministic tests and live runs."""

    def post_form(
        self,
        url: str,
        form: Mapping[str, str],
    ) -> CninfoHttpResponse:
        """Return one bounded response; raise instead of retrying."""
        ...


@dataclass(frozen=True, slots=True)
class UrllibCninfoHttpTransport:
    """Built-in stdlib transport with a fixed timeout and response byte cap.

    Every response body is read with ``max_response_bytes + 1`` so an
    oversized upstream response fails closed instead of being truncated
    silently.  Redirects, cookies and credential material are never handled.
    """

    timeout_seconds: float = 15.0
    max_response_bytes: int = 512 * 1024
    user_agent: str = _DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if not isinstance(self.user_agent, str) or not self.user_agent.strip():
            raise ValueError("user_agent must be a non-empty string")

    def post_form(self, url: str, form: Mapping[str, str]) -> CninfoHttpResponse:
        data = urlencode(dict(form)).encode("ascii")
        request = Request(
            url,
            data=data,
            method="POST",
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed official HTTPS URIs
                body = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise CninfoTransportError(
                f"CNINFO HTTP error {exc.code} for {url}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CninfoTransportError(
                f"CNINFO request failed for {url}: {type(exc).__name__}"
            ) from exc
        if len(body) > self.max_response_bytes:
            raise CninfoTransportError(
                f"CNINFO response exceeded the {self.max_response_bytes}-byte bound: {url}"
            )
        return CninfoHttpResponse(status=response.status, body=body)


def _post_json(
    transport: CninfoHttpTransport,
    url: str,
    form: Mapping[str, str],
) -> dict:
    response = transport.post_form(url, form)
    if response.status != 200:
        raise CninfoTransportError(f"CNINFO returned HTTP {response.status} for {url}")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderResponseError(
            f"CNINFO response is not valid JSON for {url}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderResponseError(f"CNINFO response is not a JSON object: {url}")
    return payload


class CninfoOrgRecord(BaseModel):
    """One bounded org-lookup row."""

    model_config = ConfigDict(extra="forbid")

    code: StrictStr = Field(min_length=1, max_length=16)
    org_id: StrictStr = Field(min_length=1, max_length=64)
    category: StrictStr = Field(min_length=1, max_length=32)
    plate: StrictStr = Field(min_length=1, max_length=16)
    short_name: StrictStr | None = Field(default=None, max_length=128)
    delisted: bool = False

    @field_validator("delisted", mode="before")
    @classmethod
    def _parse_delisted(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() == "true"
        raise ValueError("delisted must be a boolean or a 'true'/'false' string")


def resolve_cninfo_org(
    transport: CninfoHttpTransport,
    listing_id: str,
) -> CninfoOrgRecord:
    """Resolve one A-share listing to its CNINFO org identity, fail-closed.

    The lookup is bounded to five rows and requires an exact code match with
    an active A-share category.  No match is a hard error, never a guess.
    """

    code = _code_for_listing(listing_id)
    payload = _post_json(
        transport,
        CNINFO_ORG_SEARCH_URI,
        {"keyWord": code, "maxSecNum": str(_ORG_SEARCH_MAX_RESULTS), "maxListNum": "5"},
    )
    board = payload.get("keyBoardList")
    if not isinstance(board, list):
        raise ProviderResponseError("CNINFO org lookup returned no keyBoardList")
    candidates: list[CninfoOrgRecord] = []
    for item in board[:_ORG_SEARCH_MAX_RESULTS]:
        if not isinstance(item, dict):
            raise ProviderResponseError("CNINFO org lookup rows must be JSON objects")
        merged = {
            "code": item.get("code"),
            "org_id": item.get("orgId"),
            "category": item.get("category"),
            "plate": item.get("plate"),
            "short_name": item.get("zwjc"),
            "delisted": item.get("delisted"),
        }
        try:
            record = CninfoOrgRecord.model_validate(merged)
        except ValueError as exc:
            raise ProviderResponseError(f"invalid CNINFO org lookup row: {exc}") from exc
        candidates.append(record)
    matches = [
        item
        for item in candidates
        if item.code == code and item.category in {"A股", "AB股"}
    ]
    if not matches:
        raise ProviderResponseError(
            f"CNINFO org lookup found no active A-share org for listing {listing_id!r}"
        )
    active = [item for item in matches if not item.delisted]
    if not active:
        raise ProviderResponseError(
            f"CNINFO org lookup found only delisted orgs for listing {listing_id!r}"
        )
    if len(active) > 1 or len({item.org_id for item in active}) > 1:
        raise ProviderResponseError(
            f"CNINFO org lookup is ambiguous for listing {listing_id!r}"
        )
    return active[0]


class CninfoAnnouncementRecord(BaseModel):
    """Strict parse of one CNINFO announcement row (metadata only)."""

    model_config = ConfigDict(extra="forbid")

    announcement_id: StrictStr = Field(min_length=1, max_length=32)
    announcement_title: StrictStr = Field(min_length=1, max_length=500)
    announcement_type_codes: StrictStr = Field(min_length=1, max_length=256)
    announcement_time_ms: StrictInt = Field(ge=0)
    adjunct_url: StrictStr = Field(min_length=1, max_length=512)
    sec_code: StrictStr = Field(min_length=1, max_length=16)
    sec_name: StrictStr | None = Field(default=None, max_length=128)
    org_id: StrictStr = Field(min_length=1, max_length=64)

    @field_validator(
        "announcement_title",
        "announcement_type_codes",
        "adjunct_url",
        "sec_code",
        "sec_name",
        "announcement_id",
        "org_id",
    )
    @classmethod
    def _reject_control_characters(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(char) < 32 for char in value):
            raise ValueError("CNINFO metadata must not contain control characters")
        return value

    @field_validator("adjunct_url")
    @classmethod
    def _validate_adjunct_url_shape(cls, value: str) -> str:
        if not _ADJUNCT_URL_PATTERN.fullmatch(value):
            raise ValueError(
                f"CNINFO adjunctUrl has an unexpected shape: {value!r}"
            )
        return value

    @property
    def leaf_type_code(self) -> str:
        """Return the last (most specific) CNINFO taxonomy code."""

        return self.announcement_type_codes.split("||")[-1]

    def beijing_publication_date(self) -> date:
        """Return the Beijing calendar date of ``announcementTime``.

        Scheduled disclosures are stamped at Beijing midnight and re-releases
        carry a real time of day; both reduce to the same calendar date, which
        is the only precision the source actually establishes.
        """

        moment = datetime.fromtimestamp(
            self.announcement_time_ms / 1000, tz=UTC
        ).astimezone(_BEIJING_TZ)
        return moment.date()

    def document_url(self) -> str:
        """Return the canonical official static document URL."""

        if not _ADJUNCT_URL_PATTERN.fullmatch(self.adjunct_url):
            raise ValueError(
                f"CNINFO adjunctUrl has an unexpected shape: {self.adjunct_url!r}"
            )
        return f"{CNINFO_STATIC_DOCUMENT_HOST}/{self.adjunct_url}"


def parse_cninfo_announcements(payload: Mapping[str, object]) -> list[CninfoAnnouncementRecord]:
    """Validate one CNINFO query page into strict metadata rows."""

    announcements = payload.get("announcements")
    if announcements is None:
        announcements = []
    if not isinstance(announcements, list):
        raise ProviderResponseError("CNINFO announcements must be a list or null")
    records: list[CninfoAnnouncementRecord] = []
    for item in announcements:
        if not isinstance(item, dict):
            raise ProviderResponseError("CNINFO announcement rows must be JSON objects")
        merged = {
            "announcementId": item.get("announcementId"),
            "announcementTitle": item.get("announcementTitle"),
            "announcementType": item.get("announcementType"),
            "announcementTime": item.get("announcementTime"),
            "adjunctUrl": item.get("adjunctUrl"),
            "secCode": item.get("secCode"),
            "secName": item.get("secName"),
            "orgId": item.get("orgId"),
        }
        if merged["announcementType"] is None or not str(merged["announcementType"]).strip():
            raise ProviderResponseError("CNINFO announcement row lacks announcementType")
        try:
            record = CninfoAnnouncementRecord.model_validate(
                {
                    "announcement_id": merged["announcementId"],
                    "announcement_title": merged["announcementTitle"],
                    "announcement_type_codes": merged["announcementType"],
                    "announcement_time_ms": merged["announcementTime"],
                    "adjunct_url": merged["adjunctUrl"],
                    "sec_code": merged["secCode"],
                    "sec_name": merged["secName"],
                    "org_id": merged["orgId"],
                }
            )
        except ValueError as exc:
            raise ProviderResponseError(f"invalid CNINFO announcement row: {exc}") from exc
        if not _ANNOUNCEMENT_TYPE_PATTERN.fullmatch(record.announcement_type_codes):
            raise ProviderResponseError(
                "announcementType must be '||'-joined 6-to-8-digit taxonomy codes: "
                + record.announcement_type_codes
            )
        records.append(record)
    return records


def _code_for_listing(listing_id: str) -> str:
    match = _LISTING_PATTERN.fullmatch(listing_id)
    if match is None:
        raise ProviderResponseError(
            "the CNINFO live client supports SH/SZ A-share listings only "
            f"(BJ/H shares are unproven and fail closed): {listing_id!r}"
        )
    return match.group(2)


def _se_date(query: FilingDiscoveryQuery) -> str:
    """Build the CNINFO ``seDate`` form value from an explicit window.

    Both bounds are required: CNINFO does not document a one-sided ``seDate``
    form, so an unbounded discovery query fails closed instead of guessing.
    """

    if query.published_from is None or query.published_to is None:
        raise ProviderResponseError(
            "the CNINFO live client requires explicit published_from and "
            "published_to bounds (no open-ended window)"
        )
    return f"{query.published_from.isoformat()}~{query.published_to.isoformat()}"


class CninfoAnnouncementSourceClient:
    """Live CNINFO ``FilingDiscoverySourceClient`` (bounded, credential-free).

    Construct it only for an explicitly authorized live acquisition; the
    monitoring-acquisition service refuses to call it without
    ``network_allowed=True``.  ``source_uri`` pins the exact official query
    endpoint so raw cache records stay auditable.
    """

    def __init__(
        self,
        *,
        transport: CninfoHttpTransport,
        source_uri: str = CNINFO_ANNOUNCEMENT_QUERY_URI,
        org_search_uri: str = CNINFO_ORG_SEARCH_URI,
    ) -> None:
        self._transport = transport
        self._source_uri = source_uri
        self._org_search_uri = org_search_uri
        self._org_cache: dict[str, CninfoOrgRecord] = {}

    @property
    def source_uri(self) -> str:
        return self._source_uri

    def discover(self, query: FilingDiscoveryQuery):
        """Return filing descriptors for one bounded CNINFO query page."""

        if query.source is not FilingSource.CNINFO:
            raise ProviderResponseError(
                f"the CNINFO live client cannot serve source {query.source.value}"
            )
        code = _code_for_listing(query.listing_id)
        org = self._org_cache.get(query.listing_id)
        if org is None:
            org = resolve_cninfo_org(self._transport, query.listing_id)
            self._org_cache[query.listing_id] = org
        if org.code != code:
            raise ProviderResponseError(
                "CNINFO org lookup code does not match the requested listing"
            )
        page_size = min(query.limit, _MAX_PAGE_SIZE)
        form = {
            "pageNum": "1",
            "pageSize": str(page_size),
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": f"{code},{org.org_id}",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": _se_date(query),
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        payload = _post_json(self._transport, self._source_uri, form)
        records = parse_cninfo_announcements(payload)
        total = payload.get("totalRecordNum")
        if not isinstance(total, int) or total < 0:
            raise ProviderResponseError("CNINFO response lacks an integer totalRecordNum")
        if total > len(records):
            raise ProviderResponseError(
                "CNINFO returned a truncated page for the requested window "
                f"({total} matching records, {len(records)} returned); narrow the "
                "window or raise the limit instead of accepting partial results"
            )
        descriptors: list[FilingDescriptor] = []
        for record in records:
            if record.sec_code != code:
                raise ProviderResponseError(
                    "CNINFO announcement secCode does not match the requested listing"
                )
            published = record.beijing_publication_date()
            url = record.document_url()
            canonical_url = validate_filing_document_url(FilingSource.CNINFO, url)
            descriptors.append(
                FilingDescriptor(
                    title=record.announcement_title,
                    document_type=record.leaf_type_code,
                    published_date=published,
                    url=canonical_url,
                    source_document_id=record.announcement_id,
                    report_period=None,
                    issuer_name=record.sec_name,
                )
            )
        return descriptors


def cninfo_disclosure_source_client(
    transport: CninfoHttpTransport,
) -> FilingDiscoverySourceClient:
    """Bind the live client into the frozen discovery-source contract."""

    inner = CninfoAnnouncementSourceClient(transport=transport)

    def discover(query: FilingDiscoveryQuery):
        return inner.discover(query)

    return FilingDiscoverySourceClient(
        source=FilingSource.CNINFO,
        source_uri=inner.source_uri,
        discover=discover,
    )


def cninfo_filing_provider_version() -> str:
    """Return the cache-scoped provider version including the client version.

    Folding the CNINFO client version into the discovery provider version
    makes the raw-cache key change whenever CNINFO normalization changes, so a
    replayed cache entry can never be re-normalized under different rules.
    """

    from .filings import FILING_DISCOVERY_ADAPTER_VERSION

    return f"{FILING_DISCOVERY_ADAPTER_VERSION}+{CNINFO_DISCLOSURE_ADAPTER_VERSION}"


__all__ = [
    "CNINFO_ANNOUNCEMENT_QUERY_URI",
    "CNINFO_DISCLOSURE_ADAPTER_VERSION",
    "CNINFO_ORG_SEARCH_URI",
    "CninfoAnnouncementRecord",
    "CninfoAnnouncementSourceClient",
    "CninfoHttpResponse",
    "CninfoHttpTransport",
    "CninfoOrgRecord",
    "CninfoTransportError",
    "UrllibCninfoHttpTransport",
    "cninfo_disclosure_source_client",
    "cninfo_filing_provider_version",
    "parse_cninfo_announcements",
    "resolve_cninfo_org",
]
