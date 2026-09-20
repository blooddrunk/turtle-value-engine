"""Black-box M6-C1 smoke across the Python API and the local Worker preview."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "apps" / "dashboard"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    url: str, *, method: str = "GET", body: bytes | None = None
) -> tuple[int, bytes, dict[str, str]]:
    request = Request(url, method=method, data=body, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=1.0) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as error:
        return error.code, error.read(), dict(error.headers.items())
    except URLError:
        return 0, b"", {}


def _wait_for(
    url: str, process: subprocess.Popen[str], label: str
) -> tuple[int, bytes, dict[str, str]]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"{label} exited before becoming reachable: returncode={process.returncode}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            )
        result = _request(url)
        if result[0] > 0:
            return result
        time.sleep(0.1)
    raise RuntimeError(f"{label} did not become reachable at {url}")


def _stop(process: subprocess.Popen[str], label: str) -> None:
    if process.poll() is None:
        os.killpg(os.getpgid(process.pid), signal.SIGINT)
    try:
        stdout, stderr = process.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(f"{label} did not shut down cleanly: stderr={stderr!r}")
    if process.returncode != 0:
        raise RuntimeError(
            f"{label} exited unsuccessfully: returncode={process.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )


def _build_fixture(path: Path):
    from turtle_value_engine import load_normalized_input
    from turtle_value_engine.pipeline import run_analyze
    from turtle_value_engine.surface import build_research_surface_snapshot

    analysis = run_analyze(load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json"))
    snapshot = build_research_surface_snapshot(analysis)
    path.write_bytes(snapshot.canonical_bytes())
    return snapshot


def main() -> int:
    api_port = _free_port()
    dashboard_port = _free_port()
    api_process: subprocess.Popen[str] | None = None
    dashboard_process: subprocess.Popen[str] | None = None
    dev_vars = DASHBOARD / ".dev.vars"
    previous_dev_vars = dev_vars.read_bytes() if dev_vars.exists() else None

    node = Path(shutil.which("node") or "node")
    node_dir = node.parent if node.parent != Path("") else Path.cwd()
    vite = DASHBOARD / "node_modules" / ".bin" / "vite"
    if not vite.exists():
        raise RuntimeError(
            "Dashboard Vite is unavailable; install the declared Dashboard dependencies first"
        )
    smoke_env = os.environ.copy()
    smoke_env["PATH"] = f"{node_dir}:{smoke_env.get('PATH', '')}"
    smoke_env["CI"] = "1"

    try:
        with tempfile.TemporaryDirectory(prefix="tve-dashboard-smoke-") as temp_dir:
            snapshot_path = Path(temp_dir) / "frozen-surface.json"
            snapshot = _build_fixture(snapshot_path)
            dev_vars.write_text(
                f"SURFACE_API_ORIGIN=http://127.0.0.1:{api_port}\n",
                encoding="utf-8",
            )

            build = subprocess.run(
                [str(vite), "build"],
                cwd=DASHBOARD,
                env=smoke_env,
                capture_output=True,
                text=True,
                check=False,
            )
            if build.returncode != 0:
                raise RuntimeError(
                    f"Dashboard build for preview failed: stdout={build.stdout!r}; "
                    f"stderr={build.stderr!r}"
                )

            api_command = [
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
                str(api_port),
            ]
            api_process = subprocess.Popen(
                api_command,
                cwd=ROOT,
                env=smoke_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            _wait_for(f"http://127.0.0.1:{api_port}/healthz", api_process, "M6-B API")

            dashboard_command = [
                str(node),
                str(ROOT / "scripts" / "dashboard_preview_runner.mjs"),
                str(vite),
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(dashboard_port),
                "--strictPort",
            ]
            dashboard_process = subprocess.Popen(
                dashboard_command,
                cwd=DASHBOARD,
                env=smoke_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            root_status, root_body, _ = _wait_for(
                f"http://127.0.0.1:{dashboard_port}/",
                dashboard_process,
                "Dashboard Worker preview",
            )
            if root_status != 200 or b"Turtle Value Engine" not in root_body:
                raise RuntimeError(
                    f"Dashboard root did not return the built HTML: status={root_status}"
                )

            base = f"http://127.0.0.1:{dashboard_port}"
            health_status, health_body, _ = _request(base + "/api/healthz")
            if health_status != 200 or json.loads(health_body)["loaded_snapshot_count"] != 1:
                raise RuntimeError(
                    f"same-origin health check failed: {health_status} {health_body!r}"
                )

            list_status, list_body, _ = _request(base + "/api/v1/surfaces")
            if (
                list_status != 200
                or json.loads(list_body)["surfaces"][0]["surface_id"] != snapshot.surface_id
            ):
                raise RuntimeError(f"same-origin list check failed: {list_status} {list_body!r}")

            detail_status, detail_body, _ = _request(
                base + f"/api/v1/surfaces/{snapshot.surface_id}"
            )
            detail = json.loads(detail_body)
            if (
                detail_status != 200
                or detail["surface_id"] != snapshot.surface_id
                or detail["content_sha256"] != snapshot.content_sha256
            ):
                raise RuntimeError(
                    f"same-origin detail check failed: {detail_status} {detail_body!r}"
                )

            unknown_status, _, _ = _request(base + "/api/v1/surfaces/" + "0" * 64)
            if unknown_status != 404:
                raise RuntimeError(f"unknown surface should remain 404, got {unknown_status}")

            for method in ("POST", "PUT", "PATCH", "DELETE"):
                mutation_status, mutation_body, _ = _request(
                    base + f"/api/v1/surfaces/{snapshot.surface_id}",
                    method=method,
                    body=b"{}",
                )
                mutation = json.loads(mutation_body)
                if (
                    mutation_status != 405
                    or mutation["error"]["code"] != "READ_ONLY_METHOD_NOT_ALLOWED"
                ):
                    raise RuntimeError(
                        f"Worker {method} mutation boundary failed: "
                        f"{mutation_status} {mutation_body!r}"
                    )

            print(
                "M6-C1 cross-stack smoke passed: fixture -> M6-B -> Cloudflare/Vite preview -> "
                "same-origin health/list/detail/404/mutations"
            )
            return 0
    finally:
        if dashboard_process is not None:
            _stop(dashboard_process, "Dashboard Worker preview")
        if api_process is not None:
            _stop(api_process, "M6-B API")
        if previous_dev_vars is None:
            dev_vars.unlink(missing_ok=True)
        else:
            dev_vars.write_bytes(previous_dev_vars)


if __name__ == "__main__":
    raise SystemExit(main())
