"""Deterministic M4-A/B/C tests for sampled A-share reconciliation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from turtle_value_engine.backtest import MarketBar, PriceBasis
from turtle_value_engine.historical import (
    BAOSTOCK_PRICE_ADAPTER_ID,
    BAOSTOCK_PRICE_SCHEMA_VERSION,
    BaoStockAsharePriceReferenceAdapter,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionRequestV1,
    HistoricalAcquisitionService,
    HistoricalArtifactStore,
    HistoricalIngestionCompiler,
    HistoricalReconciliationSampleSpec,
    HistoricalSourceSchemaError,
    HistoricalSourceSpecV1,
    HistoricalTargetScope,
    MappingCredentialResolver,
    NetworkResponse,
    RawBlobStore,
    ReconciliationSourceIndependenceError,
    ShardArtifactKind,
    assert_reconciliation_source_independence,
    reconcile_sampled_market_bars,
    reconcile_sampled_prices,
)


class FakeBaoStockResult:
    def __init__(self, fields: list[str], rows: list[list[object]]) -> None:
        self.error_code = "0"
        self.error_msg = ""
        self.fields = fields
        self.rows = rows


PRICE_FIELDS = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adjustflag",
]


class FakeBaoStockPriceClient:
    def __init__(self, rows_by_code: dict[str, list[list[object]]] | None = None) -> None:
        self.rows_by_code = rows_by_code or {
            "sh.600000": [
                ["2020-01-02", "sh.600000", "10", "11", "9", "10.10", "100", "1000", "3"]
            ]
        }
        self.calls: list[tuple[object, ...]] = []

    def login(self) -> FakeBaoStockResult:
        self.calls.append(("login",))
        return FakeBaoStockResult([], [])

    def logout(self) -> FakeBaoStockResult:
        self.calls.append(("logout",))
        return FakeBaoStockResult([], [])

    def query_history_k_data_plus(
        self,
        *,
        code: str,
        fields: str,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> FakeBaoStockResult:
        self.calls.append((code, fields, start_date, end_date, frequency, adjustflag))
        return FakeBaoStockResult(PRICE_FIELDS, self.rows_by_code.get(code, []))


class FakeTransport:
    def request(self, method: str, url: str, **kwargs: object) -> NetworkResponse:
        del method, kwargs
        return NetworkResponse(200, {"content-type": "application/json"}, b"", url)


def _target() -> HistoricalTargetScope:
    return HistoricalTargetScope(
        target_id="m4-a-fixed",
        target_name="M4 fixed A sample",
        universe_id="private-a",
        markets=["A"],
        listing_ids=["SH600000"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=["PRICES"],
        calendar_ids={"SH600000": "A:SSE"},
        listing_markets={"SH600000": "A"},
        licensing_scope="private local research",
    )


def _source() -> HistoricalSourceSpecV1:
    return HistoricalSourceSpecV1(
        source_id="baostock-price-source",
        source_kind="PRICES",
        adapter_id=BAOSTOCK_PRICE_ADAPTER_ID,
        provider_id="baostock",
        source_name="BaoStock sampled price reference",
        source_uri="https://www.baostock.com",
        authority="DOCUMENTED_PROVIDER",
        licensing_constraints="private local research only",
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2020, 1, 3),
        coverage_listing_ids=["SH600000"],
    )


def _request(**parameter_updates: object) -> HistoricalAcquisitionRequestV1:
    parameters = {
        "source_uri": "https://www.baostock.com",
        "frequency": "d",
        "adjustflag": "3",
        "price_basis": "UNADJUSTED",
        "currency": "CNY",
    }
    parameters.update(parameter_updates)
    return HistoricalAcquisitionRequestV1(
        request_id="baostock-price-request",
        source_id="baostock-price-source",
        adapter_id=BAOSTOCK_PRICE_ADAPTER_ID,
        source_kind="PRICES",
        artifact_kind="MARKET_BAR",
        schema_version=BAOSTOCK_PRICE_SCHEMA_VERSION,
        listing_ids=["SH600000"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        parameters=parameters,
        coverage_evidence_basis="TRADING_SESSIONS",
    )


def _plan(request: HistoricalAcquisitionRequestV1) -> HistoricalAcquisitionPlanV1:
    return HistoricalAcquisitionPlanV1(
        plan_id="m4-price-plan",
        plan_version="1",
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        target=_target(),
        sources=[_source()],
        requests=[request],
    )


def _acquire(
    tmp_path: Path,
    *,
    client: FakeBaoStockPriceClient | None = None,
    request: HistoricalAcquisitionRequestV1 | None = None,
):
    raw_store = RawBlobStore(tmp_path / "raw")
    request = request or _request()
    result = HistoricalAcquisitionService(
        {BAOSTOCK_PRICE_ADAPTER_ID: BaoStockAsharePriceReferenceAdapter(
            lambda: client or FakeBaoStockPriceClient()
        )},
        transport=FakeTransport(),
        credentials=MappingCredentialResolver({}),
    ).acquire(_plan(request), raw_store=raw_store, network_allowed=True)
    return result, raw_store


def _sample(
    *,
    canonical_provider_id: str | None = "hithink-financial-api",
    canonical_upstream_id: str | None = "hithink-financial-api",
    independent_provider_id: str | None = "baostock",
    independent_upstream_id: str | None = "baostock",
    canonical_price_basis: PriceBasis = PriceBasis.UNADJUSTED,
    independent_price_basis: PriceBasis = PriceBasis.UNADJUSTED,
) -> HistoricalReconciliationSampleSpec:
    return HistoricalReconciliationSampleSpec.build(
        sample_id="m4-sh600000-close",
        target_id="m4-a-fixed",
        listing_ids=["SH600000"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        canonical_source_id="hithink-price-source",
        canonical_adapter_id="hithink-market-dumps",
        canonical_provider_id=canonical_provider_id,
        canonical_upstream_id=canonical_upstream_id,
        independent_source_id="baostock-price-source",
        independent_adapter_id=BAOSTOCK_PRICE_ADAPTER_ID,
        independent_provider_id=independent_provider_id,
        independent_upstream_id=independent_upstream_id,
        currency="CNY",
        canonical_price_basis=canonical_price_basis,
        independent_price_basis=independent_price_basis,
        absolute_tolerance=0.02,
        relative_tolerance=0.001,
        selection_rationale="Reuse the fixed SH600000 M3/Hithink bounded sample.",
    )


def _bar(day: date, close: float, *, source_hash: str = "0" * 64) -> MarketBar:
    return MarketBar(
        bar_id=f"SH600000:{day.isoformat()}",
        listing_id="SH600000",
        market="A",
        trading_date=day,
        close=close,
        currency="CNY",
        source_hash=source_hash,
    )


def test_baostock_price_reference_acquires_and_replays_from_private_cas(tmp_path: Path):
    result, raw_store = _acquire(tmp_path)
    receipt = result.batch.receipts[0]
    envelope = raw_store.read(receipt.sha256)
    assert b"query_history_k_data_plus" in envelope
    assert b'"adjustflag":"3"' in envelope

    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    ).compile_with_replay_check(result.batch)
    shard = next(
        item for item in manifest.shards if item.artifact_kind is ShardArtifactKind.MARKET_BAR
    )
    rows = artifact_store.read_shard(shard, model_type=MarketBar)
    assert rows[0].listing_id == "SH600000"
    assert rows[0].close == pytest.approx(10.10)
    assert rows[0].price_basis is PriceBasis.UNADJUSTED


def test_baostock_price_reference_rejects_schema_drift():
    class DriftClient(FakeBaoStockPriceClient):
        def query_history_k_data_plus(self, **kwargs: str) -> FakeBaoStockResult:
            del kwargs
            return FakeBaoStockResult(PRICE_FIELDS + ["unexpected"], [])

    with pytest.raises(HistoricalSourceSchemaError, match="fields changed"):
        BaoStockAsharePriceReferenceAdapter(lambda: DriftClient()).acquire(
            _request(), transport=FakeTransport(), credentials=MappingCredentialResolver({})
        )


def test_baostock_price_reference_rejects_adjusted_mode_and_h_identity():
    with pytest.raises(HistoricalSourceSchemaError, match="adjustflag"):
        BaoStockAsharePriceReferenceAdapter(lambda: FakeBaoStockPriceClient()).acquire(
            _request(adjustflag="1"),
            transport=FakeTransport(),
            credentials=MappingCredentialResolver({}),
        )
    h_request = _request().model_copy(update={"listing_ids": ["HK00001"]})
    with pytest.raises(HistoricalSourceSchemaError, match="A-share"):
        BaoStockAsharePriceReferenceAdapter(lambda: FakeBaoStockPriceClient()).acquire(
            h_request, transport=FakeTransport(), credentials=MappingCredentialResolver({})
        )


def test_baostock_price_reference_rejects_duplicate_and_out_of_scope_rows(tmp_path: Path):
    duplicate = [
        ["2020-01-02", "sh.600000", "10", "11", "9", "10.10", "100", "1000", "3"],
        ["2020-01-02", "sh.600000", "10", "11", "9", "10.11", "100", "1000", "3"],
    ]
    with pytest.raises(HistoricalSourceSchemaError, match="duplicate"):
        _acquire(tmp_path / "duplicate", client=FakeBaoStockPriceClient({"sh.600000": duplicate}))

    out_of_scope = [["2020-01-04", "sh.600000", "10", "11", "9", "10.10", "100", "1000", "3"]]
    with pytest.raises(HistoricalSourceSchemaError, match="outside"):
        _acquire(tmp_path / "scope", client=FakeBaoStockPriceClient({"sh.600000": out_of_scope}))


def test_source_ids_do_not_prove_independence_and_unresolved_upstream_blocks():
    with pytest.raises(
        ReconciliationSourceIndependenceError,
        match="RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN",
    ):
        assert_reconciliation_source_independence(
            canonical_source_id="source-a",
            canonical_adapter_id="adapter-a",
            canonical_provider_id="same-provider",
            canonical_upstream_id="same-upstream",
            independent_source_id="source-b",
            independent_adapter_id="adapter-b",
            independent_provider_id="same-provider",
            independent_upstream_id="same-upstream",
        )
    with pytest.raises(
        ReconciliationSourceIndependenceError,
        match="RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN",
    ):
        assert_reconciliation_source_independence(
            canonical_source_id="source-a",
            canonical_adapter_id="adapter-a",
            canonical_provider_id="provider-a",
            independent_source_id="source-b",
            independent_adapter_id="adapter-b",
            independent_provider_id="provider-b",
        )


def test_sampled_reconciliation_pass_fail_and_missing_union():
    sample = _sample()
    day_one = date(2020, 1, 2)
    day_two = date(2020, 1, 3)
    passed = reconcile_sampled_prices(
        sample=sample,
        canonical_values={("SH600000", day_one): 10.10},
        independent_values={("SH600000", day_one): 10.11},
    )
    assert passed.status.value == "PASS"
    assert passed.comparisons[0].status.value == "PASS"

    failed = reconcile_sampled_prices(
        sample=sample,
        canonical_values={("SH600000", day_one): 10.10},
        independent_values={("SH600000", day_one): 10.50},
    )
    assert failed.status.value == "FAIL"

    partial = reconcile_sampled_prices(
        sample=sample,
        canonical_values={("SH600000", day_one): 10.10},
        independent_values={("SH600000", day_two): 10.20},
    )
    assert partial.status.value == "PARTIAL"
    assert len(partial.comparisons) == 2
    assert all(item.status.value == "MISSING" for item in partial.comparisons)


def test_sampled_market_bar_reconciliation_rejects_adjusted_basis_and_is_stable():
    sample = _sample()
    report = reconcile_sampled_market_bars(
        sample=sample,
        canonical_bars=[_bar(date(2020, 1, 2), 10.10)],
        independent_bars=[_bar(date(2020, 1, 2), 10.11)],
    )
    repeated = reconcile_sampled_market_bars(
        sample=sample,
        canonical_bars=[_bar(date(2020, 1, 2), 10.10)],
        independent_bars=[_bar(date(2020, 1, 2), 10.11)],
    )
    assert report.content_sha256 == repeated.content_sha256

    adjusted_sample = _sample(independent_price_basis=PriceBasis.ADJUSTED)
    with pytest.raises(ValueError, match="unadjusted"):
        reconcile_sampled_prices(
            sample=adjusted_sample,
            canonical_values={("SH600000", date(2020, 1, 2)): 10.10},
            independent_values={("SH600000", date(2020, 1, 2)): 10.11},
        )
