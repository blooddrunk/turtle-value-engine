"""Point-in-time validation and frozen dataset construction."""

from __future__ import annotations

import hashlib
import re
from calendar import monthrange
from collections.abc import Iterable
from datetime import UTC, date, datetime, time

from pydantic import ValidationError

from turtle_value_engine.models import CompanyAnalysis, Evidence, NormalizedCompanyInput
from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    BacktestDatasetManifest,
    DateTimeLike,
    HistoricalDecisionArtifact,
    ListingLifecycle,
    UniverseCoverage,
)


class DatasetValidationError(ValueError):
    """Raised when a frozen dataset cannot prove its historical boundaries."""


def sha256_json(value: object) -> str:
    """Hash JSON-compatible source content for a replayable artifact identity."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def source_hash_for(value: object) -> str:
    """Public alias used by fixture and acquisition builders."""

    return sha256_json(value)


def _as_datetime(value: DateTimeLike, *, timezone=UTC) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise DatasetValidationError("availability datetime must be timezone-aware")
        return value.astimezone(timezone)
    return datetime.combine(value, time.min, tzinfo=timezone)


def is_available_at(available_at: DateTimeLike | None, boundary: datetime) -> bool:
    """Return true only for an explicitly known artifact available by boundary."""

    if boundary.tzinfo is None:
        raise DatasetValidationError("decision boundary must be timezone-aware")
    if available_at is None:
        return False
    if isinstance(available_at, date) and not isinstance(available_at, datetime):
        # A date-only publication/availability value has no intraday evidence.
        # Treat it as usable from the next calendar/trading session onward.
        return available_at < boundary.date()
    return _as_datetime(available_at, timezone=boundary.tzinfo) <= boundary


def _period_end(period: str) -> date | None:
    """Parse only the period formats accepted by the Phase 4 packet boundary."""

    patterns = (
        re.compile(r"^AS_OF_(\d{4})-(\d{2})-(\d{2})$"),
        re.compile(r"^FY(\d{4})(?:-FY(\d{4}))?$"),
        re.compile(r"^(\d{4})[-_]?Q([1-4])$", re.IGNORECASE),
        re.compile(r"^(\d{4})-(\d{2})$"),
        re.compile(r"^(\d{4})$"),
    )
    for index, pattern in enumerate(patterns):
        match = pattern.fullmatch(period.strip())
        if match is None:
            continue
        if index == 0:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
        if index == 1:
            return date(int(match.group(2) or match.group(1)), 12, 31)
        if index == 2:
            year = int(match.group(1))
            month = int(match.group(2)) * 3
            return date(year, month, monthrange(year, month)[1])
        if index == 3:
            year = int(match.group(1))
            month = int(match.group(2))
            if not 1 <= month <= 12:
                return None
            return date(year, month, monthrange(year, month)[1])
        return date(int(match.group(1)), 12, 31)
    return None


def _published_date(evidence: Evidence) -> date | None:
    return evidence.source.published_date


def _validate_input_availability(
    value: NormalizedCompanyInput | CompanyAnalysis,
    *,
    decision_time: datetime,
    allow_undated_evidence: bool,
) -> None:
    """Check evidence and period boundaries without recalculating any metric."""

    for evidence in value.evidence_index:
        published = _published_date(evidence)
        if published is None and not allow_undated_evidence:
            raise DatasetValidationError(
                f"undated evidence is unavailable by default: {evidence.id}"
            )
        if published is not None and published >= decision_time.date():
            raise DatasetValidationError(f"future evidence is unavailable: {evidence.id}")
    for fact in value.facts:
        period_end = _period_end(fact.period)
        if period_end is not None and period_end > value.as_of:
            raise DatasetValidationError(f"fact period is after input as_of: {fact.id}")


def validate_decision_artifact(
    artifact: HistoricalDecisionArtifact,
    *,
    decision_time: datetime,
    allow_undated_evidence: bool = False,
) -> None:
    """Validate one decision artifact against a signal timestamp."""

    if artifact.decision_time > decision_time:
        raise DatasetValidationError("decision artifact is after the requested boundary")
    if not is_available_at(artifact.available_at, decision_time):
        raise DatasetValidationError(
            f"decision artifact is unavailable at decision time: {artifact.artifact_id}"
        )
    for value in (artifact.normalized_input, artifact.analysis):
        if value is not None:
            _validate_input_availability(
                value,
                decision_time=decision_time,
                allow_undated_evidence=allow_undated_evidence,
            )


def _validate_unique_ids(values: Iterable[str], label: str) -> None:
    items = list(values)
    if len(items) != len(set(items)):
        raise DatasetValidationError(f"{label} must not contain duplicate IDs")


def validate_manifest(manifest: BacktestDatasetManifest) -> BacktestDatasetManifest:
    """Revalidate a manifest at the offline execution boundary."""

    if not isinstance(manifest, BacktestDatasetManifest):
        raise TypeError("manifest must be a BacktestDatasetManifest")
    try:
        manifest = BacktestDatasetManifest.model_validate(
            manifest.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise DatasetValidationError(f"invalid dataset manifest: {exc}") from exc

    listings = {item.listing_id: item for item in manifest.listing_lifecycles}
    _validate_unique_ids(listings, "listing lifecycle")
    _validate_unique_ids(
        (item.membership_id for item in manifest.universe_memberships),
        "universe membership",
    )
    _validate_unique_ids(
        (item.artifact_id for item in manifest.availability),
        "availability artifact",
    )
    for membership in manifest.universe_memberships:
        if membership.universe_id != manifest.universe_id:
            raise DatasetValidationError("membership universe_id does not match manifest")
        if membership.listing_id not in listings:
            raise DatasetValidationError(
                f"membership references unknown listing: {membership.listing_id}"
            )
        lifecycle = listings[membership.listing_id]
        if membership.valid_from < lifecycle.listing_date:
            raise DatasetValidationError(
                f"universe membership precedes listing date: {membership.membership_id}"
            )
        if lifecycle.delisting_date is not None and (
            membership.valid_from > lifecycle.delisting_date
        ):
            raise DatasetValidationError(
                f"universe membership begins after delisting: {membership.membership_id}"
            )
        if lifecycle.delisting_date is not None and (
            membership.valid_to is None or membership.valid_to > lifecycle.delisting_date
        ):
            raise DatasetValidationError(
                f"universe membership extends beyond delisting: {membership.membership_id}"
            )
    for listing_id in listings:
        intervals = sorted(
            (
                item
                for item in manifest.universe_memberships
                if item.listing_id == listing_id and item.included
            ),
            key=lambda item: item.valid_from,
        )
        for previous, current in zip(intervals, intervals[1:], strict=False):
            if previous.valid_to is None or previous.valid_to >= current.valid_from:
                raise DatasetValidationError(
                    f"overlapping included universe membership for listing {listing_id}"
                )

    _validate_unique_ids((item.bar_id for item in manifest.market_bars), "market bar")
    _validate_unique_ids(
        (item.action_id for item in manifest.corporate_actions), "corporate action"
    )
    _validate_unique_ids(
        (item.observation_id for item in manifest.benchmarks), "benchmark observation"
    )
    _validate_unique_ids(
        (item.observation_id for item in manifest.fx_observations), "FX observation"
    )
    _validate_unique_ids(
        (item.artifact_id for item in manifest.decision_artifacts), "decision artifact"
    )
    for bar in manifest.market_bars:
        if not manifest.start_date <= bar.trading_date <= manifest.end_date:
            raise DatasetValidationError(f"market bar lies outside dataset range: {bar.bar_id}")

    for artifact in manifest.decision_artifacts:
        if artifact.listing_id not in listings:
            raise DatasetValidationError(
                f"decision artifact references unknown listing: {artifact.listing_id}"
            )
        validate_decision_artifact(
            artifact,
            decision_time=artifact.decision_time,
            allow_undated_evidence=manifest.allow_undated_evidence,
        )
        lifecycle = listings[artifact.listing_id]
        if not lifecycle.is_listed_on(artifact.decision_time.date()):
            raise DatasetValidationError(
                f"decision artifact lies outside listing lifecycle: {artifact.artifact_id}"
            )
        if manifest.universe_coverage is UniverseCoverage.HISTORICAL and not any(
            membership.listing_id == artifact.listing_id
            and membership.included
            and membership.includes(artifact.decision_time.date())
            for membership in manifest.universe_memberships
        ):
            raise DatasetValidationError(
                "decision artifact is not a member of the historical universe: "
                f"{artifact.artifact_id}"
            )
        if artifact.historical_business_quality_valid and (
            artifact.research_artifact_id not in manifest.business_quality_artifact_ids
        ):
            raise DatasetValidationError(
                "historical Business Quality artifact is not listed in the manifest: "
                f"{artifact.research_artifact_id}"
            )

    return manifest


def build_dataset_manifest(**kwargs) -> BacktestDatasetManifest:
    """Construct and validate an immutable manifest from frozen components."""

    try:
        manifest = BacktestDatasetManifest.build(**kwargs)
    except (TypeError, ValueError, ValidationError) as exc:
        raise DatasetValidationError(f"cannot build dataset manifest: {exc}") from exc
    return validate_manifest(manifest)


class HistoricalUniverse:
    """Offline listing/lifecycle view over a validated manifest."""

    def __init__(self, manifest: BacktestDatasetManifest) -> None:
        self.manifest = validate_manifest(manifest)
        self._lifecycles = {item.listing_id: item for item in self.manifest.listing_lifecycles}

    @property
    def listings(self) -> tuple[str, ...]:
        return tuple(sorted(self._lifecycles))

    def lifecycle(self, listing_id: str) -> ListingLifecycle:
        try:
            return self._lifecycles[listing_id]
        except KeyError as exc:
            raise DatasetValidationError(f"unknown listing: {listing_id}") from exc

    def is_in_universe(self, listing_id: str, value: date) -> bool:
        return listing_id in self.manifest.memberships_on(value)

    def is_listed(self, listing_id: str, value: date) -> bool:
        return self.lifecycle(listing_id).is_listed_on(value)

    def active_listings(self, value: date) -> tuple[str, ...]:
        members = set(self.manifest.memberships_on(value))
        return tuple(
            listing_id
            for listing_id in sorted(members)
            if self._lifecycles[listing_id].is_listed_on(value)
        )

    def terminal_value(self, listing_id: str, value: date) -> float | None:
        for action in self.manifest.actions_for(listing_id):
            if action.action_type.value == "TERMINAL_VALUE" and action.effective_date <= value:
                return action.terminal_value_per_share
        return None


__all__ = [
    "DatasetValidationError",
    "HistoricalUniverse",
    "build_dataset_manifest",
    "is_available_at",
    "sha256_json",
    "source_hash_for",
    "validate_decision_artifact",
    "validate_manifest",
]
