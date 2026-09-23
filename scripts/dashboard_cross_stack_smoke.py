"""Black-box M6-C1/6-D3 smoke across the Python API and the local Worker preview."""

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


def _build_monitoring_fixture(chain_dir: Path):
    """Build a genuine Phase 6-A/6-C/D1/D2A/D2B store chain on disk.

    The delivery leg intentionally ends as an R2 orphan: the durable dispatch
    claim consumed the only authorized outbound slot while no attempt outcome
    ever became durable, so persisted outcome count and consumed slot count
    are observably distinct facts.
    """

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.test_monitoring_dashboard import _deliver, _run_chain
    from tests.test_monitoring_delivery import _CrashAfterDispatchTransport, _settings

    chain_dir.mkdir(parents=True, exist_ok=True)
    chain = _run_chain(chain_dir, event_type="INTERIM_REPORT", binding=True)
    settings = _settings(max_attempts=1, receiver_idempotency_declared=True)
    try:
        _deliver(chain, chain_dir, _CrashAfterDispatchTransport(), settings=settings)
    except RuntimeError as error:
        if "after possible dispatch" not in str(error):
            raise
    return chain


def _expected_monitoring_projection(chain, chain_dir: Path):
    """Read-only ground truth derived in-process from the real store chain."""

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from turtle_value_engine.monitoring_operations import (
        build_monitoring_operations_projection,
        sources_from_runner_config,
    )

    return build_monitoring_operations_projection(
        sources_from_runner_config(chain.config, delivery_root=str(chain_dir / "delivery"))
    )


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
            chain_dir = Path(temp_dir) / "monitoring-chain"
            chain = _build_monitoring_fixture(chain_dir)
            expected = _expected_monitoring_projection(chain, chain_dir)
            runner_config_path = Path(temp_dir) / "runner-config.json"
            runner_config_path.write_text(chain.config.model_dump_json(), encoding="utf-8")
            project_config_path = Path(temp_dir) / "project.toml"
            project_config_path.write_text(
                "[monitoring.delivery]\n"
                f"delivery_root = {json.dumps(str(chain_dir / 'delivery'))}\n",
                encoding="utf-8",
            )
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
                "--monitoring-runner-config",
                str(runner_config_path),
                "--monitoring-project-config",
                str(project_config_path),
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

            monitoring_status, monitoring_body, monitoring_headers = _request(
                base + "/api/v1/monitoring/operations"
            )
            projection = json.loads(monitoring_body)
            cache_control = monitoring_headers.get("Cache-Control") or monitoring_headers.get(
                "cache-control"
            )
            if monitoring_status != 200 or cache_control != "no-store":
                raise RuntimeError(
                    f"same-origin monitoring check failed: "
                    f"{monitoring_status} {cache_control!r} {monitoring_body!r}"
                )
            expected_activation = expected.activation
            expected_cycle = expected.cycle
            expected_delivery = expected.deliveries[0]
            expected_job = expected.jobs[0]
            problems = []
            if projection["runner_id"] != chain.config.runner_id:
                problems.append(f"runner_id={projection['runner_id']!r}")
            activation = projection.get("activation") or {}
            if activation.get("activation_id") != expected_activation.activation_id:
                problems.append(f"activation_id={activation.get('activation_id')!r}")
            if activation.get("kind") != "LATEST_TERMINAL":
                problems.append(f"activation.kind={activation.get('kind')!r}")
            cycle = projection.get("cycle") or {}
            if cycle.get("cycle_id") != expected_cycle.cycle_id:
                problems.append(f"cycle_id={cycle.get('cycle_id')!r}")
            if cycle.get("status") != "ALERTS_EMITTED":
                problems.append(f"cycle.status={cycle.get('status')!r}")
            jobs = projection.get("jobs") or []
            if len(jobs) != 1 or jobs[0].get("job_id") != expected_job.job_id:
                problems.append(f"jobs={jobs!r}")
            elif jobs[0].get("disposition_status") != "SUCCEEDED":
                problems.append(f"job.status={jobs[0].get('disposition_status')!r}")
            deliveries = projection.get("deliveries") or []
            if len(deliveries) != 1 or deliveries[0].get("delivery_id") != (
                expected_delivery.delivery_id
            ):
                problems.append(f"deliveries={deliveries!r}")
            else:
                delivery = deliveries[0]
                state = delivery.get("state") or {}
                # The R2 accounting pair must survive the whole path: zero
                # persisted outcomes, one consumed authorized outbound slot,
                # and the unresolved slot number preserved.
                if state.get("status") != "AMBIGUOUS":
                    problems.append(f"delivery.status={state.get('status')!r}")
                if state.get("last_error_code") != "ORPHANED_DISPATCH":
                    problems.append(f"delivery.error={state.get('last_error_code')!r}")
                if state.get("attempt_count") != 0:
                    problems.append(f"attempt_count={state.get('attempt_count')!r}")
                if delivery.get("dispatch_claim_count") != 1:
                    problems.append(
                        f"dispatch_claim_count={delivery.get('dispatch_claim_count')!r}"
                    )
                if delivery.get("unresolved_claim_numbers") != [1]:
                    problems.append(f"unresolved={delivery.get('unresolved_claim_numbers')!r}")
            if problems:
                raise RuntimeError(f"monitoring projection mismatch over the wire: {problems}")

            monitoring_text = monitoring_body.decode("utf-8")
            for sentinel in (
                "webhook-path-secret-sentinel-7f31",
                "webhook-bearer-secret-sentinel-9c2d",
                str(temp_dir),
                "delivery_root",
            ):
                if sentinel in monitoring_text:
                    raise RuntimeError(
                        f"monitoring response leaked a forbidden sentinel: {sentinel!r}"
                    )

            mutation_status, mutation_body, _ = _request(
                base + "/api/v1/monitoring/operations", method="POST", body=b"{}"
            )
            mutation = json.loads(mutation_body)
            if (
                mutation_status != 405
                or mutation["error"]["code"] != "READ_ONLY_METHOD_NOT_ALLOWED"
            ):
                raise RuntimeError(
                    f"Worker monitoring mutation boundary failed: "
                    f"{mutation_status} {mutation_body!r}"
                )

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
                "M6-C1/6-D3 cross-stack smoke passed: fixture -> M6-B -> Cloudflare/Vite "
                "preview -> same-origin health/list/detail/404/mutations plus the R2-orphan "
                "monitoring operations projection (identities, statuses, distinct outcome/"
                "slot counts, unresolved slots, no secret/path leakage)"
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
