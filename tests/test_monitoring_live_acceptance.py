"""Deterministic tests for the Phase 6-E live-acceptance harness.

These tests stay offline and mutation-free with respect to the host system:
systemd is only exercised through ``systemd-analyze verify`` on files inside
a temporary directory, live paths are never invoked, and the lock-visibility
proof runs against a private temporary lease slot with real local
subprocesses (the same proof the preflight performs on the deployment host).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.monitoring_live_acceptance as harness
from scripts.monitoring_live_acceptance import (
    _SOCKET_GUARD_SOURCE_TEMPLATE,
    DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN,
    EXIT_FAIL_CLOSED,
    EXIT_MARKER,
    EXIT_OK,
    MANUAL_SECRET_REFERENCE_REQUIRED,
    MANUAL_SUDO_INSTALL_REQUIRED,
    AcceptanceConfigV1,
    AcceptanceError,
    ManualBoundary,
    _finish_report,
    _materialize_workspace,
    _systemd_analyze_verify,
    _tracked_files_without_secrets,
    cmd_apply,
    cmd_render,
    gate_commands,
    load_acceptance_config,
    load_gate_artifact,
    probe_lock_visibility,
    redact_text,
    render_service_unit,
    render_timer_unit,
    scan_bytes_for_secrets,
)

IS_LINUX = sys.platform.startswith("linux")

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_runner(results: dict[tuple[str, ...], subprocess.CompletedProcess]):
    """A deterministic command runner keyed by argv prefix."""

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        for prefix, completed in results.items():
            if tuple(argv[: len(prefix)]) == tuple(prefix):
                return completed
        return subprocess.CompletedProcess(argv, 0, "", "")

    return runner


def _acceptance_config(**overrides: object) -> AcceptanceConfigV1:
    values: dict[str, object] = {
        "scope": "user",
        "python_executable": sys.executable,
        "working_directory": str(REPO_ROOT),
        "unit_base_name": "tve-phase6e-test",
        "on_calendar": "daily",
        "randomized_delay_sec": 0,
        "acceptance_root": "/tmp/phase6e-acceptance/does-not-matter",
        "runner_id": "phase6e-test",
        "watchlist_id": "phase6e-test-watchlist",
        "listings": ["SH600519"],
        "published_from": "2026-04-15",
        "published_to": "2026-04-17",
        "as_of": "2026-04-18T00:00:00+00:00",
    }
    values.update(overrides)
    return AcceptanceConfigV1.model_validate(values)


# ---------------------------------------------------------------------------
# Acceptance configuration
# ---------------------------------------------------------------------------


def test_checked_in_example_config_parses() -> None:
    config = load_acceptance_config(REPO_ROOT / "config" / "monitoring-acceptance.example.json")
    assert config.scope == "system"
    assert config.delivery_endpoint_env == "TVE_MONITORING_WEBHOOK_URL"
    assert 1 <= len(config.listings) <= 2


def test_config_rejects_more_than_two_listings() -> None:
    with pytest.raises(Exception):
        _acceptance_config(listings=["SH600519", "SZ000858", "SH601318"])


def test_config_rejects_wide_window_and_bad_scope() -> None:
    with pytest.raises(Exception):
        _acceptance_config(published_from="2026-01-01", published_to="2026-04-17")
    with pytest.raises(Exception):
        _acceptance_config(scope="system")
    with pytest.raises(Exception):
        _acceptance_config(acceptance_root="relative/path")
    with pytest.raises(Exception):
        _acceptance_config(as_of="2026-04-16T00:00:00+00:00")


def test_config_requires_timezone_aware_as_of() -> None:
    with pytest.raises(Exception):
        _acceptance_config(as_of="2026-04-18T00:00:00")


# ---------------------------------------------------------------------------
# Rendering: deterministic, secret-free, mutation-free
# ---------------------------------------------------------------------------


def test_render_is_deterministic_and_contains_no_secrets(tmp_path: Path) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    runner_config = config.runner_live_config_path
    runner_config.parent.mkdir(parents=True, exist_ok=True)
    runner_config.write_text("{}", encoding="utf-8")
    first = render_service_unit(config, runner_config)
    second = render_service_unit(config, runner_config)
    assert first == second
    assert "User=" not in first  # user scope must not pin a service user
    assert str(runner_config) in first
    assert "watch unattended-run" in first
    assert "SuccessExitStatus=3" in first
    timer = render_timer_unit(config)
    assert f"OnCalendar={config.on_calendar}" in timer
    assert config.service_unit_name in timer


def test_render_system_scope_pins_service_user(tmp_path: Path) -> None:
    config = _acceptance_config(
        scope="system", service_user="turtle", acceptance_root=str(tmp_path)
    )
    content = render_service_unit(config, config.runner_live_config_path)
    assert "User=turtle" in content


@pytest.mark.skipif(not IS_LINUX, reason="systemd-analyze is a Linux host tool")
def test_cmd_render_verifies_and_writes_redacted_plan(tmp_path: Path) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    config.runner_live_config_path.parent.mkdir(parents=True, exist_ok=True)
    config.runner_live_config_path.write_text("{}", encoding="utf-8")
    args = SimpleNamespace(
        acceptance_config=None,
        allow_missing_runner_config=False,
    )
    args.acceptance_config = _write_config(tmp_path, config)
    rc = cmd_render(args)
    assert rc == EXIT_OK
    plan = json.loads((config.systemd_output_dir / "render-plan.json").read_text(encoding="utf-8"))
    assert plan["mutation_of_system_performed"] is False
    assert plan["contains_secrets"] is False
    assert plan["verify"]["returncode"] == 0
    assert len(plan["files"]) == 2
    first_service = (config.systemd_output_dir / config.service_unit_name).read_bytes()
    # Idempotent rerender: identical bytes.
    assert cmd_render(args) == EXIT_OK
    assert (config.systemd_output_dir / config.service_unit_name).read_bytes() == first_service


@pytest.mark.skipif(not IS_LINUX, reason="systemd-analyze is a Linux host tool")
def test_systemd_analyze_verify_detects_broken_unit(tmp_path: Path) -> None:
    broken = tmp_path / "broken.service"
    broken.write_text("[Service]\nType=oneshot\n", encoding="utf-8")
    outcome = _systemd_analyze_verify((broken,), runner=harness._default_runner)
    assert not outcome.ok


# ---------------------------------------------------------------------------
# Gate artifact binding
# ---------------------------------------------------------------------------


def _write_config(directory: Path, config: AcceptanceConfigV1) -> Path:
    path = directory / "acceptance-config.json"
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_gate_artifact_binding(tmp_path: Path) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    good = {"head_sha": "a" * 40, "green": True}
    config.gate_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    config.gate_artifact_path.write_text(json.dumps(good), encoding="utf-8")
    assert load_gate_artifact(config, head_sha="a" * 40) == good
    with pytest.raises(AcceptanceError):
        load_gate_artifact(config, head_sha="b" * 40)
    config.gate_artifact_path.write_text(
        json.dumps({"head_sha": "a" * 40, "green": False}), encoding="utf-8"
    )
    with pytest.raises(AcceptanceError):
        load_gate_artifact(config, head_sha="a" * 40)
    config.gate_artifact_path.unlink()
    with pytest.raises(AcceptanceError):
        load_gate_artifact(config, head_sha="a" * 40)


def test_gate_commands_match_the_mandatory_gate() -> None:
    commands = gate_commands(sys.executable)
    names = [name for name, _argv, _env in commands]
    assert names == [
        "ruff",
        "config-validate",
        "monitoring-suite",
        "python-suite",
        "surface-openapi-check",
        "dashboard-install",
        "dashboard-api-check",
        "dashboard-types-check",
        "dashboard-lint",
        "dashboard-typecheck",
        "dashboard-test",
        "dashboard-build",
        "dashboard-security-client-bundle",
        "wrangler-strict-dry-run",
        "cross-stack-smoke",
        "systemd-verify-reference",
    ]
    build = next(argv for name, argv, _env in commands if name == "dashboard-build")
    assert build[0] == "pnpm"
    env = next(env for name, _argv, env in commands if name == "dashboard-build")
    assert env["CLOUDFLARE_API_TOKEN"].endswith("sentinel")


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_secret_scan_and_redaction() -> None:
    secrets = {"TVE_MONITORING_WEBHOOK_URL": "https://secret.example/hook?tok=abc"}
    data = b"endpoint https://secret.example/hook?tok=abc here"
    assert scan_bytes_for_secrets(data, secrets) == ["TVE_MONITORING_WEBHOOK_URL"]
    assert scan_bytes_for_secrets(b"nothing here", secrets) == []
    text = "url=https://secret.example/hook?tok=abc tail"
    assert redact_text(text, secrets) == "url=[REDACTED] tail"


def test_finish_report_refuses_to_persist_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    report = {"phase_state": "X", "detail": "https://secret.example/hook?tok=abc"}
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://secret.example/hook?tok=abc")
    with pytest.raises(AcceptanceError):
        _finish_report(config, report)
    assert not config.report_path.exists()


def test_tracked_files_secret_scan_uses_git_listing() -> None:
    secret = {"TVE_MONITORING_WEBHOOK_URL": "https://secret.example/hook"}
    listing = subprocess.CompletedProcess(
        None, 0, "scripts/monitoring_live_acceptance.py\0config/project.example.toml\0", ""
    )
    clean = _tracked_files_without_secrets(_fake_runner({("git", "ls-files"): listing}), secret)
    assert clean["clean"] is True
    reading = subprocess.CompletedProcess(None, 0, "config/project.example.toml\0", "")
    with_patch = _fake_runner({("git", "ls-files"): reading})
    # The real config file does not contain the secret either.
    assert _tracked_files_without_secrets(with_patch, secret)["clean"] is True


# ---------------------------------------------------------------------------
# Lock visibility proof
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not IS_LINUX, reason="flock//proc/locks proof is Linux-only")
def test_probe_lock_visibility_proves_shared_truth(tmp_path: Path) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    result = probe_lock_visibility(config, tmp_path / "runner", python=sys.executable)
    assert result["proven"] is True, result
    steps = result["steps"]
    assert steps["observer_while_held"] == "LIVE"
    assert steps["observer_after_release"] in {"ABANDONED", "FREE"}
    assert steps["runner_context_while_held"] == "BUSY"
    assert steps["runner_context_after_release"] == "ACQUIRED"
    assert result["observer_acquired_lock"] is False


@pytest.mark.skipif(not IS_LINUX, reason="holder subprocess is Linux-only")
def test_probe_lock_visibility_classifies_broken_holder(tmp_path: Path) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    result = probe_lock_visibility(
        config, tmp_path / "runner", python="/nonexistent/python-phase6e"
    )
    assert result["proven"] is False
    assert result["failure"] == "holder-subprocess-did-not-start"


# ---------------------------------------------------------------------------
# Apply boundary: precise manual marker when privilege is missing
# ---------------------------------------------------------------------------


def test_apply_system_scope_without_privilege_stops_at_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _acceptance_config(
        scope="system", service_user="turtle", acceptance_root=str(tmp_path)
    )
    output = config.systemd_output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / config.service_unit_name).write_text("[Service]\n", encoding="utf-8")
    (output / config.timer_unit_name).write_text("[Timer]\n", encoding="utf-8")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    denied = _fake_runner({("sudo", "-n", "true"): subprocess.CompletedProcess(None, 1, "", "")})
    args = SimpleNamespace(acceptance_config=_write_config(tmp_path, config), start_timer=False)
    with pytest.raises(ManualBoundary) as excinfo:
        cmd_apply(args, runner=denied)
    payload = excinfo.value.payload
    assert payload["marker"] == MANUAL_SUDO_INSTALL_REQUIRED
    for key in (
        "stopped_after",
        "human_action",
        "secret_boundary",
        "resume_command",
        "machine_verifiable_success",
        "remaining_unverified",
    ):
        assert isinstance(payload[key], str) and payload[key]


def test_apply_with_privilege_but_missing_install_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A passwordless-sudo host (GitHub runner) must not crash on a fake install."""

    config = _acceptance_config(
        scope="system", service_user="turtle", acceptance_root=str(tmp_path)
    )
    output = config.systemd_output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / config.service_unit_name).write_text("[Service]\n", encoding="utf-8")
    (output / config.timer_unit_name).write_text("[Timer]\n", encoding="utf-8")
    monkeypatch.setattr(harness, "_systemd_privilege_available", lambda *a, **k: True)
    # The fake runner reports success for every command without installing.
    nothing_installs = _fake_runner({})
    args = SimpleNamespace(
        acceptance_config=_write_config(tmp_path, config), start_timer=False
    )
    with pytest.raises(AcceptanceError, match="does not exist"):
        cmd_apply(args, runner=nothing_installs)


