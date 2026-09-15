"""Offline audit for the minimum real private A/H acceptance."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from turtle_value_engine.backtest import (
    BenchmarkObservation,
    CorporateAction,
    FXObservation,
    ListingLifecycle,
    Market,
    MarketBar,
    UniverseMembership,
)
from turtle_value_engine.providers.models import canonical_json_bytes

from .acquisition import (
    AcquisitionReadinessReportV1,
    HistoricalAcquisitionPlanV1,
    HistoricalIngestionCompiler,
    RawAcquisitionBatchManifestV1,
    RawBlobStore,
    SourceProbeReportV1,
    build_readiness_report,
)
from .compiler import HistoricalDatasetCompiler
from .contracts import (
    CoverageEvidenceBasis,
    HistoricalDatasetManifest,
    HistoricalFilingDocumentRecord,
    HistoricalFXObservation,
    HistoricalListingLifecycle,
    HistoricalMembershipInterval,
    HistoricalSourceKind,
    HistoricalTerminalOutcome,
    ShardArtifactKind,
    SourceAuthority,
)
from .store import HistoricalArtifactError, HistoricalArtifactStore

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_CHECK_PASS = "PASS"
_CHECK_BLOCKED = "BLOCKED"
_OFFICIAL_AUTHORITIES = {
    SourceAuthority.OFFICIAL_EXCHANGE,
    SourceAuthority.REGULATOR,
    SourceAuthority.ISSUER,
}
_COVERAGE_KINDS: dict[str, set[HistoricalSourceKind]] = {
    "UNIVERSE_MEMBERSHIP": {HistoricalSourceKind.UNIVERSE_MEMBERSHIP},
    "PRICES": {HistoricalSourceKind.PRICES},
    "CORPORATE_ACTIONS": {HistoricalSourceKind.CORPORATE_ACTIONS},
    "BENCHMARK": {HistoricalSourceKind.BENCHMARK},
    "FX": {HistoricalSourceKind.FX},
    "FILINGS": {HistoricalSourceKind.FILINGS},
    "LISTING_LIFECYCLE": {
        HistoricalSourceKind.LISTING_LIFECYCLE,
        HistoricalSourceKind.DELISTINGS,
    },
}
_COVERAGE_BASES: dict[HistoricalSourceKind, set[CoverageEvidenceBasis]] = {
    HistoricalSourceKind.UNIVERSE_MEMBERSHIP: {
        CoverageEvidenceBasis.MEMBERSHIP_INTERVALS,
        CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE,
    },
    HistoricalSourceKind.PRICES: {CoverageEvidenceBasis.TRADING_SESSIONS},
    HistoricalSourceKind.CORPORATE_ACTIONS: {
        CoverageEvidenceBasis.EVENT_INDEX,
        CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE,
    },
    HistoricalSourceKind.BENCHMARK: {CoverageEvidenceBasis.OBSERVATION_SESSIONS},
    HistoricalSourceKind.FX: {CoverageEvidenceBasis.OBSERVATION_SESSIONS},
    HistoricalSourceKind.FILINGS: {
        CoverageEvidenceBasis.FILING_INDEX,
        CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE,
    },
    HistoricalSourceKind.LISTING_LIFECYCLE: {
        CoverageEvidenceBasis.LIFECYCLE_INDEX,
        CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE,
    },
    HistoricalSourceKind.DELISTINGS: {
        CoverageEvidenceBasis.LIFECYCLE_INDEX,
        CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE,
    },
}
_ROW_TYPES: dict[ShardArtifactKind, tuple[type[BaseModel], ...]] = {
    ShardArtifactKind.LISTING_LIFECYCLE: (HistoricalListingLifecycle, ListingLifecycle),
    ShardArtifactKind.UNIVERSE_MEMBERSHIP: (HistoricalMembershipInterval, UniverseMembership),
    ShardArtifactKind.MARKET_BAR: (MarketBar,),
    ShardArtifactKind.CORPORATE_ACTION: (CorporateAction,),
    ShardArtifactKind.FX_OBSERVATION: (HistoricalFXObservation, FXObservation),
    ShardArtifactKind.BENCHMARK_OBSERVATION: (BenchmarkObservation,),
    ShardArtifactKind.FILING_DOCUMENT: (HistoricalFilingDocumentRecord,),
}


def _model_sha256(model: BaseModel, *, exclude: set[str] | None = None) -> str:
    payload = model.model_dump(
        mode="json",
        exclude=exclude or set(),
        warnings=False,
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class PrivateAcceptanceReportV1(BaseModel):
    """Machine-readable result of the offline A6 acceptance audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["historical_private_acceptance_report_v1"] = (
        "historical_private_acceptance_report_v1"
    )
    plan_id: StrictStr = Field(min_length=1)
    target_id: StrictStr = Field(min_length=1)
    dataset_id: StrictStr = Field(min_length=1)
    probe_report_id: StrictStr | None = Field(default=None, min_length=1)
    probe_network_used: StrictBool = False
    offline_replay_verified: StrictBool = False
    accepted: StrictBool = False
    checks: dict[StrictStr, Literal["PASS", "BLOCKED"]] = Field(default_factory=dict)
    blockers: list[StrictStr] = Field(default_factory=list, max_length=2048)
    report_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_report(self) -> PrivateAcceptanceReportV1:
        if self.accepted != (not self.blockers):
            raise ValueError("accepted must be false whenever blockers are present")
        if self.accepted and any(value != _CHECK_PASS for value in self.checks.values()):
            raise ValueError("accepted reports require every check to pass")
        if self.report_sha256 != _model_sha256(self, exclude={"report_sha256"}):
            raise ValueError("private acceptance report hash does not match content")
        return self

    @classmethod
    def build(cls, **values: object) -> PrivateAcceptanceReportV1:
        payload = dict(values)
        candidate = cls.model_construct(
            **payload,
            report_sha256="0" * 64,
        )
        payload["report_sha256"] = _model_sha256(candidate, exclude={"report_sha256"})
        return cls.model_validate(payload)


