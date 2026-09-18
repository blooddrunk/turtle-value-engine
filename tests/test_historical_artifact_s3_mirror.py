from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

import turtle_value_engine.cli as cli_module
from turtle_value_engine.historical import (
    ArtifactObjectConfigurationError,
    ArtifactObjectConflictError,
    ArtifactObjectMissingError,
    ArtifactObjectPermissionError,
    CredentialKind,
    CredentialReferenceV1,
    CredentialUnavailableError,
    HistoricalArtifactMirrorManifest,
    HistoricalArtifactStore,
    HistoricalDatasetManifest,
    MappingCredentialResolver,
    NetworkDisabledError,
    S3CompatibleArtifactObjectStore,
    S3CompatibleArtifactStoreConfig,
    build_historical_artifact_mirror_manifest,
    pull_historical_artifact_mirror,
    push_historical_artifact_mirror,
    verify_historical_artifact_mirror,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures" / "historical" / "phase5r-compact-v1"


class FakeS3Error(Exception):
    def __init__(self, code: str, status: int, message: str = "fake service error") -> None:
        super().__init__(message)
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.etags: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failures: dict[str, Exception] = {}
        self.race_winner: bytes | None = None

    def _call(self, operation: str, kwargs: dict[str, object]) -> None:
        self.calls.append((operation, kwargs))
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure

    def head_object(self, **kwargs: object) -> dict[str, object]:
        self._call("head_object", kwargs)
        identity = (str(kwargs["Bucket"]), str(kwargs["Key"]))
        if identity not in self.objects:
            raise FakeS3Error("NoSuchKey", 404)
        content = self.objects[identity]
        return {
            "ContentLength": len(content),
            "Metadata": dict(self.metadata.get(identity, {})),
            "ETag": self.etags.get(identity, '"opaque-etag"'),
        }

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self._call("get_object", kwargs)
        identity = (str(kwargs["Bucket"]), str(kwargs["Key"]))
        if identity not in self.objects:
            raise FakeS3Error("NoSuchKey", 404)
        content = self.objects[identity]
        return {"ContentLength": len(content), "Body": io.BytesIO(content)}

    def put_object(self, **kwargs: object) -> dict[str, object]:
        self._call("put_object", kwargs)
        identity = (str(kwargs["Bucket"]), str(kwargs["Key"]))
        if self.race_winner is not None and identity not in self.objects:
            self.objects[identity] = self.race_winner
            self.metadata[identity] = dict(kwargs.get("Metadata", {}))
            self.race_winner = None
            raise FakeS3Error("PreconditionFailed", 412)
        if identity in self.objects and kwargs.get("IfNoneMatch") == "*":
            raise FakeS3Error("PreconditionFailed", 412)
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        self.objects[identity] = body
        self.metadata[identity] = dict(kwargs.get("Metadata", {}))
        self.etags[identity] = '"opaque-etag"'
        return {"ETag": self.etags[identity]}

    def list_objects_v2(self, **kwargs: object) -> None:
        raise AssertionError("deterministic mirror operations must not list objects")

    def delete_object(self, **kwargs: object) -> None:
        raise AssertionError("deterministic mirror operations must not delete objects")


def _config(prefix: str = "private/test") -> S3CompatibleArtifactStoreConfig:
    return S3CompatibleArtifactStoreConfig(
        endpoint_url="https://objects.example.test",
        bucket="private-bucket",
        region="auto",
        key_prefix=prefix,
        access_key_ref=CredentialReferenceV1(
            reference_id="s3-access",
            kind=CredentialKind.INJECTED,
        ),
        secret_key_ref=CredentialReferenceV1(
            reference_id="s3-secret",
            kind=CredentialKind.INJECTED,
        ),
    )


def _store(fake: FakeS3Client, *, network_allowed: bool = True) -> S3CompatibleArtifactObjectStore:
    return S3CompatibleArtifactObjectStore(
        _config(),
        client=fake,
        credentials=MappingCredentialResolver(
            {
                "s3-access": "access-value",
                "s3-secret": "secret-value",
            }
        ),
        network_allowed=network_allowed,
    )


def _source_dataset() -> tuple[HistoricalDatasetManifest, HistoricalArtifactStore]:
    raw = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    raw["research_archive"] = None
    raw["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in raw.items() if key != "content_sha256"}
        )
    ).hexdigest()
    manifest = HistoricalDatasetManifest.model_validate(raw)
    return manifest, HistoricalArtifactStore(FIXTURE / "store")