def test_main_maps_manual_boundary_to_marker_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _acceptance_config(
        scope="system", service_user="turtle", acceptance_root=str(tmp_path)
    )
    output = config.systemd_output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / config.service_unit_name).write_text("[Service]\n", encoding="utf-8")
    (output / config.timer_unit_name).write_text("[Timer]\n", encoding="utf-8")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        harness,
        "run_command",
        lambda *argv, **kwargs: harness.CommandOutcome(
            ("sudo", "-n", "true"), 1, "", "authentication required"
        )
        if argv and tuple(argv[0][:3]) == ("sudo", "-n", "true")
        else harness._default_runner(*argv, **kwargs),
    )
    config_path = _write_config(tmp_path, config)
    rc = harness.main(["--acceptance-config", str(config_path), "apply"])
    assert rc == EXIT_MARKER
    payload = json.loads(capsys.readouterr().out)
    assert payload["marker"] == MANUAL_SUDO_INSTALL_REQUIRED


# ---------------------------------------------------------------------------
# Workspace materialization and delivery marker
# ---------------------------------------------------------------------------


def test_materialize_workspace_writes_typed_isolated_inputs(tmp_path: Path) -> None:
    from turtle_value_engine.config import load_project_config
    from turtle_value_engine.monitoring_runner.contracts import RunnerConfigV1

    config = _acceptance_config(acceptance_root=str(tmp_path))
    summary = _materialize_workspace(config)
    assert summary["watchlist_id"] == config.watchlist_id

    live = RunnerConfigV1.model_validate(
        json.loads(config.runner_live_config_path.read_text(encoding="utf-8"))
    )
    assert live.network_allowed is True
    assert Path(live.monitoring_workspace_root).resolve().is_relative_to(tmp_path.resolve())
    resume = RunnerConfigV1.model_validate(
        json.loads(config.runner_resume_config_path.read_text(encoding="utf-8"))
    )
    assert resume.as_of is not None and resume.as_of > live.as_of

    project = load_project_config(config.project_config_path)
    assert project.monitoring.delivery.enabled is True
    assert project.monitoring.delivery.endpoint_ref is not None
    assert project.monitoring.delivery.endpoint_ref.env == config.delivery_endpoint_env


