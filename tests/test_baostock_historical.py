"""Offline tests for the Phase 5R-A BaoStock lifecycle/calendar adapter."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from turtle_value_engine.backtest import MarketBar
from turtle_value_engine.historical import (
    BAOSTOCK_ADAPTER_ID,
    BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
    BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION,
    BaoStockAshareLifecycleAdapter,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionRequestV1,
    HistoricalAcquisitionService,
    HistoricalArtifactStore,
    HistoricalDatasetCompiler,
    HistoricalIngestionCompiler,
    HistoricalSourceSchemaError,
    HistoricalSourceSpecV1,
    HistoricalTargetScope,
    HistoricalTradingSession,
    RawBlobStore,
    ShardArtifactKind,
)
from turtle_value_engine.historical.acquisition import (
    ConfiguredHttpSourceAdapter,
    NetworkResponse,
)


class FakeBaoStockResult:
    def __init__(self, fields: list[str], rows: list[list[object]]) -> None:
        self.error_code = "0"
        self.error_msg = ""
        self.fields = fields
        self.rows = rows


class FakeBaoStockClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def login(self) -> FakeBaoStockResult:
        self.calls.append(("login",))
        return FakeBaoStockResult([], [])

    def logout(self) -> FakeBaoStockResult:
        self.calls.append(("logout",))
        return FakeBaoStockResult([], [])

    def query_stock_basic(self, *, code: str) -> FakeBaoStockResult:
        self.calls.append(("query_stock_basic", code))
        return FakeBaoStockResult(
            ["code", "code_name", "ipoDate", "outDate", "type", "status"],
            [[code, "测试股份", "2010-01-01", "", "1", "1"]],
        )

    def query_trade_dates(self, *, start_date: str, end_date: str) -> FakeBaoStockResult:
        self.calls.append(("query_trade_dates", start_date, end_date))
        return FakeBaoStockResult(
            ["calendar_date", "is_trading_day"],
            [["2020-01-01", "1"], ["2020-01-02", "1"], ["2020-01-03", "0"]],
        )


class FakeTransport:
    def __init__(self, response: NetworkResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_kwargs: object) -> NetworkResponse:
        self.calls.append((method, url))
        return self.response


def _target(*, required: list[str]) -> HistoricalTargetScope:
    return HistoricalTargetScope(
        target_id="a-target",
        target_name="bounded A target",
        universe_id="a-universe",
        markets=["A"],
        listing_ids=["SH600000"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=required,
        calendar_ids={"SH600000": "A:CN"},
        listing_markets={"SH600000": "A"},
        licensing_scope="private local research",
    )


def _source(source_id: str, *, kind: str, adapter_id: str) -> HistoricalSourceSpecV1:
    return HistoricalSourceSpecV1(
        source_id=source_id,
        source_kind=kind,
        adapter_id=adapter_id,
        provider_id="baostock" if adapter_id == BAOSTOCK_ADAPTER_ID else "test-price",
        source_name="test source",
        source_uri="https://source.example.test/data",
        authority="DOCUMENTED_PROVIDER",
        licensing_constraints="private local research only",
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2020, 1, 3),
        coverage_listing_ids=["SH600000"],
    )


def _lifecycle_request(request_id: str, artifact_kind: str, schema_version: str):
    return HistoricalAcquisitionRequestV1(
        request_id=request_id,
        source_id="lifecycle-source",
        adapter_id=BAOSTOCK_ADAPTER_ID,
        source_kind="LISTING_LIFECYCLE",
        artifact_kind=artifact_kind,
        schema_version=schema_version,
        listing_ids=["SH600000"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        parameters={"calendar_id": "A:CN"},
        coverage_evidence_basis="LIFECYCLE_INDEX",
    )


def test_baostock_fake_runtime_acquires_and_compiles_lifecycle_and_calendar(tmp_path: Path):
    client = FakeBaoStockClient()
    plan = HistoricalAcquisitionPlanV1(
        plan_id="baostock-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=_target(required=["LISTING_LIFECYCLE"]),
        sources=[
            _source(
                "lifecycle-source",
                kind="LISTING_LIFECYCLE",
                adapter_id=BAOSTOCK_ADAPTER_ID,
            )
        ],
        requests=[
            _lifecycle_request(
                "lifecycle-request",
                "LISTING_LIFECYCLE",
                BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
            ),
            _lifecycle_request(
                "calendar-request",
                "TRADING_SESSION",
                BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION,
            ),
        ],
    )
    adapter = BaoStockAshareLifecycleAdapter(lambda: client)
    raw_store = RawBlobStore(tmp_path / "raw")
    result = HistoricalAcquisitionService(
        {BAOSTOCK_ADAPTER_ID: adapter},
        transport=FakeTransport(
            NetworkResponse(200, {"content-type": "application/json"}, b"", "https://unused")
        ),
    ).acquire(plan, raw_store=raw_store, network_allowed=True)

    for receipt in result.batch.receipts:
        envelope = json.loads(raw_store.read(receipt.sha256))
        assert envelope["contract"] == "baostock_sdk_export_v1"
        assert envelope["representation_id"] == "baostock-sdk-export-v1"
    assert [call[0] for call in client.calls] == [
        "login",
        "query_stock_basic",
        "logout",
        "login",
        "query_trade_dates",
        "logout",
    ]
    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    ).compile_with_replay_check(result.batch)
    session_shards = [
        shard
        for shard in manifest.shards
        if shard.artifact_kind is ShardArtifactKind.TRADING_SESSION
    ]
    assert len(session_shards) == 1
    sessions = artifact_store.read_shard(session_shards[0], model_type=HistoricalTradingSession)
    assert [row.is_trading_day for row in sessions] == [True, True, False]
    lifecycle_shards = [
        shard
        for shard in manifest.shards
        if shard.artifact_kind is ShardArtifactKind.LISTING_LIFECYCLE
    ]
    lifecycle = artifact_store.read_shard(lifecycle_shards[0])
    assert lifecycle[0]["terminal_outcome"] == "ACTIVE"
    assert lifecycle[0]["historical_codes"] == ["sh.600000"]


def test_baostock_calendar_rows_derive_price_expected_sessions(tmp_path: Path):
    client = FakeBaoStockClient()
    bar = MarketBar(
        bar_id="SH600000:2020-01-01",
        listing_id="SH600000",
        market="A",
        trading_date=date(2020, 1, 1),
        close=10.0,
        currency="CNY",
        source_hash="0" * 64,
    )
    price_body = f"[{bar.model_dump_json()}]".encode()
    price_source = _source("price-source", kind="PRICES", adapter_id="http-json")
    lifecycle_source = _source(
        "lifecycle-source",
        kind="LISTING_LIFECYCLE",
        adapter_id=BAOSTOCK_ADAPTER_ID,
    )
    lifecycle_request = _lifecycle_request(
        "lifecycle-request",
        "LISTING_LIFECYCLE",
        BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
    )
    calendar_request = _lifecycle_request(
        "calendar-request",
        "TRADING_SESSION",
        BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION,
    )
    price_request = HistoricalAcquisitionRequestV1(
        request_id="price-request",
        source_id="price-source",
        adapter_id="http-json",
        source_kind="PRICES",
        artifact_kind="MARKET_BAR",
        schema_version="market-bar-v1",
        listing_ids=["SH600000"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        parameters={"source_uri": "https://source.example.test/data"},
    )
    plan = HistoricalAcquisitionPlanV1(
        plan_id="coverage-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=_target(required=["LISTING_LIFECYCLE", "PRICES"]),
        sources=[lifecycle_source, price_source],
        requests=[lifecycle_request, calendar_request, price_request],
    )
    transport = FakeTransport(
        NetworkResponse(
            200,
            {"content-type": "application/json", "content-length": str(len(price_body))},
            price_body,
            "https://source.example.test/data",
        )
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    acquired = HistoricalAcquisitionService(
        {
            BAOSTOCK_ADAPTER_ID: BaoStockAshareLifecycleAdapter(lambda: client),
            "http-json": ConfiguredHttpSourceAdapter(),
        },
        transport=transport,
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
    ).compile(acquired.batch)
    price_report = next(
        report
        for report in manifest.coverage_reports
        if report.records[0].source_kind.value == "PRICES"
    )
    record = price_report.records[0]
    assert record.expected_session_count == 2
    assert record.observed_session_count == 1
    assert record.missing_dates == [date(2020, 1, 2)]


def test_baostock_rejects_h_share_before_opening_sdk_session():
    opened = False

    def factory() -> object:
        nonlocal opened
        opened = True
        return object()

    request = _lifecycle_request(
        "h-request",
        "LISTING_LIFECYCLE",
        BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
    ).model_copy(update={"listing_ids": ["HK00001"]})
    adapter = BaoStockAshareLifecycleAdapter(factory)
    with pytest.raises(HistoricalSourceSchemaError, match="A-share"):
        adapter.acquire(
            request,
            transport=FakeTransport(NetworkResponse(200, {}, b"", "https://unused")),
            credentials=object(),
        )
    assert opened is False


def test_baostock_rejects_unsupported_provider_fields():
    class UnsupportedFieldClient(FakeBaoStockClient):
        def query_stock_basic(self, *, code: str) -> FakeBaoStockResult:
            return FakeBaoStockResult(
                ["code", "code_name", "ipoDate", "outDate", "type", "status", "extra"],
                [[code, "测试股份", "2010-01-01", "", "1", "1", "unexpected"]],
            )

    with pytest.raises(HistoricalSourceSchemaError, match="unsupported or changed"):
        BaoStockAshareLifecycleAdapter(lambda: UnsupportedFieldClient()).acquire(
            _lifecycle_request(
                "unsupported-fields",
                "LISTING_LIFECYCLE",
                BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
            ),
            transport=FakeTransport(
                NetworkResponse(200, {}, b"", "https://unused")
            ),
            credentials=object(),
        )


def test_baostock_rejects_inconsistent_terminal_shape_and_incomplete_calendar():
    class MissingTerminalClient(FakeBaoStockClient):
        def query_stock_basic(self, *, code: str) -> FakeBaoStockResult:
            return FakeBaoStockResult(
                ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                [[code, "测试股份", "2010-01-01", "", "1", "0"]],
            )

    with pytest.raises(HistoricalSourceSchemaError, match="no terminal date"):
        BaoStockAshareLifecycleAdapter(lambda: MissingTerminalClient()).acquire(
            _lifecycle_request(
                "missing-terminal",
                "LISTING_LIFECYCLE",
                BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
            ),
            transport=FakeTransport(
                NetworkResponse(200, {}, b"", "https://unused")
            ),
            credentials=object(),
        )

    class IncompleteCalendarClient(FakeBaoStockClient):
        def query_trade_dates(
            self, *, start_date: str, end_date: str
        ) -> FakeBaoStockResult:
            return FakeBaoStockResult(
                ["calendar_date", "is_trading_day"],
                [["2020-01-01", "1"], ["2020-01-03", "0"]],
            )

    with pytest.raises(HistoricalSourceSchemaError, match="every requested date"):
        BaoStockAshareLifecycleAdapter(lambda: IncompleteCalendarClient()).acquire(
            _lifecycle_request(
                "incomplete-calendar",
                "TRADING_SESSION",
                BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION,
            ),
            transport=FakeTransport(
                NetworkResponse(200, {}, b"", "https://unused")
            ),
            credentials=object(),
        )


def test_baostock_calendar_listing_mismatch_fails_offline_validation(tmp_path: Path):
    client = FakeBaoStockClient()
    calendar_request = _lifecycle_request(
        "calendar-mismatch",
        "TRADING_SESSION",
        BAOSTOCK_TRADING_SESSION_SCHEMA_VERSION,
    ).model_copy(update={"parameters": {"calendar_id": "A:OTHER"}})
    plan = HistoricalAcquisitionPlanV1(
        plan_id="calendar-mismatch-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=_target(required=["LISTING_LIFECYCLE"]),
        sources=[
            _source(
                "lifecycle-source",
                kind="LISTING_LIFECYCLE",
                adapter_id=BAOSTOCK_ADAPTER_ID,
            )
        ],
        requests=[
            _lifecycle_request(
                "lifecycle-request",
                "LISTING_LIFECYCLE",
                BAOSTOCK_LIFECYCLE_SCHEMA_VERSION,
            ),
            calendar_request,
        ],
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    acquired = HistoricalAcquisitionService(
        {BAOSTOCK_ADAPTER_ID: BaoStockAshareLifecycleAdapter(lambda: client)},
        transport=FakeTransport(
            NetworkResponse(200, {"content-type": "application/json"}, b"", "https://unused")
        ),
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    ).compile(acquired.batch)

    summary = HistoricalDatasetCompiler(manifest, artifact_store).validate(
        raise_on_error=False
    )
    assert summary.valid is False
    assert any(
        "trading session calendar does not match target scope" in item
        for item in summary.errors
    )