def _read_rows(
    manifest: HistoricalDatasetManifest,
    store: HistoricalArtifactStore,
    kind: ShardArtifactKind,
    blockers: list[str],
) -> list[BaseModel]:
    model_types = _ROW_TYPES.get(kind)
    if model_types is None:
        return []
    rows: list[BaseModel] = []
    for shard in manifest.shards:
        if shard.artifact_kind is not kind:
            continue
        try:
            raw_rows = store.read_shard(shard)
            typed_rows: list[BaseModel] = []
            for raw_row in raw_rows:
                for model_type in model_types:
                    try:
                        typed_rows.append(model_type.model_validate(raw_row))
                    except (TypeError, ValueError):
                        continue
                    break
                else:
                    raise HistoricalArtifactError(
                        f"historical shard row does not match {kind.value} schema"
                    )
            rows.extend(typed_rows)
        except HistoricalArtifactError as exc:
            blockers.append(f"A6_ARTIFACT_UNREADABLE: {shard.shard_id}: {exc}")
    return rows


def _complete_coverage(
    coverage_status: dict[str, str],
    coverage_reports: Sequence[BaseModel],
    source_kind: HistoricalSourceKind,
    listing_id: str,
) -> bool:
    if not any(
        coverage_status.get(f"{candidate.value}:{listing_id}") == "COMPLETE"
        for candidate in _COVERAGE_KINDS[source_kind.value]
    ):
        return False
    accepted_kinds = _COVERAGE_KINDS[source_kind.value]
    return any(
        record.source_kind in accepted_kinds
        and record.listing_id == listing_id
        and record.status.value == "COMPLETE"
        and record.evidence_basis in _COVERAGE_BASES[record.source_kind]
        and (
            record.expected_session_count > 0
            or record.evidence_basis is CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE
        )
        for report in coverage_reports
        for record in report.records
    )


def _full_calendar_years(start: date, end: date) -> list[int]:
    return [
        year
        for year in range(start.year, end.year + 1)
        if start <= date(year, 1, 1) and end >= date(year, 12, 31)
    ]


