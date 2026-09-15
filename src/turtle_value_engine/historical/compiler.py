"""Offline compiler from source-aware shards to the Phase 5 replay boundary."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from turtle_value_engine.backtest import (
    BacktestDatasetManifest,
    BenchmarkObservation,
    CorporateAction,
    DatasetValidationError,
    FXObservation,
    HistoricalAvailability,
    HistoricalDecisionArtifact,
    ListingLifecycle,
    MarketBar,
    UniverseCoverage,
    UniverseMembership,
    build_decision_snapshot,
    validate_decision_artifact,
    validate_manifest,
)
from turtle_value_engine.backtest.contracts import DecisionSnapshot

from .archive import HistoricalResearchArchiveError, validate_research_archive
from .contracts import (
    ArchiveArtifactType,
    HistoricalAvailabilityRecord,
    HistoricalDatasetManifest,
    HistoricalFXObservation,
    HistoricalListingLifecycle,
    HistoricalMembershipInterval,
    HistoricalSourceDescriptor,
    HistoricalSourceKind,
    HistoricalTargetScope,
    HistoricalTerminalOutcome,
    ShardArtifactKind,
)
from .store import HistoricalArtifactError, HistoricalArtifactStore


class HistoricalDatasetValidationError(ValueError):
    """Raised when a source-aware historical dataset cannot be compiled safely."""

    def __init__(self, message: str, summary: HistoricalValidationSummary | None = None):
        super().__init__(message)
        self.summary = summary


class HistoricalValidationSummary(BaseModel):
    """Machine-readable validation output suitable for a coverage report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: str = "historical_validation_summary_v1"
    dataset_id: str
    valid: bool
    production_eligible: bool
    shard_rows: dict[str, int] = Field(default_factory=dict)
    coverage_status: dict[str, str] = Field(default_factory=dict)
    production_blockers: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_MODEL_BY_KIND: dict[ShardArtifactKind, type[BaseModel]] = {
    ShardArtifactKind.LISTING_LIFECYCLE: HistoricalListingLifecycle,
    ShardArtifactKind.UNIVERSE_MEMBERSHIP: HistoricalMembershipInterval,
    ShardArtifactKind.AVAILABILITY: HistoricalAvailabilityRecord,
    ShardArtifactKind.MARKET_BAR: MarketBar,
    ShardArtifactKind.CORPORATE_ACTION: CorporateAction,
    ShardArtifactKind.FX_OBSERVATION: HistoricalFXObservation,
    ShardArtifactKind.BENCHMARK_OBSERVATION: BenchmarkObservation,
    ShardArtifactKind.DECISION_ARTIFACT: HistoricalDecisionArtifact,
}

_SOURCE_KIND_BY_SHARD: dict[ShardArtifactKind, set[HistoricalSourceKind]] = {
    ShardArtifactKind.LISTING_LIFECYCLE: {
        HistoricalSourceKind.LISTING_LIFECYCLE,
        HistoricalSourceKind.DELISTINGS,
    },
    ShardArtifactKind.UNIVERSE_MEMBERSHIP: {HistoricalSourceKind.UNIVERSE_MEMBERSHIP},
    ShardArtifactKind.AVAILABILITY: set(HistoricalSourceKind),
    ShardArtifactKind.MARKET_BAR: {HistoricalSourceKind.PRICES},
    ShardArtifactKind.CORPORATE_ACTION: {HistoricalSourceKind.CORPORATE_ACTIONS},
    ShardArtifactKind.FX_OBSERVATION: {HistoricalSourceKind.FX},
    ShardArtifactKind.BENCHMARK_OBSERVATION: {HistoricalSourceKind.BENCHMARK},
    ShardArtifactKind.DECISION_ARTIFACT: {
        HistoricalSourceKind.FILINGS,
        HistoricalSourceKind.RESEARCH_ARCHIVE,
        HistoricalSourceKind.PRICES,
    },
}


def _row_id(kind: ShardArtifactKind, row: BaseModel) -> str:
    field_by_kind = {
        ShardArtifactKind.LISTING_LIFECYCLE: "listing_id",
        ShardArtifactKind.UNIVERSE_MEMBERSHIP: "membership_id",
        ShardArtifactKind.AVAILABILITY: "artifact_id",
        ShardArtifactKind.MARKET_BAR: "bar_id",
        ShardArtifactKind.CORPORATE_ACTION: "action_id",
        ShardArtifactKind.FX_OBSERVATION: "observation_id",
        ShardArtifactKind.BENCHMARK_OBSERVATION: "observation_id",
        ShardArtifactKind.DECISION_ARTIFACT: "artifact_id",
    }
    return str(getattr(row, field_by_kind[kind]))


def _row_listing(row: BaseModel) -> str | None:
    value = getattr(row, "listing_id", None)
    return str(value) if value is not None else None


