"""Immutable content-addressed storage for historical dataset shards."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    HistoricalShardReference,
    ShardArtifactKind,
    ShardFormat,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class HistoricalArtifactError(ValueError):
    """Raised when a frozen historical artifact is missing or corrupted."""


def _reject_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def canonical_jsonl_bytes(rows: Iterable[object]) -> bytes:
    """Serialize rows deterministically, one canonical JSON object per line."""

    serialized: list[bytes] = []
    for row in rows:
        if isinstance(row, BaseModel):
            row = row.model_dump(mode="json", warnings=False)
        serialized.append(canonical_json_bytes(row) + b"\n")
    return b"".join(serialized)


def jsonl_sha256(rows: Iterable[object]) -> str:
    """Return the content identity used by ``HistoricalShardReference``."""

    return hashlib.sha256(canonical_jsonl_bytes(rows)).hexdigest()


class HistoricalArtifactStore:
    """Small immutable filesystem store with no network fallback.

    Shard paths are derived from their SHA-256 content identity.  A write is
    idempotent only when the bytes are identical; a conflicting artifact ID is
    never overwritten.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise HistoricalArtifactError("artifact store root must be a regular directory")
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
        except OSError as exc:
            raise HistoricalArtifactError("cannot secure artifact store root") from exc

    def path_for(self, reference: HistoricalShardReference) -> Path:
        if reference.format is not ShardFormat.JSONL:
            raise HistoricalArtifactError(f"unsupported shard format: {reference.format}")
        derived = Path("sha256") / reference.content_sha256[:2] / (
            f"{reference.content_sha256}.jsonl"
        )
        if reference.relative_path is not None:
            supplied = Path(reference.relative_path)
            if supplied != derived:
                raise HistoricalArtifactError(
                    "content-addressed shard relative_path must match its content hash"
                )
        return self.root / derived

    def write_shard(
        self,
        reference: HistoricalShardReference,
        rows: Iterable[object],
    ) -> Path:
        """Persist rows after checking count and content hash against the reference."""

        row_list = list(rows)
        serialized = canonical_jsonl_bytes(row_list)
        actual_hash = hashlib.sha256(serialized).hexdigest()
        if len(row_list) != reference.row_count:
            raise HistoricalArtifactError(
                f"shard row count mismatch for {reference.shard_id}: "
                f"{len(row_list)} != {reference.row_count}"
            )
        if actual_hash != reference.content_sha256:
            raise HistoricalArtifactError(
                f"shard content hash mismatch for {reference.shard_id}: "
                f"{actual_hash} != {reference.content_sha256}"
            )
        path = self.path_for(reference)
        self._write_immutable(path, serialized)
        return path

    def freeze_shard(
        self,
        *,
        shard_id: str,
        artifact_kind: ShardArtifactKind,
        schema_version: str,
        date_start,
        date_end,
        listing_scope: list[str],
        source_artifact_id: str,
        rows: Iterable[object],
    ) -> HistoricalShardReference:
        """Build and persist a reference from already acquired cached rows."""

        row_list = list(rows)
        serialized = canonical_jsonl_bytes(row_list)
        content_sha256 = hashlib.sha256(serialized).hexdigest()
        reference = HistoricalShardReference(
            shard_id=shard_id,
            artifact_kind=artifact_kind,
            schema_version=schema_version,
            content_sha256=content_sha256,
            row_count=len(row_list),
            date_start=date_start,
            date_end=date_end,
            listing_scope=listing_scope,
            source_artifact_id=source_artifact_id,
        )
        self.write_shard(reference, row_list)
        return reference

    def read_shard(
        self,
        reference: HistoricalShardReference,
        model_type: type[ModelT] | None = None,
    ) -> list[dict[str, object]] | list[ModelT]:
        """Read and verify a shard; never fetch a missing shard."""

        path = self.path_for(reference)
        self._check_directory(path.parent)
        if path.is_symlink() or not path.is_file():
            raise HistoricalArtifactError(f"historical shard is missing: {path}")
        try:
            serialized = path.read_bytes()
        except OSError as exc:
            raise HistoricalArtifactError(f"cannot read historical shard {path}: {exc}") from exc
        actual_hash = hashlib.sha256(serialized).hexdigest()
        if actual_hash != reference.content_sha256:
            raise HistoricalArtifactError(
                f"historical shard hash mismatch: {reference.shard_id} "
                f"{actual_hash} != {reference.content_sha256}"
            )
        if not serialized and reference.row_count != 0:
            raise HistoricalArtifactError(f"empty shard has non-zero row count: {path}")
        raw_rows: list[dict[str, object]] = []
        try:
            for line_number, line in enumerate(serialized.splitlines(), start=1):
                if not line.strip():
                    raise ValueError(f"blank JSONL row at line {line_number}")
                value = json.loads(line, parse_constant=_reject_number)
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL row {line_number} is not an object")
                raw_rows.append(value)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HistoricalArtifactError(f"invalid historical shard {path}: {exc}") from exc
        if len(raw_rows) != reference.row_count:
            raise HistoricalArtifactError(
                f"historical shard row count mismatch: {len(raw_rows)} != {reference.row_count}"
            )
        if model_type is None:
            return raw_rows
        try:
            return [model_type.model_validate(row) for row in raw_rows]
        except (TypeError, ValueError, ValidationError) as exc:
            raise HistoricalArtifactError(
                f"historical shard schema validation failed for {reference.shard_id}: {exc}"
            ) from exc

    def read_json_artifact(self, relative_path: str, expected_sha256: str) -> object:
        """Read an archived JSON artifact and verify its persisted bytes."""

        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or "\\" in relative_path
            or ".." in relative.parts
        ):
            raise HistoricalArtifactError("JSON artifact path escapes the artifact store")
        path = self.root / relative
        self._check_directory(path.parent)
        if path.is_symlink() or not path.is_file():
            raise HistoricalArtifactError(f"historical JSON artifact is missing: {path}")
        try:
            serialized = path.read_bytes()
        except OSError as exc:
            raise HistoricalArtifactError(
                f"cannot read historical JSON artifact {path}: {exc}"
            ) from exc
        actual_hash = hashlib.sha256(serialized).hexdigest()
        if actual_hash != expected_sha256:
            raise HistoricalArtifactError(
                f"historical JSON artifact hash mismatch: {actual_hash} != {expected_sha256}"
            )
        try:
            return json.loads(serialized, parse_constant=_reject_number)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HistoricalArtifactError(
                f"invalid historical JSON artifact {path}: {exc}"
            ) from exc

    def freeze_json_artifact(self, artifact: BaseModel | object) -> tuple[str, str]:
        """Persist one canonical JSON artifact and return ``(path, sha256)``."""

        payload = (
            artifact.model_dump(mode="json", warnings=False)
            if isinstance(artifact, BaseModel)
            else artifact
        )
        serialized = canonical_json_bytes(payload)
        content_sha256 = hashlib.sha256(serialized).hexdigest()
        relative_path = Path("json") / content_sha256[:2] / f"{content_sha256}.json"
        self._write_immutable(self.root / relative_path, serialized)
        return str(relative_path), content_sha256

    def _secure_directory(self, path: Path) -> None:
        """Create a store-relative directory without following symlinks."""

        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise HistoricalArtifactError(
                "artifact path escapes the artifact store"
            ) from exc
        current = self.root
        try:
            for component in relative.parts:
                current = current / component
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise HistoricalArtifactError(
                        "artifact store directory component is not a regular directory: "
                        + str(current)
                    )
                current.mkdir(exist_ok=True, mode=0o700)
                current.chmod(0o700)
        except HistoricalArtifactError:
            raise
        except OSError as exc:
            raise HistoricalArtifactError("cannot secure artifact store directory") from exc

    def _check_directory(self, path: Path) -> None:
        """Check an existing store-relative directory without following links."""

        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise HistoricalArtifactError(
                "artifact path escapes the artifact store"
            ) from exc
        current = self.root
        for component in relative.parts:
            current = current / component
            if current.is_symlink() or not current.is_dir():
                raise HistoricalArtifactError(
                    "artifact store directory component is not a regular directory: "
                    + str(current)
                )

    def _write_immutable(self, path: Path, serialized: bytes) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise HistoricalArtifactError(f"artifact path is not a regular file: {path}")
            if path.read_bytes() != serialized:
                raise HistoricalArtifactError(f"artifact path contains conflicting content: {path}")
            return
        descriptor = -1
        temporary_path: Path | None = None
        try:
            self._secure_directory(path.parent)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_path, path)
            temporary_path.unlink()
            temporary_path = None
        except (OSError, TypeError, ValueError) as exc:
            raise HistoricalArtifactError(
                f"cannot persist historical artifact {path}: {exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "HistoricalArtifactError",
    "HistoricalArtifactStore",
    "canonical_jsonl_bytes",
    "jsonl_sha256",
]
