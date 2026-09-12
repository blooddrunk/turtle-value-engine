import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.providers import (
    DataCategory,
    FilesystemRawResponseCache,
    FilingDiscoveryQuery,
    FilingDiscoverySourceClient,
    FilingMarket,
    FilingSource,
    OfficialFilingDiscoveryProvider,
    ProviderNormalizationError,
    ProviderRequest,
    ProviderRequestError,
    ProviderResponseError,
    RawProviderRecord,
    fetch_filing_discovery_with_cache,
    filing_id_for,
    parse_filing_discovery_record,
)

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "filings" / "discovery_a_h.json"
SCHEMA_PATH = ROOT / "schemas" / "filing-discovery.schema.json"
RETRIEVED_AT = datetime(2026, 9, 12, 4, 5, 6, tzinfo=UTC)


def _fixture(name: str) -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload[name]


def _client(
    source: FilingSource,
    source_uri: str,
    filings: list[dict],
    calls: list[FilingDiscoveryQuery] | None = None,
) -> FilingDiscoverySourceClient:
    def discover(query: FilingDiscoveryQuery) -> list[dict]:
        if calls is not None:
            calls.append(query)
        return deepcopy(filings)

    return FilingDiscoverySourceClient(
        source=source,
        source_uri=source_uri,
        discover=discover,
    )


def _provider(*clients: FilingDiscoverySourceClient) -> OfficialFilingDiscoveryProvider:
    return OfficialFilingDiscoveryProvider(
        {client.source: client for client in clients},
        clock=lambda: RETRIEVED_AT,
    )


def _record_with(
    record: RawProviderRecord,
    *,
    raw_payload: object | None = None,
    response_metadata: dict | None = None,
    source_uri: str | None = None,
) -> RawProviderRecord:
    return RawProviderRecord(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=record.raw_payload if raw_payload is None else raw_payload,
        source_uri=record.source_uri if source_uri is None else source_uri,
        response_metadata=(
            record.response_metadata if response_metadata is None else response_metadata
        ),
    )


def test_a_cninfo_discovery_is_metadata_only_and_deterministically_identified():
    config = _fixture("a_cninfo")
    calls: list[FilingDiscoveryQuery] = []
    client = _client(
        FilingSource.CNINFO,
        config["source_uri"],
        config["filings"],
        calls,
    )
    query = FilingDiscoveryQuery(
        listing_id=config["listing_id"],
        source=config["source"],
        published_from="2025-04-01",
        published_to="2025-04-30",
        limit=10,
        as_of="2025-04-30",
    )

    record = _provider(client).fetch(query.to_provider_request())
    result = parse_filing_discovery_record(record)

    assert calls == [query]
    assert result.listing_id == "SH600000"
    assert result.market is FilingMarket.A
    assert result.source is FilingSource.CNINFO
    assert [filing.published_date.isoformat() for filing in result.filings] == [
        "2025-04-30",
        "2025-04-29",
    ]
    first = result.filings[0]
    assert first.filing_id == filing_id_for(
        listing_id="SH600000",
        market=FilingMarket.A,
        source=FilingSource.CNINFO,
        source_document_id="cninfo-600000-2024-annual",
        url=first.url,
    )
    assert record.source_uri == config["source_uri"]
    assert record.response_metadata["metadata_only"] is True
    assert record.response_metadata["download_performed"] is False
    assert record.response_metadata["filing_ids"] == [
        filing.filing_id for filing in result.filings
    ]


def test_hkexnews_discovery_preserves_h_share_scope_and_source_provenance():
    config = _fixture("h_hkexnews")
    client = _client(
        FilingSource.HKEXNEWS,
        config["source_uri"],
        config["filings"],
    )
    query = FilingDiscoveryQuery(
        listing_id=config["listing_id"],
        source=config["source"],
        limit=10,
    )

    result = parse_filing_discovery_record(_provider(client).fetch(query.to_provider_request()))

    assert result.market is FilingMarket.H
    assert result.source is FilingSource.HKEXNEWS
    assert result.filings[0].published_date.isoformat() == "2025-08-13"
    assert result.filings[0].source_document_id == "HKEX-2025081300456"
    assert all(filing.listing_id == "HK00700" for filing in result.filings)
    assert str(result.source_uri) == config["source_uri"]


