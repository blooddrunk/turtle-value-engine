"""Frozen acceptance coverage for the Phase 5R historical boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.backtest.contracts import (
    BenchmarkObservation,
    BenchmarkReturnType,
    CorporateAction,
    CorporateActionType,
    Market,
    MarketBar,
    PriceBasis,
)
from turtle_value_engine.historical import (
    ArchiveArtifactType,
    CoverageClaim,
    HistoricalArtifactStore,
    HistoricalAvailabilityRecord,
    HistoricalCodeChange,
    HistoricalDatasetManifest,
    HistoricalFilingLocator,
    HistoricalFXObservation,
    HistoricalListingLifecycle,
    HistoricalMembershipInterval,
    HistoricalResearchArchiveManifest,
    HistoricalResearchArtifactReference,
    HistoricalSourceDescriptor,
    HistoricalSourceKind,
    HistoricalTargetScope,
    HistoricalTerminalOutcome,
    LicenseStatus,
    ReconciliationStatus,
    ReviewStatus,
    ShardArtifactKind,
    SourceAuthority,
    build_coverage_report,
    compile_backtest_manifest,
    reconcile_observations,
    validate_historical_dataset,
    validate_research_archive,
)

START = date(2020, 1, 1)
END = date(2020, 1, 3)
UTC_NOON = datetime(2020, 1, 2, 12, tzinfo=UTC)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source(
    source_id: str,
    kind: HistoricalSourceKind,
    *,
    listings: list[str] | None = None,
    authority: SourceAuthority = SourceAuthority.FIXTURE,
    license_status: LicenseStatus = LicenseStatus.UNKNOWN,
    historical_capable: bool = False,
    is_current_snapshot: bool = False,
) -> HistoricalSourceDescriptor:
    return HistoricalSourceDescriptor(
        source_id=source_id,
        source_kind=kind,
        provider_id="frozen-test",
        source_name="compact acceptance fixture",
        authority=authority,
        retrieved_at=datetime(2020, 1, 4, tzinfo=UTC),
        coverage_start=START,
        coverage_end=END,
        coverage_listing_ids=list(listings or ["A1", "H1"]),
        content_sha256=_hash(source_id),
        licensing_constraints="acceptance-only; no redistribution claim",
        license_status=license_status,
        historical_capable=historical_capable,
        is_current_snapshot=is_current_snapshot,
    )


def _lifecycle_rows() -> list[HistoricalListingLifecycle]:
    code_change = HistoricalCodeChange(
        effective_date=date(2019, 6, 1),
        previous_code="A1-OLD",
        new_code="A1",
        source_artifact_id="src-lifecycle",
        source_hash=_hash("src-lifecycle"),
    )
    return [
        HistoricalListingLifecycle(
            listing_id="A1",
            economic_company_id="EC-1",
            market=Market.A,
            currency="CNY",
            listing_date=date(2019, 1, 1),
            trading_calendar="SSE",
            timezone="Asia/Shanghai",
            historical_codes=["A1-OLD", "A1"],
            code_changes=[code_change],
            source_artifact_id="src-lifecycle",
            source_hash=_hash("src-lifecycle"),
        ),
        HistoricalListingLifecycle(
            listing_id="H1",
            economic_company_id="EC-1",
            market=Market.H,
            currency="HKD",
            listing_date=date(2019, 5, 1),
            trading_calendar="HKEX",
            timezone="Asia/Hong_Kong",
            historical_codes=["H1"],
            source_artifact_id="src-lifecycle",
            source_hash=_hash("src-lifecycle"),
        ),
    ]


def _build_manifest(
    tmp_path,
    *,
    bars: list[MarketBar] | None = None,
    actions: list[CorporateAction] | None = None,
    lifecycle_rows: list[HistoricalListingLifecycle] | None = None,
    later_h_listing: bool = False,
    research_archive: HistoricalResearchArchiveManifest | None = None,
    reconciliation_reports=None,
) -> tuple[HistoricalDatasetManifest, HistoricalArtifactStore]:
    store = HistoricalArtifactStore(tmp_path / "artifacts")
    sources = [
        _source("src-lifecycle", HistoricalSourceKind.LISTING_LIFECYCLE),
        _source("src-delistings", HistoricalSourceKind.DELISTINGS),
        _source("src-membership", HistoricalSourceKind.UNIVERSE_MEMBERSHIP),
        _source("src-prices", HistoricalSourceKind.PRICES),
        _source("src-actions", HistoricalSourceKind.CORPORATE_ACTIONS),
        _source("src-fx", HistoricalSourceKind.FX),
        _source("src-benchmark", HistoricalSourceKind.BENCHMARK),
        _source("filing-source", HistoricalSourceKind.FILINGS),
        _source("research-source", HistoricalSourceKind.RESEARCH_ARCHIVE),
    ]
    target = HistoricalTargetScope(
        target_id="fixture-ah-2020",
        target_name="Compact A/H replay universe",
        universe_id="fixture-ah",
        markets=[Market.A, Market.H],
        listing_ids=["A1", "H1"],
        start_date=START,
        end_date=END,
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim=CoverageClaim.PARTIAL,
        required_source_kinds=[
            HistoricalSourceKind.LISTING_LIFECYCLE,
            HistoricalSourceKind.UNIVERSE_MEMBERSHIP,
            HistoricalSourceKind.PRICES,
            HistoricalSourceKind.CORPORATE_ACTIONS,
            HistoricalSourceKind.FX,
            HistoricalSourceKind.BENCHMARK,
        ],
        licensing_scope="acceptance-only",
    )
    lifecycle_rows = lifecycle_rows or _lifecycle_rows()
    if later_h_listing:
        lifecycle_rows = [
            item.model_copy(update={"listing_date": END})
            if item.listing_id == "H1"
            else item
            for item in lifecycle_rows
        ]
    h_listing_date = next(
        item.listing_date for item in lifecycle_rows if item.listing_id == "H1"
    )
    availability_rows = [
        HistoricalAvailabilityRecord(
            artifact_id="m-a1",
            artifact_kind="UNIVERSE_MEMBERSHIP",
            available_at=datetime(2019, 12, 1, tzinfo=UTC),
            retrieved_at=datetime(2020, 1, 4, tzinfo=UTC),
            source_artifact_id="src-membership",
            source_hash=_hash("src-membership"),
        ),
        HistoricalAvailabilityRecord(
            artifact_id="m-h1",
            artifact_kind="UNIVERSE_MEMBERSHIP",
            available_at=datetime(2019, 12, 1, tzinfo=UTC),
            retrieved_at=datetime(2020, 1, 4, tzinfo=UTC),
            source_artifact_id="src-membership",
            source_hash=_hash("src-membership"),
        ),
    ]
    memberships = [
        HistoricalMembershipInterval(
            membership_id="m-a1",
            universe_id="fixture-ah",
            listing_id="A1",
            valid_from=date(2019, 1, 1),
            valid_to=END,
            availability_id="m-a1",
            source_artifact_id="src-membership",
            source_hash=_hash("src-membership"),
        ),
        HistoricalMembershipInterval(
            membership_id="m-h1",
            universe_id="fixture-ah",
            listing_id="H1",
            valid_from=h_listing_date,
            valid_to=END,
            availability_id="m-h1",
            source_artifact_id="src-membership",
            source_hash=_hash("src-membership"),
        ),
    ]
    bars = bars or [
        MarketBar(
            bar_id=f"a1-{day.isoformat()}",
            listing_id="A1",
            market=Market.A,
            trading_date=day,
            close=10.0 + index,
            currency="CNY",
            source_hash=_hash("src-prices"),
        )
        for index, day in enumerate((START, date(2020, 1, 2), END))
    ] + [
        MarketBar(
            bar_id=f"h1-{day.isoformat()}",
            listing_id="H1",
            market=Market.H,
            trading_date=day,
            close=20.0 + index,
            currency="HKD",
            source_hash=_hash("src-prices"),
        )
        for index, day in enumerate((START, date(2020, 1, 2), END))
    ]
    if later_h_listing:
        bars = [
            item
            for item in bars
            if item.listing_id == "A1" or item.trading_date == END
        ]
    if actions is None:
        actions = [
            CorporateAction(
                action_id="div-a1",
                listing_id="A1",
                action_type=CorporateActionType.CASH_DIVIDEND,
                effective_date=date(2020, 1, 2),
                cash_per_share=0.2,
                currency="CNY",
                source_hash=_hash("src-actions"),
            ),
            CorporateAction(
                action_id="split-h1",
                listing_id="H1",
                action_type=CorporateActionType.SPLIT,
                effective_date=date(2020, 1, 2),
                split_factor=2.0,
                currency="HKD",
                source_hash=_hash("src-actions"),
            ),
        ]
    if later_h_listing and actions is not None:
        actions = [
            item.model_copy(update={"effective_date": END})
            if item.listing_id == "H1"
            else item
            for item in actions
        ]
    fx_rows = [
        HistoricalFXObservation(
            observation_id=f"fx-h1-{(END if later_h_listing else date(2020, 1, 2)).isoformat()}",
            listing_id="H1",
            base_currency="HKD",
            quote_currency="CNY",
            observation_date=END if later_h_listing else date(2020, 1, 2),
            rate=0.91,
            available_at=UTC_NOON,
            source_hash=_hash("src-fx"),
        )
    ]
    benchmark_rows = [
        BenchmarkObservation(
            observation_id="benchmark-hsi-2020-01-02",
            benchmark_id="HSI",
            observation_date=date(2020, 1, 2),
            value=28_000.0,
            return_type=BenchmarkReturnType.PRICE_RETURN,
            currency="HKD",
            available_at=UTC_NOON,
            source_hash=_hash("src-benchmark"),
        )
    ]
    refs = [
        store.freeze_shard(
            shard_id="lifecycles",
            artifact_kind=ShardArtifactKind.LISTING_LIFECYCLE,
            schema_version="historical-listing-lifecycle-v1",
            date_start=date(2019, 1, 1),
            date_end=END,
            listing_scope=["A1", "H1"],
            source_artifact_id="src-lifecycle",
            rows=lifecycle_rows,
        ),
        store.freeze_shard(
            shard_id="memberships",
            artifact_kind=ShardArtifactKind.UNIVERSE_MEMBERSHIP,
            schema_version="historical-membership-v1",
            date_start=date(2019, 1, 1),
            date_end=END,
            listing_scope=["A1", "H1"],
            source_artifact_id="src-membership",
            rows=memberships,
        ),
        store.freeze_shard(
            shard_id="availability",
            artifact_kind=ShardArtifactKind.AVAILABILITY,
            schema_version="historical-availability-v1",
            date_start=START,
            date_end=END,
            listing_scope=["A1", "H1"],
            source_artifact_id="src-membership",
            rows=availability_rows,
        ),
        store.freeze_shard(
            shard_id="bars",
            artifact_kind=ShardArtifactKind.MARKET_BAR,
            schema_version="market-bar-v1",
            date_start=START,
            date_end=END,
            listing_scope=["A1", "H1"],
            source_artifact_id="src-prices",
            rows=bars,
        ),
        store.freeze_shard(
            shard_id="actions",
            artifact_kind=ShardArtifactKind.CORPORATE_ACTION,
            schema_version="corporate-action-v1",
            date_start=date(2020, 1, 2),
            date_end=END if later_h_listing else date(2020, 1, 2),
            listing_scope=["A1", "H1"],
            source_artifact_id="src-actions",
            rows=actions,
        ),
        store.freeze_shard(
            shard_id="fx",
            artifact_kind=ShardArtifactKind.FX_OBSERVATION,
            schema_version="historical-fx-observation-v1",
            date_start=END if later_h_listing else date(2020, 1, 2),
            date_end=END if later_h_listing else date(2020, 1, 2),
            listing_scope=["H1"],
            source_artifact_id="src-fx",
            rows=fx_rows,
        ),
        store.freeze_shard(
            shard_id="benchmarks",
            artifact_kind=ShardArtifactKind.BENCHMARK_OBSERVATION,
            schema_version="benchmark-observation-v1",
            date_start=date(2020, 1, 2),
            date_end=date(2020, 1, 2),
            listing_scope=["__BENCHMARK__"],
            source_artifact_id="src-benchmark",
            rows=benchmark_rows,
        ),
    ]
    coverage = build_coverage_report(
        target=target,
        source_kind=HistoricalSourceKind.PRICES,
        expected_sessions_by_listing={
            "A1": [START, date(2020, 1, 2), END],
            "H1": [END] if later_h_listing else [START, date(2020, 1, 2), END],
        },
        observed_sessions_by_listing={
            "A1": [START, date(2020, 1, 2), END],
            "H1": [END] if later_h_listing else [START, date(2020, 1, 2), END],
        },
        source_artifact_ids_by_listing={"A1": ["src-prices"], "H1": ["src-prices"]},
        report_id="prices-coverage",
    )
    manifest = HistoricalDatasetManifest.build(
        dataset_id="fixture-ah-dataset",
        dataset_version="1",
        target=target,
        source_descriptors=sources,
        shards=refs,
        coverage_reports=[coverage],
        research_archive=research_archive,
        reconciliation_reports=reconciliation_reports or [],
        limitations=["compact acceptance fixture; not a production market claim"],
    )
    return manifest, store


def _archive(*, available_at: date | datetime | None = UTC_NOON):
    document_hash = _hash("filing-document")
    reference = HistoricalResearchArtifactReference(
        artifact_id="bq-a1-2020",
        artifact_type=ArchiveArtifactType.BUSINESS_QUALITY,
        listing_id="A1",
        analysis_id="analysis-a1-2020",
        as_of=START,
        available_at=available_at,
        source_document_hashes=[document_hash],
        filing_ids=["filing-a1-2020"],
        locators=[
            HistoricalFilingLocator(
                filing_id="filing-a1-2020",
                document_hash=document_hash,
                page=12,
                section="Business risks",
            )
        ],
        source_artifact_ids=["filing-source"],
        content_sha256=_hash("bq-artifact"),
        review_status=ReviewStatus.FROZEN_VALIDATED,
    )
    from turtle_value_engine.historical import HistoricalDecisionResearchBinding

    binding = HistoricalDecisionResearchBinding(
        decision_artifact_id="decision-a1-2020",
        research_artifact_id=reference.artifact_id,
        business_quality_artifact_id=reference.artifact_id,
        listing_id="A1",
        analysis_id="analysis-a1-2020",
        as_of=START,
        decision_time=UTC_NOON,
        used_artifact_ids=[reference.artifact_id],
    )
    return HistoricalResearchArchiveManifest.build(
        archive_id="archive-1",
        target_id="fixture-ah-2020",
        artifacts=[reference],
        decision_bindings=[binding],
    )


def test_source_aware_compilation_keeps_a_h_lifecycles_and_shards(tmp_path):
    manifest, store = _build_manifest(tmp_path)

    summary = validate_historical_dataset(manifest, store)
    compiled = compile_backtest_manifest(manifest, store)

    assert summary.valid is True
    assert summary.production_eligible is False
    assert len(compiled.market_bars) == 6
    assert {item.market for item in compiled.listing_lifecycles} == {Market.A, Market.H}
    assert (
        compiled.lifecycle("A1").economic_company_id
        == compiled.lifecycle("H1").economic_company_id
    )
    assert compiled.universe_memberships[0].availability is not None
    assert compiled.fx_observations[0].listing_id == "H1"
    assert compiled.fx_observations[0].base_currency == "HKD"
    assert compiled.benchmarks[0].return_type is BenchmarkReturnType.PRICE_RETURN
    assert not hasattr(manifest, "market_bars")


def test_later_listed_listing_is_retained_without_present_day_substitution(tmp_path):
    manifest, store = _build_manifest(tmp_path, later_h_listing=True)
    compiled = compile_backtest_manifest(manifest, store)

    assert compiled.lifecycle("H1").listing_date == END
    assert compiled.universe_memberships[1].valid_from == END


def test_content_addressed_missing_and_hash_mismatch_fail_closed(tmp_path):
    manifest, store = _build_manifest(tmp_path)
    bars_ref = next(item for item in manifest.shards if item.shard_id == "bars")
    path = store.path_for(bars_ref)
    path.unlink()
    with pytest.raises(ValueError, match="missing"):
        validate_historical_dataset(manifest, store)

    manifest, store = _build_manifest(tmp_path / "second")
    bars_ref = next(item for item in manifest.shards if item.shard_id == "bars")
    store.path_for(bars_ref).write_bytes(b'{"tampered":true}\n')
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_historical_dataset(manifest, store)


def test_current_constituent_substitution_is_rejected():
    with pytest.raises(ValueError, match="current constituent"):
        _source(
            "current",
            HistoricalSourceKind.UNIVERSE_MEMBERSHIP,
            is_current_snapshot=True,
        )


def test_production_license_evidence_must_be_persisted_as_a_pair():
    payload = _source(
        "licensed",
        HistoricalSourceKind.PRICES,
        authority=SourceAuthority.OFFICIAL_EXCHANGE,
        license_status=LicenseStatus.OPEN_REDISTRIBUTABLE,
        historical_capable=True,
    ).model_dump(mode="python")
    payload["license_evidence_uri"] = "https://example.test/license"
    with pytest.raises(ValueError, match="supplied together"):
        HistoricalSourceDescriptor.model_validate(payload)


def test_unknown_terminal_outcome_is_retained_without_fabricated_value(tmp_path):
    unresolved = _lifecycle_rows()
    unresolved[1] = unresolved[1].model_copy(
        update={
            "terminal_date": date(2020, 1, 3),
            "terminal_outcome": HistoricalTerminalOutcome.UNRESOLVED_TERMINAL,
        }
    )
    manifest, store = _build_manifest(tmp_path, lifecycle_rows=unresolved)
    compiled = compile_backtest_manifest(manifest, store)
    assert compiled.lifecycle("H1").terminal_status == "UNKNOWN"
    assert not any(
        action.listing_id == "H1" and action.action_type is CorporateActionType.TERMINAL_VALUE
        for action in compiled.corporate_actions
    )


def test_unresolved_terminal_outcome_rejects_a_terminal_value_action(tmp_path):
    unresolved = _lifecycle_rows()
    unresolved[1] = unresolved[1].model_copy(
        update={
            "terminal_date": END,
            "terminal_outcome": HistoricalTerminalOutcome.UNRESOLVED_TERMINAL,
        }
    )
    actions = [
        CorporateAction(
            action_id="invented-terminal-value",
            listing_id="H1",
            action_type=CorporateActionType.TERMINAL_VALUE,
            effective_date=END,
            terminal_value_per_share=0.0,
            currency="HKD",
            source_hash=_hash("src-actions"),
        )
    ]
    manifest, store = _build_manifest(
        tmp_path,
        lifecycle_rows=unresolved,
        actions=actions,
    )
    with pytest.raises(ValueError, match="terminal value.*unresolved"):
        compile_backtest_manifest(manifest, store)


def test_adjusted_prices_and_explicit_actions_cannot_be_double_counted(tmp_path):
    bars = [
        MarketBar(
            bar_id=f"{listing_id.lower()}-{day.isoformat()}",
            listing_id=listing_id,
            market=Market.A if listing_id == "A1" else Market.H,
            trading_date=day,
            close=(10.0 if listing_id == "A1" else 20.0) + index,
            currency="CNY" if listing_id == "A1" else "HKD",
            source_hash=_hash("src-prices"),
        )
        for listing_id in ("A1", "H1")
        for index, day in enumerate((START, date(2020, 1, 2), END))
    ]
    bars[0] = bars[0].model_copy(
        update={
            "price_basis": PriceBasis.ADJUSTED,
            "adjustment_scope": ["CASH_DIVIDENDS"],
        }
    )
    manifest, store = _build_manifest(
        tmp_path,
        bars=bars,
    )
    with pytest.raises(ValueError, match="double count"):
        compile_backtest_manifest(manifest, store)


def test_coverage_without_authoritative_expected_sessions_is_unknown(tmp_path):
    target = _build_manifest(tmp_path)[0].target
    report = build_coverage_report(
        target=target,
        source_kind=HistoricalSourceKind.PRICES,
        expected_sessions_by_listing=None,
        observed_sessions_by_listing={"A1": [START], "H1": [START]},
        source_artifact_ids_by_listing={"A1": ["src-prices"], "H1": ["src-prices"]},
        report_id="unknown-coverage",
    )
    assert {item.status for item in report.records} == {CoverageClaim.UNKNOWN}


def test_unknown_coverage_without_source_ids_remains_explicit_not_dangling(tmp_path):
    manifest, store = _build_manifest(tmp_path)
    report = build_coverage_report(
        target=manifest.target,
        source_kind=HistoricalSourceKind.FX,
        expected_sessions_by_listing=None,
        observed_sessions_by_listing={},
        source_artifact_ids_by_listing={},
        report_id="unknown-fx-coverage",
    )
    rebuilt = HistoricalDatasetManifest.build(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.dataset_version,
        target=manifest.target,
        source_descriptors=manifest.source_descriptors,
        shards=manifest.shards,
        coverage_reports=[*manifest.coverage_reports, report],
        limitations=manifest.limitations,
    )
    summary = validate_historical_dataset(rebuilt, store)
    assert summary.valid is True
    assert summary.production_eligible is False


def test_research_archive_requires_frozen_pit_artifacts_and_locators():
    archive = _archive()
    assert validate_research_archive(archive).archive_id == "archive-1"

    late = _archive(available_at=date(2020, 1, 2))
    with pytest.raises(ValueError, match="not available"):
        validate_research_archive(late)

    unknown = _archive(available_at=None)
    with pytest.raises(ValueError, match="unknown availability"):
        validate_research_archive(unknown)


def test_research_archive_rejects_a_used_artifact_outside_decision_scope():
    archive = _archive()
    outside = archive.artifacts[0].model_copy(
        update={"artifact_id": "bq-a1-outside", "analysis_id": "other-analysis"}
    )
    changed = HistoricalResearchArchiveManifest.build(
        archive_id="outside-scope",
        target_id=archive.target_id,
        artifacts=[archive.artifacts[0], outside],
        decision_bindings=[
            archive.decision_bindings[0].model_copy(
                update={
                    "used_artifact_ids": [
                        archive.artifacts[0].artifact_id,
                        outside.artifact_id,
                    ]
                }
            )
        ],
    )
    with pytest.raises(ValueError, match="outside its decision scope"):
        validate_research_archive(changed)


def test_research_archive_reference_can_verify_actual_frozen_json_bytes(tmp_path):
    store = HistoricalArtifactStore(tmp_path / "archive-store")
    source = _source("source-artifact", HistoricalSourceKind.FILINGS)
    relative_path, content_sha256 = store.freeze_json_artifact(source)
    reference = HistoricalResearchArtifactReference.from_model(
        artifact_id="filing-document-1",
        artifact_type="FILING_DOCUMENT",
        artifact=source,
        listing_id="A1",
        analysis_id="analysis-a1-2020",
        as_of=START,
        available_at=UTC_NOON,
        source_document_hashes=[_hash("filing-document")],
        filing_ids=["filing-a1-2020"],
        locators=[
            HistoricalFilingLocator(
                filing_id="filing-a1-2020",
                document_hash=_hash("filing-document"),
                page=1,
            )
        ],
        source_artifact_ids=[source.source_id],
        review_status="FROZEN_VALIDATED",
        relative_path=relative_path,
    )
    assert reference.content_sha256 == content_sha256
    archive = HistoricalResearchArchiveManifest.build(
        archive_id="archive-with-bytes",
        target_id="fixture-ah-2020",
        artifacts=[reference],
        decision_bindings=[],
    )
    assert validate_research_archive(archive).archive_id == "archive-with-bytes"

    path = store.root / relative_path
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        store.read_json_artifact(relative_path, content_sha256)


def test_review_required_research_artifact_cannot_support_a_decision():
    archive = _archive()
    reference = archive.artifacts[0].model_copy(update={"review_status": "REVIEW_REQUIRED"})
    changed = HistoricalResearchArchiveManifest.build(
        archive_id="review-required",
        target_id=archive.target_id,
        artifacts=[reference],
        decision_bindings=archive.decision_bindings,
    )
    with pytest.raises(ValueError, match="not frozen|FROZEN_VALIDATED"):
        validate_research_archive(changed)


def test_compiler_rejects_dangling_research_binding_and_source(tmp_path):
    manifest, store = _build_manifest(tmp_path, research_archive=_archive())
    with pytest.raises(ValueError, match="unknown source artifact|unknown decision artifact"):
        compile_backtest_manifest(manifest, store)


def test_compiler_rejects_dangling_research_document_hash(tmp_path):
    archive = _archive()
    manifest, store = _build_manifest(tmp_path, research_archive=archive)
    with pytest.raises(ValueError, match="unknown source document hash"):
        compile_backtest_manifest(manifest, store)


def test_compiler_rejects_dangling_reconciliation_source(tmp_path):
    report = reconcile_observations(
        target_id="fixture-ah-2020",
        canonical_source_id="missing-canonical-source",
        independent_source_id="src-prices",
        canonical_values={("A1", START): 10.0},
        independent_values={("A1", START): 10.0},
        absolute_tolerance=0.01,
        relative_tolerance=0.01,
    )
    manifest, store = _build_manifest(tmp_path, reconciliation_reports=[report])
    with pytest.raises(ValueError, match="reconciliation references unknown source"):
        compile_backtest_manifest(manifest, store)


def test_reconciliation_persists_tolerance_and_independent_identity():
    report = reconcile_observations(
        target_id="fixture-ah-2020",
        canonical_source_id="src-prices",
        independent_source_id="independent-reference",
        canonical_values={("A1", START): 10.0, ("A1", END): 11.0},
        independent_values={("A1", START): 10.01, ("A1", END): 11.0},
        absolute_tolerance=0.02,
        relative_tolerance=0.001,
    )
    assert report.status is ReconciliationStatus.PASS
    assert report.comparisons[0].absolute_difference == pytest.approx(0.01)


def test_production_claim_requires_real_source_and_complete_evidence(tmp_path):
    manifest, store = _build_manifest(tmp_path)
    target = manifest.target.model_copy(
        update={"membership_claim": "HISTORICAL", "coverage_claim": CoverageClaim.COMPLETE}
    )
    manifest = HistoricalDatasetManifest.build(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.dataset_version,
        target=target,
        source_descriptors=manifest.source_descriptors,
        shards=manifest.shards,
        coverage_reports=manifest.coverage_reports,
        limitations=manifest.limitations,
    )
    with pytest.raises(ValueError, match="production|HISTORICAL|source"):
        validate_historical_dataset(manifest, store, require_production=True)


def test_checked_in_compact_corpus_replays_without_network_or_model():
    root = Path(__file__).parents[1] / "fixtures" / "historical" / "phase5r-compact-v1"
    from turtle_value_engine.historical import HistoricalDatasetManifest

    manifest = HistoricalDatasetManifest.model_validate(
        json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    )
    store = HistoricalArtifactStore(root / "store")
    summary = validate_historical_dataset(manifest, store)
    compiled = compile_backtest_manifest(manifest, store)

    assert summary.production_eligible is False
    assert compiled.lifecycle("H1").terminal_status == "DELISTED"
    assert any(item.suspended for item in compiled.market_bars)
    assert len(compiled.fx_observations) == 1
    assert len(compiled.benchmarks) == 1
    assert {item.market for item in compiled.listing_lifecycles} == {Market.A, Market.H}


def test_same_frozen_inputs_reproduce_identical_manifest_hashes():
    root = Path(__file__).parents[1] / "fixtures" / "historical" / "phase5r-compact-v1"
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    first = HistoricalDatasetManifest.model_validate(payload)
    second = HistoricalDatasetManifest.model_validate(json.loads(json.dumps(payload)))
    store = HistoricalArtifactStore(root / "store")

    first_compiled = compile_backtest_manifest(first, store)
    second_compiled = compile_backtest_manifest(second, store)
    assert first.content_sha256 == second.content_sha256
    assert first_compiled.content_sha256 == second_compiled.content_sha256


def test_phase5r_schemas_validate_the_frozen_manifest():
    root = Path(__file__).parents[1]
    for schema_path in sorted((root / "schemas").glob("historical-*.schema.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    manifest = json.loads(
        (
            root
            / "fixtures"
            / "historical"
            / "phase5r-compact-v1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "schemas" / "historical-dataset-manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(manifest)


def test_strict_v1_remains_byte_identical():
    path = Path(__file__).parents[1] / "rules" / "strict-v1.yaml"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"
    )
