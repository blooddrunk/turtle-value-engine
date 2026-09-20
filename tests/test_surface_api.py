"""Offline registry/API tests plus the real loopback server smoke test."""

from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from turtle_value_engine import load_normalized_input
from turtle_value_engine.pipeline import run_analyze
from turtle_value_engine.surface import (
    DuplicateSurfaceError,
    SnapshotValidationError,
    SurfaceBindError,
    SurfaceRegistry,
    build_research_surface_snapshot,
    create_surface_app,
    validate_bind_host,
)

ROOT = Path(__file__).resolve().parents[1]


def _snapshot():
    analysis = run_analyze(load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json"))
    return build_research_surface_snapshot(analysis)


def _variant_snapshot(*, analysis_id: str, as_of: date, profile_id: str, listing: str):
    analysis = run_analyze(load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json"))
    analysis = analysis.model_copy(
        update={
            "analysis_id": analysis_id,
            "as_of": as_of,
            "profile_id": profile_id,
            "company": analysis.company.model_copy(update={"primary_listing": listing}),
        }
    )
    return build_research_surface_snapshot(analysis)


def _write_snapshot(path: Path, snapshot) -> None:
    path.write_bytes(snapshot.canonical_bytes())


def _client(app):
    testclient = pytest.importorskip("fastapi.testclient")
    return testclient.TestClient(app)


def test_registry_loads_explicit_valid_snapshot_and_has_no_path_metadata(tmp_path: Path):
    snapshot = _snapshot()
    path = tmp_path / "surface.json"
    _write_snapshot(path, snapshot)

    registry = SurfaceRegistry.from_paths([path])

    assert registry.count == 1
    assert registry.get_surface(snapshot.surface_id) == snapshot
    metadata = registry.list_metadata()
    assert metadata[0].model_dump(mode="json") == {
        "surface_id": snapshot.surface_id,
        "content_sha256": snapshot.content_sha256,
        "analysis_id": snapshot.analysis_id,
        "primary_listing": snapshot.company.primary_listing,
        "profile_id": snapshot.profile_id,
        "as_of": snapshot.as_of.isoformat(),
    }
    assert str(path) not in json.dumps(metadata[0].model_dump(mode="json"))


def test_tampered_snapshot_fails_startup(tmp_path: Path):
    snapshot = _snapshot()
    path = tmp_path / "tampered.json"
    payload = snapshot.model_dump(mode="json")
    payload["content_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotValidationError) as exc_info:
        SurfaceRegistry.from_paths([path])

    assert exc_info.value.code == "SNAPSHOT_VALIDATION_FAILED"


def test_duplicate_surface_registration_fails_closed(tmp_path: Path):
    snapshot = _snapshot()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_snapshot(first, snapshot)
    _write_snapshot(second, snapshot)

    with pytest.raises(DuplicateSurfaceError) as exc_info:
        SurfaceRegistry.from_paths([first, second])

    assert exc_info.value.code == "DUPLICATE_SURFACE_ID"


def test_registry_ordering_and_filters_are_deterministic():
    older = _variant_snapshot(
        analysis_id="analysis-older",
        as_of=date(2025, 12, 31),
        profile_id="strict-v1",
        listing="OLDER",
    )
    newer = _variant_snapshot(
        analysis_id="analysis-newer",
        as_of=date(2026, 6, 30),
        profile_id="research-v1",
        listing="NEWER",
    )

    registry = SurfaceRegistry.from_snapshots([older, newer])

    assert [item.surface_id for item in registry.list_metadata()] == [
        newer.surface_id,
        older.surface_id,
    ]
    assert registry.list_metadata(primary_listing="NEWER")[0].surface_id == newer.surface_id
    assert registry.list_metadata(profile_id="strict-v1")[0].surface_id == older.surface_id
    assert registry.list_metadata(as_of="2025-12-31")[0].surface_id == older.surface_id


def test_api_health_list_get_filters_etag_and_stable_errors():
    snapshot = _snapshot()
    client = _client(create_surface_app(SurfaceRegistry.from_snapshots([snapshot])))

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "contract": "research_surface_api_v1",
        "version": "1.0.0",
        "loaded_snapshot_count": 1,
    }
    assert "provider" not in health.text.lower()

    listed = client.get(
        "/v1/surfaces",
        params={"primary_listing": snapshot.company.primary_listing},
    )
    assert listed.status_code == 200
    assert listed.json()["surfaces"][0]["surface_id"] == snapshot.surface_id
    assert "surface.json" not in listed.text

    fetched = client.get(f"/v1/surfaces/{snapshot.surface_id}")
    assert fetched.status_code == 200
    assert fetched.json() == snapshot.model_dump(mode="json")
    assert fetched.headers["etag"] == f'"{snapshot.content_sha256}"'

    not_modified = client.get(
        f"/v1/surfaces/{snapshot.surface_id}",
        headers={"If-None-Match": fetched.headers["etag"]},
    )
    assert not_modified.status_code == 304
    assert not_modified.headers["etag"] == fetched.headers["etag"]

    unknown = client.get("/v1/surfaces/" + "f" * 64)
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "SURFACE_NOT_FOUND"

    invalid_query = client.get("/v1/surfaces", params={"as_of": "not-a-date"})
    assert invalid_query.status_code == 400
    assert invalid_query.json()["error"]["code"] == "INVALID_QUERY_PARAMETER"


def test_mutations_and_path_like_ids_are_rejected_without_file_access():
    snapshot = _snapshot()
    client = _client(create_surface_app(SurfaceRegistry.from_snapshots([snapshot])))

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        mutation = client.request(
            method,
            f"/v1/surfaces/{snapshot.surface_id}",
            json={"state": "PASS"},
        )
        assert mutation.status_code == 405
        assert mutation.json()["error"]["code"] == "READ_ONLY_METHOD_NOT_ALLOWED"

    traversal = client.get("/v1/surfaces/%2E%2E%2Fetc%2Fpasswd")
    assert traversal.status_code == 404
    assert traversal.json()["error"]["code"] == "SURFACE_NOT_FOUND"


def test_default_bind_is_loopback_and_non_loopback_requires_opt_in():
    validate_bind_host("127.0.0.1", allow_non_loopback=False)
    validate_bind_host("::1", allow_non_loopback=False)
    with pytest.raises(SurfaceBindError):
        validate_bind_host("0.0.0.0", allow_non_loopback=False)
    validate_bind_host("0.0.0.0", allow_non_loopback=True)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_real_loopback_socket_smoke_starts_cli_server_and_shuts_down_cleanly(
    tmp_path: Path,
):
    """Black-box acceptance: health, known/unknown IDs, mutations and shutdown."""

    httpx = pytest.importorskip("httpx")
    snapshot = _snapshot()
    snapshot_path = tmp_path / "known-surface.json"
    _write_snapshot(snapshot_path, snapshot)
    port = _free_loopback_port()
    command = [
        sys.executable,
        "-m",
        "turtle_value_engine",
        "surface",
        "serve",
        "--snapshot",
        str(snapshot_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        health = None
        with httpx.Client(timeout=0.5) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    pytest.fail(
                        "surface server exited before /healthz became reachable; "
                        f"returncode={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
                    )
                try:
                    candidate = client.get(base_url + "/healthz")
                except httpx.HTTPError:
                    time.sleep(0.05)
                    continue
                if candidate.status_code == 200:
                    health = candidate
                    break
                time.sleep(0.05)
            assert health is not None, "loopback /healthz did not become reachable"

            known = client.get(base_url + f"/v1/surfaces/{snapshot.surface_id}")
            assert known.status_code == 200
            assert known.json()["surface_id"] == snapshot.surface_id
            assert known.json()["content_sha256"] == snapshot.content_sha256

            unknown = client.get(base_url + "/v1/surfaces/" + "e" * 64)
            assert unknown.status_code == 404

            for method in ("POST", "PUT", "PATCH", "DELETE"):
                mutation = client.request(
                    method,
                    base_url + f"/v1/surfaces/{snapshot.surface_id}",
                    json={"decision": "PASS"},
                )
                assert mutation.status_code == 405
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(f"surface server did not shut down cleanly: {stderr!r}")
        assert process.returncode == 0, (
            f"surface server exited unsuccessfully: stdout={stdout!r}, stderr={stderr!r}"
        )
