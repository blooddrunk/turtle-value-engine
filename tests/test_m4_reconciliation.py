"""Deterministic M4-A/B/C tests for sampled A-share reconciliation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from turtle_value_engine.backtest import MarketBar, PriceBasis
from turtle_value_engine.cli import main
from turtle_value_engine.historical import (
    BAOSTOCK_PRICE_ADAPTER_ID,
    BAOSTOCK_PRICE_SCHEMA_VERSION,
    BaoStockAsharePriceReferenceAdapter,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionRequestV1,
    HistoricalAcquisitionService,
    HistoricalArtifactReconciliationError,
    HistoricalArtifactStore,
    HistoricalDatasetManifest,
    HistoricalIngestionCompiler,
    HistoricalReconciliationReport,
    HistoricalReconciliationSampleSpec,
    HistoricalSourceDescriptor,
    HistoricalSourceSchemaError,
    HistoricalSourceSpecV1,
    HistoricalTargetScope,
    MappingCredentialResolver,
    NetworkResponse,
    RawBlobStore,
    ReconciliationSourceIndependenceError,
    ShardArtifactKind,
    assert_reconciliation_source_independence,
    build_coverage_report,
    reconcile_sampled_market_bars,
    reconcile_sampled_market_bars_from_artifacts,
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
    canonical_source_id: str = "hithink-price-source",
    independent_source_id: str = "baostock-price-source",
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
        canonical_source_id=canonical_source_id,
        canonical_adapter_id="hithink-market-dumps",
        canonical_provider_id=canonical_provider_id,
        canonical_upstream_id=canonical_upstream_id,
        independent_source_id=independent_source_id,
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


def _artifact_manifest(
    tmp_path: Path,
    *,
    source_id: str,
    adapter_id: str,
    provider_id: str,
    upstream_id: str | None,
    rows: list[MarketBar],
    directory_name: str,
) -> tuple[HistoricalDatasetManifest, HistoricalArtifactStore]:
    store = HistoricalArtifactStore(tmp_path / directory_name)
    target = _target()
    descriptor = HistoricalSourceDescriptor(
        source_id=source_id,
        source_kind="PRICES",
        adapter_id=adapter_id,
        upstream_id=upstream_id,
        provider_id=provider_id,
        source_name=f"{provider_id} frozen M4 price source",
        authority="DOCUMENTED_PROVIDER",
        retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        coverage_start=target.start_date,
        coverage_end=target.end_date,
        coverage_listing_ids=list(target.listing_ids),
        content_sha256=hashlib.sha256(source_id.encode()).hexdigest(),
        licensing_constraints="private deterministic test fixture",
    )
    reference = store.freeze_shard(
        shard_id=f"{source_id}-market-bars",
        artifact_kind=ShardArtifactKind.MARKET_BAR,
        schema_version="market-bar-v1",
        date_start=min(row.trading_date for row in rows),
        date_end=max(row.trading_date for row in rows),
        listing_scope=sorted({row.listing_id for row in rows}),
        source_artifact_id=source_id,
        rows=rows,
    )
    coverage = {
        "SH600000": [date(2020, 1, 2), date(2020, 1, 3)],
    }
    manifest = HistoricalDatasetManifest.build(
        dataset_id=f"dataset-{source_id}",
        dataset_version="1",
        target=target,
        source_descriptors=[descriptor],
        shards=[reference],
        coverage_reports=[
            build_coverage_report(
                target=target,
                source_kind="PRICES",
                expected_sessions_by_listing=coverage,
                observed_sessions_by_listing=coverage,
                source_artifact_ids_by_listing={"SH600000": [source_id]},
                report_id=f"coverage-{source_id}",
                evidence_basis="TRADING_SESSIONS",
            )
        ],
    )
    return manifest, store


def _artifact_inputs(
    tmp_path: Path,
    *,
    canonical_rows: list[MarketBar] | None = None,
    independent_rows: list[MarketBar] | None = None,
    independent_provider_id: str = "baostock",
    independent_upstream_id: str | None = "baostock",
):
    canonical_rows = canonical_rows or [
        _bar(date(2020, 1, 2), 10.10),
        _bar(date(2020, 1, 3), 10.20),
    ]
    independent_rows = independent_rows or [
        _bar(date(2020, 1, 2), 10.11),
        _bar(date(2020, 1, 3), 10.21),
    ]
    canonical = _artifact_manifest(
        tmp_path,
        source_id="hithink-price-source",
        adapter_id="hithink-market-dumps",
        provider_id="hithink-financial-api",
        upstream_id="hithink-financial-api",
        rows=canonical_rows,
        directory_name="canonical-artifacts",
    )
    independent = _artifact_manifest(
        tmp_path,
        source_id="baostock-price-source",
        adapter_id=BAOSTOCK_PRICE_ADAPTER_ID,
        provider_id=independent_provider_id,
        upstream_id=independent_upstream_id,
        rows=independent_rows,
        directory_name="independent-artifacts",
    )
    return canonical, independent


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


def test_artifact_backed_reconciliation_reads_scope_and_persists_existing_report(
    tmp_path: Path,
):
    day_one = date(2020, 1, 2)
    day_two = date(2020, 1, 3)
    canonical, independent = _artifact_inputs(
        tmp_path,
        canonical_rows=[
            _bar(day_one, 10.10),
            _bar(day_two, 10.20),
            _bar(date(2020, 1, 4), 99.0),
        ],
        independent_rows=[
            _bar(day_one, 10.11),
            _bar(day_two, 10.21),
        ],
    )
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    source_bytes_before = [
        path.read_bytes() for path in canonical_store.root.rglob("*.jsonl")
    ] + [path.read_bytes() for path in independent_store.root.rglob("*.jsonl")]
    report_store = HistoricalArtifactStore(tmp_path / "reports")

    report = reconcile_sampled_market_bars_from_artifacts(
        sample=_sample(),
        canonical_manifest=canonical_manifest,
        canonical_store=canonical_store,
        independent_manifest=independent_manifest,
        independent_store=independent_store,
        report_store=report_store,
    )

    assert report.status.value == "PASS"
    assert [item.comparison_id for item in report.comparisons] == [
        f"SH600000:{day_one.isoformat()}",
        f"SH600000:{day_two.isoformat()}",
    ]
    persisted = sorted(report_store.root.rglob("*.json"))
    assert len(persisted) == 1
    persisted_report = HistoricalReconciliationReport.model_validate(
        json.loads(persisted[0].read_text(encoding="utf-8"))
    )
    assert persisted_report == report
    source_bytes_after = [
        path.read_bytes() for path in canonical_store.root.rglob("*.jsonl")
    ] + [path.read_bytes() for path in independent_store.root.rglob("*.jsonl")]
    assert source_bytes_after == source_bytes_before


@pytest.mark.parametrize(
    ("sample_update", "message"),
    [
        ({"independent_source_id": "missing-source"}, "exactly one declared source"),
        ({"independent_provider_id": "wrong-provider"}, "provider identity"),
        ({"independent_upstream_id": "wrong-upstream"}, "upstream identity"),
    ],
)
def test_artifact_backed_reconciliation_rejects_identity_mismatch(
    tmp_path: Path,
    sample_update: dict[str, str],
    message: str,
):
    canonical, independent = _artifact_inputs(tmp_path)
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    sample = _sample(**sample_update)
    with pytest.raises(HistoricalArtifactReconciliationError, match=message):
        reconcile_sampled_market_bars_from_artifacts(
            sample=sample,
            canonical_manifest=canonical_manifest,
            canonical_store=canonical_store,
            independent_manifest=independent_manifest,
            independent_store=independent_store,
        )


def test_artifact_backed_reconciliation_rejects_unresolved_upstream(tmp_path: Path):
    canonical, independent = _artifact_inputs(tmp_path, independent_upstream_id=None)
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    sample = _sample(independent_upstream_id=None)
    with pytest.raises(
        ReconciliationSourceIndependenceError,
        match="RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN",
    ):
        reconcile_sampled_market_bars_from_artifacts(
            sample=sample,
            canonical_manifest=canonical_manifest,
            canonical_store=canonical_store,
            independent_manifest=independent_manifest,
            independent_store=independent_store,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("price_basis", PriceBasis.ADJUSTED, "ADJUSTED"),
        ("currency", "HKD", "A-share CNY"),
    ],
)
def test_artifact_backed_reconciliation_rejects_adjusted_or_non_cny_rows(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
):
    bad_bar = _bar(date(2020, 1, 2), 10.11).model_copy(update={field: value})
    canonical, independent = _artifact_inputs(
        tmp_path,
        independent_rows=[bad_bar],
    )
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    with pytest.raises(ValueError, match=message):
        reconcile_sampled_market_bars_from_artifacts(
            sample=_sample(),
            canonical_manifest=canonical_manifest,
            canonical_store=canonical_store,
            independent_manifest=independent_manifest,
            independent_store=independent_store,
        )


def test_artifact_backed_reconciliation_keeps_missing_sessions_partial(tmp_path: Path):
    canonical, independent = _artifact_inputs(
        tmp_path,
        canonical_rows=[_bar(date(2020, 1, 2), 10.10), _bar(date(2020, 1, 3), 10.20)],
        independent_rows=[_bar(date(2020, 1, 2), 10.11)],
    )
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    report = reconcile_sampled_market_bars_from_artifacts(
        sample=_sample(),
        canonical_manifest=canonical_manifest,
        canonical_store=canonical_store,
        independent_manifest=independent_manifest,
        independent_store=independent_store,
    )
    assert report.status.value == "PARTIAL"
    missing = next(item for item in report.comparisons if item.observation_date == date(2020, 1, 3))
    assert missing.status.value == "MISSING"


@pytest.mark.parametrize(
    ("independent_close", "expected"),
    [(10.12, "PASS"), (10.121, "FAIL")],
)
def test_artifact_backed_reconciliation_honors_tolerance_boundary(
    tmp_path: Path,
    independent_close: float,
    expected: str,
):
    canonical, independent = _artifact_inputs(
        tmp_path,
        canonical_rows=[_bar(date(2020, 1, 2), 10.10)],
        independent_rows=[_bar(date(2020, 1, 2), independent_close)],
    )
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    report = reconcile_sampled_market_bars_from_artifacts(
        sample=_sample(),
        canonical_manifest=canonical_manifest,
        canonical_store=canonical_store,
        independent_manifest=independent_manifest,
        independent_store=independent_store,
    )
    assert report.status.value == expected


def test_artifact_backed_reconciliation_replay_hash_is_stable(tmp_path: Path):
    canonical, independent = _artifact_inputs(tmp_path)
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    first = reconcile_sampled_market_bars_from_artifacts(
        sample=_sample(),
        canonical_manifest=canonical_manifest,
        canonical_store=canonical_store,
        independent_manifest=independent_manifest,
        independent_store=independent_store,
    )
    second = reconcile_sampled_market_bars_from_artifacts(
        sample=_sample(),
        canonical_manifest=canonical_manifest,
        canonical_store=canonical_store,
        independent_manifest=independent_manifest,
        independent_store=independent_store,
    )
    assert first.content_sha256 == second.content_sha256


def test_artifact_backed_reconciliation_cli_is_additive_and_offline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    canonical, independent = _artifact_inputs(tmp_path)
    canonical_manifest, canonical_store = canonical
    independent_manifest, independent_store = independent
    sample = _sample()
    sample_path = tmp_path / "sample.json"
    canonical_manifest_path = tmp_path / "canonical-manifest.json"
    independent_manifest_path = tmp_path / "independent-manifest.json"
    output_path = tmp_path / "report.json"
    for path, model in (
        (sample_path, sample),
        (canonical_manifest_path, canonical_manifest),
        (independent_manifest_path, independent_manifest),
    ):
        path.write_text(
            json.dumps(model.model_dump(mode="json", warnings=False)),
            encoding="utf-8",
        )

    assert main(
        [
            "dataset",
            "reconcile-artifacts",
            "--sample",
            str(sample_path),
            "--canonical-manifest",
            str(canonical_manifest_path),
            "--canonical-store",
            str(canonical_store.root),
            "--independent-manifest",
            str(independent_manifest_path),
            "--independent-store",
            str(independent_store.root),
            "--output",
            str(output_path),
        ]
    ) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["contract"] == (
        "historical_reconciliation_report_v1"
    )