def _row_date(kind: ShardArtifactKind, row: BaseModel) -> date | None:
    field_by_kind = {
        ShardArtifactKind.LISTING_LIFECYCLE: "listing_date",
        ShardArtifactKind.UNIVERSE_MEMBERSHIP: "valid_from",
        ShardArtifactKind.AVAILABILITY: None,
        ShardArtifactKind.MARKET_BAR: "trading_date",
        ShardArtifactKind.CORPORATE_ACTION: "effective_date",
        ShardArtifactKind.FX_OBSERVATION: "observation_date",
        ShardArtifactKind.BENCHMARK_OBSERVATION: "observation_date",
        ShardArtifactKind.DECISION_ARTIFACT: "as_of",
    }
    field_name = field_by_kind[kind]
    if field_name is None:
        return None
    return getattr(row, field_name)


def _source_hash(row: BaseModel) -> str | None:
    value = getattr(row, "source_hash", None)
    return str(value) if value is not None else None


def _scope_source_kind(kind: HistoricalSourceKind) -> set[HistoricalSourceKind]:
    if kind is HistoricalSourceKind.LISTING_LIFECYCLE:
        return {HistoricalSourceKind.LISTING_LIFECYCLE, HistoricalSourceKind.DELISTINGS}
    return {kind}


class HistoricalDatasetCompiler:
    """Validate frozen shards and project them into Phase 5 contracts."""

    def __init__(
        self,
        manifest: HistoricalDatasetManifest,
        store: HistoricalArtifactStore,
    ) -> None:
        self.manifest = manifest
        self.store = store

    def validation_summary(
        self,
        *,
        require_production: bool = False,
    ) -> HistoricalValidationSummary:
        errors: list[str] = []
        warnings: list[str] = []
        shard_rows: dict[str, int] = {}
        coverage_status: dict[str, str] = {}
        rows_by_kind: dict[ShardArtifactKind, list[BaseModel]] = defaultdict(list)

        try:
            manifest = HistoricalDatasetManifest.model_validate(
                self.manifest.model_dump(
                    mode="python",
                    exclude_unset=True,
                    warnings=False,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            return HistoricalValidationSummary(
                dataset_id=getattr(self.manifest, "dataset_id", "invalid"),
                valid=False,
                production_eligible=False,
                production_blockers=[f"invalid historical manifest: {exc}"],
                errors=[f"invalid historical manifest: {exc}"],
            )

        sources = {item.source_id: item for item in manifest.source_descriptors}
        if len(sources) != len(manifest.source_descriptors):
            errors.append("source descriptors contain duplicate source IDs")

        for required in manifest.target.required_source_kinds:
            if not any(
                item.source_kind in _scope_source_kind(required) for item in sources.values()
            ):
                errors.append(f"required source category is missing: {required.value}")

        for source in sources.values():
            if source.source_kind is HistoricalSourceKind.UNIVERSE_MEMBERSHIP and (
                source.is_current_snapshot
            ):
                errors.append(
                    "current-constituent substitution is not historical membership: "
                    + source.source_id
                )
            if not _covers_target(source, manifest.target):
                warnings.append(f"source coverage does not span target: {source.source_id}")
            if require_production and (
                source.license_status.value in {"UNKNOWN", "PROHIBITED"}
                or source.authority.value in {"UNKNOWN", "FIXTURE"}
                or source.license_evidence_uri is None
                or source.license_evidence_sha256 is None
                or (
                    source.license_status.value == "RESTRICTED_INTERNAL"
                    and source.access_grant_reference is None
                )
            ):
                errors.append(
                    "source authority/licensing cannot support a production claim: "
                    + source.source_id
                )
            if require_production and not source.historical_capable:
                errors.append("source is not declared historical-capable: " + source.source_id)

        for report in manifest.coverage_reports:
            for record in report.records:
                key = f"{record.source_kind.value}:{record.listing_id}"
                previous = coverage_status.get(key)
                status = record.status.value
                if previous == "UNKNOWN" or status == "UNKNOWN":
                    coverage_status[key] = "UNKNOWN"
                elif previous == "PARTIAL" or status == "PARTIAL":
                    coverage_status[key] = "PARTIAL"
                else:
                    coverage_status[key] = status
                if record.listing_id not in manifest.target.listing_ids:
                    errors.append(
                        f"coverage report references listing outside target: {record.listing_id}"
                    )
                if not (
                    manifest.target.start_date
                    <= record.period_start
                    <= record.period_end
                    <= manifest.target.end_date
                ):
                    errors.append(
                        "coverage report period lies outside target: "
                        f"{record.source_kind.value}:{record.listing_id}"
                    )
                for source_id in record.source_artifact_ids:
                    if source_id == "UNRESOLVED_SOURCE" and record.status.value == "UNKNOWN":
                        continue
                    source = sources.get(source_id)
                    if source is None:
                        errors.append(
                            f"coverage report references unknown source artifact: {source_id}"
                        )
                    elif source.source_kind not in _scope_source_kind(record.source_kind):
                        errors.append(
                            "coverage report/source category mismatch: "
                            f"{record.source_kind.value}:{record.listing_id} -> {source_id}"
                        )
                if record.status.value != "COMPLETE":
                    warnings.append(
                        f"incomplete coverage for {record.source_kind.value}:{record.listing_id}"
                    )

        for shard in manifest.shards:
            source = sources.get(shard.source_artifact_id)
            if source is None:
                errors.append(f"shard references unknown source artifact: {shard.shard_id}")
                continue
            if source.source_kind not in _SOURCE_KIND_BY_SHARD[shard.artifact_kind]:
                errors.append(
                    "shard/source category mismatch: "
                    f"{shard.shard_id} -> {source.source_kind.value}"
                )
            model_type = _MODEL_BY_KIND[shard.artifact_kind]
            try:
                rows = self.store.read_shard(shard, model_type=model_type)
            except HistoricalArtifactError as exc:
                errors.append(str(exc))
                continue
            shard_rows[shard.shard_id] = len(rows)
            rows_by_kind[shard.artifact_kind].extend(rows)
            seen_ids: set[str] = set()
            for row in rows:
                row_id = _row_id(shard.artifact_kind, row)
                if row_id in seen_ids:
                    errors.append(f"duplicate row ID in shard {shard.shard_id}: {row_id}")
                seen_ids.add(row_id)
                listing_id = _row_listing(row)
                if listing_id is not None and listing_id not in shard.listing_scope:
                    errors.append(f"row lies outside shard listing scope: {row_id}")
                if listing_id is not None and listing_id not in manifest.target.listing_ids:
                    errors.append(f"row references listing outside target: {row_id}")
                row_date = _row_date(shard.artifact_kind, row)
                if row_date is not None and not (
                    shard.date_start <= row_date <= shard.date_end
                ):
                    errors.append(f"row lies outside shard date range: {row_id}")
                if row_date is not None and shard.artifact_kind not in {
                    ShardArtifactKind.LISTING_LIFECYCLE,
                    ShardArtifactKind.UNIVERSE_MEMBERSHIP,
                } and not (manifest.target.start_date <= row_date <= manifest.target.end_date):
                    errors.append(f"row lies outside target date range: {row_id}")
                row_hash = _source_hash(row)
                if row_hash is not None and row_hash != source.content_sha256:
                    errors.append(f"row/source hash mismatch: {row_id}")
                row_source_id = getattr(row, "source_artifact_id", None)
                if row_source_id is not None and row_source_id != source.source_id:
                    errors.append(f"row/source identity mismatch: {row_id}")

        observed_dates: dict[tuple[HistoricalSourceKind, str], set[date]] = defaultdict(set)
        for bar in rows_by_kind[ShardArtifactKind.MARKET_BAR]:
            observed_dates[(HistoricalSourceKind.PRICES, bar.listing_id)].add(
                bar.trading_date
            )
        for action in rows_by_kind[ShardArtifactKind.CORPORATE_ACTION]:
            observed_dates[(HistoricalSourceKind.CORPORATE_ACTIONS, action.listing_id)].add(
                action.effective_date
            )
        for report in manifest.coverage_reports:
            for record in report.records:
                if record.source_kind not in {
                    HistoricalSourceKind.PRICES,
                    HistoricalSourceKind.CORPORATE_ACTIONS,
                }:
                    continue
                observed = {
                    item
                    for item in observed_dates[(record.source_kind, record.listing_id)]
                    if record.period_start <= item <= record.period_end
                }
                if len(observed) != record.observed_session_count:
                    errors.append(
                        "coverage observed count does not match frozen rows: "
                        f"{record.source_kind.value}:{record.listing_id}"
                    )

        lifecycles = {
            item.listing_id: item
            for item in rows_by_kind[ShardArtifactKind.LISTING_LIFECYCLE]
        }
        if len(lifecycles) != len(rows_by_kind[ShardArtifactKind.LISTING_LIFECYCLE]):
            errors.append("listing lifecycle rows contain duplicate listing IDs")
        for listing_id in manifest.target.listing_ids:
            if listing_id not in lifecycles:
                errors.append(f"target listing has no lifecycle row: {listing_id}")
        for listing_id, lifecycle in lifecycles.items():
            if listing_id not in manifest.target.listing_ids:
                errors.append(f"lifecycle references listing outside target: {listing_id}")
            if lifecycle.market not in manifest.target.markets:
                errors.append(f"lifecycle market lies outside target markets: {listing_id}")
            expected_calendar = manifest.target.calendar_ids.get(listing_id)
            if expected_calendar is not None and expected_calendar != lifecycle.trading_calendar:
                errors.append(f"listing calendar does not match target scope: {listing_id}")
            for change in lifecycle.code_changes:
                source = sources.get(change.source_artifact_id)
                if source is None:
                    errors.append(
                        "code change references unknown source artifact: "
                        + change.source_artifact_id
                    )
                elif change.source_hash != source.content_sha256:
                    errors.append("code change/source hash mismatch: " + listing_id)
                elif source.source_kind not in {
                    HistoricalSourceKind.LISTING_LIFECYCLE,
                    HistoricalSourceKind.DELISTINGS,
                }:
                    errors.append(
                        "code change source category is not lifecycle/delisting: "
                        + listing_id
                    )

        availability = {
            item.artifact_id: item for item in rows_by_kind[ShardArtifactKind.AVAILABILITY]
        }
        if len(availability) != len(rows_by_kind[ShardArtifactKind.AVAILABILITY]):
            errors.append("availability rows contain duplicate artifact IDs")
        artifact_kind_by_id: dict[str, str] = {}
        for kind, rows in rows_by_kind.items():
            if kind is ShardArtifactKind.AVAILABILITY:
                continue
            for row in rows:
                row_id = _row_id(kind, row)
                previous_kind = artifact_kind_by_id.get(row_id)
                if previous_kind is not None:
                    errors.append(
                        "artifact ID is duplicated across frozen rows: " + row_id
                    )
                else:
                    artifact_kind_by_id[row_id] = kind.value
        known_artifact_ids = set(artifact_kind_by_id)
        if manifest.research_archive is not None:
            for item in manifest.research_archive.artifacts:
                known_artifact_ids.add(item.artifact_id)
                if item.artifact_id in artifact_kind_by_id:
                    errors.append(
                        "research artifact ID collides with frozen row: " + item.artifact_id
                    )
                artifact_kind_by_id[item.artifact_id] = item.artifact_type.value
        for record in availability.values():
            if record.artifact_id not in known_artifact_ids:
                errors.append(
                    "availability references unrelated artifact: " + record.artifact_id
                )
            expected_kind = artifact_kind_by_id.get(record.artifact_id)
            if expected_kind is not None and record.artifact_kind != expected_kind:
                errors.append(
                    "availability artifact kind does not match referenced artifact: "
                    + record.artifact_id
                )
        memberships = rows_by_kind[ShardArtifactKind.UNIVERSE_MEMBERSHIP]
        membership_ids: set[str] = set()
        membership_listings: set[str] = set()
        for membership in memberships:
            membership_id = membership.membership_id
            if membership_id in membership_ids:
                errors.append(f"duplicate membership ID: {membership_id}")
            membership_ids.add(membership_id)
            if membership.included and (
                membership.valid_from <= manifest.target.end_date
                and (
                    membership.valid_to is None
                    or membership.valid_to >= manifest.target.start_date
                )
            ):
                membership_listings.add(membership.listing_id)
            lifecycle = lifecycles.get(membership.listing_id)
            if lifecycle is None:
                continue
            if membership.universe_id != manifest.target.universe_id:
                errors.append(f"membership universe mismatch: {membership_id}")
            if membership.valid_from < lifecycle.listing_date:
                errors.append(f"membership precedes listing date: {membership_id}")
            if lifecycle.terminal_date is not None and (
                membership.valid_to is None or membership.valid_to > lifecycle.terminal_date
            ):
                errors.append(f"membership extends beyond terminal date: {membership_id}")
            availability_record = availability.get(membership.availability_id)
            if availability_record is None:
                errors.append(f"membership has dangling availability: {membership_id}")
            elif availability_record.artifact_kind != "UNIVERSE_MEMBERSHIP":
                errors.append(f"membership availability kind mismatch: {membership_id}")

        memberships_by_listing: dict[str, list[HistoricalMembershipInterval]] = defaultdict(list)
        for membership in memberships:
            if membership.included:
                memberships_by_listing[membership.listing_id].append(membership)
        for listing_id, intervals in memberships_by_listing.items():
            ordered = sorted(intervals, key=lambda item: item.valid_from)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if previous.valid_to is None or previous.valid_to >= current.valid_from:
                    errors.append("overlapping historical membership intervals: " + listing_id)

        for listing_id in manifest.target.listing_ids:
            if listing_id not in membership_listings:
                errors.append(
                    "target listing has no source-backed membership interval at target start: "
                    + listing_id
                )

        for fx in rows_by_kind[ShardArtifactKind.FX_OBSERVATION]:
            lifecycle = lifecycles.get(fx.listing_id)
            if lifecycle is None:
                errors.append(f"FX observation references unknown listing: {fx.observation_id}")
            elif fx.base_currency != lifecycle.currency:
                errors.append(
                    "FX base currency does not match listing currency: " + fx.observation_id
                )

        for action in rows_by_kind[ShardArtifactKind.CORPORATE_ACTION]:
            lifecycle = lifecycles.get(action.listing_id)
            if lifecycle is None:
                continue
            if action.action_type.value != "TERMINAL_VALUE":
                continue
            if lifecycle.terminal_outcome in {
                HistoricalTerminalOutcome.ACTIVE,
                HistoricalTerminalOutcome.PROLONGED_SUSPENSION,
                HistoricalTerminalOutcome.UNRESOLVED_TERMINAL,
                HistoricalTerminalOutcome.UNKNOWN,
            }:
                errors.append(
                    "terminal value is not permitted for unresolved or non-terminal listing: "
                    + action.action_id
                )

        terminal_scope_errors = _terminal_scope_errors(
            target=manifest.target,
            lifecycles=lifecycles.values(),
            actions=rows_by_kind[ShardArtifactKind.CORPORATE_ACTION],
        )
        if require_production or manifest.target.membership_claim == "HISTORICAL":
            errors.extend(terminal_scope_errors)

        decisions = rows_by_kind[ShardArtifactKind.DECISION_ARTIFACT]
        decision_ids = {item.artifact_id for item in decisions}
        if len(decision_ids) != len(decisions):
            errors.append("decision artifact rows contain duplicate IDs")
        for decision in decisions:
            if decision.listing_id not in lifecycles:
                errors.append(
                    "decision artifact references unknown listing: "
                    f"{decision.artifact_id}"
                )
            try:
                validate_decision_artifact(
                    decision,
                    decision_time=decision.decision_time,
                    allow_undated_evidence=False,
                )
            except (DatasetValidationError, ValueError) as exc:
                errors.append(f"invalid decision availability {decision.artifact_id}: {exc}")

        if manifest.research_archive is not None:
            try:
                validate_research_archive(
                    manifest.research_archive,
                    decision_times={item.artifact_id: item.decision_time for item in decisions},
                )
            except (HistoricalResearchArchiveError, TypeError, ValueError) as exc:
                errors.append(f"invalid historical research archive: {exc}")
            archive_source_hashes = {
                source.content_sha256
                for source in sources.values()
                if source.source_kind is HistoricalSourceKind.FILINGS
            }
            archive_document_hashes = set(archive_source_hashes)
            archive_document_hashes.update(
                artifact.content_sha256
                for artifact in manifest.research_archive.artifacts
                if artifact.artifact_type
                in {
                    ArchiveArtifactType.FILING,
                    ArchiveArtifactType.FILING_DOCUMENT,
                    ArchiveArtifactType.FILING_EXTRACTION,
                    ArchiveArtifactType.FILING_EVIDENCE,
                }
            )
            for artifact in manifest.research_archive.artifacts:
                if artifact.listing_id not in manifest.target.listing_ids:
                    errors.append(
                        "research artifact references listing outside target: "
                        + artifact.artifact_id
                    )
                for source_id in artifact.source_artifact_ids:
                    if source_id not in sources:
                        errors.append(
                            "research artifact references unknown source artifact: "
                            + source_id
                        )
                for document_hash in artifact.source_document_hashes:
                    if document_hash not in archive_document_hashes:
                        errors.append(
                            "research artifact references unknown source document hash: "
                            + artifact.artifact_id
                        )
                if artifact.relative_path is None:
                    if require_production:
                        errors.append(
                            "production research archive reference has no persisted artifact path: "
                            + artifact.artifact_id
                        )
                else:
                    try:
                        payload = self.store.read_json_artifact(
                            artifact.relative_path,
                            artifact.content_sha256,
                        )
                        scope_error = _archived_json_scope_error(artifact, payload)
                        if scope_error is not None:
                            errors.append(scope_error)
                    except HistoricalArtifactError as exc:
                        errors.append(str(exc))
                if require_production and not set(artifact.source_document_hashes).intersection(
                    archive_source_hashes
                ):
                    errors.append(
                        "research artifact has no filing source descriptor hash: "
                        + artifact.artifact_id
                    )
        elif HistoricalSourceKind.RESEARCH_ARCHIVE in manifest.target.required_source_kinds:
            errors.append("target requires a historical research archive but none is declared")

        if manifest.research_archive is None:
            for decision in decisions:
                if decision.research_artifact_id is not None:
                    errors.append(
                        "decision artifact has a research reference but no archive is declared: "
                        + decision.artifact_id
                    )

        if manifest.research_archive is not None:
            bindings = {
                item.decision_artifact_id: item
                for item in manifest.research_archive.decision_bindings
            }
            for binding in manifest.research_archive.decision_bindings:
                decision = next(
                    (
                        item
                        for item in decisions
                        if item.artifact_id == binding.decision_artifact_id
                    ),
                    None,
                )
                if decision is None:
                    errors.append(
                        "research binding references unknown decision artifact: "
                        + binding.decision_artifact_id
                    )
                    continue
                if (
                    decision.listing_id != binding.listing_id
                    or decision.as_of != binding.as_of
                    or decision.decision_time != binding.decision_time
                ):
                    errors.append(
                        "decision/research binding scope mismatch: "
                        + binding.decision_artifact_id
                    )
                if (
                    decision.analysis is not None
                    and decision.analysis.analysis_id != binding.analysis_id
                ):
                    errors.append(
                        "decision/research binding analysis mismatch: "
                        + binding.decision_artifact_id
                    )
            for decision in decisions:
                if decision.research_artifact_id is None:
                    if decision.historical_business_quality_valid:
                        errors.append(
                            f"validated historical Business Quality has no research reference: "
                            f"{decision.artifact_id}"
                        )
                    continue
                binding = bindings.get(decision.artifact_id)
                if binding is None:
                    errors.append(f"decision has no research binding: {decision.artifact_id}")
                elif binding.research_artifact_id != decision.research_artifact_id:
                    errors.append(f"decision/research reference mismatch: {decision.artifact_id}")
                if decision.historical_business_quality_valid and (
                    binding is None or binding.business_quality_artifact_id is None
                ):
                    errors.append(
                        "validated historical Business Quality has no archive binding: "
                        + decision.artifact_id
                    )

        for report in manifest.reconciliation_reports:
            for source_id in (report.canonical_source_id, report.independent_source_id):
                if source_id not in sources:
                    errors.append(
                        "reconciliation references unknown source artifact: " + source_id
                    )
            for comparison in report.comparisons:
                if comparison.canonical_source_id != report.canonical_source_id:
                    errors.append("reconciliation canonical source identity mismatch")
                if comparison.independent_source_id != report.independent_source_id:
                    errors.append("reconciliation independent source identity mismatch")
                if comparison.listing_id not in manifest.target.listing_ids:
                    errors.append(
                        "reconciliation references listing outside target: "
                        + comparison.listing_id
                    )
                if not (
                    manifest.target.start_date
                    <= comparison.observation_date
                    <= manifest.target.end_date
                ):
                    errors.append(
                        "reconciliation observation lies outside target: "
                        + comparison.comparison_id
                    )

        production_blockers = _production_scope_blockers(
            manifest.target,
            sources,
            manifest.coverage_reports,
            manifest.reconciliation_reports,
            terminal_scope_errors=terminal_scope_errors,
        )
        production_eligible = not errors and not production_blockers
        if require_production and not production_eligible:
            errors.append(
                "declared target does not meet the production historical coverage contract"
            )
        if manifest.target.membership_claim == "HISTORICAL" and not production_eligible:
            errors.append("HISTORICAL claim is not supported by complete auditable evidence")

        summary = HistoricalValidationSummary(
            dataset_id=manifest.dataset_id,
            valid=not errors,
            production_eligible=production_eligible,
            shard_rows=shard_rows,
            coverage_status=coverage_status,
            production_blockers=production_blockers,
            errors=errors,
            warnings=sorted(set(warnings)),
        )
        return summary

    def validate(
        self,
        *,
        require_production: bool = False,
        raise_on_error: bool = True,
    ) -> HistoricalValidationSummary:
        summary = self.validation_summary(require_production=require_production)
        if raise_on_error and summary.errors:
            raise HistoricalDatasetValidationError(
                "; ".join(summary.errors),
                summary=summary,
            )
        return summary

    def compile_backtest_manifest(
        self,
        *,
        require_production: bool = False,
    ) -> BacktestDatasetManifest:
        """Compile only after every source-aware reference has passed validation."""

        self.validate(require_production=require_production)
        rows_by_kind: dict[ShardArtifactKind, list[BaseModel]] = defaultdict(list)
        for shard in self.manifest.shards:
            rows_by_kind[shard.artifact_kind].extend(
                self.store.read_shard(shard, model_type=_MODEL_BY_KIND[shard.artifact_kind])
            )

        target = self.manifest.target
        lifecycles = [
            _to_backtest_lifecycle(item)
            for item in rows_by_kind[ShardArtifactKind.LISTING_LIFECYCLE]
        ]
        availability_rows = rows_by_kind[ShardArtifactKind.AVAILABILITY]
        availability = [_to_backtest_availability(item) for item in availability_rows]
        availability_by_id = {item.artifact_id: item for item in availability}
        memberships = []
        for item in rows_by_kind[ShardArtifactKind.UNIVERSE_MEMBERSHIP]:
            memberships.append(
                UniverseMembership(
                    membership_id=item.membership_id,
                    universe_id=item.universe_id,
                    listing_id=item.listing_id,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                    included=item.included,
                    availability=availability_by_id.get(item.availability_id),
                )
            )
        decisions = list(rows_by_kind[ShardArtifactKind.DECISION_ARTIFACT])
        archive_ids = []
        if self.manifest.research_archive is not None:
            archive_ids = [
                item.artifact_id
                for item in self.manifest.research_archive.artifacts
                if item.artifact_type is ArchiveArtifactType.BUSINESS_QUALITY
            ]
        compiled = BacktestDatasetManifest.build(
            dataset_id=self.manifest.dataset_id,
            dataset_version=self.manifest.dataset_version,
            start_date=target.start_date,
            end_date=target.end_date,
            calendar_id="historical-scope",
            universe_id=target.universe_id,
            universe_coverage=UniverseCoverage(target.membership_claim),
            listing_lifecycles=lifecycles,
            universe_memberships=memberships,
            availability=availability,
            market_bars=list(rows_by_kind[ShardArtifactKind.MARKET_BAR]),
            corporate_actions=list(rows_by_kind[ShardArtifactKind.CORPORATE_ACTION]),
            fx_observations=[
                FXObservation(
                    observation_id=item.observation_id,
                    listing_id=item.listing_id,
                    base_currency=item.base_currency,
                    quote_currency=item.quote_currency,
                    observation_date=item.observation_date,
                    rate=item.rate,
                    available_at=item.available_at,
                    source_hash=item.source_hash,
                )
                for item in rows_by_kind[ShardArtifactKind.FX_OBSERVATION]
            ],
            benchmarks=list(rows_by_kind[ShardArtifactKind.BENCHMARK_OBSERVATION]),
            decision_artifacts=decisions,
            source_artifact_ids=[item.source_id for item in self.manifest.source_descriptors],
            financial_artifact_ids=[item.source_id for item in self.manifest.source_descriptors],
            business_quality_artifact_ids=archive_ids,
            missing_data_summary=self.manifest.missing_data_summary,
            limitations=self.manifest.limitations,
            survivorship_bias_note=(
                "historical membership is source-backed"
                if target.membership_claim == "HISTORICAL"
                else "target is not a complete historical-universe claim"
            ),
            claims_survivorship_bias_free=(target.membership_claim == "HISTORICAL"),
        )
        return validate_manifest(compiled)


def _covers_target(source: HistoricalSourceDescriptor, target: HistoricalTargetScope) -> bool:
    return source.coverage_start <= target.start_date and source.coverage_end >= target.end_date


def _archived_json_scope_error(artifact, payload: object) -> str | None:
    """Reject a persisted JSON object that contradicts its archive reference."""

    if not isinstance(payload, dict):
        return "historical research artifact must contain a JSON object: " + artifact.artifact_id
    for field_name, expected in (
        ("artifact_id", artifact.artifact_id),
        ("listing_id", artifact.listing_id),
        ("analysis_id", artifact.analysis_id),
    ):
        if field_name in payload and payload[field_name] != expected:
            return (
                "historical research artifact scope does not match persisted JSON: "
                + artifact.artifact_id
            )
    if "artifact_type" in payload and payload["artifact_type"] != artifact.artifact_type.value:
        return (
            "historical research artifact type does not match persisted JSON: "
            + artifact.artifact_id
        )
    if "as_of" in payload:
        try:
            if date.fromisoformat(str(payload["as_of"])) != artifact.as_of:
                return (
                    "historical research artifact as_of does not match persisted JSON: "
                    + artifact.artifact_id
                )
        except ValueError:
            return (
                "historical research artifact has invalid persisted as_of: "
                + artifact.artifact_id
            )
    return None


def _production_scope_blockers(
    target: HistoricalTargetScope,
    sources: dict[str, HistoricalSourceDescriptor],
    reports,
    reconciliations,
    *,
    terminal_scope_errors: list[str],
) -> list[str]:
    blockers: list[str] = []
    if target.membership_claim != "HISTORICAL":
        blockers.append("target membership claim is not HISTORICAL")
    if target.coverage_claim.value != "COMPLETE":
        blockers.append("target coverage claim is not COMPLETE")
    if not sources:
        blockers.append("no source descriptors are declared")
    target_listings = set(target.listing_ids)
    for item in sources.values():
        if (
            item.authority.value in {"UNKNOWN", "FIXTURE"}
            or item.license_status.value in {"UNKNOWN", "PROHIBITED"}
            or item.license_evidence_uri is None
            or item.license_evidence_sha256 is None
            or (
                item.license_status.value == "RESTRICTED_INTERNAL"
                and item.access_grant_reference is None
            )
        ):
            blockers.append("source authority/licensing evidence is incomplete: " + item.source_id)
        if not item.historical_capable:
            blockers.append("source is not historical-capable: " + item.source_id)
        if not _covers_target(item, target):
            blockers.append("source coverage does not span target: " + item.source_id)
        if not target_listings.issubset(item.coverage_listing_ids):
            blockers.append("source listing coverage does not span target: " + item.source_id)
    # A caller may declare a smaller obligation set for a compact acceptance
    # fixture, but a production Phase 5R claim must cover every source class in
    # the contract.  This prevents an apparently complete price-only manifest
    # from being presented as a complete historical research dataset.
    required = set(target.required_source_kinds) | set(HistoricalSourceKind)
    available = {item.source_kind for item in sources.values()}
    for kind in required:
        if not any(candidate in available for candidate in _scope_source_kind(kind)):
            blockers.append("required source category is missing: " + kind.value)
    for report in reports:
        for record in report.records:
            if record.status.value != "COMPLETE":
                blockers.append(
                    "coverage is not COMPLETE: "
                    f"{record.source_kind.value}:{record.listing_id}"
                )
            if (
                record.source_kind is HistoricalSourceKind.PRICES
                and record.status.value == "COMPLETE"
                and record.expected_session_count == 0
            ):
                blockers.append(
                    "price coverage has no expected sessions: " + record.listing_id
                )
    coverage_keys = {
        (record.source_kind, record.listing_id)
        for report in reports
        for record in report.records
        if record.status.value == "COMPLETE"
    }
    for kind in required:
        accepted_kinds = _scope_source_kind(kind)
        for listing_id in target.listing_ids:
            if not any((candidate, listing_id) in coverage_keys for candidate in accepted_kinds):
                blockers.append(
                    "complete coverage record is missing: "
                    f"{kind.value}:{listing_id}"
                )
    if not reconciliations:
        blockers.append("no independent reconciliation report is declared")
    else:
        for report in reconciliations:
            if report.status.value != "PASS":
                blockers.append("reconciliation is not PASS: " + report.report_id)
    blockers.extend(terminal_scope_errors)
    return sorted(set(blockers))


def _terminal_scope_errors(
    *,
    target: HistoricalTargetScope,
    lifecycles,
    actions,
) -> list[str]:
    """Return terminal-economics failures for a claimed production scope."""

    terminal_actions_by_listing: dict[str, bool] = defaultdict(bool)
    for action in actions:
        if action.action_type.value == "TERMINAL_VALUE":
            terminal_actions_by_listing[action.listing_id] = True
    errors: list[str] = []
    unresolved = {
        HistoricalTerminalOutcome.PROLONGED_SUSPENSION,
        HistoricalTerminalOutcome.UNRESOLVED_TERMINAL,
        HistoricalTerminalOutcome.UNKNOWN,
    }
    for lifecycle in lifecycles:
        if lifecycle.terminal_date is None or lifecycle.terminal_date > target.end_date:
            continue
        if lifecycle.terminal_outcome in unresolved:
            errors.append(
                "production terminal economics are unresolved: " + lifecycle.listing_id
            )
        elif not terminal_actions_by_listing.get(lifecycle.listing_id, False):
            errors.append(
                "production terminal listing has no explicit terminal value: "
                + lifecycle.listing_id
            )
    return errors


def _to_backtest_lifecycle(item: HistoricalListingLifecycle) -> ListingLifecycle:
    if item.terminal_outcome is HistoricalTerminalOutcome.ACTIVE:
        terminal_status = "ACTIVE"
    elif item.terminal_outcome is HistoricalTerminalOutcome.UNRESOLVED_TERMINAL:
        terminal_status = "UNKNOWN"
    elif item.terminal_outcome in {
        HistoricalTerminalOutcome.PROLONGED_SUSPENSION,
        HistoricalTerminalOutcome.UNKNOWN,
    }:
        terminal_status = "UNKNOWN"
    else:
        terminal_status = "DELISTED"
    return ListingLifecycle(
        listing_id=item.listing_id,
        economic_company_id=item.economic_company_id,
        market=item.market,
        currency=item.currency,
        listing_date=item.listing_date,
        delisting_date=item.terminal_date,
        terminal_status=terminal_status,
        trading_calendar=item.trading_calendar,
        timezone=item.timezone,
        source_artifact_id=item.source_artifact_id,
        source_hash=item.source_hash,
    )


def _to_backtest_availability(item: HistoricalAvailabilityRecord) -> HistoricalAvailability:
    return HistoricalAvailability(
        artifact_id=item.artifact_id,
        published_at=item.published_at,
        available_at=item.available_at,
        retrieved_at=item.retrieved_at,
        source_hash=item.source_hash,
        source_id=item.source_artifact_id,
        status=item.status,
        notes=item.notes,
    )


def validate_historical_dataset(
    manifest: HistoricalDatasetManifest,
    store: HistoricalArtifactStore,
    *,
    require_production: bool = False,
) -> HistoricalValidationSummary:
    """Validate a frozen source-aware manifest without any network fallback."""

    return HistoricalDatasetCompiler(manifest, store).validate(
        require_production=require_production
    )


def compile_backtest_manifest(
    manifest: HistoricalDatasetManifest,
    store: HistoricalArtifactStore,
    *,
    require_production: bool = False,
) -> BacktestDatasetManifest:
    """Functional facade for the offline Phase 5 compiler boundary."""

    return HistoricalDatasetCompiler(manifest, store).compile_backtest_manifest(
        require_production=require_production
    )


def freeze_decision_snapshots(
    manifest: BacktestDatasetManifest,
) -> list[DecisionSnapshot]:
    """Project existing analyses into immutable Phase 5 decision snapshots."""

    snapshots: list[DecisionSnapshot] = []
    for artifact in manifest.decision_artifacts:
        if artifact.analysis is None:
            continue
        snapshots.append(
            build_decision_snapshot(
                artifact.analysis,
                decision_time=artifact.decision_time,
                normalized_input=artifact.normalized_input,
                input_artifact_id=artifact.artifact_id,
                research_artifact_id=artifact.research_artifact_id,
            )
        )
    return sorted(snapshots, key=lambda item: (item.decision_time, item.listing_id))


__all__ = [
    "HistoricalDatasetCompiler",
    "HistoricalDatasetValidationError",
    "HistoricalValidationSummary",
    "compile_backtest_manifest",
    "freeze_decision_snapshots",
    "validate_historical_dataset",
]