@pytest.mark.parametrize(
    ("listing_id", "source"),
    [
        ("HK00700", FilingSource.CNINFO),
        ("SH600000", FilingSource.HKEXNEWS),
        ("SZ000001", FilingSource.SSE),
        ("SH600000", FilingSource.SZSE),
        ("BJ430047", FilingSource.SSE),
    ],
)
def test_query_rejects_wrong_market_or_exchange_source(listing_id: str, source: FilingSource):
    request = ProviderRequest(
        category=DataCategory.FILING_DISCOVERY,
        entity_id=listing_id,
        parameters={"source": source.value},
    )
    with pytest.raises(ProviderRequestError, match="not an allowed source|requires a"):
        _provider().fetch(request)


def test_query_allows_each_documented_a_h_source_boundary():
    cases = [
        ("SH600000", FilingSource.CNINFO, "https://www.cninfo.com.cn/search"),
        ("SH600000", FilingSource.SSE, "https://www.sse.com.cn/disclosure/search"),
        ("SZ000001", FilingSource.SZSE, "https://www.szse.cn/disclosure/search"),
        ("BJ430047", FilingSource.BSE, "https://www.bse.cn/disclosure/search"),
        (
            "SH600000",
            FilingSource.A_COMPANY_ANNOUNCEMENT,
            "https://investor.example.cn/announcements",
        ),
        ("HK00700", FilingSource.HKEXNEWS, "https://www1.hkexnews.hk/search/titlesearch.xhtml"),
        (
            "HK00700",
            FilingSource.H_COMPANY_REPORT,
            "https://ir.example.com/reports",
        ),
        (
            "HK00700",
            FilingSource.H_COMPANY_ANNOUNCEMENT,
            "https://ir.example.com/announcements",
        ),
    ]

    for listing_id, source, source_uri in cases:
        client = _client(source, source_uri, [])
        query = FilingDiscoveryQuery(listing_id=listing_id, source=source)
        record = _provider(client).fetch(query.to_provider_request())
        assert parse_filing_discovery_record(record).filings == []


@pytest.mark.parametrize(
    ("listing_id", "source", "source_uri", "document_url"),
    [
        (
            "SH600000",
            FilingSource.CNINFO,
            "https://www.cninfo.com.cn/search",
            "https://static.cninfo.com.cn/report.pdf",
        ),
        (
            "SH600000",
            FilingSource.SSE,
            "https://www.sse.com.cn/disclosure/search",
            "https://www.sse.com.cn/disclosure/report.pdf",
        ),
        (
            "SZ000001",
            FilingSource.SZSE,
            "https://www.szse.cn/disclosure/search",
            "https://www.szse.cn/disclosure/report.pdf",
        ),
        (
            "BJ430047",
            FilingSource.BSE,
            "https://www.bse.cn/disclosure/search",
            "https://www.bse.cn/disclosure/report.pdf",
        ),
        (
            "SH600000",
            FilingSource.A_COMPANY_ANNOUNCEMENT,
            "https://investor.example.cn/announcements",
            "https://investor.example.cn/announcements/report.pdf",
        ),
        (
            "HK00700",
            FilingSource.HKEXNEWS,
            "https://www1.hkexnews.hk/search/titlesearch.xhtml",
            "https://www1.hkexnews.hk/listedco/report.pdf",
        ),
        (
            "HK00700",
            FilingSource.H_COMPANY_REPORT,
            "https://ir.example.com/reports",
            "https://ir.example.com/reports/annual.pdf",
        ),
        (
            "HK00700",
            FilingSource.H_COMPANY_ANNOUNCEMENT,
            "https://ir.example.com/announcements",
            "https://ir.example.com/announcements/dividend.pdf",
        ),
    ],
)
def test_valid_document_metadata_stays_inside_each_source_boundary(
    listing_id: str,
    source: FilingSource,
    source_uri: str,
    document_url: str,
):
    client = _client(
        source,
        source_uri,
        [
            {
                "title": "Formal announcement",
                "document_type": "ANNOUNCEMENT",
                "published_date": "2025-04-30",
                "url": document_url,
            }
        ],
    )
    result = parse_filing_discovery_record(
        _provider(client)
        .fetch(
            FilingDiscoveryQuery(listing_id=listing_id, source=source).to_provider_request()
        )
    )

    assert len(result.filings) == 1
    assert result.filings[0].source is source


