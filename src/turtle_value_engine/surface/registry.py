"""Framework-neutral registry and read service for frozen surface snapshots.

The registry is deliberately constructed from explicit inputs.  It loads and
validates files once at construction time, keeps the validated projections in
memory, and exposes only deterministic read operations afterwards.  It never
knows about a workspace, a raw store, a provider, or an analysis pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .contracts import ResearchSurfaceSnapshotV1
from .projection import (
    load_research_surface_snapshot,
    validate_research_surface_snapshot,
)

SURFACE_API_CONTRACT = "research_surface_api_v1"
SURFACE_API_VERSION = "1.0.0"
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class SurfaceRegistryError(ValueError):
    """Base error with a stable machine-readable code."""

    code: ClassVar[str] = "SURFACE_REGISTRY_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(message)


class NoSnapshotsError(SurfaceRegistryError):
    """Raised when the server is configured without an explicit snapshot."""

    code = "NO_SNAPSHOTS_CONFIGURED"


class SnapshotValidationError(SurfaceRegistryError):
    """Raised when an explicit snapshot cannot be validated."""

    code = "SNAPSHOT_VALIDATION_FAILED"

    def __init__(self, source: str, cause: Exception) -> None:
        self.source = source
        self.cause = cause
        super().__init__(f"snapshot validation failed for {source}: {cause}")


class DuplicateSurfaceError(SurfaceRegistryError):
    """Raised when two explicit inputs register the same surface identity."""

    code = "DUPLICATE_SURFACE_ID"


class SurfaceNotFoundError(SurfaceRegistryError):
    """Raised for a surface ID that is not in the immutable registry."""

    code = "SURFACE_NOT_FOUND"

    def __init__(self, surface_id: str) -> None:
        self.surface_id = surface_id
        super().__init__("surface not found")


class InvalidSurfaceQueryError(SurfaceRegistryError):
    """Raised for an unsupported or malformed read filter."""

    code = "INVALID_QUERY_PARAMETER"


class SurfaceBindError(SurfaceRegistryError):
    """Raised when a non-loopback bind was not explicitly authorized."""

    code = "NON_LOOPBACK_BIND_REQUIRES_OPT_IN"


class SurfaceMetadata(BaseModel):
    """Safe deterministic metadata returned by the list operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    surface_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    analysis_id: StrictStr = Field(min_length=1)
    primary_listing: StrictStr = Field(min_length=1)
    profile_id: StrictStr = Field(min_length=1)
    as_of: date


