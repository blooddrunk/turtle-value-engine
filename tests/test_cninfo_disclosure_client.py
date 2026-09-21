"""Deterministic CNINFO live-client tests (Phase 6-B).

All tests run against an injected fake transport; no test in this file
touches the network.  The scripted response shapes mirror the bounded live
probe evidence recorded on 2026-09-21 (see
``docs/status/phase-6-b-2026-09-21.md``).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from turtle_value_engine.providers.cninfo_disclosure import (
    CNINFO_ANNOUNCEMENT_QUERY_URI,
    CNINFO_ORG_SEARCH_URI,
    CninfoHttpResponse,
    CninfoTransportError,
    UrllibCninfoHttpTransport,
    cninfo_disclosure_source_client,
    cninfo_filing_provider_version,
    parse_cninfo_announcements,
    resolve_cninfo_org,
)
from turtle_value_engine.providers.errors import (
    ProviderRequestError,
    ProviderResponseError,
)
from turtle_value_engine.providers.filings import (
    FilingDiscoveryQuery,
    FilingSource,
    OfficialFilingDiscoveryProvider,
)

BEIJING = timezone(timedelta(hours=8))
# 2026-04-17T00:00:00+08:00 in UTC epoch milliseconds (midnight-normalized
# stamp, exactly like the live source emits for scheduled disclosures; this
# is the observed stamp of the live 600519 FY2025 annual-report row).
MIDNIGHT_2026_04_17_MS = 1776355200000
# 2026-04-30T18:20:27+08:00 (a genuine re-release instant observed live).
RE_RELEASE_MS = 1777544427000


class FakeTransport:
    """Scripted transport that records every request it serves."""

    def __init__(self, *, org_response: dict, query_response: dict):
        self._org_response = org_response
        self._query_response = query_response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post_form(self, url: str, form: dict[str, str]) -> CninfoHttpResponse:
        self.calls.append((url, dict(form)))
        if url == CNINFO_ORG_SEARCH_URI:
            payload = self._org_response
        elif url == CNINFO_ANNOUNCEMENT_QUERY_URI:
            payload = self._query_response
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected URL: {url}")
        return CninfoHttpResponse(
            status=200, body=json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )


def _org_row(code: str = "600519", org_id: str = "gssh0600519", **overrides):
    row = {
        "code": code,
        "orgId": org_id,
        "category": "A股",
        "plate": "sse",
        "zwjc": "贵州茅台",
        "delisted": "false",
        "pinyin": "gzmt",
        "type": "shj",
        "sjstsBond": "false",
    }
    row.update(overrides)
    return row


def _org_response(rows: list[dict]) -> dict:
    return {"keyBoardList": rows, "classifiedAnnouncements": None}


def _announcement(
    announcement_id: str,
    title: str,
    leaf: str,
    time_ms: int,
    code: str = "600519",
    org_id: str = "gssh0600519",
    adjunct_url: str | None = None,
) -> dict:
    if isinstance(time_ms, (int, float)):
        day = (
            datetime.fromtimestamp(time_ms / 1000, tz=UTC)
            .astimezone(BEIJING)
            .strftime("%Y-%m-%d")
        )
    else:  # deliberately malformed row: pick a syntactically valid day
        day = "2026-04-17"
    return {
        "announcementId": announcement_id,
        "announcementTitle": title,
        "shortTitle": title,
        "announcementType": f"01010503||010113||{leaf}",
        "announcementTypeName": None,
        "announcementTime": time_ms,
        "adjunctUrl": adjunct_url or f"finalpage/{day}/{announcement_id}.PDF",
        "adjunctType": "PDF",
        "adjunctSize": 80,
        "secCode": code,
        "secName": "贵州茅台",
        "secNameList": None,
        "orgId": org_id,
        "orgName": "贵州茅台",
        "columnId": "250401||251302",
        "pageColumn": "SHZB",
        "important": None,
        "batchNum": 1,
        "storageTime": None,
        "associateAnnouncement": None,
        "announcementContent": None,
        "tileSecName": None,
        "id": announcement_id,
    }


def _query_response(rows: list[dict], *, total: int | None = None) -> dict:
    return {
        "announcements": rows,
        "hasMore": False,
        "totalRecordNum": len(rows) if total is None else total,
        "totalpages": 1,
        "totalAnnouncement": len(rows) if total is None else total,
        "totalSecurities": 1,
        "categoryList": None,
        "classifiedAnnouncements": None,
    }


def _query(listing_id: str = "SH600519", **overrides) -> FilingDiscoveryQuery:
    values = {
        "listing_id": listing_id,
        "source": FilingSource.CNINFO,
        "published_from": date(2026, 4, 10),
        "published_to": date(2026, 4, 30),
        "limit": 10,
    }
    values.update(overrides)
    return FilingDiscoveryQuery(**values)


def _client(transport: FakeTransport):
    return cninfo_disclosure_source_client(transport)


class TestHappyPath:
    def test_discover_maps_rows_to_descriptors(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response(
                [
                    _announcement(
                        "1225114741", "贵州茅台2025年年度报告", "010301",
                        MIDNIGHT_2026_04_17_MS,
                    ),
                    _announcement(
                        "1225114747", "贵州茅台2025年度社会责任报告", "012330",
                        MIDNIGHT_2026_04_17_MS,
                    ),
                ]
            ),
        )
        client = _client(transport)
        descriptors = list(client.discover(_query()))
        assert [d.document_type for d in descriptors] == ["010301", "012330"]
        assert [d.source_document_id for d in descriptors] == [
            "1225114741",
            "1225114747",
        ]
        assert all(d.published_date == date(2026, 4, 17) for d in descriptors)
        assert all(str(d.url).startswith("https://static.cninfo.com.cn/finalpage/")
                   for d in descriptors)
        assert descriptors[0].issuer_name == "贵州茅台"

    def test_beijing_publication_date_handles_re_release_instants(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response(
                [_announcement("1225273126", "2025年半年度报告（更新后）", "010303", RE_RELEASE_MS)]
            ),
        )
        descriptors = list(_client(transport).discover(_query()))
        assert descriptors[0].published_date == date(2026, 4, 30)

    def test_requests_are_bounded_and_credential_free(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response([]),
        )
        _client(transport).discover(_query())
        org_url, org_form = transport.calls[0]
        query_url, query_form = transport.calls[1]
        assert org_url == CNINFO_ORG_SEARCH_URI
        assert org_form["keyWord"] == "600519"
        assert int(org_form["maxSecNum"]) <= 5
        assert query_url == CNINFO_ANNOUNCEMENT_QUERY_URI
        assert query_form["pageNum"] == "1"
        assert int(query_form["pageSize"]) <= 30
        assert query_form["stock"] == "600519,gssh0600519"
        assert query_form["seDate"] == "2026-04-10~2026-04-30"
        for _, form in transport.calls:
            for key in form:
                assert key not in {
                    "password", "token", "cookie", "authorization", "secret", "apikey"
                }, key

    def test_only_two_requests_per_listing(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response([]),
        )
        client = _client(transport)
        client.discover(_query())
        client.discover(_query(limit=5))
        assert len(transport.calls) == 3  # org lookup cached within one client

    def test_deterministic_descriptors_across_clients(self):
        rows = [
            _announcement("1225114741", "贵州茅台2025年年度报告", "010301", MIDNIGHT_2026_04_17_MS)
        ]
        def run_once() -> list:
            transport = FakeTransport(
                org_response=_org_response([_org_row()]),
                query_response=_query_response(rows),
            )
            return list(_client(transport).discover(_query()))

        first = run_once()
        second = run_once()
        assert [d.model_dump() for d in first] == [d.model_dump() for d in second]


class TestOrgResolution:
    def test_rejects_missing_a_share_match(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row(category="债券")]),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="no active A-share org"):
            resolve_cninfo_org(transport, "SH600519")

    def test_rejects_delisted_org(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row(delisted="true")]),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="delisted"):
            resolve_cninfo_org(transport, "SH600519")

    def test_rejects_ambiguous_orgs(self):
        transport = FakeTransport(
            org_response=_org_response(
                [_org_row(org_id="gssh0600519"), _org_row(org_id="gsshX600519")]
            ),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="ambiguous"):
            resolve_cninfo_org(transport, "SH600519")

    def test_ignores_non_matching_codes(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row(code="000001", org_id="gssz0000001")]),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="no active A-share org"):
            resolve_cninfo_org(transport, "SH600519")


class TestListingScope:
    @pytest.mark.parametrize("listing_id", ["HK00288", "600519.SH", "SH6005"])
    def test_invalid_listing_forms_fail_at_query_contract(self, listing_id):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _query(listing_id=listing_id)

    def test_bj_listing_fails_closed_in_client(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="SH/SZ A-share listings only"):
            _client(transport).discover(_query(listing_id="BJ430047"))

    def test_h_share_source_rejected(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response([]),
        )
        query = FilingDiscoveryQuery(
            listing_id="HK00288",
            source=FilingSource.HKEXNEWS,
            published_from=date(2026, 4, 10),
            published_to=date(2026, 4, 30),
        )
        with pytest.raises(ProviderResponseError, match="cannot serve source"):
            _client(transport).discover(query)

    def test_open_ended_window_rejected(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="explicit published_from"):
            _client(transport).discover(
                _query(published_from=None, published_to=date(2026, 4, 30))
            )
        with pytest.raises(ProviderResponseError, match="explicit published_from"):
            _client(transport).discover(
                _query(published_from=date(2026, 4, 10), published_to=None)
            )


class TestTruncationAndMalformedResponses:
    def test_truncated_page_fails_closed(self):
        rows = [_announcement("1", "标题一", "012399", MIDNIGHT_2026_04_17_MS)]
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response(rows, total=5),
        )
        with pytest.raises(ProviderResponseError, match="truncated"):
            _client(transport).discover(_query())

    def test_null_announcements_is_an_empty_page(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response={"announcements": None, "totalRecordNum": 0},
        )
        assert list(_client(transport).discover(_query())) == []

    def test_missing_total_fails_closed(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response={"announcements": []},
        )
        with pytest.raises(ProviderResponseError, match="totalRecordNum"):
            _client(transport).discover(_query())

    def test_sec_code_mismatch_fails_closed(self):
        transport = FakeTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response(
                [_announcement("1", "标题", "012399", MIDNIGHT_2026_04_17_MS, code="000858")]
            ),
        )
        with pytest.raises(ProviderResponseError, match="secCode"):
            _client(transport).discover(_query())

    def test_malformed_rows_fail_closed(self):
        bad_rows = [
            {"announcementId": "1"},
            _announcement("2", "标题", "012", MIDNIGHT_2026_04_17_MS),  # 3-digit segment: too short
            _announcement(
                "3", "标题", "012399", "not-a-number", adjunct_url="finalpage/2026-04-17/3.PDF"
            ),
            _announcement("4", "bad\x01title", "012399", MIDNIGHT_2026_04_17_MS),
            _announcement(
                "5", "标题", "012399", MIDNIGHT_2026_04_17_MS,
                adjunct_url="../escape/1.PDF",
            ),
            _announcement(None, "标题", "012399", MIDNIGHT_2026_04_17_MS),
        ]
        for row in bad_rows:
            payload = _query_response([row])
            with pytest.raises((ProviderResponseError, ValueError)):
                parse_cninfo_announcements(payload)

    def test_non_json_body_fails_closed(self):
        class BrokenTransport(FakeTransport):
            def post_form(self, url, form):
                if url == CNINFO_ANNOUNCEMENT_QUERY_URI:
                    return CninfoHttpResponse(status=200, body=b"not json")
                return super().post_form(url, form)

        transport = BrokenTransport(
            org_response=_org_response([_org_row()]),
            query_response=_query_response([]),
        )
        with pytest.raises(ProviderResponseError, match="not valid JSON"):
            _client(transport).discover(_query())

    def test_non_200_status_fails_closed(self):
        class StatusTransport(FakeTransport):
            def post_form(self, url, form):
                return CninfoHttpResponse(status=503, body=b"{}")

        transport = StatusTransport(
            org_response=_org_response([_org_row()]), query_response=_query_response([])
        )
        with pytest.raises(CninfoTransportError, match="HTTP 503"):
            _client(transport).discover(_query())


class TestUrllibTransportBounds:
    def test_invalid_constructor_arguments_fail(self):
        with pytest.raises(ValueError):
            UrllibCninfoHttpTransport(timeout_seconds=0)
        with pytest.raises(ValueError):
            UrllibCninfoHttpTransport(max_response_bytes=0)

    def _patch_urlopen(self, monkeypatch, body: bytes, *, error=None):
        import turtle_value_engine.providers.cninfo_disclosure as module

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit: int) -> bytes:
                return body[:limit]

        def fake_urlopen(request, timeout):  # noqa: ARG001
            if error is not None:
                raise error
            return FakeResponse()

        monkeypatch.setattr(module, "urlopen", fake_urlopen)

    def test_oversized_response_fails_closed(self, monkeypatch):
        transport = UrllibCninfoHttpTransport(max_response_bytes=1024)
        self._patch_urlopen(monkeypatch, body=b"x" * 2048)
        with pytest.raises(CninfoTransportError, match="exceeded the 1024-byte bound"):
            transport.post_form(CNINFO_ANNOUNCEMENT_QUERY_URI, {"a": "1"})

    def test_urlerror_becomes_transport_error(self, monkeypatch):
        from urllib.error import URLError

        transport = UrllibCninfoHttpTransport()
        self._patch_urlopen(monkeypatch, body=b"", error=URLError("refused"))
        with pytest.raises(CninfoTransportError, match="request failed"):
            transport.post_form(CNINFO_ANNOUNCEMENT_QUERY_URI, {"a": "1"})

    def test_http_error_becomes_transport_error(self, monkeypatch):
        from urllib.error import HTTPError

        transport = UrllibCninfoHttpTransport()
        self._patch_urlopen(
            monkeypatch,
            body=b"",
            error=HTTPError("url", 500, "boom", None, None),  # type: ignore[arg-type]
        )
        with pytest.raises(CninfoTransportError, match="HTTP error 500"):
            transport.post_form(CNINFO_ANNOUNCEMENT_QUERY_URI, {"a": "1"})


class TestProviderIntegration:
    def test_client_serves_the_frozen_discovery_contract(self, tmp_path: Path):
        from turtle_value_engine.providers.cache import FilesystemRawResponseCache

        rows = [
            _announcement("1225114741", "贵州茅台2025年年度报告", "010301", MIDNIGHT_2026_04_17_MS)
        ]
        transport = FakeTransport(
            org_response=_org_response([_org_row()]), query_response=_query_response(rows)
        )
        provider = OfficialFilingDiscoveryProvider(
            {FilingSource.CNINFO: _client(transport)},
            provider_version=cninfo_filing_provider_version(),
        )
        cache = FilesystemRawResponseCache(tmp_path / "cache")
        record = provider.fetch(_query().to_provider_request())
        assert record.provider.provider_version == "filing-discovery-v1+cninfo-disclosure-v1"
        assert record.source_uri == CNINFO_ANNOUNCEMENT_QUERY_URI
        cache.write(record)
        cached = cache.read(
            __import__(
                "turtle_value_engine.providers.cache", fromlist=["CacheKey"]
            ).CacheKey.from_request(record.provider, record.request)
        )
        assert cached is not None
        assert cached.raw_payload == record.raw_payload

    def test_transport_failure_wraps_into_provider_error(self):
        class ExplodingTransport(FakeTransport):
            def post_form(self, url, form):
                raise CninfoTransportError("CNINFO request failed: timeout")

        exploding = ExplodingTransport(
            org_response=_org_response([]), query_response=_query_response([])
        )
        provider = OfficialFilingDiscoveryProvider(
            {FilingSource.CNINFO: _client(exploding)}
        )
        with pytest.raises(ProviderRequestError):
            provider.fetch(_query().to_provider_request())