def test_request_requires_source_and_rejects_unknown_parameters():
    provider = _provider()
    missing = ProviderRequest(
        category=DataCategory.FILING_DISCOVERY,
        entity_id="SH600000",
        parameters={},
    )
    with pytest.raises(ProviderRequestError, match="requires a source"):
        provider.fetch(missing)

    extra = ProviderRequest(
        category=DataCategory.FILING_DISCOVERY,
        entity_id="SH600000",
        parameters={"source": "CNINFO", "keyword": "annual"},
    )
    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(extra)


@pytest.mark.parametrize(
    "parameters",
    [
        {"source": "CNINFO", "published_from": "2025-05-01", "published_to": "2025-04-30"},
        {"source": "CNINFO", "limit": 0},
        {"source": "CNINFO", "limit": 101},
        {"source": "CNINFO", "limit": True},
        {"source": "CNINFO", "published_from": "2025/04/01"},
        {"source": "CNINFO", "as_of": "2025-04-01", "published_from": "2025-04-02"},
    ],
)
def test_request_rejects_ambiguous_dates_and_limits(parameters: dict):
    request = ProviderRequest(
        category=DataCategory.FILING_DISCOVERY,
        entity_id="SH600000",
        parameters=parameters,
    )
    with pytest.raises(ProviderRequestError, match="invalid filing-discovery request"):
        _provider().fetch(request)


def test_client_and_document_urls_must_stay_inside_declared_official_boundary():
    with pytest.raises(ValueError, match="official host"):
        _client(FilingSource.CNINFO, "https://cninfo.com.cn.evil.example/search", [])

    config = _fixture("a_cninfo")
    invalid = deepcopy(config["filings"])
    invalid[0]["url"] = "https://documents.example.invalid/report.pdf"
    provider = _provider(
        _client(FilingSource.CNINFO, config["source_uri"], invalid)
    )
    with pytest.raises(ProviderResponseError, match="official host"):
        provider.fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000",
                source=FilingSource.CNINFO,
            ).to_provider_request()
        )

    company = _client(
        FilingSource.H_COMPANY_REPORT,
        "https://ir.example.com/reports",
        [
            {
                "title": "Annual report",
                "document_type": "ANNUAL_REPORT",
                "published_date": "2025-03-01",
                "url": "http://ir.example.com/report.pdf",
            }
        ],
    )
    with pytest.raises(ProviderResponseError, match="HTTPS"):
        _provider(company).fetch(
            FilingDiscoveryQuery(
                listing_id="HK00700",
                source=FilingSource.H_COMPANY_REPORT,
            ).to_provider_request()
        )


def test_response_rejects_out_of_scope_rows_extra_fields_and_over_limit():
    config = _fixture("a_cninfo")
    out_of_range = deepcopy(config["filings"])
    out_of_range[0]["published_date"] = "2024-12-31"
    with pytest.raises(ProviderResponseError, match="before published_from"):
        _provider(_client(FilingSource.CNINFO, config["source_uri"], out_of_range)).fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000",
                source=FilingSource.CNINFO,
                published_from="2025-01-01",
            ).to_provider_request()
        )

    extra = deepcopy(config["filings"])
    extra[0]["unexpected"] = "must not be ignored"
    with pytest.raises(ProviderResponseError, match="invalid CNINFO filing discovery metadata"):
        _provider(_client(FilingSource.CNINFO, config["source_uri"], extra)).fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000", source=FilingSource.CNINFO
            ).to_provider_request()
        )

    too_many = config["filings"] + [deepcopy(config["filings"][0])]
    with pytest.raises(ProviderResponseError, match="over requested limit"):
        _provider(_client(FilingSource.CNINFO, config["source_uri"], too_many)).fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000",
                source=FilingSource.CNINFO,
                limit=2,
            ).to_provider_request()
        )


