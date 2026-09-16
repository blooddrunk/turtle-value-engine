"""Offline tests for the FQGate historical MARKET_BAR adapter."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from turtle_value_engine.backtest import MarketBar
from turtle_value_engine.historical import (
    FQGateMarketHistoryAdapter,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionRequestV1,
    HistoricalAcquisitionService,
    HistoricalArtifactStore,
    HistoricalIngestionCompiler,
    HistoricalIngestionError,
    HistoricalSourceSchemaError,
    HistoricalSourceSpecV1,
    HistoricalTargetScope,
    LicenseStatus,
    NetworkDisabledError,
    NetworkResponse,
    RawBlobStore,
    ShardArtifactKind,
)

SOURCE_URI = "http://127.0.0.1:17281/v1/market/history/klines"


class FakeFQGateTransport:
    def __init__(self, bodies: list[bytes], *, status_code: int = 200) -> None:
        self.bodies = list(bodies)
        self.status_code = status_code
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        body: bytes | None = None,
        timeout_seconds: float = 30.0,
    ) -> NetworkResponse:
        del timeout_seconds
        self.calls.append((method, url, dict(headers or {}), body))
        response_body = self.bodies.pop(0)
        return NetworkResponse(
            status_code=self.status_code,
            headers={
                "content-type": "application/json",
                "content-length": str(len(response_body)),
            },
            body=response_body,
            url=url,
        )


def _field(value: object) -> dict[str, object]:
    kind = "string" if isinstance(value, str) else "integer" if isinstance(value, int) else "float"
    return {"type": kind, "value": value}


def _response_body(
    *,
    records: object,
    data_metadata: dict[str, object] | None = None,
) -> bytes:
    data = dict(data_metadata or {})
    data["records"] = records
    return json.dumps(
        {
            "code": 0,
            "message": "操作成功",
            "data": data,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _daily_body() -> bytes:
    return _response_body(
        records=[
            [
                {
                    "1": _field("2026-09-08"),
                    "7": _field(10.0),
                    "8": _field(10.8),
                    "9": _field(9.8),
                    "11": _field(10.5),
                    "13": _field(1000),
                    "19": _field(10500.0),
                },
                {
                    "1": _field("20260909"),
                    "7": _field("10.5"),
                    "8": _field("11.0"),
                    "9": _field("10.2"),
                    "11": _field("10.8"),
                    "13": _field("1,200"),
                    "19": _field("12,960"),
                },
                {
                    "1": _field("20260910"),
                    "7": _field(10.8),
                    "8": _field(11.2),
                    "9": _field(10.6),
                    "11": _field(11.0),
                    "13": _field(1400),
                    "19": _field(15400.0),
                },
            ]
        ]
    )


def _target(*, market: str = "A", listing_id: str = "A1") -> HistoricalTargetScope:
    return HistoricalTargetScope(
        target_id=f"target-{market.lower()}",
        target_name="FQGate fake target",
        universe_id="fqgate-fake-universe",
        markets=[market],
        listing_ids=[listing_id],
        start_date=date(2026, 9, 8),
        end_date=date(2026, 9, 10),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=["PRICES"],
        calendar_ids={listing_id: f"{market}:TEST"},
        listing_markets={listing_id: market},
        licensing_scope="private owner research only",
    )


def _plan(
    *,
    market: str = "A",
    listing_id: str = "A1",
    fqgate_market: str = "USHA",
    body_parameters: dict[str, object] | None = None,
) -> HistoricalAcquisitionPlanV1:
    target = _target(market=market, listing_id=listing_id)
    parameters: dict[str, object] = {
        "source_uri": SOURCE_URI,
        "market": fqgate_market,
        "code": "600519" if market == "A" else "owner-observed-h-code",
        "canonical_market": market,
        "currency": "CNY" if market == "A" else "HKD",
    }
    parameters.update(body_parameters or {})
    source = HistoricalSourceSpecV1(
        source_id=f"fqgate-{market.lower()}-prices",
        source_kind="PRICES",
        adapter_id=FQGateMarketHistoryAdapter.adapter_id,
        provider_id="fqgate-local-session",
        source_name="FQGate local historical K-lines",
        source_uri=SOURCE_URI,
        authority="DOCUMENTED_PROVIDER",
        license_status=LicenseStatus.RESTRICTED_INTERNAL,
        licensing_constraints="private local research cache only",
        license_evidence_uri="https://source.example.test/fqgate-terms",
        license_evidence_sha256="1" * 64,
        access_grant_reference="owner-local-fqgate-session",
        coverage_start=target.start_date,
        coverage_end=target.end_date,
        coverage_listing_ids=[listing_id],
    )
    request = HistoricalAcquisitionRequestV1(
        request_id=f"fqgate-{market.lower()}-request",
        source_id=source.source_id,
        adapter_id=source.adapter_id,
        source_kind="PRICES",
        artifact_kind=ShardArtifactKind.MARKET_BAR,
        schema_version="market-bar-v1",
        listing_ids=[listing_id],
        start_date=target.start_date,
        end_date=target.end_date,
        parameters=parameters,
    )
    return HistoricalAcquisitionPlanV1(
        plan_id=f"fqgate-{market.lower()}-plan",
        plan_version="1",
        created_at=datetime(2026, 9, 16, tzinfo=UTC),
        target=target,
        sources=[source],
        requests=[request],
    )


def _service(transport: FakeFQGateTransport) -> HistoricalAcquisitionService:
    return HistoricalAcquisitionService(
        adapters={FQGateMarketHistoryAdapter.adapter_id: FQGateMarketHistoryAdapter()},
        transport=transport,
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )


def test_fqgate_acquires_exact_post_bytes_into_raw_cas(tmp_path: Path):
    body = _daily_body()
    transport = FakeFQGateTransport([body])
    plan = _plan()

    result = _service(transport).acquire(
        plan,
        raw_store=RawBlobStore(tmp_path / "raw"),
        network_allowed=True,
    )

    method, url, headers, request_body = transport.calls[0]
    assert method == "POST"
    assert url == SOURCE_URI
    assert headers["Content-Type"] == "application/json"
    assert json.loads(request_body or b"") == {
        "adjust": "",
        "code": "600519",
        "end_date": "20260910",
        "interval": "day",
        "market": "USHA",
        "start_date": "20260908",
    }
    receipt = result.batch.receipts[0]
    assert RawBlobStore(tmp_path / "raw").read(receipt.sha256) == body
    assert receipt.artifact_metadata["response_schema"] == "fqgate-envelope-v1"
    assert receipt.artifact_metadata["fqgate_market"] == "USHA"
    assert receipt.artifact_metadata["fqgate_code"] == "600519"


def test_fqgate_probe_records_observed_span_and_only_claims_successful_history():
    transport = FakeFQGateTransport([_daily_body()])
    report = _service(transport).probe(_plan(), network_allowed=True)

    probe = report.probe_reports[0]
    assert probe.status == "PASS"
    assert probe.historical_capable is True
    assert probe.observed_listing_ids == ["A1"]
    assert probe.observed_start == date(2026, 9, 8)
    assert probe.observed_end == date(2026, 9, 10)
    assert report.production_eligible is False


def test_fqgate_accepts_observed_data_metadata_envelope():
    body = _response_body(
        records=[
            [
                {
                    "1": _field("20260908"),
                    "7": _field(10.0),
                    "8": _field(10.8),
                    "9": _field(9.8),
                    "11": _field(10.5),
                }
            ]
        ],
        data_metadata={
            "business_type": 210,
            "data_state": "rows_returned",
            "format": "hxfile",
            "instance": 1,
            "record_count": 1,
            "row_count": 1,
            "segment_count": 1,
        },
    )
    report = _service(FakeFQGateTransport([body])).probe(
        _plan(),
        network_allowed=True,
    )

    assert report.probe_reports[0].status == "PASS"
    assert not any(
        "response shape is unsupported" in item
        for item in report.probe_reports[0].blockers
    )


def test_fqgate_compiles_explicit_ohlcv_date_mapping_and_replays_identically(tmp_path: Path):
    body = _daily_body()
    raw_store = RawBlobStore(tmp_path / "raw")
    transport = FakeFQGateTransport([body])
    result = _service(transport).acquire(plan := _plan(), raw_store=raw_store, network_allowed=True)
    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    compiler = HistoricalIngestionCompiler(raw_store=raw_store, artifact_store=artifact_store)

    first = compiler.compile(result.batch)
    second = compiler.compile(result.batch)

    assert first.dataset_id == second.dataset_id
    assert first.content_sha256 == second.content_sha256
    assert [item.shard_id for item in first.shards] == [item.shard_id for item in second.shards]
    shard = first.shards[0]
    rows = artifact_store.read_shard(shard, model_type=MarketBar)
    assert [row.trading_date for row in rows] == [
        date(2026, 9, 8),
        date(2026, 9, 9),
        date(2026, 9, 10),
    ]
    assert rows[0].timestamp == datetime(
        2026,
        9,
        8,
        12,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    assert rows[0].open == 10.0
    assert rows[0].high == 10.8
    assert rows[0].low == 9.8
    assert rows[0].close == 10.5
    assert rows[0].volume == 1000.0
    assert rows[0].amount == 10500.0
    assert all(row.market.value == "A" for row in rows)
    assert all(row.price_basis.value == "UNADJUSTED" for row in rows)
    assert plan.requests[0].parameters["canonical_market"] == "A"


def test_fqgate_accepts_missing_optional_volume_and_amount_without_synthetic_values(tmp_path: Path):
    body = _response_body(
        records=[
            [
                {
                    "1": _field("20260908"),
                    "7": _field(10.0),
                    "8": _field(10.8),
                    "9": _field(9.8),
                    "11": _field(10.5),
                }
            ]
        ]
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    result = _service(FakeFQGateTransport([body])).acquire(
        _plan(), raw_store=raw_store, network_allowed=True
    )
    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    ).compile(result.batch)
    row = artifact_store.read_shard(manifest.shards[0], model_type=MarketBar)[0]
    assert row.volume is None
    assert row.amount is None


@pytest.mark.parametrize(
    "records",
    [
        [[{"1": _field("20260908"), "7": _field(10.0)}]],
        [
            [
                {
                    "1": _field("20260908"),
                    "7": _field(10.0),
                    "8": _field(10.8),
                    "9": _field(9.8),
                    "11": {"type": "float"},
                }
            ]
        ],
        [
            [
                {
                    "1": _field("20260908"),
                    "7": _field(10.0),
                    "8": _field(10.8),
                    "9": _field(9.8),
                    "11": _field(10.5),
                    "13": _field(float("nan")),
                }
            ]
        ],
    ],
)
def test_fqgate_malformed_or_unknown_shapes_fail_closed(tmp_path: Path, records: object):
    # json.dumps serializes NaN; the adapter must reject it while decoding.
    body = _response_body(records=records)
    raw_store = RawBlobStore(tmp_path / "raw")
    result = _service(FakeFQGateTransport([body])).acquire(
        _plan(), raw_store=raw_store, network_allowed=True
    )
    with pytest.raises(HistoricalIngestionError):
        HistoricalIngestionCompiler(
            raw_store=raw_store,
            artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
        ).compile(result.batch)


def test_fqgate_rejects_adjusted_or_non_daily_requests_before_network(tmp_path: Path):
    transport = FakeFQGateTransport([])
    with pytest.raises(HistoricalSourceSchemaError, match="unadjusted"):
        _service(transport).acquire(
            _plan(body_parameters={"adjust": "forward"}),
            raw_store=RawBlobStore(tmp_path / "raw"),
            network_allowed=True,
        )
    assert transport.calls == []

    with pytest.raises(HistoricalSourceSchemaError, match="date-range mode"):
        _service(transport).acquire(
            _plan(body_parameters={"count": 100}),
            raw_store=RawBlobStore(tmp_path / "raw-count"),
            network_allowed=True,
        )
    assert transport.calls == []


def test_fqgate_h_probe_does_not_claim_h_capability_without_observed_success():
    empty_body = _response_body(records=[])
    report = _service(FakeFQGateTransport([empty_body])).probe(
        _plan(market="H", listing_id="H1", fqgate_market="owner-observed-h-market"),
        network_allowed=True,
    )

    probe = report.probe_reports[0]
    assert probe.historical_capable is False
    assert probe.observed_listing_ids == []
    assert report.personal_research_ready is False
    assert report.production_eligible is False
    assert any("HISTORICAL_CAPABILITY_UNVERIFIED" in item for item in report.blockers)


def test_default_registry_contains_fqgate_without_affecting_hithink_path():
    from turtle_value_engine.historical import default_decoders, default_source_adapters

    adapters = default_source_adapters()
    decoders = default_decoders(include_optional_parquet=False)
    assert adapters[FQGateMarketHistoryAdapter.adapter_id].requires_live_credential is False
    assert (
        FQGateMarketHistoryAdapter.adapter_id,
        ShardArtifactKind.MARKET_BAR,
        "market-bar-v1",
    ) in decoders
    assert "hithink-market-dumps" in adapters


def test_fqgate_live_boundary_requires_opt_in_but_not_provider_credentials():
    service = HistoricalAcquisitionService()
    plan = _plan()

    with pytest.raises(NetworkDisabledError, match="network is denied"):
        service._require_network_authorization(plan, network_allowed=False)
    service._require_network_authorization(plan, network_allowed=True)