def validate_private_acceptance(
    batch: RawAcquisitionBatchManifestV1,
    manifest: HistoricalDatasetManifest,
    raw_store: RawBlobStore,
    artifact_store: HistoricalArtifactStore,
    *,
    probe_report: AcquisitionReadinessReportV1 | None = None,
) -> PrivateAcceptanceReportV1:
    """Audit A6 using only persisted artifacts and the prior live probe report.

    This function intentionally does not run a provider, resolve credentials,
    or make a network request.  A report with blockers is still persisted by
    the CLI so an unresolved acceptance state is auditable.
    """

    plan: HistoricalAcquisitionPlanV1 = batch.plan
    blockers: list[str] = []
    checks: dict[str, Literal["PASS", "BLOCKED"]] = {}

    def record_check(name: str, issues: Sequence[str]) -> None:
        if issues:
            checks[name] = _CHECK_BLOCKED
            blockers.extend(issues)
        else:
            checks[name] = _CHECK_PASS

    ingestion_compiler = HistoricalIngestionCompiler(
        raw_store=raw_store,
        artifact_store=artifact_store,
    )
    validation = HistoricalDatasetCompiler(manifest, artifact_store).validation_summary()
    record_check(
        "A6_DATASET_VALIDATION",
        [f"DATASET_VALIDATION_ERROR: {error}" for error in validation.errors],
    )

    replay_issues: list[str] = []
    replay_verified = False
    try:
        replayed = ingestion_compiler.compile_with_replay_check(batch)
    except Exception as exc:  # compiler errors are converted to an auditable blocker
        replay_issues.append(f"OFFLINE_REPLAY_FAILED: {exc}")
    else:
        replay_verified = True
        if replayed.content_sha256 != manifest.content_sha256:
            replay_issues.append(
                "OFFLINE_REPLAY_MANIFEST_MISMATCH: "
                f"{replayed.content_sha256} != {manifest.content_sha256}"
            )
        expected_shards = sorted(
            (item.shard_id, item.content_sha256, item.row_count)
            for item in replayed.shards
        )
        actual_shards = sorted(
            (item.shard_id, item.content_sha256, item.row_count)
            for item in manifest.shards
        )
        if expected_shards != actual_shards:
            replay_issues.append("OFFLINE_REPLAY_SHARD_MISMATCH: shard identities differ")
    record_check("A6_OFFLINE_REPLAY", replay_issues)

    probe_issues: list[str] = []
    probe_reports: list[SourceProbeReportV1] = []
    probe_report_id: str | None = None
    probe_network_used = False
    if probe_report is None:
        probe_issues.append("SOURCE_PROBE_REPORT_MISSING: no persisted probe report was supplied")
    else:
        probe_report_id = probe_report.report_id
        probe_network_used = probe_report.network_used
        if probe_report.plan_id != plan.plan_id:
            probe_issues.append("SOURCE_PROBE_REPORT_SCOPE_MISMATCH: plan_id")
        if not probe_report.network_used:
            probe_issues.append(
                "SOURCE_PROBE_NETWORK_UNVERIFIED: probe report does not record live network use"
            )
        probe_reports = list(probe_report.probe_reports)
        reports_by_request: dict[str, list[SourceProbeReportV1]] = {}
        for report in probe_reports:
            reports_by_request.setdefault(report.request_id, []).append(report)
        for request in plan.requests:
            matches = reports_by_request.get(request.request_id, [])
            if not matches:
                probe_issues.append("SOURCE_PROBE_MISSING: " + request.request_id)
            elif len(matches) != 1:
                probe_issues.append("SOURCE_PROBE_DUPLICATE: " + request.request_id)
            for report in matches:
                if report.status != "PASS":
                    probe_issues.extend(
                        report.blockers or ["SOURCE_PROBE_FAILED: " + report.source_id]
                    )
                elif report.blockers:
                    probe_issues.extend(report.blockers)
    readiness = build_readiness_report(
        plan,
        probe_reports=probe_reports,
        batch=batch,
        raw_store=raw_store,
        validation_summary=validation,
        compiled_manifest=manifest,
        network_used=False,
    )
    probe_issues.extend(readiness.blockers)
    record_check("A6_PROBES_AUTHORIZATION_AND_H_CAPABILITY", probe_issues)

    target = plan.target
    target_issues: list[str] = []
    a_listings = [
        listing_id
        for listing_id in target.listing_ids
        if target.listing_markets.get(listing_id) is Market.A
    ]
    h_listings = [
        listing_id
        for listing_id in target.listing_ids
        if target.listing_markets.get(listing_id) is Market.H
    ]
    if Market.A not in target.markets or not a_listings:
        target_issues.append("A6_TARGET_A_LISTING_UNVERIFIED: target lacks an explicit A listing")
    if Market.H not in target.markets or not h_listings:
        target_issues.append("A6_TARGET_H_LISTING_UNVERIFIED: target lacks an explicit H listing")
    if len(_full_calendar_years(target.start_date, target.end_date)) < 2:
        target_issues.append(
            "A6_TARGET_PERIOD_INSUFFICIENT: target must contain two complete calendar years"
        )
    record_check("A6_TARGET_SCOPE_AND_PERIOD", target_issues)

    artifact_issues: list[str] = []
    lifecycle_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.LISTING_LIFECYCLE,
        artifact_issues,
    )
    market_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.MARKET_BAR,
        artifact_issues,
    )
    action_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.CORPORATE_ACTION,
        artifact_issues,
    )
    benchmark_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.BENCHMARK_OBSERVATION,
        artifact_issues,
    )
    membership_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.UNIVERSE_MEMBERSHIP,
        artifact_issues,
    )
    fx_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.FX_OBSERVATION,
        artifact_issues,
    )
    filing_rows = _read_rows(
        manifest,
        artifact_store,
        ShardArtifactKind.FILING_DOCUMENT,
        artifact_issues,
    )
    record_check("A6_ARTIFACT_READS", artifact_issues)

    calendar_issues: list[str] = []
    missing_calendars = sorted(set(target.listing_ids) - set(target.calendar_ids))
    calendar_issues.extend(
        "A6_CALENDAR_UNVERIFIED: " + listing_id for listing_id in missing_calendars
    )
    lifecycle_by_listing = {
        row.listing_id: row
        for row in lifecycle_rows
        if getattr(row, "listing_id", None) is not None
    }
    for listing_id in target.listing_ids:
        lifecycle = lifecycle_by_listing.get(listing_id)
        expected_calendar = target.calendar_ids.get(listing_id)
        if lifecycle is None:
            calendar_issues.append("A6_LIFECYCLE_MISSING: " + listing_id)
        elif expected_calendar is not None and lifecycle.trading_calendar != expected_calendar:
            calendar_issues.append("A6_CALENDAR_MISMATCH: " + listing_id)
    price_requests = [
        request
        for request in plan.requests
        if request.source_kind is HistoricalSourceKind.PRICES
    ]
    for listing_id in target.listing_ids:
        if not any(
            request.expected_sessions_by_listing is not None
            and listing_id in request.expected_sessions_by_listing
            and request.expected_sessions_by_listing[listing_id]
            for request in price_requests
        ):
            calendar_issues.append("A6_EXPECTED_TRADING_SESSIONS_MISSING: " + listing_id)
    record_check("A6_CALENDARS_MISSINGNESS_AND_LIFECYCLE", calendar_issues)

    coverage_issues: list[str] = []
    for source_kind in _COVERAGE_KINDS:
        if source_kind == "UNIVERSE_MEMBERSHIP":
            continue
        enum_kind = HistoricalSourceKind(source_kind)
        for listing_id in target.listing_ids:
            if not _complete_coverage(
                validation.coverage_status,
                manifest.coverage_reports,
                enum_kind,
                listing_id,
            ):
                coverage_issues.append(
                    f"A6_COVERAGE_INCOMPLETE: {source_kind}:{listing_id}"
                )
    record_check("A6_CATEGORY_COVERAGE", coverage_issues)

    terminal_case_issues: list[str] = []
    has_terminal_case = any(
        (
            getattr(row, "terminal_outcome", None) is not None
            and (
                getattr(row, "terminal_outcome") is not HistoricalTerminalOutcome.ACTIVE
                or bool(getattr(row, "code_changes", []))
            )
        )
        or (
            getattr(row, "terminal_outcome", None) is None
            and getattr(row, "terminal_status", "ACTIVE") != "ACTIVE"
        )
        for row in lifecycle_rows
        if getattr(row, "listing_id", None) is not None
    )
    has_missingness_case = any(
        bool(getattr(row, "suspended", False))
        for row in market_rows
        if getattr(row, "listing_id", None) is not None
    )
    if not has_terminal_case and not has_missingness_case:
        terminal_case_issues.append(
            "A6_TERMINAL_CASE_UNPROVEN: no source-backed terminal, delisted, code-change, "
            "or prolonged-suspension case is retained"
        )
    record_check("A6_TERMINAL_OR_SUSPENSION_CASE", terminal_case_issues)

    terminal_action_listing_ids = {
        getattr(row, "listing_id", None)
        for row in action_rows
        if getattr(row, "listing_id", None) is not None
        and getattr(getattr(row, "action_type", None), "value", None) == "TERMINAL_VALUE"
    }
    terminal_economics_issues: list[str] = []
    for row in lifecycle_rows:
        listing_id = getattr(row, "listing_id", None)
        if listing_id is None:
            continue
        outcome = getattr(row, "terminal_outcome", None)
        if outcome is not None:
            if outcome in {
                HistoricalTerminalOutcome.UNRESOLVED_TERMINAL,
                HistoricalTerminalOutcome.UNKNOWN,
            }:
                terminal_economics_issues.append(
                    "A6_TERMINAL_ECONOMICS_UNRESOLVED: " + listing_id
                )
            elif (
                outcome not in {
                    HistoricalTerminalOutcome.ACTIVE,
                    HistoricalTerminalOutcome.PROLONGED_SUSPENSION,
                }
                and listing_id not in terminal_action_listing_ids
            ):
                terminal_economics_issues.append(
                    "A6_TERMINAL_VALUE_MISSING: " + listing_id
                )
        else:
            terminal_status = getattr(row, "terminal_status", "ACTIVE")
            if terminal_status == "UNKNOWN":
                terminal_economics_issues.append(
                    "A6_TERMINAL_ECONOMICS_UNRESOLVED: " + listing_id
                )
            elif (
                terminal_status in {"DELISTED", "TERMINAL"}
                and listing_id not in terminal_action_listing_ids
            ):
                terminal_economics_issues.append(
                    "A6_TERMINAL_VALUE_MISSING: " + listing_id
                )
    record_check("A6_TERMINAL_ECONOMICS", terminal_economics_issues)

    benchmark_fx_issues: list[str] = []
    if not any(
        target.start_date <= row.observation_date <= target.end_date
        for row in benchmark_rows
        if getattr(row, "observation_date", None) is not None
    ):
        benchmark_fx_issues.append("A6_BENCHMARK_MISSING: no in-scope benchmark observation")
    fx_by_listing = {
        row.listing_id
        for row in fx_rows
        if getattr(row, "listing_id", None) is not None
        and target.start_date <= row.observation_date <= target.end_date
    }
    for listing_id in target.listing_ids:
        if listing_id not in fx_by_listing:
            benchmark_fx_issues.append("A6_FX_PATH_MISSING: " + listing_id)
    record_check("A6_BENCHMARK_AND_FX_PATH", benchmark_fx_issues)

    source_by_id = {source.source_id: source for source in manifest.source_descriptors}
    filing_issues: list[str] = []
    official_markets = {
        row.market
        for row in filing_rows
        if getattr(row, "market", None) is not None
        and source_by_id.get(row.source_artifact_id) is not None
        and source_by_id[row.source_artifact_id].authority in _OFFICIAL_AUTHORITIES
    }
    for market, label in ((Market.A, "A"), (Market.H, "H")):
        if market not in official_markets:
            filing_issues.append("A6_OFFICIAL_FILING_MISSING: " + label)
    record_check("A6_OFFICIAL_FILING_PER_MARKET", filing_issues)

    membership_issues: list[str] = []
    if target.membership_claim == "HISTORICAL":
        membership_listing_ids = {
            getattr(row, "listing_id", None)
            for row in membership_rows
            if getattr(row, "listing_id", None) in target.listing_ids
            and getattr(row, "included", False)
        }
        for listing_id in target.listing_ids:
            if listing_id not in membership_listing_ids:
                membership_issues.append("A6_HISTORICAL_MEMBERSHIP_MISSING: " + listing_id)
            elif not _complete_coverage(
                validation.coverage_status,
                manifest.coverage_reports,
                HistoricalSourceKind.UNIVERSE_MEMBERSHIP,
                listing_id,
            ):
                membership_issues.append(
                    "A6_HISTORICAL_MEMBERSHIP_COVERAGE_INCOMPLETE: " + listing_id
                )
    record_check("A6_HISTORICAL_MEMBERSHIP", membership_issues)

    actions_issues: list[str] = []
    if not manifest.limitations:
        actions_issues.append("A6_SOURCE_LIMITATIONS_MISSING: manifest has no limitations")
    has_explicit_action_scope = any(
        record.status.value == "COMPLETE"
        and record.evidence_basis is CoverageEvidenceBasis.EXPLICIT_SOURCE_SCOPE
        for report in manifest.coverage_reports
        for record in report.records
        if record.source_kind is HistoricalSourceKind.CORPORATE_ACTIONS
    )
    if not action_rows and not has_explicit_action_scope:
        actions_issues.append("A6_CORPORATE_ACTIONS_MISSING: no action evidence is retained")
    record_check("A6_ACTIONS_AND_LIMITATIONS", actions_issues)

    reconciliation_issues = (
        ["A6_RECONCILIATION_MISSING: no independent reconciliation report passes"]
        if not any(report.status.value == "PASS" for report in manifest.reconciliation_reports)
        else []
    )
    record_check("A6_INDEPENDENT_RECONCILIATION", reconciliation_issues)

    unique_blockers = sorted(set(blockers))
    return PrivateAcceptanceReportV1.build(
        plan_id=plan.plan_id,
        target_id=target.target_id,
        dataset_id=manifest.dataset_id,
        probe_report_id=probe_report_id,
        probe_network_used=probe_network_used,
        offline_replay_verified=replay_verified,
        accepted=not unique_blockers,
        checks=checks,
        blockers=unique_blockers,
    )


__all__ = ["PrivateAcceptanceReportV1", "validate_private_acceptance"]