def _mirror() -> tuple[
    HistoricalDatasetManifest,
    HistoricalArtifactStore,
    HistoricalArtifactMirrorManifest,
]:
    manifest, store = _source_dataset()
    return manifest, store, build_historical_artifact_mirror_manifest(manifest, store)


def test_network_denied_before_injected_client_use():
    fake = FakeS3Client()
    store = _store(fake, network_allowed=False)

    with pytest.raises(NetworkDisabledError):
        store.stat("manifest.json")

    assert fake.calls == []


def test_missing_credentials_fail_before_injected_client_use():
    fake = FakeS3Client()
    store = S3CompatibleArtifactObjectStore(
        _config(),
        client=fake,
        credentials=MappingCredentialResolver({}),
        network_allowed=True,
    )

    with pytest.raises(CredentialUnavailableError):
        store.stat("manifest.json")

    assert fake.calls == []


def test_rejected_raw_secret_configuration_is_redacted():
    secret = "raw-secret-that-must-not-echo"
    with pytest.raises(ArtifactObjectConfigurationError) as error:
        S3CompatibleArtifactObjectStore(
            {
                "endpoint_url": "https://objects.example.test",
                "bucket": "private-bucket",
                "access_key_ref": secret,
                "secret_key_ref": secret,
            },
            client=FakeS3Client(),
        )
    assert secret not in str(error.value)


def test_prefix_mapping_conditional_create_and_explicit_sha_metadata():
    fake = FakeS3Client()
    store = _store(fake)
    content = b"immutable bytes"

    metadata = store.put_if_absent("manifest.json", content)
    assert metadata.key == "manifest.json"
    assert metadata.content_sha256 == hashlib.sha256(content).hexdigest()
    assert fake.calls[0][1]["Key"] == "private/test/manifest.json"
    put_kwargs = next(kwargs for operation, kwargs in fake.calls if operation == "put_object")
    assert put_kwargs["Key"] == "private/test/manifest.json"
    assert put_kwargs["IfNoneMatch"] == "*"
    assert put_kwargs["Metadata"] == {"tve-sha256": hashlib.sha256(content).hexdigest()}
    assert store.stat("manifest.json").content_sha256 == metadata.content_sha256

    identity = ("private-bucket", "private/test/manifest.json")
    fake.metadata[identity] = {}
    fake.etags[identity] = f'"{metadata.content_sha256}"'
    assert store.stat("manifest.json").content_sha256 is None


def test_existing_same_bytes_is_idempotent_and_different_bytes_conflict():
    fake = FakeS3Client()
    store = _store(fake)
    store.put_if_absent("object.bin", b"same")

    store.put_if_absent("object.bin", b"same")
    with pytest.raises(ArtifactObjectConflictError):
        store.put_if_absent("object.bin", b"different")


def test_conditional_write_race_accepts_only_identical_winner():
    fake = FakeS3Client()
    store = _store(fake)
    fake.race_winner = b"same"
    store.put_if_absent("race.bin", b"same")

    fake.race_winner = b"different"
    with pytest.raises(ArtifactObjectConflictError):
        store.put_if_absent("race-different.bin", b"same")


