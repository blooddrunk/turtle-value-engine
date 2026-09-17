"""Offline acceptance tests for the bounded Futu OpenD H-share adapter."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from turtle_value_engine.backtest import MarketBar
from turtle_value_engine.historical import (
    FUTU_COVERAGE_INSUFFICIENT,
    FUTU_ENTITLEMENT_DENIED,
    FUTU_HISTORY_QUOTA_EXHAUSTED,
    FUTU_HISTORY_REQUEST_FAILED,
    FUTU_NO_ROWS,
    FUTU_OPEND_ADAPTER_ID,
    FUTU_SCHEMA_UNSUPPORTED,
    FutuDiagnostic,
    FutuOpenDDailyKDecoder,
    FutuOpenDMarketHistoryAdapter,
    FutuOpenDProviderError,
    FutuOpenDSession,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionRequestV1,
    HistoricalAcquisitionService,
    HistoricalArtifactStore,
    HistoricalIngestionCompiler,
    HistoricalSourceSpecV1,
    HistoricalTargetScope,
    LicenseStatus,
    NetworkResponse,
    RawBlobStore,
    ShardArtifactKind,
    default_decoders,
    default_source_adapters,
)

SOURCE_URI = "https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html"
FIXED_NOW = datetime(2026, 9, 17, tzinfo=UTC)
REQUIRED_COLUMNS = [
    "code",
    "time_key",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "turnover",
]


@dataclass(frozen=True)
class FakeFrame:
    columns: list[str]
    rows: list[dict[str, object]]

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return [dict(row) for row in self.rows]


def _row(day: str, *, code: str = "HK.00700", close: float = 10.0) -> dict[str, object]:
    return {
        "code": code,
        "time_key": f"{day} 00:00:00",
        "open": close - 0.2,
        "close": close,
        "high": close + 0.3,
        "low": close - 0.4,
        "volume": 1_000.0,
        "turnover": 10_000.0,
    }


class FakeOpenDClient:
    def __init__(
        self,
        pages: list[tuple[object, object, object]],
        *,
        quota: object = (0, 1, 10, {"code": "HK.00700"}),
        history_error: Exception | None = None,
    ) -> None:
        self.pages = list(pages)
        self.quota = quota
        self.history_error = history_error
        self.history_calls: list[tuple[str, dict[str, object]]] = []
        self.quota_calls: list[bool] = []
        self.closed = False

    def get_history_kl_quota(self, *, get_detail: bool = False) -> object:
        self.quota_calls.append(get_detail)
        return self.quota

    def request_history_kline(self, code: str, **kwargs: object) -> object:
        self.history_calls.append((code, dict(kwargs)))
        if self.history_error is not None:
            raise self.history_error
        if not self.pages:
            raise AssertionError("fake page queue exhausted")
        return self.pages.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        body: bytes | None = None,
        timeout_seconds: float = 30.0,
    ) -> NetworkResponse:
        del method, url, headers, body, timeout_seconds
        raise AssertionError("Futu SDK adapter must not use the HTTP transport")


def _session_factory(client: FakeOpenDClient):
    def factory(*, host: str, port: int) -> FutuOpenDSession:
        assert host == "127.0.0.1"
        assert port == 11111
        return FutuOpenDSession(
            client=client,
            k_day="fake-K_DAY",
            au_none="fake-AuType.NONE",
            fields_all="fake-KL_FIELD.ALL",
            ret_ok=0,
            sdk_version="fake-sdk-1",
            opend_version="fake-opend-1",
        )

    return factory


def _target() -> HistoricalTargetScope:
    return HistoricalTargetScope(
        target_id="futu-target",
        target_name="bounded Futu H fixture",
        universe_id="futu-fixture-universe",
        markets=["H"],
        listing_ids=["H1"],
        start_date=date(2026, 9, 8),
        end_date=date(2026, 9, 10),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=["PRICES"],
        calendar_ids={"H1": "H:HKEX"},
        listing_markets={"H1": "H"},
        licensing_scope="private owner research only",
    )


def _plan(
    *,
    parameters: dict[str, object] | None = None,
    expected_sessions: dict[str, list[date]] | None = None,
) -> HistoricalAcquisitionPlanV1:
    target = _target()
    source = HistoricalSourceSpecV1(
        source_id="futu-source",
        source_kind="PRICES",
        adapter_id=FUTU_OPEND_ADAPTER_ID,
        provider_id="futu-opend",
        source_name="Futu OpenD SDK export",
        source_uri=SOURCE_URI,
        authority="DOCUMENTED_PROVIDER",
        license_status=LicenseStatus.RESTRICTED_INTERNAL,
        licensing_constraints="private local owner research only",
        license_evidence_uri="https://openapi.futunn.com/futu-api-doc/en/",
        license_evidence_sha256="1" * 64,
        access_grant_reference="owner-futu-opend-session",
        coverage_start=target.start_date,
        coverage_end=target.end_date,
        coverage_listing_ids=["H1"],
    )
    request_parameters: dict[str, object] = {
        "source_uri": SOURCE_URI,
        "futu_code": "HK.00700",
        "canonical_market": "H",
        "currency": "HKD",
        "kline_type": "K_DAY",
        "adjustment": "NONE",
        "timezone": "Asia/Shanghai",
        "max_count": 2,
        "max_pages": 8,
        "opend_host": "127.0.0.1",
        "opend_port": 11111,
    }
    request_parameters.update(parameters or {})
    request = HistoricalAcquisitionRequestV1(
        request_id="futu-request",
        source_id=source.source_id,
        adapter_id=source.adapter_id,
        source_kind="PRICES",
        artifact_kind=ShardArtifactKind.MARKET_BAR,
        schema_version="market-bar-v1",
        listing_ids=["H1"],
        start_date=target.start_date,
        end_date=target.end_date,
        parameters=request_parameters,
        expected_sessions_by_listing=expected_sessions,
        coverage_evidence_basis="TRADING_SESSIONS",
    )
    return HistoricalAcquisitionPlanV1(
        plan_id="futu-plan",
        plan_version="1",
        created_at=FIXED_NOW,
        target=target,
        sources=[source],
        requests=[request],
    )


def _service(client: FakeOpenDClient) -> HistoricalAcquisitionService:
    adapter = FutuOpenDMarketHistoryAdapter(client_factory=_session_factory(client))
    return HistoricalAcquisitionService(
        adapters={FUTU_OPEND_ADAPTER_ID: adapter},
        transport=FakeTransport(),
        clock=lambda: FIXED_NOW,
    )


def _single_page_client() -> FakeOpenDClient:
    return FakeOpenDClient(
        [
            (
                0,
                FakeFrame(
                    REQUIRED_COLUMNS,
                    [_row("2026-09-08"), _row("2026-09-10", close=11.0)],
                ),
                None,
            )
        ]
    )


def test_import_and_default_registration_are_lazy_and_offline():
    assert FUTU_OPEND_ADAPTER_ID in default_source_adapters()
    assert (
        FUTU_OPEND_ADAPTER_ID,
        ShardArtifactKind.MARKET_BAR,
        "market-bar-v1",
    ) in default_decoders(include_optional_parquet=False)
    assert "futu" not in sys.modules


def test_explicit_daily_unadjusted_request_and_quota_are_constructed():
    client = _single_page_client()
    result = _service(client).probe(_plan(), network_allowed=True)

    assert result.probe_reports[0].historical_capable is True
    assert result.probe_reports[0].blockers == []
    assert client.quota_calls == [True]
    code, kwargs = client.history_calls[0]
    assert code == "HK.00700"
    assert kwargs["start"] == "2026-09-08"
    assert kwargs["end"] == "2026-09-10"
    assert kwargs["ktype"] == "fake-K_DAY"
    assert kwargs["autype"] == "fake-AuType.NONE"
    assert kwargs["fields"] == ["fake-KL_FIELD.ALL"]
    assert kwargs["max_count"] == 2
    assert kwargs["page_req_key"] is None
    assert kwargs["extended_time"] is False
    assert client.closed is True


def test_single_page_acquire_compile_and_market_bar_mapping(tmp_path: Path):
    client = _single_page_client()
    plan = _plan()
    acquired = _service(client).acquire(
        plan,
        raw_store=RawBlobStore(tmp_path / "raw"),
        network_allowed=True,
    )
    receipt = acquired.batch.receipts[0]
    assert receipt.artifact_metadata["representation"] == "futu-opend-sdk-export-v1"
    assert receipt.artifact_metadata["adjustment"] == "NONE"
    assert receipt.artifact_metadata["futu_code"] == "HK.00700"
    body = RawBlobStore(tmp_path / "raw").read(receipt.sha256)
    assert json.loads(body)["representation_id"] == "futu-opend-sdk-export-v1"

    manifest = HistoricalIngestionCompiler(
        raw_store=RawBlobStore(tmp_path / "raw"),
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
    ).compile_with_replay_check(acquired.batch)
    shard = next(
        item for item in manifest.shards if item.artifact_kind is ShardArtifactKind.MARKET_BAR
    )
    bars = HistoricalArtifactStore(tmp_path / "artifacts").read_shard(shard, MarketBar)
    assert bars[0].listing_id == "H1"
    assert bars[0].market.value == "H"
    assert bars[0].currency == "HKD"
    assert bars[0].price_basis.value == "UNADJUSTED"
    assert bars[0].amount == 10_000.0


def test_multi_page_order_and_opaque_page_key_are_frozen_deterministically(tmp_path: Path):
    secret_page_key = b"owner-session-page-key"
    client = FakeOpenDClient(
        [
            (0, FakeFrame(REQUIRED_COLUMNS, [_row("2026-09-08")]), secret_page_key),
            (0, FakeFrame(REQUIRED_COLUMNS, [_row("2026-09-10", close=11.0)]), None),
        ]
    )
    acquired = _service(client).acquire(
        _plan(), raw_store=RawBlobStore(tmp_path / "raw"), network_allowed=True
    )
    body = RawBlobStore(tmp_path / "raw").read(acquired.batch.receipts[0].sha256)
    payload = json.loads(body)
    assert [page["page_ordinal"] for page in payload["pages"]] == [1, 2]
    assert [row["time_key"] for page in payload["pages"] for row in page["rows"]] == [
        "2026-09-08 00:00:00",
        "2026-09-10 00:00:00",
    ]
    assert secret_page_key.decode() not in body.decode()
    assert payload["pages"][1]["page_key_in"]["kind"] == "bytes"
    assert client.history_calls[1][1]["page_req_key"] == secret_page_key


def test_identity_is_not_inferred_from_fqgate_fields():
    client = _single_page_client()
    plan = _plan(parameters={"market": "USHA", "code": "600519"})
    _service(client).probe(plan, network_allowed=True)
    assert client.history_calls[0][0] == "HK.00700"


@pytest.mark.parametrize(
    ("client_kwargs", "expected"),
    [
        (
            {"quota": (0, 1, 0, [])},
            FUTU_HISTORY_QUOTA_EXHAUSTED,
        ),
        (
            {"history_error": FutuOpenDProviderError(FutuDiagnostic.ENTITLEMENT_DENIED)},
            FUTU_ENTITLEMENT_DENIED,
        ),
        (
            {"history_error": FutuOpenDProviderError(FutuDiagnostic.OPEND_UNAVAILABLE)},
            "FUTU_OPEND_UNAVAILABLE",
        ),
        (
            {"history_error": FutuOpenDProviderError(FutuDiagnostic.HISTORY_REQUEST_FAILED)},
            FUTU_HISTORY_REQUEST_FAILED,
        ),
    ],
)
def test_provider_diagnostics_are_distinguished(client_kwargs: dict[str, object], expected: str):
    client = FakeOpenDClient([], **client_kwargs)
    report = _service(client).probe(_plan(), network_allowed=True)
    assert report.probe_reports[0].blockers == [expected]
    assert client.closed is True


def test_unknown_provider_failure_stays_unknown_and_does_not_persist_error_text():
    client = FakeOpenDClient([(17, "private broker error text", None)])
    report = _service(client).probe(_plan(), network_allowed=True)
    assert report.probe_reports[0].blockers == ["FUTU_HISTORY_REQUEST_FAILED: provider code 17"]
    assert "private broker error text" not in report.model_dump_json()


def test_malformed_required_schema_fails_closed(tmp_path: Path):
    client = FakeOpenDClient(
        [(0, FakeFrame([*REQUIRED_COLUMNS[:-1]], [_row("2026-09-08")]), None)]
    )
    report = _service(client).probe(_plan(), network_allowed=True)
    assert report.probe_reports[0].blockers == [
        FUTU_SCHEMA_UNSUPPORTED + ": required daily-K schema or semantics are unsupported"
    ]
    with pytest.raises(Exception, match="FUTU_SCHEMA_UNSUPPORTED"):
        _service(
            FakeOpenDClient(
                [(0, FakeFrame([*REQUIRED_COLUMNS[:-1]], [_row("2026-09-08")]), None)]
            )
        ).acquire(_plan(), raw_store=RawBlobStore(tmp_path / "raw"), network_allowed=True)


def test_duplicate_dates_fail_closed():
    client = FakeOpenDClient(
        [
            (
                0,
                FakeFrame(REQUIRED_COLUMNS, [_row("2026-09-08"), _row("2026-09-08")]),
                None,
            )
        ]
    )
    report = _service(client).probe(_plan(), network_allowed=True)
    assert report.probe_reports[0].blockers == [
        FUTU_SCHEMA_UNSUPPORTED + ": required daily-K schema or semantics are unsupported"
    ]


def test_successful_response_without_rows_is_not_entitlement_evidence():
    client = FakeOpenDClient([(0, FakeFrame(REQUIRED_COLUMNS, []), None)])
    report = _service(client).probe(_plan(), network_allowed=True)
    assert report.probe_reports[0].blockers == [FUTU_NO_ROWS]
    assert report.probe_reports[0].account_entitlement == "UNKNOWN"


def test_bounded_date_filtering_keeps_out_of_range_rows_out_of_canonical_manifest(tmp_path: Path):
    client = FakeOpenDClient(
        [
            (
                0,
                FakeFrame(
                    REQUIRED_COLUMNS,
                    [_row("2026-09-01"), _row("2026-09-08"), _row("2026-09-10")],
                ),
                None,
            )
        ]
    )
    acquired = _service(client).acquire(
        _plan(), raw_store=RawBlobStore(tmp_path / "raw"), network_allowed=True
    )
    manifest = HistoricalIngestionCompiler(
        raw_store=RawBlobStore(tmp_path / "raw"),
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
    ).compile(acquired.batch)
    shard = next(
        item for item in manifest.shards if item.artifact_kind is ShardArtifactKind.MARKET_BAR
    )
    bars = HistoricalArtifactStore(tmp_path / "artifacts").read_shard(shard, MarketBar)
    assert [bar.trading_date for bar in bars] == [
        date(2026, 9, 8),
        date(2026, 9, 10),
    ]


def test_expected_session_gap_is_conservative():
    client = _single_page_client()
    report = _service(client).probe(
        _plan(
            expected_sessions={
                "H1": [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)]
            }
        ),
        network_allowed=True,
    )
    assert FUTU_COVERAGE_INSUFFICIENT in report.probe_reports[0].blockers[0]


def test_plan_rejects_credentials_and_missing_explicit_adjustment():
    with pytest.raises(ValueError, match="credential"):
        _plan(parameters={"credential": "not-allowed"})
    report = _service(_single_page_client()).probe(
        _plan(parameters={"adjustment": "QFQ"}), network_allowed=True
    )
    assert report.probe_reports[0].blockers == [
        FUTU_SCHEMA_UNSUPPORTED + ": required daily-K schema or semantics are unsupported"
    ]


def test_lazy_factory_reports_sdk_absence_without_importing_it(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def reject_futu(name, *args, **kwargs):
        if name == "futu":
            raise ModuleNotFoundError("futu is intentionally absent in this test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_futu)
    from turtle_value_engine.historical import LazyFutuOpenDClientFactory

    with pytest.raises(FutuOpenDProviderError) as caught:
        LazyFutuOpenDClientFactory()(host="127.0.0.1", port=11111)
    assert caught.value.diagnostic == "FUTU_SDK_UNAVAILABLE"


def test_same_frozen_provider_envelope_replays_to_same_identity(tmp_path: Path):
    client = _single_page_client()
    acquired = _service(client).acquire(
        _plan(), raw_store=RawBlobStore(tmp_path / "raw"), network_allowed=True
    )
    compiler = HistoricalIngestionCompiler(
        raw_store=RawBlobStore(tmp_path / "raw"),
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
        decoders=default_decoders(include_optional_parquet=False),
    )
    first = compiler.compile(acquired.batch)
    second = compiler.compile(acquired.batch)
    assert first.content_sha256 == second.content_sha256
    assert [(item.shard_id, item.content_sha256) for item in first.shards] == [
        (item.shard_id, item.content_sha256) for item in second.shards
    ]
    assert isinstance(default_decoders(include_optional_parquet=False)[
        (FUTU_OPEND_ADAPTER_ID, ShardArtifactKind.MARKET_BAR, "market-bar-v1")
    ], FutuOpenDDailyKDecoder)