def parse_surface_as_of(value: date | str | None) -> date | None:
    """Parse the one supported date filter without accepting loose values."""

    if value is None:
        return None
    if isinstance(value, datetime):
        raise InvalidSurfaceQueryError("as_of must use YYYY-MM-DD")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        if not value:
            raise InvalidSurfaceQueryError("as_of must use YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise InvalidSurfaceQueryError("as_of must use YYYY-MM-DD") from exc
    raise InvalidSurfaceQueryError("as_of must use YYYY-MM-DD")


def _validate_text_filter(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidSurfaceQueryError(f"{name} must be a non-empty string")
    return value


def _validated_snapshot(
    value: ResearchSurfaceSnapshotV1 | Mapping[str, object],
    *,
    source: str,
) -> ResearchSurfaceSnapshotV1:
    try:
        # Revalidate and deep-copy mappings/models so later caller mutations do
        # not alter the registry's startup snapshot.
        validated = validate_research_surface_snapshot(value)
        return validated.model_copy(deep=True)
    except Exception as exc:
        if isinstance(exc, SnapshotValidationError):
            raise
        raise SnapshotValidationError(source, exc) from exc


class SurfaceRegistry:
    """Immutable index over explicitly supplied validated snapshots."""

    __slots__ = ("_snapshots", "_metadata")

    def __init__(
        self,
        snapshots: Iterable[ResearchSurfaceSnapshotV1 | Mapping[str, object]] | None = None,
        *,
        snapshot_paths: Iterable[str | Path] | None = None,
    ) -> None:
        if snapshots is None and snapshot_paths is None:
            raise NoSnapshotsError("at least one explicit snapshot is required")
        if isinstance(snapshots, (str, bytes, Path)):
            raise TypeError(
                "snapshot paths must be passed through snapshot_paths or from_paths; "
                "recursive discovery is not supported"
            )
        if isinstance(snapshot_paths, (str, bytes, Path)):
            raise TypeError("snapshot_paths must be an iterable of explicit paths")

        entries: list[ResearchSurfaceSnapshotV1] = []
        if snapshot_paths is not None:
            paths = list(snapshot_paths)
            if not paths:
                raise NoSnapshotsError("at least one explicit snapshot is required")
            for path in paths:
                path_value = Path(path)
                try:
                    loaded = load_research_surface_snapshot(path_value)
                except Exception as exc:
                    raise SnapshotValidationError(str(path_value), exc) from exc
                entries.append(
                    _validated_snapshot(loaded, source=str(path_value))
                )

        if snapshots is not None:
            entries.extend(
                _validated_snapshot(value, source="in-memory snapshot")
                for value in snapshots
            )
        if not entries:
            raise NoSnapshotsError("at least one explicit snapshot is required")

        indexed: dict[str, ResearchSurfaceSnapshotV1] = {}
        for snapshot in entries:
            if snapshot.surface_id in indexed:
                raise DuplicateSurfaceError(
                    f"duplicate surface_id: {snapshot.surface_id}"
                )
            indexed[snapshot.surface_id] = snapshot

        metadata = {
            surface_id: SurfaceMetadata(
                surface_id=snapshot.surface_id,
                content_sha256=snapshot.content_sha256,
                analysis_id=snapshot.analysis_id,
                primary_listing=snapshot.company.primary_listing,
                profile_id=snapshot.profile_id,
                as_of=snapshot.as_of,
            )
            for surface_id, snapshot in indexed.items()
        }
        self._snapshots = MappingProxyType(indexed)
        self._metadata = MappingProxyType(metadata)

    @classmethod
    def from_paths(cls, paths: Iterable[str | Path]) -> SurfaceRegistry:
        """Load only the explicitly listed snapshot paths."""

        if isinstance(paths, (str, bytes, Path)):
            raise TypeError("paths must be an iterable of explicit snapshot paths")
        return cls(snapshot_paths=list(paths))

    @classmethod
    def from_snapshots(
        cls,
        snapshots: Iterable[ResearchSurfaceSnapshotV1 | Mapping[str, object]],
    ) -> SurfaceRegistry:
        """Build from explicit in-memory validated snapshots or JSON objects."""

        if isinstance(snapshots, (str, bytes, Path)):
            raise TypeError("snapshots must be an iterable of snapshot objects")
        return cls(snapshots=list(snapshots))

    @property
    def count(self) -> int:
        return len(self._snapshots)

    def get_surface(self, surface_id: str) -> ResearchSurfaceSnapshotV1:
        """Return a detached validated snapshot or raise a stable not-found error."""

        snapshot = self._snapshots.get(surface_id)
        if snapshot is None:
            raise SurfaceNotFoundError(surface_id)
        return snapshot.model_copy(deep=True)

    # Short aliases keep the framework-neutral boundary convenient without
    # introducing a mutable registration API.
    get = get_surface
    get_by_id = get_surface

    def list_metadata(
        self,
        *,
        primary_listing: str | None = None,
        profile_id: str | None = None,
        as_of: date | str | None = None,
    ) -> list[SurfaceMetadata]:
        """Return deterministic metadata filtered by the supported fields."""

        primary_listing = _validate_text_filter(primary_listing, "primary_listing")
        profile_id = _validate_text_filter(profile_id, "profile_id")
        parsed_as_of = parse_surface_as_of(as_of)
        values = self._metadata.values()
        selected = [
            metadata
            for metadata in values
            if (primary_listing is None or metadata.primary_listing == primary_listing)
            and (profile_id is None or metadata.profile_id == profile_id)
            and (parsed_as_of is None or metadata.as_of == parsed_as_of)
        ]
        selected.sort(key=lambda item: (-item.as_of.toordinal(), item.surface_id))
        return [item.model_copy(deep=True) for item in selected]

    list_surfaces = list_metadata


class SurfaceReadService:
    """Read-only application service independent of any HTTP framework."""

    def __init__(self, registry: SurfaceRegistry) -> None:
        if not isinstance(registry, SurfaceRegistry):
            raise TypeError("registry must be a SurfaceRegistry")
        self._registry = registry

    @property
    def registry(self) -> SurfaceRegistry:
        return self._registry

    def health(self) -> dict[str, object]:
        """Return only local API status; upstream health is intentionally absent."""

        return {
            "status": "ok",
            "contract": SURFACE_API_CONTRACT,
            "version": SURFACE_API_VERSION,
            "loaded_snapshot_count": self._registry.count,
        }

    def list_surfaces(
        self,
        *,
        primary_listing: str | None = None,
        profile_id: str | None = None,
        as_of: date | str | None = None,
    ) -> list[SurfaceMetadata]:
        return self._registry.list_metadata(
            primary_listing=primary_listing,
            profile_id=profile_id,
            as_of=as_of,
        )

    def get_surface(self, surface_id: str) -> ResearchSurfaceSnapshotV1:
        return self._registry.get_surface(surface_id)

    get = get_surface
    get_by_id = get_surface


# Descriptive aliases for external runtimes that use either term.
SurfaceService = SurfaceReadService
ResearchSurfaceService = SurfaceReadService
SurfaceStartupValidationError = SnapshotValidationError


__all__ = [
    "DUPLICATE_SURFACE_ID",
    "SURFACE_API_CONTRACT",
    "SURFACE_API_VERSION",
    "DuplicateSurfaceError",
    "InvalidSurfaceQueryError",
    "NoSnapshotsError",
    "ResearchSurfaceService",
    "SnapshotValidationError",
    "SurfaceBindError",
    "SurfaceMetadata",
    "SurfaceNotFoundError",
    "SurfaceReadService",
    "SurfaceRegistry",
    "SurfaceRegistryError",
    "SurfaceService",
    "SurfaceStartupValidationError",
    "parse_surface_as_of",
]


# A named constant is useful to callers that do not want to import the
# exception class just to compare startup diagnostics.
DUPLICATE_SURFACE_ID = DuplicateSurfaceError.code