def test_response_rejects_duplicate_source_identity_and_unhonored_document_filter():
    config = _fixture("a_cninfo")
    duplicate = deepcopy(config["filings"])
    duplicate[1]["source_document_id"] = duplicate[0]["source_document_id"]
    with pytest.raises(ProviderResponseError, match="duplicate filing_id"):
        _provider(_client(FilingSource.CNINFO, config["source_uri"], duplicate)).fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000", source=FilingSource.CNINFO
            ).to_provider_request()
        )

    duplicate_url = deepcopy(config["filings"])
    duplicate_url[1]["source_document_id"] = "different-source-id"
    duplicate_url[1]["url"] = duplicate_url[0]["url"]
    with pytest.raises(ProviderResponseError, match="duplicate filing URLs"):
        _provider(_client(FilingSource.CNINFO, config["source_uri"], duplicate_url)).fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000", source=FilingSource.CNINFO
            ).to_provider_request()
        )

    with pytest.raises(ProviderResponseError, match="document_type does not match"):
        _provider(_client(FilingSource.CNINFO, config["source_uri"], config["filings"])).fetch(
            FilingDiscoveryQuery(
                listing_id="SH600000",
                source=FilingSource.CNINFO,
                document_type="ANNUAL_REPORT",
            ).to_provider_request()
        )


def test_as_of_rejects_future_discovery_rows():
    config = _fixture("h_hkexnews")
    with pytest.raises(ProviderResponseError, match="after as_of"):
        _provider(_client(FilingSource.HKEXNEWS, config["source_uri"], config["filings"])).fetch(
            FilingDiscoveryQuery(
                listing_id="HK00700",
                source=FilingSource.HKEXNEWS,
                as_of="2025-03-31",
            ).to_provider_request()
        )


@pytest.mark.parametrize("mutation", ["filing_id", "metadata", "order", "download", "source_uri"])
def test_replay_parser_rejects_tampered_payload_or_provenance(mutation: str):
    config = _fixture("a_cninfo")
    client = _client(FilingSource.CNINFO, config["source_uri"], config["filings"])
    query = FilingDiscoveryQuery(listing_id="SH600000", source=FilingSource.CNINFO)
    record = _provider(client).fetch(query.to_provider_request())

    payload = deepcopy(record.raw_payload)
    metadata = dict(record.response_metadata)
    source_uri = record.source_uri
    if mutation == "filing_id":
        payload["filings"][0]["filing_id"] = "filing-" + "0" * 24
    elif mutation == "metadata":
        metadata["result_count"] += 1
    elif mutation == "order":
        payload["filings"].reverse()
    elif mutation == "download":
        metadata["download_performed"] = True
    else:
        source_uri = "https://www.cninfo.com.cn/other-search"

    replayed = _record_with(
        record,
        raw_payload=payload,
        response_metadata=metadata,
        source_uri=source_uri,
    )
    with pytest.raises(ProviderNormalizationError, match="filing-discovery"):
        parse_filing_discovery_record(replayed)


def test_offline_cache_replay_does_not_call_injected_source(tmp_path: Path):
    config = _fixture("h_hkexnews")
    calls: list[FilingDiscoveryQuery] = []
    client = _client(FilingSource.HKEXNEWS, config["source_uri"], config["filings"], calls)
    provider = _provider(client)
    query = FilingDiscoveryQuery(listing_id="HK00700", source=FilingSource.HKEXNEWS)
    cache = FilesystemRawResponseCache(tmp_path)

    live = fetch_filing_discovery_with_cache(provider, query.to_provider_request(), cache)
    calls.clear()
    replay = fetch_filing_discovery_with_cache(
        provider,
        query.to_provider_request(),
        cache,
        offline=True,
    )

    assert live.record == replay.record
    assert replay.mode.value == "CACHE_REPLAY"
    assert calls == []
    assert parse_filing_discovery_record(replay.record).filings


def test_result_matches_filing_discovery_json_schema():
    config = _fixture("a_cninfo")
    record = _provider(
        _client(FilingSource.CNINFO, config["source_uri"], config["filings"])
    ).fetch(
        FilingDiscoveryQuery(
            listing_id="SH600000", source=FilingSource.CNINFO
        ).to_provider_request()
    )
    result = parse_filing_discovery_record(record)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(result.model_dump(mode="json"))


def test_filing_discovery_is_not_advertised_by_akshare():
    from turtle_value_engine.providers import AKShareProvider

    assert not AKShareProvider().capabilities.supports(DataCategory.FILING_DISCOVERY)
