"""Acceptance tests for the offline M6-A read-only research surface."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from turtle_value_engine import (
    CoverageClaim,
    HistoricalCoverageRecord,
    HistoricalCoverageReport,
    HistoricalDatasetManifest,
    HistoricalShardReference,
    HistoricalSourceDescriptor,
    HistoricalSourceKind,
    HistoricalTargetScope,
    Market,
    PrivateAcceptanceReportV1,
    ShardArtifactKind,
    SourceAuthority,
    build_decision_trace,
    compose_report,
    load_normalized_input,
)
from turtle_value_engine.cli import main
from turtle_value_engine.pipeline import run_analyze
from turtle_value_engine.surface import (
    SurfaceProjectionError,
    build_research_surface_snapshot,
    validate_research_surface_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "schemas" / "research-surface-snapshot.schema.json").read_text(encoding="utf-8")
)


def _analysis():
    return run_analyze(load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json"))


def test_minimal_analysis_builds_schema_valid_snapshot_with_unavailable_history():
    analysis = _analysis()

    snapshot = build_research_surface_snapshot(analysis)

    Draft202012Validator(SCHEMA).validate(snapshot.model_dump(mode="json"))
    assert snapshot.analysis_id == analysis.analysis_id
    assert snapshot.historical_status.availability == "NOT_AVAILABLE"
    assert snapshot.historical_status.claim_state == "NOT_AVAILABLE"
    assert snapshot.historical_status.acceptance.status == "NOT_AVAILABLE"
    assert snapshot.analysis.business_quality_status == "NOT_EVALUATED"
    assert snapshot.analysis.business_quality is None


def test_matching_trace_and_report_are_referenced_without_embedding_sources():
    analysis = _analysis()
    trace = build_decision_trace(analysis)
    report = compose_report(analysis)

    snapshot = build_research_surface_snapshot(
        analysis,
        decision_trace=trace,
        research_report=report,
    )

    assert snapshot.decision_trace_reference is not None
    assert snapshot.research_report_reference is not None
    assert {item.artifact_type for item in snapshot.source_artifacts} == {
        "COMPANY_ANALYSIS",
        "DECISION_TRACE",
        "RESEARCH_REPORT",
    }
    assert "Annual report" not in snapshot.canonical_bytes().decode("utf-8")


def test_trace_or_report_identity_and_as_of_conflicts_fail_closed():
    analysis = _analysis()
    trace = build_decision_trace(analysis)
    report = compose_report(analysis)

    with pytest.raises(SurfaceProjectionError, match="decision trace"):
        build_research_surface_snapshot(
            analysis,
            decision_trace=trace.model_copy(update={"decision_state": "FAIL"}),
        )

    mismatched_report = report.model_copy(
        update={"analysis": report.analysis.model_copy(update={"as_of": date(2030, 1, 1)})}
    )
    with pytest.raises(SurfaceProjectionError, match="as_of"):
        build_research_surface_snapshot(analysis, research_report=mismatched_report)


def test_blocked_a6_acceptance_remains_blocked_and_exact_blockers_are_visible():
    analysis = _analysis()
    acceptance = PrivateAcceptanceReportV1.build(
        plan_id="plan-fixture",
        target_id="target-fixture",
        dataset_id="dataset-fixture",
        checks={"A6_H_SHARE": "BLOCKED"},
        blockers=["H_SOURCE_UNQUALIFIED: missing confirmed H-share evidence"],
        accepted=False,
        offline_replay_verified=True,
    )

    snapshot = build_research_surface_snapshot(
        analysis,
        historical_acceptance=acceptance,
    )

    assert snapshot.historical_status.claim_state == "BLOCKED"
    assert snapshot.historical_status.acceptance.status == "BLOCKED"
    assert snapshot.historical_status.acceptance.blockers == acceptance.blockers
    assert snapshot.historical_status.blockers == acceptance.blockers


def test_partial_historical_manifest_remains_partial():
    analysis = _analysis()
    source = HistoricalSourceDescriptor(
        source_id="source-prices",
        source_kind=HistoricalSourceKind.PRICES,
        provider_id="fixture",
        source_name="fixture prices",
        authority=SourceAuthority.FIXTURE,
        retrieved_at=datetime(2020, 1, 4, tzinfo=UTC),
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2020, 1, 2),
        coverage_listing_ids=["A1"],
        content_sha256="1" * 64,
        licensing_constraints="fixture-only",
    )
    target = HistoricalTargetScope(
        target_id="target-partial",
        target_name="Partial target",
        universe_id="fixture",
        markets=[Market.A],
        listing_ids=["A1"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 2),
        membership_claim="FIXED_RESEARCH_UNIVERSE",
        coverage_claim=CoverageClaim.PARTIAL,
        required_source_kinds=[HistoricalSourceKind.PRICES],
        licensing_scope="fixture-only",
    )
    coverage_record = HistoricalCoverageRecord(
        source_kind=HistoricalSourceKind.PRICES,
        listing_id="A1",
        period_start=date(2020, 1, 1),
        period_end=date(2020, 1, 2),
        expected_session_count=2,
        observed_session_count=1,
        missing_dates=[date(2020, 1, 2)],
        source_artifact_ids=["source-prices"],
        status=CoverageClaim.PARTIAL,
    )
    manifest = HistoricalDatasetManifest.build(
        dataset_id="dataset-partial",
        dataset_version="1",
        target=target,
        source_descriptors=[source],
        shards=[
            HistoricalShardReference(
                shard_id="shard-prices",
                artifact_kind=ShardArtifactKind.MARKET_BAR,
                schema_version="1",
                content_sha256="2" * 64,
                row_count=0,
                date_start=date(2020, 1, 1),
                date_end=date(2020, 1, 2),
                listing_scope=["A1"],
                source_artifact_id="source-prices",
            )
        ],
        coverage_reports=[
            HistoricalCoverageReport.build(
                report_id="coverage-prices",
                target_id="target-partial",
                records=[coverage_record],
            )
        ],
        limitations=["partial fixture coverage"],
    )

    snapshot = build_research_surface_snapshot(analysis, historical_manifest=manifest)

    assert snapshot.historical_status.claim_state == "PARTIAL"
    assert snapshot.historical_status.limitations == ["partial fixture coverage"]
    assert snapshot.historical_status.coverage[0].missing_date_count == 1
    assert snapshot.historical_status.source_freshness[0].source_id == "source-prices"


def test_metrics_and_valuation_are_copied_not_recomputed():
    analysis = _analysis()

    snapshot = build_research_surface_snapshot(analysis)

    assert (
        snapshot.analysis.metrics.cdc.normalized_parent_core_cdc
        == analysis.metrics.cdc.normalized_parent_core_cdc
    )
    assert snapshot.analysis.metrics.net_cash.strict_net_cash == (
        analysis.metrics.net_cash.strict_net_cash
    )
    assert snapshot.analysis.metrics.through_return.through_return == (
        analysis.metrics.through_return.through_return
    )
    assert snapshot.valuation == analysis.valuation
    assert snapshot.decision.state == analysis.decision.state


def test_unknown_metric_extras_are_not_copied_to_the_surface():
    analysis = _analysis()
    polluted_cdc = analysis.metrics.cdc.model_copy(
        update={"raw_provider_payload": {"api_key": "do-not-publish"}}
    )
    polluted_metrics = analysis.metrics.model_copy(update={"cdc": polluted_cdc})
    polluted_analysis = analysis.model_copy(update={"metrics": polluted_metrics})

    snapshot = build_research_surface_snapshot(polluted_analysis)
    serialized = snapshot.canonical_bytes()

    assert b"raw_provider_payload" not in serialized
    assert b"do-not-publish" not in serialized


def test_snapshot_identity_is_stable_and_changes_with_source_value():
    analysis = _analysis()

    first = build_research_surface_snapshot(analysis)
    second = build_research_surface_snapshot(analysis)
    changed_cdc = analysis.metrics.cdc.model_copy(
        update={"normalized_parent_core_cdc": 999.0}
    )
    changed_analysis = analysis.model_copy(
        update={"metrics": analysis.metrics.model_copy(update={"cdc": changed_cdc})}
    )
    changed = build_research_surface_snapshot(changed_analysis)

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.content_sha256 == second.content_sha256
    assert changed.content_sha256 != first.content_sha256
    assert changed.analysis.metrics.cdc.normalized_parent_core_cdc == 999.0


def test_malformed_snapshot_fails_model_and_identity_validation():
    snapshot = build_research_surface_snapshot(_analysis())
    malformed = snapshot.model_dump(mode="json")
    malformed["content_sha256"] = "0" * 64

    with pytest.raises((ValidationError, ValueError)):
        validate_research_surface_snapshot(malformed)


def test_surface_cli_build_and_validate_are_offline(tmp_path, capsys):
    analysis = _analysis()
    analysis_path = tmp_path / "analysis.json"
    surface_path = tmp_path / "surface.json"
    analysis_path.write_text(
        json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "surface",
                "build",
                "--analysis",
                str(analysis_path),
                "--output",
                str(surface_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "surface",
                "validate",
                "--input",
                str(surface_path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["contract"] == "research_surface_snapshot_v1"
    assert output["historical_status"]["claim_state"] == "NOT_AVAILABLE"
