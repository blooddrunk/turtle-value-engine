from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.historical import (
    ArtifactObjectConflictError,
    ArtifactObjectMissingError,
    ArtifactObjectSecurityError,
    FilesystemArtifactObjectStore,
    HistoricalArtifactMirrorManifest,
    HistoricalArtifactStore,
    HistoricalDatasetManifest,
    build_historical_artifact_mirror_manifest,
    compile_backtest_manifest,
    pull_historical_artifact_mirror,
    push_historical_artifact_mirror,
    validate_historical_dataset,
    verify_historical_artifact_mirror,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures" / "historical" / "phase5r-compact-v1"


def _source_dataset() -> tuple[HistoricalDatasetManifest, HistoricalArtifactStore]:
    raw = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    # M5-A intentionally mirrors only the manifest and its JSONL shards.  The
    # fixture's research sidecar is retained in the source root as an
    # unrelated/non-M5 artifact.
    raw["research_archive"] = None
    raw["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in raw.items() if key != "content_sha256"}
        )
    ).hexdigest()
    manifest = HistoricalDatasetManifest.model_validate(raw)
    store = HistoricalArtifactStore(FIXTURE / "store")
    assert validate_historical_dataset(manifest, store).valid
    return manifest, store


def _mirror() -> tuple[
    HistoricalDatasetManifest,
    HistoricalArtifactStore,
    HistoricalArtifactMirrorManifest,
]:
    manifest, store = _source_dataset()
    return manifest, store, build_historical_artifact_mirror_manifest(manifest, store)


def test_build_inventory_is_explicit_and_schema_valid():
    manifest, store, mirror = _mirror()
    expected_keys = {"manifest.json"}
    expected_keys.update(
        store.path_for(reference).relative_to(store.root).as_posix()
        for reference in manifest.shards
    )

    assert {item.object_key for item in mirror.objects} == expected_keys
    assert not any(item.object_key.startswith("json/") for item in mirror.objects)
    assert mirror.source_dataset_id == manifest.dataset_id
    assert mirror.source_manifest_sha256 == manifest.content_sha256

    schema = json.loads(
        (ROOT / "schemas" / "historical-artifact-mirror-manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(mirror.model_dump(mode="json"))


def test_push_is_byte_preserving_idempotent_and_ignores_unrelated_files(tmp_path: Path):
    manifest, store, mirror = _mirror()
    destination = FilesystemArtifactObjectStore(tmp_path / "mirror")

    first = push_historical_artifact_mirror(mirror, manifest, store, destination)
    second = push_historical_artifact_mirror(mirror, manifest, store, destination)

    assert first == second == tuple(item.object_key for item in mirror.objects)
    assert not (destination.root / "json").exists()
    for item in mirror.objects:
        content = destination.get(item.object_key)
        assert hashlib.sha256(content).hexdigest() == item.content_sha256
        assert len(content) == item.byte_length


def test_conflicting_destination_bytes_fail_closed(tmp_path: Path):
    manifest, store, mirror = _mirror()
    destination = FilesystemArtifactObjectStore(tmp_path / "mirror")
    destination.put_if_absent("manifest.json", b"conflicting")

    with pytest.raises(ArtifactObjectConflictError):
        push_historical_artifact_mirror(mirror, manifest, store, destination)


def test_missing_and_corrupt_objects_fail_verification(tmp_path: Path):
    manifest, store, mirror = _mirror()
    destination = FilesystemArtifactObjectStore(tmp_path / "mirror")
    push_historical_artifact_mirror(mirror, manifest, store, destination)

    missing_key = mirror.objects[-1].object_key
    (destination.root / missing_key).unlink()
    with pytest.raises(ArtifactObjectMissingError):
        verify_historical_artifact_mirror(mirror, destination)

    push_historical_artifact_mirror(mirror, manifest, store, destination)
    corrupt_key = mirror.objects[1].object_key
    (destination.root / corrupt_key).write_bytes(b"corrupted bytes")
    with pytest.raises(ValueError, match="hash mismatch|content hash mismatch"):
        verify_historical_artifact_mirror(mirror, destination)


def test_filesystem_backend_rejects_escape_and_symlink_traversal(tmp_path: Path):
    backend = FilesystemArtifactObjectStore(tmp_path / "mirror")
    for key in ("/absolute", "../escape", "nested/../../escape", "nested\\escape"):
        with pytest.raises(ArtifactObjectSecurityError):
            backend.put_if_absent(key, b"x")

    outside = tmp_path / "outside"
    outside.mkdir()
    (backend.root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactObjectSecurityError):
        backend.put_if_absent("linked/object", b"x")
    with pytest.raises(ArtifactObjectSecurityError):
        backend.get("linked/object")


def test_pull_verifies_every_object_before_writing_and_restores_exact_dataset(tmp_path: Path):
    manifest, store, mirror = _mirror()
    source_backend = FilesystemArtifactObjectStore(tmp_path / "source")
    push_historical_artifact_mirror(mirror, manifest, store, source_backend)

    missing_key = mirror.objects[-1].object_key
    (source_backend.root / missing_key).unlink()
    target_root = tmp_path / "restored-missing"
    with pytest.raises(ArtifactObjectMissingError):
        pull_historical_artifact_mirror(mirror, source_backend, target_root)
    assert not target_root.exists()

    push_historical_artifact_mirror(mirror, manifest, store, source_backend)
    restored = pull_historical_artifact_mirror(mirror, source_backend, tmp_path / "restored")

    assert restored.validation.valid
    assert restored.manifest.content_sha256 == manifest.content_sha256
    assert compile_backtest_manifest(manifest, store).model_dump(
        mode="json", warnings=False
    ) == compile_backtest_manifest(restored.manifest, restored.store).model_dump(
        mode="json", warnings=False
    )
    for reference in manifest.shards:
        source_bytes = store.read_shard_bytes(reference)
        restored_bytes = restored.store.read_shard_bytes(reference)
        assert restored_bytes == source_bytes
        assert hashlib.sha256(restored_bytes).hexdigest() == reference.content_sha256


def test_tampered_mirror_manifest_fails_validation(tmp_path: Path):
    _, _, mirror = _mirror()
    tampered = mirror.model_copy(update={"source_dataset_version": "tampered"})

    with pytest.raises(ValueError, match="content_sha256"):
        verify_historical_artifact_mirror(
            tampered,
            FilesystemArtifactObjectStore(tmp_path / "mirror"),
        )


def test_manifest_tampering_inside_json_fails_validation():
    _, _, mirror = _mirror()
    payload = mirror.model_dump(mode="json")
    payload["objects"][0]["byte_length"] += 1

    with pytest.raises(ValueError, match="content_sha256"):
        HistoricalArtifactMirrorManifest.model_validate(payload)


def test_filesystem_mirror_never_needs_network(tmp_path: Path, monkeypatch):
    import socket

    def fail_socket(*args, **kwargs):
        raise AssertionError("filesystem mirror attempted network access")

    monkeypatch.setattr(socket, "socket", fail_socket)
    manifest, store, mirror = _mirror()
    destination = FilesystemArtifactObjectStore(tmp_path / "mirror")
    push_historical_artifact_mirror(mirror, manifest, store, destination)
    verify_historical_artifact_mirror(mirror, destination)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink support is unavailable")
def test_symlinked_backend_root_is_rejected(tmp_path: Path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ArtifactObjectSecurityError):
        FilesystemArtifactObjectStore(link)