def test_delivery_section_without_owner_endpoint_records_precise_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.monitoring_live_acceptance import _delivery_section

    config = _acceptance_config(acceptance_root=str(tmp_path), delivery_receiver="owner_env")
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_TOKEN", raising=False)
    markers: list[dict[str, object]] = []
    section = _delivery_section(
        config, sys.executable, _fake_runner({}), {"activation_id": "a" * 64}, markers.append
    )
    assert section["ok"] is False
    assert section["skipped"] is True
    assert markers and markers[0]["marker"] == MANUAL_SECRET_REFERENCE_REQUIRED
    for key in (
        "stopped_after",
        "human_action",
        "secret_boundary",
        "resume_command",
        "machine_verifiable_success",
        "remaining_unverified",
    ):
        assert markers[0][key]


# ---------------------------------------------------------------------------
# Socket guard
# ---------------------------------------------------------------------------


def test_socket_guard_blocks_any_connect_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    guard = types.ModuleType("guard_under_test")
    # Snapshot the socket surface so the in-process guard activation cannot
    # poison unrelated tests in the same session.
    originals = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.create_connection,
        socket.getaddrinfo,
    )
    # Activate only the guard-patching prologue of the wrapper source.
    source = _SOCKET_GUARD_SOURCE_TEMPLATE.split("from turtle_value_engine.cli")[0]
    try:
        exec(source, guard.__dict__)  # noqa: S102 - test-only guard activation
        # After activation, every outbound socket path is hard-blocked.
        with pytest.raises(AssertionError, match="SOCKET_CONNECT_ATTEMPTED"):
            socket.create_connection(("127.0.0.1", 1), timeout=0.2)
        with pytest.raises(AssertionError, match="SOCKET_CONNECT_ATTEMPTED"):
            socket.getaddrinfo("127.0.0.1", 1)
    finally:
        (
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.create_connection,
            socket.getaddrinfo,
        ) = originals


