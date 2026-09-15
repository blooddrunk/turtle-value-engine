"""Point-in-time validation for frozen Phase 4 research archives."""

from __future__ import annotations

from datetime import date, datetime

from .contracts import (
    ArchiveArtifactType,
    HistoricalResearchArchiveManifest,
    HistoricalResearchArtifactReference,
    ReviewStatus,
)


class HistoricalResearchArchiveError(ValueError):
    """Raised when a research archive cannot support a historical decision."""


def _available_at(value: date | datetime | None, boundary: datetime) -> bool:
    if value is None:
        return False
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return False
        return value <= boundary
    # A date-only record has no intraday evidence and is usable only before the
    # decision date, matching the conservative Phase 5 rule.
    return value < boundary.date()


def validate_research_archive(
    archive: HistoricalResearchArchiveManifest,
    *,
    decision_times: dict[str, datetime] | None = None,
) -> HistoricalResearchArchiveManifest:
    """Validate archive references and their point-in-time availability.

    This function only reads frozen typed references.  It never calls an
    analyst client and never reconstructs Business Quality.
    """

    if not isinstance(archive, HistoricalResearchArchiveManifest):
        raise TypeError("archive must be a HistoricalResearchArchiveManifest")
    by_id = {item.artifact_id: item for item in archive.artifacts}
    decision_times = decision_times or {}
    for item in archive.artifacts:
        if item.available_at is None:
            raise HistoricalResearchArchiveError(
                f"research artifact has unknown availability: {item.artifact_id}"
            )
        if item.review_status is ReviewStatus.REJECTED:
            raise HistoricalResearchArchiveError(
                f"research artifact is rejected: {item.artifact_id}"
            )
        if item.artifact_type is ArchiveArtifactType.BUSINESS_QUALITY and (
            item.review_status is not ReviewStatus.FROZEN_VALIDATED
        ):
            raise HistoricalResearchArchiveError(
                "historical Business Quality requires a FROZEN_VALIDATED archive artifact: "
                + item.artifact_id
            )

    for binding in archive.decision_bindings:
        referenced = by_id.get(binding.research_artifact_id)
        if referenced is None:
            raise HistoricalResearchArchiveError(
                f"decision binding references dangling research artifact: "
                f"{binding.research_artifact_id}"
            )
        if (
            referenced.listing_id != binding.listing_id
            or referenced.analysis_id != binding.analysis_id
            or referenced.as_of != binding.as_of
        ):
            raise HistoricalResearchArchiveError(
                f"research artifact scope does not match decision binding: {referenced.artifact_id}"
            )
        if binding.research_artifact_id not in by_id:
            raise HistoricalResearchArchiveError("research binding has no archive reference")
        if binding.business_quality_artifact_id is not None:
            if binding.business_quality_artifact_id not in binding.used_artifact_ids:
                raise HistoricalResearchArchiveError(
                    "business_quality_artifact_id must be included in used_artifact_ids"
                )
            quality = by_id.get(binding.business_quality_artifact_id)
            if quality is None:
                raise HistoricalResearchArchiveError(
                    f"decision binding references dangling Business Quality artifact: "
                    f"{binding.business_quality_artifact_id}"
                )
            if quality.artifact_type is not ArchiveArtifactType.BUSINESS_QUALITY:
                raise HistoricalResearchArchiveError(
                    "business_quality_artifact_id does not reference a Business Quality result"
                )
            if quality.review_status is not ReviewStatus.FROZEN_VALIDATED:
                raise HistoricalResearchArchiveError(
                    "Business Quality artifact is not frozen and validated"
                )
        boundary = binding.decision_time
        explicit_boundary = decision_times.get(binding.decision_artifact_id)
        if explicit_boundary is not None:
            if explicit_boundary.tzinfo is None:
                raise HistoricalResearchArchiveError("decision time must be timezone-aware")
            boundary = explicit_boundary
        for artifact_id in binding.used_artifact_ids:
            item = by_id.get(artifact_id)
            if item is None:
                raise HistoricalResearchArchiveError(
                    f"decision binding references dangling artifact: {artifact_id}"
                )
            if (
                item.listing_id != binding.listing_id
                or item.analysis_id != binding.analysis_id
                or item.as_of != binding.as_of
            ):
                raise HistoricalResearchArchiveError(
                    "decision binding uses an artifact outside its decision scope: "
                    + artifact_id
                )
            if item.review_status is not ReviewStatus.FROZEN_VALIDATED:
                raise HistoricalResearchArchiveError(
                    f"decision uses an artifact that is not frozen and validated: {artifact_id}"
                )
            if not _available_at(item.available_at, boundary):
                raise HistoricalResearchArchiveError(
                    f"research artifact was not available at decision time: {artifact_id}"
                )
    return archive


def archive_artifact_available_at(
    artifact: HistoricalResearchArtifactReference,
    decision_time: datetime,
) -> bool:
    """Public PIT predicate used by compilers and acceptance tests."""

    return _available_at(artifact.available_at, decision_time)


__all__ = [
    "HistoricalResearchArchiveError",
    "archive_artifact_available_at",
    "validate_research_archive",
]
