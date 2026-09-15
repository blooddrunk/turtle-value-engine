"""Deterministic coverage accounting for frozen historical rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from .contracts import (
    CoverageClaim,
    HistoricalCoverageRecord,
    HistoricalCoverageReport,
    HistoricalSourceKind,
    HistoricalTargetScope,
    HistoricalTerminalOutcome,
)


def build_coverage_report(
    *,
    target: HistoricalTargetScope,
    source_kind: HistoricalSourceKind,
    expected_sessions_by_listing: Mapping[str, Iterable[date]] | None,
    observed_sessions_by_listing: Mapping[str, Iterable[date]],
    source_artifact_ids_by_listing: Mapping[str, Iterable[str]],
    report_id: str,
    terminal_outcomes: Mapping[str, HistoricalTerminalOutcome] | None = None,
) -> HistoricalCoverageReport:
    """Build one deterministic report for every declared listing.

    ``expected_sessions_by_listing=None`` intentionally produces UNKNOWN
    coverage.  A row count without an authoritative expected-session universe
    cannot prove completeness.
    """

    terminal_outcomes = terminal_outcomes or {}
    records: list[HistoricalCoverageRecord] = []
    for listing_id in target.listing_ids:
        observed = set(observed_sessions_by_listing.get(listing_id, ()))
        source_ids = list(source_artifact_ids_by_listing.get(listing_id, ()))
        if not source_ids:
            source_ids = ["UNRESOLVED_SOURCE"]
        if expected_sessions_by_listing is None or listing_id not in expected_sessions_by_listing:
            records.append(
                HistoricalCoverageRecord(
                    source_kind=source_kind,
                    listing_id=listing_id,
                    period_start=target.start_date,
                    period_end=target.end_date,
                    expected_session_count=0,
                    observed_session_count=len(observed),
                    missing_dates=[],
                    source_artifact_ids=source_ids,
                    status=CoverageClaim.UNKNOWN,
                    terminal_outcome=terminal_outcomes.get(listing_id),
                )
            )
            continue
        expected = set(expected_sessions_by_listing[listing_id])
        missing = sorted(expected - observed)
        status = CoverageClaim.COMPLETE if not missing else CoverageClaim.PARTIAL
        records.append(
            HistoricalCoverageRecord(
                source_kind=source_kind,
                listing_id=listing_id,
                period_start=target.start_date,
                period_end=target.end_date,
                expected_session_count=len(expected),
                observed_session_count=len(expected & observed),
                missing_dates=missing,
                source_artifact_ids=source_ids,
                status=status,
                terminal_outcome=terminal_outcomes.get(listing_id),
            )
        )
    return HistoricalCoverageReport.build(
        report_id=report_id,
        target_id=target.target_id,
        records=records,
    )


__all__ = ["build_coverage_report"]
