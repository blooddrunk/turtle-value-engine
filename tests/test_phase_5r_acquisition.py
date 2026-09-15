"""Offline acceptance tests for the Phase 5R-A acquisition boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from turtle_value_engine.backtest import ListingLifecycle, Market, MarketBar, PriceBasis
from turtle_value_engine.cli import main
from turtle_value_engine.historical import (
    AccountEntitlement,
    ConfiguredHttpSourceAdapter,
    CoverageClaim,
    CoverageEvidenceBasis,
    CoverageEvidenceStatus,
    CredentialReferenceV1,
    CredentialUnavailableError,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionRequestV1,
    HistoricalAcquisitionService,
    HistoricalArtifactStore,
    HistoricalFilingDocumentRecord,
    HistoricalIngestionCompiler,
    HistoricalIngestionError,
    HistoricalReconciliationReport,
    HistoricalSourceDescriptor,
    HistoricalSourceKind,
    HistoricalSourceSchemaError,
    HistoricalSourceSpecV1,
    HistoricalTargetScope,
    HithinkMarketDumpAdapter,
    MappingCredentialResolver,
    NetworkDisabledError,
    NetworkResponse,
    OfficialFilingDocumentAdapter,
    ProbeStatus,
    RawAcquisitionBatchManifestV1,
    RawArtifactReceiptV1,
    RawBlobError,
    RawBlobStore,
    RawDownload,
    ReconciliationComparison,
    ResilientNetworkTransport,
    ShardArtifactKind,
    SourceProbeReportV1,
    build_coverage_report,
    build_readiness_report,
)
from turtle_value_engine.historical.compiler import _production_scope_blockers
from turtle_value_engine.providers import (
    FilingDescriptor,
    FilingDocumentDownloader,
    FilingDocumentSourceClient,
    FilingDownloadPayload,
    FilingMarket,
    FilingRecord,
    FilingSource,
    filing_id_for,
)

HASH = "0" * 64


class FakeTransport:
    def __init__(self, responses: list[NetworkResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, url, *, headers=None, timeout_seconds=30.0):
        self.calls.append((method, url, dict(headers or {})))
        return self.responses.pop(0)


def _target(*, include_h: bool = False) -> HistoricalTargetScope:
    listings = ["A1", "H1"] if include_h else ["A1"]
    markets = ["A", "H"] if include_h else ["A"]
    listing_markets = {"A1": "A"}
    calendars = {"A1": "A:SSE"}
    if include_h:
        listing_markets["H1"] = "H"
        calendars["H1"] = "H:HKEX"
    return HistoricalTargetScope(
        target_id="target",
        target_name="private target",
        universe_id="private-universe",
        markets=markets,
        listing_ids=listings,
        start_date=date(2020, 1, 1),
        end_date=date(2022, 1, 2),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=["PRICES"],
        calendar_ids=calendars,
        listing_markets=listing_markets,
        licensing_scope="private owner research only",
    )


def _source(*, include_h: bool = False, adapter_id: str = "http-json"):
    listings = ["A1", "H1"] if include_h else ["A1"]
    return HistoricalSourceSpecV1(
        source_id="prices-source",
        source_kind="PRICES",
        adapter_id=adapter_id,
        provider_id="documented-test-source",
        source_name="documented test source",
        source_uri="https://source.example.test/history",
        authority="DOCUMENTED_PROVIDER",
        license_status="RESTRICTED_INTERNAL",
        licensing_constraints="private local cache only",
        license_evidence_uri="https://source.example.test/terms",
        license_evidence_sha256="1" * 64,
        access_grant_reference="personal-account-grant",
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2022, 1, 2),
        coverage_listing_ids=listings,
    )


def _request(*, include_h: bool = False, adapter_id: str = "http-json"):
    listings = ["A1", "H1"] if include_h else ["A1"]
    return HistoricalAcquisitionRequestV1(
        request_id="prices-request",
        source_id="prices-source",
        adapter_id=adapter_id,
        source_kind="PRICES",
        artifact_kind="MARKET_BAR",
        schema_version="market-bar-v1",
        listing_ids=listings,
        start_date=date(2020, 1, 1),
        end_date=date(2022, 1, 2),
        parameters={"source_uri": "https://source.example.test/history"},
        coverage_evidence_basis="TRADING_SESSIONS",
    )


def _plan(*, include_h: bool = False, adapter_id: str = "http-json"):
    return HistoricalAcquisitionPlanV1(
        plan_id="plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=_target(include_h=include_h),
        sources=[_source(include_h=include_h, adapter_id=adapter_id)],
        requests=[_request(include_h=include_h, adapter_id=adapter_id)],
    )


def _market_bar_body() -> bytes:
    row = MarketBar(
        bar_id="A1:2020-01-02",
        listing_id="A1",
        market="A",
        trading_date=date(2020, 1, 2),
        close=10.0,
        currency="CNY",
        source_hash=HASH,
    )
    return json.dumps([row.model_dump(mode="json")], separators=(",", ":")).encode()


def test_network_is_denied_before_transport_is_touched():
    transport = FakeTransport([])
    with pytest.raises(NetworkDisabledError, match="--network=allow"):
        HistoricalAcquisitionService(
            {"http-json": ConfiguredHttpSourceAdapter()}, transport=transport
        ).probe(_plan(), network_allowed=False)
    assert transport.calls == []


def test_default_live_transport_requires_environment_credential_before_network(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("the live transport must not be touched")

    monkeypatch.setattr("turtle_value_engine.historical.acquisition.urlopen", fail_if_called)
    with pytest.raises(NetworkDisabledError, match="ENVIRONMENT credential"):
        HistoricalAcquisitionService().probe(_plan(), network_allowed=True)


def test_default_live_transport_rejects_injected_resolver_for_environment_reference():
    reference = CredentialReferenceV1(
        reference_id="env-source-key",
        kind="ENVIRONMENT",
        name="TVE_SOURCE_KEY",
    )
    request = _request().model_copy(update={"credential_ref": reference})
    plan = _plan().model_copy(
        update={"requests": [request], "credential_references": [reference]}
    )
    with pytest.raises(CredentialUnavailableError, match="EnvironmentCredentialResolver"):
        HistoricalAcquisitionService(
            credentials=MappingCredentialResolver({"env-source-key": "not-a-process-env-value"})
        ).probe(plan, network_allowed=True)


def test_default_live_transport_accepts_available_environment_reference(monkeypatch):
    reference = CredentialReferenceV1(
        reference_id="env-source-key",
        kind="ENVIRONMENT",
        name="TVE_SOURCE_KEY_FOR_TEST",
    )
    request = _request().model_copy(update={"credential_ref": reference})
    plan = _plan().model_copy(
        update={"requests": [request], "credential_references": [reference]}
    )
    monkeypatch.setenv("TVE_SOURCE_KEY_FOR_TEST", "test-only-value")
    HistoricalAcquisitionService()._require_network_authorization(
        plan,
        network_allowed=True,
    )


def test_default_live_transport_rejects_non_environment_credential_reference():
    reference = CredentialReferenceV1(
        reference_id="keyring-source-key",
        kind="KEYRING",
        service="tve",
        account="source",
    )
    request = _request().model_copy(update={"credential_ref": reference})
    plan = _plan().model_copy(
        update={"requests": [request], "credential_references": [reference]}
    )
    with pytest.raises(CredentialUnavailableError, match="only ENVIRONMENT"):
        HistoricalAcquisitionService().probe(plan, network_allowed=True)


def test_default_live_transport_checks_all_credential_reference_kinds(monkeypatch):
    environment_reference = CredentialReferenceV1(
        reference_id="env-source-key",
        kind="ENVIRONMENT",
        name="TVE_SOURCE_KEY_FOR_TEST",
    )
    keyring_reference = CredentialReferenceV1(
        reference_id="keyring-source-key",
        kind="KEYRING",
        service="tve",
        account="source",
    )
    first_source = _source().model_copy(update={"source_id": "first-source"})
    second_source = _source().model_copy(update={"source_id": "second-source"})
    first_request = _request().model_copy(
        update={
            "request_id": "first-request",
            "source_id": "first-source",
            "credential_ref": environment_reference,
        }
    )
    second_request = _request().model_copy(
        update={
            "request_id": "second-request",
            "source_id": "second-source",
            "credential_ref": keyring_reference,
        }
    )
    plan = _plan().model_copy(
        update={
            "sources": [first_source, second_source],
            "requests": [first_request, second_request],
            "credential_references": [environment_reference, keyring_reference],
        }
    )
    monkeypatch.setenv("TVE_SOURCE_KEY_FOR_TEST", "test-only-value")
    with pytest.raises(CredentialUnavailableError, match="only ENVIRONMENT"):
        HistoricalAcquisitionService().probe(plan, network_allowed=True)


def test_empty_adapter_mapping_is_not_replaced_by_defaults():
    with pytest.raises(HistoricalSourceSchemaError, match="no adapter is registered"):
        HistoricalAcquisitionService({}, transport=FakeTransport([])).probe(
            _plan(), network_allowed=True
        )


def test_historical_probe_cli_denies_network_by_default(tmp_path: Path, capsys):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(_plan().model_dump_json(), encoding="utf-8")

    assert main(["historical", "source", "probe", "--plan", str(plan_path)]) == 2
    assert "--network=allow" in capsys.readouterr().err


def test_plan_rejects_credential_reference_aliasing():
    declared = CredentialReferenceV1(
        reference_id="source-key",
        kind="ENVIRONMENT",
        name="TVE_SOURCE_KEY",
    )
    request = _request().model_copy(
        update={
            "credential_ref": declared.model_copy(update={"name": "OTHER_SOURCE_KEY"}),
        }
    )
    with pytest.raises(ValueError, match="differs from plan declaration"):
        HistoricalAcquisitionPlanV1(
            plan_id="credential-alias-plan",
            plan_version="1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            target=_target(),
            sources=[_source()],
            requests=[request],
            credential_references=[declared],
        )


def test_plan_rejects_source_coverage_outside_target():
    source = _source().model_copy(update={"coverage_listing_ids": ["A1", "A2"]})
    with pytest.raises(ValueError, match="outside target"):
        HistoricalAcquisitionPlanV1(
            plan_id="out-of-scope-source-plan",
            plan_version="1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            target=_target(),
            sources=[source],
            requests=[_request()],
        )


def test_batch_id_is_bound_to_receipt_identities():
    request = _request()
    receipt = RawArtifactReceiptV1.build(
        batch_id="batch-wrong",
        request=request,
        adapter_version="1",
        body=b"raw batch bytes",
        retrieval_started_at=datetime(2026, 1, 1, tzinfo=UTC),
        retrieval_finished_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        source_uri="https://source.example.test/history",
        http_status=200,
        content_type="application/json",
        response_headers={},
    )
    with pytest.raises(ValueError, match="batch_id does not match"):
        RawAcquisitionBatchManifestV1.build(
            batch_id="batch-wrong",
            plan=_plan(),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            receipts=[receipt],
        )


def test_raw_receipt_requires_stable_source_uri():
    with pytest.raises(ValueError, match="source_uri"):
        RawArtifactReceiptV1.build(
            batch_id="batch-missing-source-uri",
            request=_request(),
            adapter_version="1",
            body=b"raw batch bytes",
            retrieval_started_at=datetime(2026, 1, 1, tzinfo=UTC),
            retrieval_finished_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            source_uri=None,
            http_status=200,
            content_type="application/json",
            response_headers={},
        )


def test_resilient_transport_retries_only_bounded_transient_responses():
    responses = [
        NetworkResponse(429, {"Retry-After": "2"}, b"busy", "https://source.example.test"),
        NetworkResponse(200, {}, b"ok", "https://source.example.test"),
    ]
    sleeps: list[float] = []
    transport = ResilientNetworkTransport(
        FakeTransport(responses),
        max_attempts=3,
        base_delay_seconds=0.1,
        max_delay_seconds=5,
        per_host_min_interval_seconds=0,
        sleep=sleeps.append,
        random_value=lambda: 0,
    )
    assert transport.request("GET", "https://source.example.test").status_code == 200
    assert sleeps == [2.0]
    assert transport.throttling_observed is True


def test_raw_blob_store_keeps_failed_stream_in_quarantine(tmp_path: Path):
    store = RawBlobStore(tmp_path / "raw")
    digest = store.put(b"exact bytes")
    assert store.path_for(digest).relative_to(tmp_path / "raw").as_posix() == (
        f"sha256/{digest[:2]}/{digest}.blob"
    )
    assert store.put(b"exact bytes") == digest

    def incomplete():
        yield b"partial"
        raise OSError("connection ended")

    with pytest.raises(OSError):
        store.put_stream(incomplete(), quarantine_id="download-1")
    assert (tmp_path / "raw" / "quarantine" / "download-1.part").read_bytes() == b"partial"
    with pytest.raises(RawBlobError):
        store.put(b"wrong", expected_sha256=digest)


def test_raw_blob_store_rejects_symlinked_quarantine_partial(tmp_path: Path):
    store = RawBlobStore(tmp_path / "raw")
    quarantine = tmp_path / "raw" / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside.part"
    target.write_bytes(b"untouched")
    try:
        (quarantine / "unsafe.part").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(RawBlobError, match="quarantine partial path"):
        store.put_stream([b"must not overwrite"], quarantine_id="unsafe")
    assert target.read_bytes() == b"untouched"


def test_empty_event_result_is_not_complete_coverage():
    report = build_coverage_report(
        target=_target(),
        source_kind=HistoricalSourceKind.CORPORATE_ACTIONS,
        expected_sessions_by_listing={"A1": []},
        observed_sessions_by_listing={},
        source_artifact_ids_by_listing={"A1": ["actions-source"]},
        report_id="empty-actions",
        evidence_basis=CoverageEvidenceBasis.EVENT_INDEX,
    )
    assert report.records[0].status == CoverageClaim.UNKNOWN


def test_compiler_rebinds_receipt_terms_to_the_embedded_plan(tmp_path: Path):
    body = _market_bar_body()
    transport = FakeTransport(
        [NetworkResponse(200, {"Content-Type": "application/json"}, body, "https://source.test")]
    )
    plan = _plan()
    raw_store = RawBlobStore(tmp_path / "raw")
    acquired = HistoricalAcquisitionService(
        {"http-json": ConfiguredHttpSourceAdapter()}, transport=transport
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    tampered_receipt = acquired.batch.receipts[0].model_copy(
        update={"license_evidence_sha256": "2" * 64}
    )
    tampered_batch = RawAcquisitionBatchManifestV1.build(
        batch_id=acquired.batch.batch_id,
        plan=plan,
        created_at=acquired.batch.created_at,
        receipts=[tampered_receipt],
    )
    compiler = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
    )
    with pytest.raises(HistoricalIngestionError, match="license evidence mismatch"):
        compiler.compile(tampered_batch)


def test_empty_decoder_mapping_is_not_replaced_by_defaults(tmp_path: Path):
    compiler = HistoricalIngestionCompiler(
        raw_store=RawBlobStore(tmp_path / "raw"),
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
        decoders={},
    )
    assert compiler.decoders == {}


def test_private_acquisition_and_offline_compile_are_replayable(tmp_path: Path):
    body = _market_bar_body()
    transport = FakeTransport(
        [
            NetworkResponse(
                200,
                {"Content-Type": "application/json"},
                body,
                "https://source.example.test/history",
            )
        ]
    )
    plan = _plan()
    raw_store = RawBlobStore(tmp_path / "raw")
    result = HistoricalAcquisitionService(
        {"http-json": ConfiguredHttpSourceAdapter()}, transport=transport
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    assert result.readiness.readiness == "ACQUISITION_READY"
    assert result.batch.receipts[0].sha256 == hashlib.sha256(body).hexdigest()
    assert result.batch.receipts[0].model_dump_json().find("secret") == -1

    compiler = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=HistoricalArtifactStore(tmp_path / "artifacts"),
    )
    first = compiler.compile_with_replay_check(result.batch)
    second = compiler.compile(
        type(result.batch).model_validate(result.batch.model_dump(mode="json"))
    )
    assert first.content_sha256 == second.content_sha256
    assert [item.content_sha256 for item in first.shards] == [
        item.content_sha256 for item in second.shards
    ]


def test_acquisition_rejects_schema_drift_before_persisting_blob(tmp_path: Path):
    class SchemaDriftAdapter:
        adapter_id = "schema-drift"
        adapter_version = "1"

        def acquire(self, request, *, transport, credentials):
            response = NetworkResponse(
                200,
                {"Content-Type": "application/json"},
                b"payload",
                "https://source.example.test/history",
            )
            return [
                RawDownload(
                    body=response.body,
                    response=response,
                    source_uri=response.url,
                    schema_version="unrecognized-schema",
                )
            ]

        def probe(self, request, *, transport, credentials, plan_id, clock):
            raise AssertionError("probe is not part of this test")

    plan = _plan(adapter_id="schema-drift")
    raw_store = RawBlobStore(tmp_path / "raw")
    with pytest.raises(HistoricalSourceSchemaError, match="incompatible schema version"):
        HistoricalAcquisitionService(
            {"schema-drift": SchemaDriftAdapter()},
            transport=FakeTransport([]),
        ).acquire(plan, raw_store=raw_store, network_allowed=True)
    assert list((tmp_path / "raw").rglob("*.blob")) == []


def test_acquisition_rejects_missing_source_uri_before_persisting_blob(tmp_path: Path):
    class MissingSourceUriAdapter:
        adapter_id = "missing-source-uri"
        adapter_version = "1"

        def acquire(self, request, *, transport, credentials):
            response = NetworkResponse(
                200,
                {"Content-Type": "application/json"},
                b"payload",
                "https://source.example.test/history",
            )
            return [
                RawDownload(
                    body=response.body,
                    response=response,
                    source_uri=None,
                    schema_version=request.schema_version,
                )
            ]

        def probe(self, request, *, transport, credentials, plan_id, clock):
            raise AssertionError("probe is not part of this test")

    source = _source(adapter_id="missing-source-uri").model_copy(
        update={"source_uri": "https://source.example.test/history"}
    )
    request = _request(adapter_id="missing-source-uri")
    plan = _plan(adapter_id="missing-source-uri").model_copy(
        update={"sources": [source], "requests": [request]}
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    with pytest.raises(HistoricalSourceSchemaError, match="stable source URI"):
        HistoricalAcquisitionService(
            {"missing-source-uri": MissingSourceUriAdapter()},
            transport=FakeTransport([]),
        ).acquire(plan, raw_store=raw_store, network_allowed=True)
    assert list((tmp_path / "raw").rglob("*.blob")) == []


def test_compiler_filters_full_market_rows_to_declared_request_scope(tmp_path: Path):
    in_scope = MarketBar(
        bar_id="A1:2020-01-02",
        listing_id="A1",
        market="A",
        trading_date=date(2020, 1, 2),
        close=10.0,
        currency="CNY",
        source_hash=HASH,
    )
    outside_scope = in_scope.model_copy(
        update={"bar_id": "A2:2020-01-02", "listing_id": "A2"}
    )
    body = json.dumps(
        [
            in_scope.model_dump(mode="json"),
            outside_scope.model_dump(mode="json"),
        ],
        separators=(",", ":"),
    ).encode()
    transport = FakeTransport(
        [NetworkResponse(200, {"Content-Type": "application/json"}, body, "https://source.test")]
    )
    plan = _plan()
    raw_store = RawBlobStore(tmp_path / "raw")
    acquired = HistoricalAcquisitionService(
        {"http-json": ConfiguredHttpSourceAdapter()}, transport=transport
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    ).compile(acquired.batch)
    assert len(manifest.shards) == 1
    rows = artifact_store.read_shard(manifest.shards[0], model_type=MarketBar)
    assert [row.listing_id for row in rows] == ["A1"]
    assert rows[0].bar_id == in_scope.bar_id
    assert rows[0].source_hash == acquired.batch.source_aggregate_hash("prices-source")


def test_compiler_keeps_only_overlapping_lifecycle_intervals(tmp_path: Path):
    overlapping = ListingLifecycle(
        listing_id="A1",
        company_id="company-1",
        market="A",
        currency="CNY",
        listing_date=date(2019, 1, 1),
        delisting_date=date(2021, 1, 1),
        terminal_status="DELISTED",
        trading_calendar="A:SSE",
        timezone="Asia/Shanghai",
        source_hash=HASH,
    )
    future = ListingLifecycle(
        listing_id="A1",
        company_id="company-1",
        market="A",
        currency="CNY",
        listing_date=date(2023, 1, 1),
        terminal_status="ACTIVE",
        trading_calendar="A:SSE",
        timezone="Asia/Shanghai",
        source_hash=HASH,
    )
    source_payload = _source().model_dump(mode="python")
    source_payload["source_kind"] = HistoricalSourceKind.LISTING_LIFECYCLE
    source = HistoricalSourceSpecV1.model_validate(source_payload)
    request_payload = _request().model_dump(mode="python")
    request_payload.update(
        {
            "source_id": source.source_id,
            "source_kind": HistoricalSourceKind.LISTING_LIFECYCLE,
            "artifact_kind": "LISTING_LIFECYCLE",
            "schema_version": "listing-lifecycle-v1",
            "coverage_evidence_basis": CoverageEvidenceBasis.LIFECYCLE_INDEX,
        }
    )
    request = HistoricalAcquisitionRequestV1.model_validate(request_payload)
    plan = HistoricalAcquisitionPlanV1(
        plan_id="lifecycle-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=_target(),
        sources=[source],
        requests=[request],
    )
    body = json.dumps(
        [overlapping.model_dump(mode="json"), future.model_dump(mode="json")],
        separators=(",", ":"),
    ).encode()
    transport = FakeTransport(
        [NetworkResponse(200, {"Content-Type": "application/json"}, body, "https://source.test")]
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    acquired = HistoricalAcquisitionService(
        {"http-json": ConfiguredHttpSourceAdapter()}, transport=transport
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    manifest = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    ).compile(acquired.batch)
    lifecycle_shards = [
        shard for shard in manifest.shards if shard.artifact_kind.value == "LISTING_LIFECYCLE"
    ]
    assert len(lifecycle_shards) == 1
    rows = artifact_store.read_shard(lifecycle_shards[0], model_type=ListingLifecycle)
    assert len(rows) == 1
    assert rows[0].listing_date == date(2019, 1, 1)


def test_official_filing_documents_compile_to_hash_and_locator_shard(tmp_path: Path):
    filing_url = "https://static.cninfo.com.cn/finalpage/2025-04-30/121000001.PDF"
    filing = FilingRecord(
        filing_id=filing_id_for(
            listing_id="SH600000",
            market=FilingMarket.A,
            source=FilingSource.CNINFO,
            source_document_id="cninfo-600000-2024-annual",
            url=filing_url,
        ),
        listing_id="SH600000",
        market=FilingMarket.A,
        source=FilingSource.CNINFO,
        title="2024 annual report",
        document_type="ANNUAL_REPORT",
        published_date=date(2025, 4, 30),
        url=filing_url,
        source_document_id="cninfo-600000-2024-annual",
        report_period="FY2024",
    )
    body = b"official filing bytes"
    client = FilingDocumentSourceClient(
        source=FilingSource.CNINFO,
        download=lambda _filing: FilingDownloadPayload(
            content=body,
            media_type="application/pdf",
        ),
    )
    downloader = FilingDocumentDownloader(
        {FilingSource.CNINFO: client},
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    target = HistoricalTargetScope(
        target_id="filing-target",
        target_name="filing target",
        universe_id="filing-universe",
        markets=[Market.A],
        listing_ids=["SH600000"],
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=[HistoricalSourceKind.FILINGS],
        calendar_ids={"SH600000": "A:SSE"},
        listing_markets={"SH600000": Market.A},
        licensing_scope="private filing research",
    )
    source = _source(adapter_id="official-filing-documents").model_copy(
        update={
            "source_id": "filing-source",
            "source_kind": HistoricalSourceKind.FILINGS,
            "provider_id": "official-filing",
            "source_name": "official filing source",
            "source_uri": "https://www.cninfo.com.cn",
            "coverage_listing_ids": ["SH600000"],
            "coverage_start": target.start_date,
            "coverage_end": target.end_date,
        }
    )
    request = _request(adapter_id="official-filing-documents").model_copy(
        update={
            "request_id": "filing-request",
            "source_id": source.source_id,
            "source_kind": HistoricalSourceKind.FILINGS,
            "artifact_kind": ShardArtifactKind.FILING_DOCUMENT,
            "schema_version": "filing-document-v1",
            "listing_ids": ["SH600000"],
            "start_date": target.start_date,
            "end_date": target.end_date,
            "parameters": {"filing_ids": [filing.filing_id]},
            "coverage_evidence_basis": CoverageEvidenceBasis.FILING_INDEX,
        }
    )
    plan = HistoricalAcquisitionPlanV1(
        plan_id="filing-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=target,
        sources=[source],
        requests=[request],
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    acquired = HistoricalAcquisitionService(
        {
            "official-filing-documents": OfficialFilingDocumentAdapter(
                downloader,
                {filing.filing_id: filing},
            )
        },
        transport=FakeTransport([]),
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
    ).acquire(plan, raw_store=raw_store, network_allowed=True)

    receipt = acquired.batch.receipts[0]
    assert receipt.artifact_role == "FILING_DOCUMENT"
    assert receipt.artifact_kind is None
    assert receipt.artifact_metadata["document_sha256"] == receipt.sha256
    assert receipt.artifact_metadata["final_url"] == filing_url

    artifact_store = HistoricalArtifactStore(tmp_path / "artifacts")
    compiler = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    )
    manifest = compiler.compile(acquired.batch)
    filing_shards = [
        item for item in manifest.shards if item.artifact_kind is ShardArtifactKind.FILING_DOCUMENT
    ]
    assert len(filing_shards) == 1
    rows = artifact_store.read_shard(
        filing_shards[0],
        model_type=HistoricalFilingDocumentRecord,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.filing_id == filing.filing_id
    assert row.document_hash == receipt.sha256
    assert row.document_locator == filing_url
    assert row.available_at == row.retrieved_at
    assert row.revision_identity == f"{filing.filing_id}:{receipt.sha256}"
    assert row.source_hash == acquired.batch.source_aggregate_hash(source.source_id)
    assert compiler.compile(acquired.batch).content_sha256 == manifest.content_sha256


def test_official_filing_discovery_callback_avoids_hand_assembled_ids(tmp_path: Path):
    filing_url = "https://static.cninfo.com.cn/finalpage/2025-04-30/121000002.PDF"
    descriptor = FilingDescriptor(
        title="2024 annual report",
        document_type="ANNUAL_REPORT",
        published_date=date(2025, 4, 30),
        url=filing_url,
        source_document_id="cninfo-discovered-2024-annual",
        report_period="FY2024",
    )
    queries = []

    def discover(query):
        queries.append(query)
        return [descriptor]

    client = FilingDocumentSourceClient(
        source=FilingSource.CNINFO,
        download=lambda _filing: FilingDownloadPayload(
            content=b"discovered official filing",
            media_type="application/pdf",
        ),
    )
    downloader = FilingDocumentDownloader(
        {FilingSource.CNINFO: client},
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    target = HistoricalTargetScope(
        target_id="discovered-filing-target",
        target_name="discovered filing target",
        universe_id="discovered-filing-universe",
        markets=[Market.A],
        listing_ids=["SH600000"],
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim="PARTIAL",
        required_source_kinds=[HistoricalSourceKind.FILINGS],
        calendar_ids={"SH600000": "A:SSE"},
        listing_markets={"SH600000": Market.A},
        licensing_scope="private filing research",
    )
    source = _source(adapter_id="official-filing-documents").model_copy(
        update={
            "source_id": "discovered-filing-source",
            "source_kind": HistoricalSourceKind.FILINGS,
            "provider_id": "official-filing-discovery",
            "source_name": "official filing discovery",
            "source_uri": "https://www.cninfo.com.cn",
            "coverage_listing_ids": ["SH600000"],
            "coverage_start": target.start_date,
            "coverage_end": target.end_date,
        }
    )
    request = _request(adapter_id="official-filing-documents").model_copy(
        update={
            "request_id": "discovered-filing-request",
            "source_id": source.source_id,
            "source_kind": HistoricalSourceKind.FILINGS,
            "artifact_kind": ShardArtifactKind.FILING_DOCUMENT,
            "schema_version": "filing-document-v1",
            "listing_ids": ["SH600000"],
            "start_date": target.start_date,
            "end_date": target.end_date,
            "parameters": {"source": "CNINFO", "document_type": "ANNUAL_REPORT"},
            "coverage_evidence_basis": CoverageEvidenceBasis.FILING_INDEX,
        }
    )
    plan = HistoricalAcquisitionPlanV1(
        plan_id="discovered-filing-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=target,
        sources=[source],
        requests=[request],
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    result = HistoricalAcquisitionService(
        {
            "official-filing-documents": OfficialFilingDocumentAdapter(
                downloader,
                discover=discover,
            )
        },
        transport=FakeTransport([]),
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
    ).acquire(plan, raw_store=raw_store, network_allowed=True)

    assert len(queries) == 1
    assert queries[0].listing_id == "SH600000"
    assert queries[0].source is FilingSource.CNINFO
    assert queries[0].published_from == target.start_date
    assert queries[0].published_to == target.end_date
    assert result.batch.receipts[0].artifact_metadata["source_document_id"] == (
        "cninfo-discovered-2024-annual"
    )


def test_hithink_credential_is_used_in_memory_and_never_persisted(tmp_path: Path):
    signing = b'{"code":0,"data":{"presigned_url":"https://signed.example.test/file?X-Amz-Signature=secret"}}'
    data = b"parquet bytes"
    transport = FakeTransport(
        [
            NetworkResponse(
                200,
                {"Content-Type": "application/json"},
                signing,
                "https://fuyao.aicubes.cn/api/dump/market-dumps/daily-k/download-url",
            ),
            NetworkResponse(
                200,
                {"Content-Type": "application/octet-stream"},
                data,
                "https://signed.example.test/file",
            ),
        ]
    )
    credential = CredentialReferenceV1(reference_id="hithink-key", kind="INJECTED", required=True)
    hithink_target = _target().model_copy(
        update={
            "listing_ids": ["SH000001"],
            "listing_markets": {"SH000001": Market.A},
            "calendar_ids": {"SH000001": "A:SSE"},
        }
    )
    hithink_source = _source(adapter_id="hithink-market-dumps").model_copy(
        update={
            "provider_id": "hithink-financial-api",
            "coverage_listing_ids": ["SH000001"],
        }
    )
    hithink_request = _request(adapter_id="hithink-market-dumps").model_copy(
        update={"listing_ids": ["SH000001"]}
    )
    plan = HistoricalAcquisitionPlanV1(
        plan_id="hithink-plan",
        plan_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target=hithink_target,
        sources=[hithink_source],
        requests=[
            hithink_request.model_copy(
                update={
                    "parameters": {"dump_type": "daily-k"},
                    "credential_ref": credential,
                }
            )
        ],
        credential_references=[credential],
    )
    raw_store = RawBlobStore(tmp_path / "raw")
    result = HistoricalAcquisitionService(
        {"hithink-market-dumps": HithinkMarketDumpAdapter()},
        transport=transport,
        credentials=MappingCredentialResolver({"hithink-key": "secret"}),
    ).acquire(plan, raw_store=raw_store, network_allowed=True)
    assert transport.calls[0][2]["X-api-key"] == "secret"
    serialized = json.dumps(result.batch.model_dump(mode="json"), ensure_ascii=False)
    assert "secret" not in serialized
    assert "X-Amz-Signature" not in serialized
    assert len(result.batch.receipts) == 1
    assert all(
        b"X-Amz-Signature" not in path.read_bytes()
        for path in (tmp_path / "raw").rglob("*.blob")
    )


def test_h_target_readiness_fails_closed_without_qualified_probe():
    readiness = build_readiness_report(
        _plan(include_h=True),
        network_used=False,
    )
    assert any(item.startswith("H_SOURCE_UNQUALIFIED") for item in readiness.blockers)
    assert readiness.personal_research_ready is False


def test_personal_readiness_requires_declared_coverage():
    summary = SimpleNamespace(
        valid=True,
        production_eligible=False,
        errors=[],
        coverage_status={},
    )
    readiness = build_readiness_report(
        _plan(include_h=True),
        validation_summary=summary,
        compiled_manifest=SimpleNamespace(dataset_id="dataset-1"),
    )
    assert "PERSONAL_COVERAGE_UNVERIFIED: PRICES:A1" in readiness.blockers
    assert "PERSONAL_COVERAGE_UNVERIFIED: PRICES:H1" in readiness.blockers
    assert readiness.personal_research_ready is False


def test_h_readiness_requires_probe_to_observe_every_target_h_listing():
    target = _target(include_h=True).model_copy(
        update={
            "listing_ids": ["A1", "H1", "H2"],
            "listing_markets": {"A1": Market.A, "H1": Market.H, "H2": Market.H},
            "calendar_ids": {"A1": "A:SSE", "H1": "H:HKEX", "H2": "H:HKEX"},
        }
    )
    source = _source(include_h=True).model_copy(
        update={"coverage_listing_ids": ["A1", "H1", "H2"]}
    )
    request = _request(include_h=True).model_copy(
        update={"listing_ids": ["A1", "H1", "H2"]}
    )
    plan = _plan(include_h=True).model_copy(
        update={"target": target, "sources": [source], "requests": [request]}
    )
    probe = SourceProbeReportV1.build(
        report_id="probe-prices",
        plan_id=plan.plan_id,
        request_id=request.request_id,
        source_id=source.source_id,
        adapter_id=request.adapter_id,
        adapter_version="1",
        source_kind=request.source_kind,
        status=ProbeStatus.PASS,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        account_entitlement=AccountEntitlement.CONFIRMED,
        historical_capable=True,
        terminal_coverage=CoverageEvidenceStatus.CONFIRMED,
        action_coverage=CoverageEvidenceStatus.CONFIRMED,
        license_evidence_uri=source.license_evidence_uri,
        license_evidence_sha256=source.license_evidence_sha256,
        observed_listing_ids=["A1", "H1"],
        observed_start=plan.target.start_date,
        observed_end=plan.target.end_date,
        blockers=[],
    )
    readiness = build_readiness_report(plan, probe_reports=[probe])
    assert any(item.startswith("H_SOURCE_UNQUALIFIED") for item in readiness.blockers)


def test_production_coverage_unions_market_scoped_sources_by_listing():
    target = _target(include_h=True).model_copy(
        update={"coverage_claim": CoverageClaim.COMPLETE}
    )
    all_kinds = list(HistoricalSourceKind)
    descriptors: list[HistoricalSourceDescriptor] = []
    reports = []
    bases = {
        HistoricalSourceKind.UNIVERSE_MEMBERSHIP: CoverageEvidenceBasis.MEMBERSHIP_INTERVALS,
        HistoricalSourceKind.LISTING_LIFECYCLE: CoverageEvidenceBasis.LIFECYCLE_INDEX,
        HistoricalSourceKind.DELISTINGS: CoverageEvidenceBasis.LIFECYCLE_INDEX,
        HistoricalSourceKind.PRICES: CoverageEvidenceBasis.TRADING_SESSIONS,
        HistoricalSourceKind.CORPORATE_ACTIONS: CoverageEvidenceBasis.EVENT_INDEX,
        HistoricalSourceKind.BENCHMARK: CoverageEvidenceBasis.OBSERVATION_SESSIONS,
        HistoricalSourceKind.FX: CoverageEvidenceBasis.OBSERVATION_SESSIONS,
        HistoricalSourceKind.FILINGS: CoverageEvidenceBasis.FILING_INDEX,
        HistoricalSourceKind.RESEARCH_ARCHIVE: CoverageEvidenceBasis.ARCHIVE_BINDING,
    }
    for kind in all_kinds:
        source_ids: dict[str, list[str]] = {}
        for listing_id in target.listing_ids:
            source_id = f"{kind.value.lower()}-{listing_id.lower()}"
            source_ids[listing_id] = [source_id]
            descriptors.append(
                HistoricalSourceDescriptor(
                    source_id=source_id,
                    source_kind=kind,
                    provider_id="verified-test-source",
                    source_name="verified test source",
                    authority="OFFICIAL_EXCHANGE",
                    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                    coverage_start=target.start_date,
                    coverage_end=target.end_date,
                    coverage_listing_ids=[listing_id],
                    content_sha256=hashlib.sha256(source_id.encode()).hexdigest(),
                    source_uri="https://source.example.test/data",
                    license_status="OPEN_REDISTRIBUTABLE",
                    licensing_constraints="test-only",
                    license_evidence_uri="https://source.example.test/terms",
                    license_evidence_sha256="1" * 64,
                    historical_capable=True,
                )
            )
        reports.append(
            build_coverage_report(
                target=target,
                source_kind=kind,
                expected_sessions_by_listing={
                    listing_id: [target.start_date] for listing_id in target.listing_ids
                },
                observed_sessions_by_listing={
                    listing_id: [target.start_date] for listing_id in target.listing_ids
                },
                source_artifact_ids_by_listing=source_ids,
                report_id=f"coverage-{kind.value.lower()}",
                evidence_basis=bases[kind],
            )
        )
    comparison = ReconciliationComparison(
        comparison_id="comparison-1",
        listing_id="A1",
        observation_date=target.start_date,
        canonical_value=1.0,
        independent_value=1.0,
        absolute_tolerance=0.01,
        relative_tolerance=0.01,
        canonical_source_id="prices-a1",
        independent_source_id="prices-h1",
    )
    reconciliation = HistoricalReconciliationReport.build(
        report_id="reconciliation-1",
        target_id=target.target_id,
        canonical_source_id="prices-a1",
        independent_source_id="prices-h1",
        canonical_price_basis=PriceBasis.UNADJUSTED,
        return_semantics="PRICE_RETURN",
        explicit_actions_used=False,
        comparisons=[comparison],
    )
    blockers = _production_scope_blockers(
        target,
        {item.source_id: item for item in descriptors},
        reports,
        [reconciliation],
        terminal_scope_errors=[],
    )
    assert "source coverage union does not span target: PRICES:A1" not in blockers
    assert "source coverage union does not span target: PRICES:H1" not in blockers
    assert "complete coverage record is missing: PRICES:A1" not in blockers
    assert "complete coverage record is missing: PRICES:H1" not in blockers