def test_conditional_request_conflict_status_also_verifies_the_winner():
    fake = FakeS3Client()
    store = _store(fake)

    original_put = fake.put_object

    def conflict_put(**kwargs: object) -> dict[str, object]:
        identity = (str(kwargs["Bucket"]), str(kwargs["Key"]))
        fake.objects[identity] = b"winner"
        raise FakeS3Error("ConditionalRequestConflict", 409)

    fake.put_object = conflict_put  # type: ignore[method-assign]
    with pytest.raises(ArtifactObjectConflictError):
        store.put_if_absent("race-409.bin", b"loser")
    fake.put_object = original_put  # type: ignore[method-assign]


def test_missing_and_permission_errors_are_distinct_and_secrets_are_redacted():
    fake = FakeS3Client()
    store = _store(fake)
    with pytest.raises(ArtifactObjectMissingError):
        store.stat("missing.bin")

    secret = "super-secret-value"
    fake.failures["head_object"] = FakeS3Error("AccessDenied", 403, f"token={secret}")
    with pytest.raises(ArtifactObjectPermissionError) as error:
        store.stat("private.bin")
    assert secret not in str(error.value)
    assert error.value.__cause__ is None


def test_fake_s3_push_verify_pull_restores_exact_m5_a_dataset(tmp_path: Path):
    manifest, source_store, mirror = _mirror()
    fake = FakeS3Client()
    remote = _store(fake)

    assert push_historical_artifact_mirror(mirror, manifest, source_store, remote)
    assert verify_historical_artifact_mirror(mirror, remote) == tuple(
        item.object_key for item in mirror.objects
    )
    restored = pull_historical_artifact_mirror(mirror, remote, tmp_path / "restored")

    assert restored.validation.valid
    assert restored.manifest.content_sha256 == manifest.content_sha256
    for reference in manifest.shards:
        assert restored.store.read_shard_bytes(reference) == source_store.read_shard_bytes(
            reference
        )
    assert all(
        key[0] == "private-bucket" and key[1].startswith("private/test/")
        for key in fake.objects
    )
    assert not any(operation == "list_objects_v2" for operation, _ in fake.calls)
    assert not any(operation == "delete_object" for operation, _ in fake.calls)


def test_configuration_rejects_non_loopback_http_and_allows_explicit_local_minio():
    with pytest.raises(ValueError, match="HTTPS"):
        S3CompatibleArtifactStoreConfig(
            endpoint_url="http://minio.example.test:9000",
            bucket="bucket",
        )

    local = S3CompatibleArtifactStoreConfig(
        endpoint_url="http://127.0.0.1:9000",
        bucket="bucket",
        allow_insecure_local_endpoint=True,
    )
    assert local.endpoint_url == "http://127.0.0.1:9000"


def test_cli_selects_s3_backend_without_persisting_remote_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, source_store, mirror = _mirror()
    fake = FakeS3Client()
    remote = _store(fake)
    push_historical_artifact_mirror(mirror, manifest, source_store, remote)

    mirror_path = tmp_path / "mirror.json"
    mirror_path.write_bytes(mirror.model_dump_json().encode("utf-8"))
    config_path = tmp_path / "remote-config.json"
    config_path.write_text(
        json.dumps(
            {
                "endpoint_url": "https://objects.example.test",
                "bucket": "private-bucket",
                "region": "auto",
                "key_prefix": "private/test",
                "access_key_ref": {
                    "reference_id": "s3-access",
                    "kind": "INJECTED",
                },
                "secret_key_ref": {
                    "reference_id": "s3-secret",
                    "kind": "INJECTED",
                },
            }
        ),
        encoding="utf-8",
    )

    def injected_backend(
        config: object, *, network_allowed: bool
    ) -> S3CompatibleArtifactObjectStore:
        assert isinstance(config, dict)
        assert network_allowed is True
        return remote

    monkeypatch.setattr(cli_module, "S3CompatibleArtifactObjectStore", injected_backend)
    exit_code = cli_module.main(
        [
            "artifacts",
            "mirror",
            "verify",
            "--mirror-manifest",
            str(mirror_path),
            "--backend",
            "s3",
            "--remote-config",
            str(config_path),
            "--network=allow",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["verified"] is True
    assert "secret-value" not in captured.out + captured.err
