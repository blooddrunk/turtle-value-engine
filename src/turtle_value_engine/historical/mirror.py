"""Backend-neutral, exact-byte transport for frozen historical datasets.

The mirror layer deliberately sits beside HistoricalArtifactStore. The local
content-addressed store remains authoritative; this module only moves a
declared manifest and its explicitly referenced shards.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import ValidationError

from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    HistoricalArtifactMirrorManifest,
    HistoricalArtifactMirrorObject,
    HistoricalArtifactMirrorRole,
    HistoricalDatasetManifest,
    HistoricalShardReference,
    _validate_mirror_object_key,
)
from .store import HistoricalArtifactError, HistoricalArtifactStore

if TYPE_CHECKING:
    from .compiler import HistoricalValidationSummary


class HistoricalArtifactMirrorError(HistoricalArtifactError):
    """Raised when a declared mirror package cannot be moved safely."""


class ArtifactObjectMissingError(HistoricalArtifactMirrorError):
    """Raised when a declared object is absent from an object backend."""


class ArtifactObjectConflictError(HistoricalArtifactMirrorError):
    """Raised when an immutable object key already contains different bytes."""


class ArtifactObjectSecurityError(HistoricalArtifactMirrorError):
    """Raised when an object key or filesystem path is unsafe."""


@dataclass(frozen=True, slots=True)
class ArtifactObjectMetadata:
    """Backend-neutral integrity metadata for one exact-byte object."""

    key: str
    byte_length: int
    content_sha256: str | None = None

    @property
    def sha256(self) -> str | None:
        """Short alias for callers that use the generic SHA-256 terminology."""

        return self.content_sha256


class ArtifactObjectStore(Protocol):
    """Minimal immutable object transport boundary for future backends."""

    def put_if_absent(self, key: str, content: bytes) -> ArtifactObjectMetadata:
        """Put exact bytes, allowing only an identical existing object."""

    def get(self, key: str) -> bytes:
        """Read exact bytes by an explicit object key."""

    def stat(self, key: str) -> ArtifactObjectMetadata:
        """Inspect object length and integrity metadata where available."""


class FilesystemArtifactObjectStore:
    """Offline reference implementation of ArtifactObjectStore.

    Keys are portable POSIX-relative paths. Every parent directory is checked
    without following symlinks, and files are immutable/idempotent.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise ArtifactObjectSecurityError("mirror object root must be a regular directory")
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
        except OSError as exc:
            raise ArtifactObjectSecurityError("cannot secure mirror object root") from exc

    def put_if_absent(self, key: str, content: bytes) -> ArtifactObjectMetadata:
        safe_key = self._safe_key(key)
        if not isinstance(content, bytes):
            raise TypeError("mirror object content must be bytes")
        path = self._path_for(safe_key)
        self._secure_directory(path.parent)
        expected_hash = hashlib.sha256(content).hexdigest()
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ArtifactObjectSecurityError(f"mirror object path is not a regular file: {path}")
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise HistoricalArtifactMirrorError(
                    f"cannot read existing mirror object {path}: {exc}"
                ) from exc
            if existing != content:
                raise ArtifactObjectConflictError(
                    f"mirror object contains conflicting content: {safe_key}"
                )
            return ArtifactObjectMetadata(safe_key, len(existing), expected_hash)

        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                # A concurrent identical writer is still idempotent; a
                # concurrent different writer remains a conflict.
                if path.is_symlink() or not path.is_file():
                    raise ArtifactObjectSecurityError(
                        f"mirror object path is not a regular file: {path}"
                    )
                existing = path.read_bytes()
                if existing != content:
                    raise ArtifactObjectConflictError(
                        f"mirror object contains conflicting content: {safe_key}"
                    )
            temporary_path.unlink()
            temporary_path = None
        except (ArtifactObjectConflictError, ArtifactObjectSecurityError):
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise HistoricalArtifactMirrorError(
                f"cannot persist mirror object {safe_key}: {exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return ArtifactObjectMetadata(safe_key, len(content), expected_hash)

    def get(self, key: str) -> bytes:
        safe_key = self._safe_key(key)
        path = self._path_for(safe_key)
        self._check_directory(path.parent)
        if path.is_symlink() or not path.is_file():
            raise ArtifactObjectMissingError(f"mirror object is missing: {safe_key}")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise HistoricalArtifactMirrorError(
                f"cannot read mirror object {safe_key}: {exc}"
            ) from exc

    def stat(self, key: str) -> ArtifactObjectMetadata:
        safe_key = self._safe_key(key)
        content = self.get(safe_key)
        return ArtifactObjectMetadata(
            key=safe_key,
            byte_length=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )

    # Explicit aliases make the narrow protocol convenient to use without
    # introducing a second backend-specific contract.
    def put_exact(self, key: str, content: bytes) -> ArtifactObjectMetadata:
        return self.put_if_absent(key, content)

    def read_exact(self, key: str) -> bytes:
        return self.get(key)

    def inspect(self, key: str) -> ArtifactObjectMetadata:
        return self.stat(key)

    def _safe_key(self, key: str) -> str:
        try:
            return _validate_mirror_object_key(key)
        except (TypeError, ValueError) as exc:
            raise ArtifactObjectSecurityError(str(exc)) from exc

    def _path_for(self, key: str) -> Path:
        return self.root.joinpath(*key.split("/"))

    def _secure_directory(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactObjectSecurityError("mirror object path escapes its root") from exc
        current = self.root
        try:
            for component in relative.parts:
                current = current / component
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise ArtifactObjectSecurityError(
                        "mirror object directory component is not a regular directory: "
                        + str(current)
                    )
                current.mkdir(exist_ok=True, mode=0o700)
                current.chmod(0o700)
        except ArtifactObjectSecurityError:
            raise
        except OSError as exc:
            raise ArtifactObjectSecurityError("cannot secure mirror object directory") from exc

    def _check_directory(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactObjectSecurityError("mirror object path escapes its root") from exc
        current = self.root
        for component in relative.parts:
            current = current / component
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise ArtifactObjectSecurityError(
                    "mirror object directory component is not a regular directory: "
                    + str(current)
                )
            if not current.exists():
                raise ArtifactObjectMissingError(
                    "mirror object directory is missing: " + str(current)
                )


@dataclass(frozen=True, slots=True)
class RestoredHistoricalDataset:
    """Validated result of pulling one declared mirror package."""

    manifest: HistoricalDatasetManifest
    store: HistoricalArtifactStore
    validation: HistoricalValidationSummary


def _canonical_manifest_bytes(manifest: HistoricalDatasetManifest) -> bytes:
    # Preserve omitted additive fields so old historical-v1 hashes remain
    # readable and the restored manifest validates against the same wire form.
    return canonical_json_bytes(
        manifest.model_dump(
            mode="json",
            exclude_unset=True,
            warnings=False,
        )
    )


def _validated_mirror_manifest(
    mirror_manifest: HistoricalArtifactMirrorManifest,
) -> HistoricalArtifactMirrorManifest:
    if not isinstance(mirror_manifest, HistoricalArtifactMirrorManifest):
        raise TypeError("mirror_manifest must be a HistoricalArtifactMirrorManifest")
    try:
        return HistoricalArtifactMirrorManifest.model_validate(
            mirror_manifest.model_dump(mode="json", warnings=False)
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise HistoricalArtifactMirrorError(f"invalid mirror manifest: {exc}") from exc


def _validated_dataset_manifest(
    manifest: HistoricalDatasetManifest,
) -> HistoricalDatasetManifest:
    if not isinstance(manifest, HistoricalDatasetManifest):
        raise TypeError("manifest must be a HistoricalDatasetManifest")
    try:
        return HistoricalDatasetManifest.model_validate(
            manifest.model_dump(
                mode="python",
                exclude_unset=True,
                warnings=False,
            )
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise HistoricalArtifactMirrorError(f"invalid source dataset manifest: {exc}") from exc


def _shard_object_key(
    store: HistoricalArtifactStore,
    reference: HistoricalShardReference,
) -> str:
    path = store.path_for(reference)
    try:
        return path.relative_to(store.root).as_posix()
    except ValueError as exc:
        raise HistoricalArtifactMirrorError(
            f"historical shard path escapes its store: {path}"
        ) from exc


def _object_from_bytes(
    *,
    artifact_id: str,
    artifact_role: HistoricalArtifactMirrorRole,
    artifact_type: str,
    object_key: str,
    content: bytes,
) -> HistoricalArtifactMirrorObject:
    return HistoricalArtifactMirrorObject(
        artifact_id=artifact_id,
        artifact_role=artifact_role,
        artifact_type=artifact_type,
        object_key=object_key,
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
    )


def build_historical_artifact_mirror_manifest(
    manifest: HistoricalDatasetManifest,
    store: HistoricalArtifactStore,
    *,
    manifest_object_key: str = "manifest.json",
) -> HistoricalArtifactMirrorManifest:
    """Freeze an explicit dataset manifest and exactly its referenced shards."""

    source_manifest = _validated_dataset_manifest(manifest)
    try:
        safe_manifest_key = _validate_mirror_object_key(manifest_object_key)
    except (TypeError, ValueError) as exc:
        raise HistoricalArtifactMirrorError(str(exc)) from exc

    manifest_bytes = _canonical_manifest_bytes(source_manifest)
    objects = [
        _object_from_bytes(
            artifact_id=source_manifest.dataset_id,
            artifact_role=HistoricalArtifactMirrorRole.DATASET_MANIFEST,
            artifact_type=source_manifest.contract,
            object_key=safe_manifest_key,
            content=manifest_bytes,
        )
    ]
    for reference in source_manifest.shards:
        # Validate the current source artifact through the authoritative store
        # before taking its exact bytes for transport.
        store.read_shard(reference)
        shard_bytes = store.read_shard_bytes(reference)
        objects.append(
            _object_from_bytes(
                artifact_id=reference.shard_id,
                artifact_role=HistoricalArtifactMirrorRole.DATASET_SHARD,
                artifact_type=reference.artifact_kind.value,
                object_key=_shard_object_key(store, reference),
                content=shard_bytes,
            )
        )
    return HistoricalArtifactMirrorManifest.build(
        source_dataset_id=source_manifest.dataset_id,
        source_dataset_version=source_manifest.dataset_version,
        source_manifest_sha256=source_manifest.content_sha256,
        source_manifest_object_key=safe_manifest_key,
        objects=objects,
    )


def _source_object_payloads(
    mirror_manifest: HistoricalArtifactMirrorManifest,
    source_manifest: HistoricalDatasetManifest,
    source_store: HistoricalArtifactStore,
) -> dict[str, bytes]:
    mirror = _validated_mirror_manifest(mirror_manifest)
    dataset = _validated_dataset_manifest(source_manifest)
    if (
        dataset.dataset_id != mirror.source_dataset_id
        or dataset.dataset_version != mirror.source_dataset_version
        or dataset.content_sha256 != mirror.source_manifest_sha256
    ):
        raise HistoricalArtifactMirrorError(
            "source dataset manifest does not match the mirror manifest identity"
        )

    references = {reference.shard_id: reference for reference in dataset.shards}
    shard_objects = {
        item.artifact_id: item
        for item in mirror.objects
        if item.artifact_role is HistoricalArtifactMirrorRole.DATASET_SHARD
    }
    if set(shard_objects) != set(references):
        raise HistoricalArtifactMirrorError(
            "mirror inventory does not match the explicitly referenced dataset shards"
        )

    payloads: dict[str, bytes] = {}
    for item in mirror.objects:
        if item.artifact_role is HistoricalArtifactMirrorRole.DATASET_MANIFEST:
            content = _canonical_manifest_bytes(dataset)
        else:
            reference = references.get(item.artifact_id)
            if reference is None:
                raise HistoricalArtifactMirrorError(
                    f"mirror object references an unknown shard: {item.artifact_id}"
                )
            expected_key = _shard_object_key(source_store, reference)
            if item.object_key != expected_key:
                raise HistoricalArtifactMirrorError(
                    f"mirror shard key does not match content-addressed path: {item.object_key}"
                )
            source_store.read_shard(reference)
            content = source_store.read_shard_bytes(reference)
        actual_hash = hashlib.sha256(content).hexdigest()
        if len(content) != item.byte_length or actual_hash != item.content_sha256:
            raise HistoricalArtifactMirrorError(
                f"source bytes do not match mirror declaration: {item.object_key}"
            )
        payloads[item.object_key] = content
    return payloads


def _verified_destination_payloads(
    mirror_manifest: HistoricalArtifactMirrorManifest,
    destination: ArtifactObjectStore,
) -> dict[str, bytes]:
    mirror = _validated_mirror_manifest(mirror_manifest)
    payloads: dict[str, bytes] = {}
    for item in mirror.objects:
        try:
            metadata = destination.stat(item.object_key)
        except ArtifactObjectMissingError:
            raise
        except HistoricalArtifactMirrorError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise HistoricalArtifactMirrorError(
                f"cannot inspect mirror object {item.object_key}: {exc}"
            ) from exc
        if metadata.byte_length != item.byte_length:
            raise HistoricalArtifactMirrorError(
                f"mirror object byte length/hash mismatch: {item.object_key}"
            )
        if metadata.content_sha256 is not None and metadata.content_sha256 != item.content_sha256:
            raise HistoricalArtifactMirrorError(
                f"mirror object metadata hash mismatch: {item.object_key}"
            )
        try:
            content = destination.get(item.object_key)
        except ArtifactObjectMissingError:
            raise
        except HistoricalArtifactMirrorError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise HistoricalArtifactMirrorError(
                f"cannot read mirror object {item.object_key}: {exc}"
            ) from exc
        actual_hash = hashlib.sha256(content).hexdigest()
        if len(content) != item.byte_length or actual_hash != item.content_sha256:
            raise HistoricalArtifactMirrorError(
                f"mirror object content hash mismatch: {item.object_key}"
            )
        payloads[item.object_key] = content
    return payloads


def push_historical_artifact_mirror(
    mirror_manifest: HistoricalArtifactMirrorManifest,
    source_manifest: HistoricalDatasetManifest,
    source_store: HistoricalArtifactStore,
    destination: ArtifactObjectStore,
) -> tuple[str, ...]:
    """Push only declared objects and verify the destination immediately."""

    mirror = _validated_mirror_manifest(mirror_manifest)
    payloads = _source_object_payloads(mirror, source_manifest, source_store)
    for item in mirror.objects:
        destination.put_if_absent(item.object_key, payloads[item.object_key])
    _verified_destination_payloads(mirror, destination)
    return tuple(item.object_key for item in mirror.objects)


def verify_historical_artifact_mirror(
    mirror_manifest: HistoricalArtifactMirrorManifest,
    destination: ArtifactObjectStore,
) -> tuple[str, ...]:
    """Verify every declared destination object by length and exact SHA-256."""

    mirror = _validated_mirror_manifest(mirror_manifest)
    payloads = _verified_destination_payloads(mirror, destination)
    return tuple(payloads)


def _preflight_restore_target(
    mirror: HistoricalArtifactMirrorManifest,
    target: FilesystemArtifactObjectStore,
    payloads: dict[str, bytes],
) -> None:
    for item in mirror.objects:
        try:
            existing = target.stat(item.object_key)
        except ArtifactObjectMissingError:
            continue
        if (
            existing.byte_length != item.byte_length
            or existing.content_sha256 != item.content_sha256
        ):
            raise ArtifactObjectConflictError(
                f"restore target contains conflicting content: {item.object_key}"
            )
        if target.get(item.object_key) != payloads[item.object_key]:
            raise ArtifactObjectConflictError(
                f"restore target contains conflicting content: {item.object_key}"
            )


def pull_historical_artifact_mirror(
    mirror_manifest: HistoricalArtifactMirrorManifest,
    source: ArtifactObjectStore,
    target_root: str | Path,
) -> RestoredHistoricalDataset:
    """Pull, verify and validate one declared dataset into a local CAS root."""

    mirror = _validated_mirror_manifest(mirror_manifest)
    # Read and verify all source objects before writing any restore bytes.
    payloads = _verified_destination_payloads(mirror, source)
    target = FilesystemArtifactObjectStore(target_root)
    _preflight_restore_target(mirror, target, payloads)
    for item in mirror.objects:
        target.put_if_absent(item.object_key, payloads[item.object_key])

    manifest_object = next(
        item
        for item in mirror.objects
        if item.artifact_role is HistoricalArtifactMirrorRole.DATASET_MANIFEST
    )
    serialized_manifest = payloads[manifest_object.object_key]
    try:
        raw_manifest = json.loads(serialized_manifest, parse_constant=_reject_json_number)
        restored_manifest = HistoricalDatasetManifest.model_validate(raw_manifest)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise HistoricalArtifactMirrorError(
            f"restored dataset manifest is invalid: {exc}"
        ) from exc
    if _canonical_manifest_bytes(restored_manifest) != serialized_manifest:
        raise HistoricalArtifactMirrorError("restored dataset manifest is not canonical JSON")
    if (
        restored_manifest.dataset_id != mirror.source_dataset_id
        or restored_manifest.dataset_version != mirror.source_dataset_version
        or restored_manifest.content_sha256 != mirror.source_manifest_sha256
    ):
        raise HistoricalArtifactMirrorError("restored dataset manifest identity does not match")

    restored_store = HistoricalArtifactStore(target_root)
    rebuilt = build_historical_artifact_mirror_manifest(
        restored_manifest,
        restored_store,
        manifest_object_key=mirror.source_manifest_object_key,
    )
    if rebuilt != mirror:
        raise HistoricalArtifactMirrorError(
            "restored bytes do not reproduce the declared mirror manifest"
        )

    from .compiler import validate_historical_dataset

    validation = validate_historical_dataset(restored_manifest, restored_store)
    return RestoredHistoricalDataset(
        manifest=restored_manifest,
        store=restored_store,
        validation=validation,
    )


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


# Short aliases keep the additive boundary easy to discover without creating
# another contract or backend-specific vocabulary.
ArtifactMirrorManifest = HistoricalArtifactMirrorManifest
FilesystemArtifactStore = FilesystemArtifactObjectStore
build_artifact_mirror_manifest = build_historical_artifact_mirror_manifest
push_artifact_mirror = push_historical_artifact_mirror
verify_artifact_mirror = verify_historical_artifact_mirror
pull_artifact_mirror = pull_historical_artifact_mirror
restore_historical_dataset = pull_historical_artifact_mirror


__all__ = [
    "ArtifactMirrorManifest",
    "ArtifactObjectConflictError",
    "ArtifactObjectMetadata",
    "ArtifactObjectMissingError",
    "ArtifactObjectSecurityError",
    "ArtifactObjectStore",
    "FilesystemArtifactObjectStore",
    "FilesystemArtifactStore",
    "HistoricalArtifactMirrorError",
    "RestoredHistoricalDataset",
    "build_artifact_mirror_manifest",
    "build_historical_artifact_mirror_manifest",
    "pull_artifact_mirror",
    "pull_historical_artifact_mirror",
    "push_artifact_mirror",
    "push_historical_artifact_mirror",
    "restore_historical_dataset",
    "verify_artifact_mirror",
    "verify_historical_artifact_mirror",
]