def test_socket_guard_wrapper_runs_cli_help_offline(tmp_path: Path) -> None:
    guard_script = tmp_path / "guard.py"
    guard_script.write_text(_SOCKET_GUARD_SOURCE_TEMPLATE, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(guard_script), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0


# ---------------------------------------------------------------------------
# Report validation
# ---------------------------------------------------------------------------


def test_cmd_report_validates_and_flags_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _acceptance_config(acceptance_root=str(tmp_path))
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    good = {
        "contract": "monitoring_live_acceptance_report_v1",
        "phase_state": "READY_FOR_OWNER_AUTHORIZED_PHASE_6E",
        "failures": [],
        "markers": [],
    }
    config.report_path.write_text(json.dumps(good), encoding="utf-8")
    rc = harness.main(["--acceptance-config", str(_write_config(tmp_path, config)), "report"])
    assert rc == EXIT_OK
    bad = dict(good, failures=["delivery"])
    config.report_path.write_text(json.dumps(bad), encoding="utf-8")
    capsys.readouterr()
    rc = harness.main(["--acceptance-config", str(_write_config(tmp_path, config)), "report"])
    assert rc == EXIT_FAIL_CLOSED


def test_lock_visibility_marker_is_precise() -> None:
    # The unproven-topology marker is a distinct machine-readable constant.
    assert DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN == "DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN"
    assert EXIT_OK == 0 and EXIT_FAIL_CLOSED == 2 and EXIT_MARKER == 5
