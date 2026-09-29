"""Deterministic tests for the Phase 6-F production-operations harness.

These tests stay offline and host-mutation-free: systemd is exercised only
through ``systemd-analyze verify`` on files inside a temporary directory and
injected fake command runners; no real unit is installed, enabled, started
or disabled.  The lock-visibility proof is not re-run here (it is covered by
the Phase 6-E harness tests) and production firings are proven on the real
host, not in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

import pytest

import scripts.monitoring_production_ops as prodops
from scripts.monitoring_live_acceptance import (
    EXIT_FAIL_CLOSED,
    EXIT_MARKER,
    EXIT_OK,
    AcceptanceError,
    ManualBoundary,
)
from scripts.monitoring_production_ops import (
    MANUAL_ENABLE_LINGER_REQUIRED,
    WINDOWS_HOST_BOOTSTRAP_UNPROVEN,
    ProductionConfigV1,
    build_runner_config,
    classify_topology_from_facts,
    compute_plan,
    ensure_linger,
    environment_file_values,
    load_production_config,
    render_project_config,
    render_service_unit,
    render_timer_unit,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAD_SHA = "0" * 40


class FakeRunner:
    """Deterministic, stateful command runner keyed by argv prefixes."""

    def __init__(
        self,
        responses: dict[tuple[str, ...], str] | None = None,
        *,
        config: ProductionConfigV1 | None = None,
    ) -> None:
        self.responses: dict[tuple[str, ...], str] = dict(responses or {})
        self.config = config
        self.calls: list[tuple[str, ...]] = []
        self.linger_enabled = False
        self.timer_enabled = False
        self.service_started = False

    def add(self, prefix: tuple[str, ...], stdout: str) -> None:
        self.responses[prefix] = stdout

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(tuple(argv))
        for prefix, stdout in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, 0, stdout, "")
        if argv[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(argv, 0, HEAD_SHA, "")
        if argv[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:1] == ["install"]:
            target = Path(argv[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(argv[-2]).read_bytes())
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["loginctl", "enable-linger"]:
            self.linger_enabled = True
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["loginctl", "show-user"]:
            value = "yes" if self.linger_enabled else "no"
            return subprocess.CompletedProcess(argv, 0, f"Linger={value}\n", "")
        if argv[:2] == ["systemctl", "--user"] and argv[2:4] == ["enable", "--now"]:
            self.timer_enabled = True
            self.service_started = True
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["systemctl", "--user"] and argv[2] == "enable":
            self.timer_enabled = True
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["systemctl", "--user"] and argv[2] == "disable":
            self.timer_enabled = False
            self.service_started = False
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["systemctl", "--user"] and argv[2] in {"start", "stop"}:
            unit = argv[3]
            if unit.endswith(".timer"):
                self.timer_enabled = argv[2] == "start"
            elif unit.endswith(".service"):
                self.service_started = argv[2] == "start"
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["systemctl", "--user"] and argv[2] == "show":
            return subprocess.CompletedProcess(argv, 0, self._show(argv), "")
        if argv[:1] == ["busctl"] and "get-property" in argv:
            return subprocess.CompletedProcess(argv, 0, self._busctl(argv), "")
        if argv[:1] == ["systemd-analyze"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:1] == ["journalctl"]:
            return subprocess.CompletedProcess(argv, 0, "COMPLETED_REUSED\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def _show(self, argv: list[str]) -> str:
        lines: list[str] = []
        properties = [item for item in argv if item.startswith("--property=")]
        for prop in properties:
            name = prop.partition("=")[2]
            if name == "UnitFileState":
                state = "enabled" if self.timer_enabled else "disabled"
                lines.append(f"UnitFileState={state}")
            elif name == "ActiveState":
                state = "active" if self.timer_enabled else "inactive"
                lines.append(f"ActiveState={state}")
            elif name == "Persistent":
                lines.append("Persistent=yes")
            elif name == "NextElapseUSecRealtime":
                lines.append("NextElapseUSecRealtime=Tue 2026-09-30 04:00:00 CST")
            elif name == "ExecMainStartTimestamp":
                lines.append(
                    "ExecMainStartTimestamp=Tue 2026-09-29 10:00:00 CST"
                    if self.service_started
                    else "ExecMainStartTimestamp="
                )
            elif name == "Result":
                lines.append("Result=success")
            elif name == "ExecMainStatus":
                lines.append("ExecMainStatus=0")
            elif name == "ExecStart":
                if self.config is not None:
                    subcommand = (
                        "unattended-notify"
                        if self.config.delivery_enabled
                        else "unattended-run"
                    )
                    command = (
                        f"{self.config.python_executable} -m turtle_value_engine watch "
                        f"{subcommand} --runner-config {self.config.runner_config_path}"
                    )
                    lines.append(
                        f"ExecStart={{ path={self.config.python_executable}"
                        f" ; argv[]={command} }}"
                    )
                else:
                    lines.append(
                        "ExecStart={ path=/usr/bin/python3 ; argv[]="
                        "/usr/bin/python3 -m help }"
                    )
            elif name == "ExecStartPre":
                if self.config is not None and self.config.delivery_enabled:
                    command = prodops.credential_gate_command(self.config)
                    lines.append(
                        f"ExecStartPre={{ path={self.config.python_executable}"
                        f" ; argv[]={command} }}"
                    )
                else:
                    lines.append("ExecStartPre=")
            elif name == "WorkingDirectory":
                directory = (
                    str(self.config.working_directory)
                    if self.config is not None
                    else "/srv/turtle-value-engine"
                )
                lines.append(f"WorkingDirectory={directory}")
            elif name == "User":
                lines.append("User=")
        return "\n".join(lines) + "\n"

    def _busctl(self, argv: list[str]) -> str:
        """The D-Bus manager-effective Exec/EnvironmentFile property payload.

        Mirrors ``busctl --json=short get-property ... Service <Prop>``: the
        ``data`` rows carry the exact manager-effective argv arrays the R4
        structural verification compares.  ``*_override`` lets a test publish
        a tampered effective argv while the textual properties stay
        substring-compatible (the pre-R4 blind spot).
        """

        if self.config is None:
            return ""
        property_name = argv[-1]
        runner_path = self.config.runner_config_path.resolve()
        if property_name == "ExecStart":
            argv_effective = getattr(self, "exec_start_override", None) or list(
                prodops.main_exec_argv(self.config, runner_path)
            )
            rows = [[self.config.python_executable, argv_effective, False, 0, 0, 0, 0, 0, 0, 0]]
        elif property_name == "ExecStartPre":
            if not self.config.delivery_enabled:
                return json.dumps({"type": "a(sasbttttuii)", "data": []})
            argv_effective = getattr(self, "exec_start_pre_override", None) or list(
                prodops.credential_gate_argv(self.config)
            )
            rows = [[self.config.python_executable, argv_effective, False, 0, 0, 0, 0, 0, 0, 0]]
        elif property_name == "EnvironmentFiles":
            if not self.config.delivery_enabled or not self.config.delivery_environment_file:
                return json.dumps({"type": "a(sb)", "data": []})
            rows = [[self.config.delivery_environment_file, False]]
        else:
            return ""
        return json.dumps({"type": "a(sasbttttuii)", "data": rows})


def _production_config(tmp_path: Path, **overrides: object) -> ProductionConfigV1:
    root = tmp_path / "production"
    values: dict[str, object] = {
        "scope": "user",
        "python_executable": sys.executable,
        "working_directory": str(REPO_ROOT),
        "unit_base_name": "tve-production-test",
        "on_calendar": "daily",
        "randomized_delay_sec": 0,
        "production_root": str(root),
        "runner_id": "production-test",
        "watchlist_path": str(root / "watchlist.json"),
        "monitoring_workspace_root": str(root / "workspace"),
        "reanalysis_job_root": str(root / "reanalysis"),
        "cycle_store_root": str(root / "cycles"),
        "runner_root": str(root / "runner"),
        "cache_dir": str(root / "provider-cache"),
        "delivery_root": str(root / "delivery"),
        "network_allowed": True,
        "window_days": 7,
    }
    values.update(overrides)
    return ProductionConfigV1.model_validate(values)


def _write_watchlist(config: ProductionConfigV1) -> None:
    watchlist = {
        "contract": "watchlist_spec_v1",
        "schema_version": "1.0.0",
        "watchlist_id": "production-test-watchlist",
        "profile_id": "strict-v1",
        "entries": [{"listing_id": "SH600519"}, {"listing_id": "SZ000858"}],
    }
    path = Path(config.watchlist_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(watchlist), encoding="utf-8")


@pytest.fixture()
def destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dest = tmp_path / "systemd-destination"
    monkeypatch.setattr(prodops, "systemd_unit_destination_dir", lambda config: dest)
    return dest


# ---------------------------------------------------------------------------
# Configuration separation and validation
# ---------------------------------------------------------------------------


def test_checked_in_example_config_parses() -> None:
    config = load_production_config(
        REPO_ROOT / "config" / "monitoring-production.example.json"
    )
    assert config.scope in {"user", "system"}
    assert not config.delivery_enabled
    assert config.window_days >= 1


def test_config_rejects_phase6e_acceptance_reuse() -> None:
    with pytest.raises(Exception, match="acceptance"):
        ProductionConfigV1.model_validate(
            {
                "scope": "user",
                "python_executable": "/usr/bin/python3",
                "working_directory": "/srv/x",
                "unit_base_name": "tve-production-test",
                "on_calendar": "daily",
                "randomized_delay_sec": 0,
                "production_root": "/tmp/x/.tve-private/monitoring/phase6e",
                "runner_id": "production-test",
                "watchlist_path": "/tmp/x/watchlist.json",
                "monitoring_workspace_root": "/tmp/x/ws",
                "reanalysis_job_root": "/tmp/x/re",
                "cycle_store_root": "/tmp/x/cy",
                "runner_root": "/tmp/x/ru",
                "cache_dir": "/tmp/x/ca",
                "delivery_root": "/tmp/x/de",
                "window_days": 7,
            }
        )


def test_config_rejects_acceptance_unit_and_runner_namespace(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="unit_base_name"):
        _production_config(tmp_path, unit_base_name="tve-phase6e-acceptance")
    with pytest.raises(Exception, match="runner_id"):
        _production_config(tmp_path, runner_id="phase6e-owner-acceptance")


def test_system_scope_requires_service_user(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="service_user"):
        _production_config(tmp_path, scope="system")


def test_delivery_enabled_requires_typed_environment_file(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="delivery_environment_file"):
        _production_config(tmp_path, delivery_enabled=True)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_is_deterministic_and_secret_free(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    runner_config_path = config.runner_config_path
    first = render_service_unit(config, runner_config_path)
    second = render_service_unit(config, runner_config_path)
    assert first == second
    assert "\nEnvironmentFile=" not in first
    assert "unattended-run" in first
    assert "unattended-notify" not in first
    assert "TVE_MONITORING" not in first
    assert render_timer_unit(config).count("Persistent=true") == 1


def test_render_with_delivery_uses_notify_and_environment_file(tmp_path: Path) -> None:
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(tmp_path / "production" / "secrets.env"),
    )
    unit = render_service_unit(config, config.runner_config_path)
    assert f"EnvironmentFile={tmp_path / 'production' / 'secrets.env'}" in unit
    assert "unattended-notify" in unit
    assert "unattended-run" not in unit
    # Only the path appears; a value never does.
    assert (
        "=" not in unit.split(f"EnvironmentFile={tmp_path / 'production' / 'secrets.env'}")
        [1]
        .splitlines()[0]
    )


def test_runner_config_uses_rolling_window_and_live_optin(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    runner_config = build_runner_config(config)
    assert runner_config.network_allowed is True
    assert runner_config.window_days == 7
    assert runner_config.published_from is None
    assert runner_config.as_of is None


def test_project_config_delivery_disabled_and_enabled(tmp_path: Path) -> None:
    disabled = render_project_config(_production_config(tmp_path))
    assert "enabled = false" in disabled
    enabled = render_project_config(
        _production_config(
            tmp_path,
            delivery_enabled=True,
            delivery_environment_file=str(tmp_path / "production" / "secrets.env"),
        )
    )
    assert "enabled = true" in enabled
    assert "endpoint_ref" in enabled


def test_cmd_render_verifies_and_writes_material(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _production_config(tmp_path)
    _write_watchlist(config)
    monkeypatch.setattr(
        sys, "argv", ["monitoring_production_ops.py", "--production-config", "x", "render"]
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "render"]
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    assert config.runner_config_path.is_file()
    assert config.project_config_path.is_file()
    assert (config.systemd_output_dir / config.service_unit_name).is_file()
    assert (config.systemd_output_dir / "render-plan.json").is_file()
    plan = json.loads((config.systemd_output_dir / "render-plan.json").read_text())
    assert plan["contains_secrets"] is False
    assert plan["system_mutation_performed"] is False


def test_cmd_render_with_delivery_but_missing_env_file_stops_at_marker(
    tmp_path: Path, destination: Path
) -> None:
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(tmp_path / "production" / "secrets.env"),
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    for key in (
        "stopped_after",
        "human_action",
        "secret_boundary",
        "resume_command",
        "machine_verifiable_success",
        "remaining_unverified",
    ):
        assert payload[key]


# ---------------------------------------------------------------------------
# Plan (deterministic, redacted, mutation-free)
# ---------------------------------------------------------------------------


def test_plan_is_mutation_free_and_reports_actions(
    tmp_path: Path, destination: Path
) -> None:
    config = _production_config(tmp_path)
    runner = FakeRunner()
    plan = compute_plan(config, runner=runner)
    assert plan["mutation_performed"] is False
    assert plan["contains_secrets"] is False
    actions = {item["resource"]: item["action"] for item in plan["resources"]}
    assert actions["unit-file:" + config.service_unit_name] == "create"
    assert actions["runner-config"] == "create"
    assert actions["timer-enable"] == "enable"
    assert actions["timer-start"] == "explicit-activation-required"
    assert actions["linger"] == "enable"
    # Nothing was written anywhere.
    assert not destination.exists()
    assert not config.runner_config_path.exists()
    assert not config.systemd_output_dir.exists()


def test_plan_reports_unchanged_when_converged(
    tmp_path: Path, destination: Path
) -> None:
    config = _production_config(tmp_path)
    prodops._atomic_write(
        destination / config.service_unit_name,
        prodops.desired_unit_bytes(config)[config.service_unit_name],
    )
    prodops._atomic_write(
        destination / config.timer_unit_name,
        prodops.desired_unit_bytes(config)[config.timer_unit_name],
    )
    prodops._atomic_write(config.runner_config_path, prodops.desired_runner_config_bytes(config))
    runner = FakeRunner()
    runner.timer_enabled = True
    runner.linger_enabled = True
    plan = compute_plan(config, runner=runner)
    actions = {item["resource"]: item["action"] for item in plan["resources"]}
    assert actions["unit-file:" + config.service_unit_name] == "unchanged"
    assert actions["unit-file:" + config.timer_unit_name] == "unchanged"
    assert actions["runner-config"] == "unchanged"
    assert actions["timer-enable"] == "unchanged"
    assert actions["linger"] == "unchanged"


def test_plan_reports_modify_when_installed_bytes_diverge(
    tmp_path: Path, destination: Path
) -> None:
    config = _production_config(tmp_path)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / config.service_unit_name).write_text("stale unit\n")
    plan = compute_plan(config, runner=FakeRunner())
    entry = next(
        item
        for item in plan["resources"]
        if item["resource"] == "unit-file:" + config.service_unit_name
    )
    assert entry["action"] == "modify"
    assert entry["installed_sha256"] != entry["desired_sha256"]


# ---------------------------------------------------------------------------
# Apply / converge (idempotent, never starts recurring work)
# ---------------------------------------------------------------------------


def _apply_args(tmp_path: Path) -> argparse.Namespace:
    return prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "apply"]
    )


def test_apply_converges_and_is_idempotent(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _production_config(tmp_path)
    _write_watchlist(config)
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    render_args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "render"]
    )
    assert prodops.cmd_render(render_args, runner=FakeRunner()) == EXIT_OK

    runner = FakeRunner()
    assert prodops.cmd_apply(_apply_args(tmp_path), runner=runner) == EXIT_OK
    record = json.loads(
        (config.systemd_output_dir / "apply-record.json").read_text(encoding="utf-8")
    )
    assert record["applied"] is True
    actions = {item["resource"]: item["action"] for item in record["actions"]}
    assert actions[f"unit-file:{config.service_unit_name}"] == "installed"
    assert actions["linger"] == "enabled"
    # Apply must never start the timer.
    assert not any(
        call[:2] == ("systemctl", "--user") and "start" in call for call in runner.calls
    )
    assert not runner.service_started

    # Second apply converges without changes and stays idempotent.
    runner2 = FakeRunner()
    runner2.timer_enabled = True
    runner2.linger_enabled = True
    assert prodops.cmd_apply(_apply_args(tmp_path), runner=runner2) == EXIT_OK
    record2 = json.loads(
        (config.systemd_output_dir / "apply-record.json").read_text(encoding="utf-8")
    )
    actions2 = {item["resource"]: item["action"] for item in record2["actions"]}
    # daemon-reload always runs explicitly; everything else stays unchanged.
    assert set(actions2.values()) == {"unchanged", "performed"}
    assert actions2[f"unit-file:{config.service_unit_name}"] == "unchanged"
    assert actions2["timer-enable"] == "unchanged"
    assert actions2["linger"] == "unchanged"


def test_apply_system_scope_without_privilege_stops_at_marker(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _production_config(tmp_path, scope="system", service_user="turtle")
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    render_args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "render"]
    )
    assert prodops.cmd_render(render_args, runner=FakeRunner()) == EXIT_OK

    def no_sudo(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if argv[:3] == ["sudo", "-n", "true"]:
            return subprocess.CompletedProcess(argv, 1, "", "auth required")
        return FakeRunner()(argv, **kwargs)

    monkeypatch.setattr(prodops.os, "geteuid", lambda: 1000)
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_apply(_apply_args(tmp_path), runner=no_sudo)
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SUDO_INSTALL_REQUIRED"
    for key in (
        "stopped_after",
        "human_action",
        "secret_boundary",
        "resume_command",
        "machine_verifiable_success",
        "remaining_unverified",
    ):
        assert payload[key]


def test_apply_fails_closed_when_install_produces_no_file(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _production_config(tmp_path)
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    render_args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "render"]
    )
    assert prodops.cmd_render(render_args, runner=FakeRunner()) == EXIT_OK

    def lying_install(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(AcceptanceError, match="missing or diverged"):
        prodops.cmd_apply(_apply_args(tmp_path), runner=lying_install)


# ---------------------------------------------------------------------------
# Linger handling
# ---------------------------------------------------------------------------


def test_ensure_linger_already_enabled_is_unchanged(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    runner = FakeRunner()
    runner.linger_enabled = True
    result = ensure_linger(
        config,
        current_user="jelinenaro",
        runner=runner,
        production_config_path=tmp_path / "config.json",
    )
    assert result["action"] == "unchanged"
    assert result["state_before"] == "yes"


def test_ensure_linger_enables_automatically_and_verifies(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    runner = FakeRunner()  # starts at Linger=no; enable flips the state
    result = ensure_linger(
        config,
        current_user="jelinenaro",
        runner=runner,
        production_config_path=tmp_path / "config.json",
    )
    assert result["action"] == "enabled"
    assert result["state_after"] == "yes"
    assert ("loginctl", "enable-linger", "jelinenaro") in runner.calls


def test_ensure_linger_failure_stops_at_named_boundary(tmp_path: Path) -> None:
    config = _production_config(tmp_path)

    def broken(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if argv[:2] == ["loginctl", "enable-linger"]:
            return subprocess.CompletedProcess(argv, 1, "", "denied")
        if argv[:3] == ["loginctl", "show-user"]:
            return subprocess.CompletedProcess(argv, 0, "Linger=no\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(ManualBoundary) as excinfo:
        ensure_linger(
            config,
            current_user="jelinenaro",
            runner=broken,
            production_config_path=tmp_path / "config.json",
        )
    payload = excinfo.value.payload
    assert payload["marker"] == MANUAL_ENABLE_LINGER_REQUIRED
    assert "loginctl enable-linger" in payload["human_action"]
    assert "Linger=yes" in payload["machine_verifiable_success"]


# ---------------------------------------------------------------------------
# Topology classification (WSL capability boundary)
# ---------------------------------------------------------------------------


def test_topology_classifies_wsl2_with_narrow_claim() -> None:
    facts = classify_topology_from_facts(
        sys_platform="linux",
        kernel_release="6.18.33.2-microsoft-standard-WSL2",
        proc_version="Linux version 6.18 (Microsoft@WSL2)",
        pid1_comm="systemd",
        wsl_conf_text="[boot]\nsystemd=true\n",
        interop_available=True,
    )
    assert facts["wsl2"] is True
    assert facts["wsl_conf_systemd_boot"] is True
    assert facts["windows_host_bootstrap_proven"] is False
    assert "Windows-reboot" in facts["persistence_claim"]


def test_topology_native_linux_needs_no_windows_boundary() -> None:
    facts = classify_topology_from_facts(
        sys_platform="linux",
        kernel_release="6.8.0-generic",
        proc_version="Linux version 6.8",
        pid1_comm="systemd",
        wsl_conf_text=None,
        interop_available=False,
    )
    assert facts["wsl2"] is False
    assert facts["windows_host_bootstrap_proven"] is True


def test_windows_bootstrap_marker_carries_all_six_items(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    payload = prodops.windows_bootstrap_marker_payload(config, tmp_path / "config.json")
    assert payload["marker"] == WINDOWS_HOST_BOOTSTRAP_UNPROVEN
    for key in (
        "stopped_after",
        "human_action",
        "secret_boundary",
        "resume_command",
        "machine_verifiable_success",
        "remaining_unverified",
    ):
        assert payload[key]


# ---------------------------------------------------------------------------
# Activation / deactivation / effective-state verification
# ---------------------------------------------------------------------------


def test_activate_requires_apply_record(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "activate"]
    )
    with pytest.raises(AcceptanceError, match="apply record"):
        prodops.cmd_activate(args, runner=FakeRunner())


def test_activate_starts_timer_and_verifies(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    config.systemd_output_dir.mkdir(parents=True, exist_ok=True)
    (config.systemd_output_dir / "apply-record.json").write_text(
        json.dumps({"applied": True}), encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "activate"]
    )
    runner = FakeRunner()
    assert prodops.cmd_activate(args, runner=runner) == EXIT_OK
    record = json.loads(
        (config.systemd_output_dir / "activation-record.json").read_text(encoding="utf-8")
    )
    assert record["activated"] is True
    assert record["started_by_activate"] is True


def test_deactivate_is_idempotent(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "deactivate"]
    )
    runner = FakeRunner()
    runner.timer_enabled = True
    assert prodops.cmd_deactivate(args, runner=runner) == EXIT_OK
    record = json.loads(
        (config.systemd_output_dir / "deactivation-record.json").read_text(encoding="utf-8")
    )
    assert record["deactivated"] is True
    # Running deactivate again (already disabled) stays green.
    assert prodops.cmd_deactivate(args, runner=runner) == EXIT_OK


def test_verify_checks_effective_state(
    tmp_path: Path, destination: Path
) -> None:
    config = _production_config(tmp_path)
    prodops._atomic_write(
        destination / config.service_unit_name,
        prodops.desired_unit_bytes(config)[config.service_unit_name],
    )
    prodops._atomic_write(
        destination / config.timer_unit_name,
        prodops.desired_unit_bytes(config)[config.timer_unit_name],
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "verify", "--expect-active"]
    )
    runner = FakeRunner(config=config)
    runner.timer_enabled = True
    runner.linger_enabled = True
    runner.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "lease": {"state": "ABANDONED"},
                        "unfinished_activation_ids": [],
                        "latest": {"activation_id": "a" * 64, "classification": "COMPLETED_NEW"},
                    }
                ]
            }
        ),
    )
    assert prodops.cmd_verify(args, runner=runner) == EXIT_OK
    payload = json.loads(
        (config.systemd_output_dir / "verify-record.json").read_text(encoding="utf-8")
    )
    assert payload["green"] is True
    by_name = {item["name"]: item for item in payload["checks"]}
    assert by_name["timer.persistent"]["status"] == "PASS"
    assert by_name["linger"]["status"] == "PASS"


def test_verify_fails_when_units_diverge(tmp_path: Path, destination: Path) -> None:
    config = _production_config(tmp_path)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / config.service_unit_name).write_text("stale\n")
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "verify"]
    )
    assert prodops.cmd_verify(args, runner=FakeRunner()) == EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Credential source and delivery gating
# ---------------------------------------------------------------------------


def test_environment_file_values_parses_without_leaking(tmp_path: Path) -> None:
    env_file = tmp_path / "production" / "secrets.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "# comment\n; also a comment\n\n"
        "TVE_MONITORING_WEBHOOK_URL=https://example.invalid/hook\n"
        "TVE_MONITORING_WEBHOOK_TOKEN=tok-1\n",
        encoding="utf-8",
    )
    config = _production_config(
        tmp_path, delivery_enabled=True, delivery_environment_file=str(env_file)
    )
    values, error = environment_file_values(config)
    assert error is None
    assert values == {
        "TVE_MONITORING_WEBHOOK_URL": "https://example.invalid/hook",
        "TVE_MONITORING_WEBHOOK_TOKEN": "tok-1",
    }


def test_delivery_section_missing_secret_records_precise_marker(tmp_path: Path) -> None:
    env_file = tmp_path / "production" / "secrets.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("TVE_MONITORING_WEBHOOK_TOKEN=present\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    config = _production_config(
        tmp_path, delivery_enabled=True, delivery_environment_file=str(env_file)
    )
    section = prodops._delivery_section(
        config,
        FakeRunner(),
        "activation-id",
        production_config_path=tmp_path / "config.json",
    )
    assert section["ok"] is False
    marker = section["marker_payload"]
    assert marker["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "TVE_MONITORING_WEBHOOK_URL" in marker["human_action"]
    for key in (
        "stopped_after",
        "human_action",
        "secret_boundary",
        "resume_command",
        "machine_verifiable_success",
        "remaining_unverified",
    ):
        assert marker[key]


# ---------------------------------------------------------------------------
# Acceptance-root immutability and report validation
# ---------------------------------------------------------------------------


def test_acceptance_roots_immutability_detects_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_root = tmp_path / "fake-repo"
    phase6e = fake_root / ".tve-private" / "monitoring" / "phase6e"
    phase6e.mkdir(parents=True)
    (phase6e / "artifact.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(prodops, "ROOT", fake_root)
    before = {"phase6e": prodops.content_tree_hash(phase6e)}
    assert prodops._acceptance_roots_immutability(before)["ok"] is True
    (phase6e / "artifact.json").write_text('{"mutated": true}', encoding="utf-8")
    assert prodops._acceptance_roots_immutability(before)["ok"] is False


def test_report_validates_records_and_secret_scan(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _production_config(tmp_path)
    prodops._atomic_write(
        destination / config.service_unit_name,
        prodops.desired_unit_bytes(config)[config.service_unit_name],
    )
    prodops._atomic_write(
        destination / config.timer_unit_name,
        prodops.desired_unit_bytes(config)[config.timer_unit_name],
    )
    prodops._atomic_write(config.runner_config_path, prodops.desired_runner_config_bytes(config))
    config.systemd_output_dir.mkdir(parents=True, exist_ok=True)
    (config.systemd_output_dir / "apply-record.json").write_text(
        json.dumps({"applied": True}), encoding="utf-8"
    )
    (config.systemd_output_dir / "activation-record.json").write_text(
        json.dumps({"activated": True}), encoding="utf-8"
    )
    (config.systemd_output_dir / "verify-record.json").write_text(
        json.dumps({"green": True}), encoding="utf-8"
    )
    (config.systemd_output_dir / "live-proof-record.json").write_text(
        json.dumps({"failures": []}), encoding="utf-8"
    )
    (config.systemd_output_dir / "recover-proof-record.json").write_text(
        json.dumps({"failures": []}), encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    # Gate artifact bound to the faked HEAD.
    artifact = {"head_sha": HEAD_SHA, "green": True}
    prodops._atomic_write(config.gate_artifact_path, json.dumps(artifact).encode("utf-8"))

    monkeypatch.setattr(
        prodops, "load_gate_artifact", lambda config, head_sha: artifact
    )
    monkeypatch.setattr(prodops.acceptance, "_git_head", lambda cwd, runner: HEAD_SHA)
    monkeypatch.setattr(prodops.acceptance, "_git_clean", lambda cwd, runner: True)

    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "report"]
    )
    runner = FakeRunner()
    runner.timer_enabled = True
    runner.linger_enabled = True
    assert prodops.cmd_report(args, runner=runner) == EXIT_OK
    payload = json.loads(config.report_path.read_text(encoding="utf-8"))
    assert payload["contract"] == "monitoring_production_report_v1"
    # On a WSL host the Windows marker narrows the claim without blocking.
    if payload["host"]["wsl2"]:
        assert any(
            item["marker"] == WINDOWS_HOST_BOOTSTRAP_UNPROVEN for item in payload["markers"]
        )
    else:
        assert payload["markers"] == []


def test_report_refuses_missing_records(tmp_path: Path, destination: Path) -> None:
    config = _production_config(tmp_path)
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "report"]
    )
    assert prodops.cmd_report(args, runner=FakeRunner()) == EXIT_FAIL_CLOSED


def test_report_secret_scan_flags_resolved_values(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(tmp_path / "production" / "secrets.env"),
    )
    (tmp_path / "production" / "secrets.env").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "production" / "secrets.env").write_text(
        "TVE_MONITORING_WEBHOOK_URL=https://secret.invalid/hook\n", encoding="utf-8"
    )
    config.runner_config_path.parent.mkdir(parents=True, exist_ok=True)
    config.runner_config_path.write_text(
        "contains https://secret.invalid/hook\n", encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://secret.invalid/hook")
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "report"]
    )
    assert prodops.cmd_report(args, runner=FakeRunner()) == EXIT_FAIL_CLOSED
    payload = json.loads(config.report_path.read_text(encoding="utf-8"))
    assert "secret-scan" in payload["failures"]
    assert payload["secret_scan"]["hits"]


# ---------------------------------------------------------------------------
# CLI mapping
# ---------------------------------------------------------------------------


def test_main_maps_manual_boundary_to_marker_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(tmp_path / "production" / "missing.env"),
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    code = prodops.main(
        ["--production-config", str(tmp_path / "config.json"), "render"]
    )
    assert code == EXIT_MARKER
    payload = json.loads(capsys.readouterr().out)
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"


def test_converge_is_alias_of_apply(tmp_path: Path) -> None:
    parser = prodops._build_parser()
    args = parser.parse_args(
        ["--production-config", str(tmp_path / "config.json"), "converge"]
    )
    assert args.mode == "converge"


def test_d3_forbidden_strings_are_plain_strings(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    forbidden = prodops._d3_forbidden_strings(config)
    assert all(isinstance(item, str) for item in forbidden)
    assert str(config.production_root) in forbidden
    assert "holder_token" in forbidden
    # The membership check used against payload text must not raise.
    assert not [item for item in forbidden if item and item in "{}"]


def test_latest_receipt_reads_durable_receipt_classification(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    receipts = Path(config.runner_root) / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    activation_id = "a" * 64
    (receipts / f"{activation_id}.json").write_text(
        json.dumps(
            {"classification": "CYCLE_TERMINAL", "d1_status": "NO_CHANGE"}
        ),
        encoding="utf-8",
    )
    runner = FakeRunner()
    runner.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "latest": {
                            "activation_id": activation_id,
                            "cycle_id": "c" * 64,
                            "receipt_content_sha256": "d" * 64,
                        },
                    }
                ]
            }
        ),
    )
    receipt = prodops._latest_receipt(config, runner)
    assert receipt is not None
    assert receipt["classification"] == "CYCLE_TERMINAL"
    assert receipt["d1_status"] == "NO_CHANGE"
    assert receipt["activation_id"] == activation_id


def test_activate_after_deactivate_converges_enable_and_start(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    config.systemd_output_dir.mkdir(parents=True, exist_ok=True)
    (config.systemd_output_dir / "apply-record.json").write_text(
        json.dumps({"applied": True}), encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        config.model_dump_json(indent=2, warnings=False), encoding="utf-8"
    )
    args = prodops._build_parser().parse_args(
        ["--production-config", str(tmp_path / "config.json"), "activate"]
    )
    runner = FakeRunner()
    runner.timer_enabled = False  # simulate state left by deactivate
    assert prodops.cmd_activate(args, runner=runner) == EXIT_OK
    record = json.loads(
        (config.systemd_output_dir / "activation-record.json").read_text(encoding="utf-8")
    )
    assert record["activated"] is True
    assert record["enabled_by_activate"] is True
    assert record["started_by_activate"] is True
    assert ("systemctl", "--user", "enable", config.timer_unit_name) in runner.calls
    assert ("systemctl", "--user", "start", config.timer_unit_name) in runner.calls


# ---------------------------------------------------------------------------
# Phase 6-F-R1: effective secret sources and the private credential boundary
# ---------------------------------------------------------------------------


def _delivery_config(tmp_path: Path) -> tuple[ProductionConfigV1, Path]:
    """A delivery-enabled config whose environment file lives in the root."""

    env_file = tmp_path / "production" / "secrets.env"
    config = _production_config(
        tmp_path, delivery_enabled=True, delivery_environment_file=str(env_file)
    )
    return config, env_file


def _write_private_env_file(env_file: Path, content: str) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(content, encoding="utf-8")
    os.chmod(env_file, 0o600)


def _write_config_file(tmp_path: Path, config: ProductionConfigV1) -> Path:
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(indent=2, warnings=False), encoding="utf-8")
    return config_path


def _assert_parser_round_trip(command: str, expected_mode: str, config_path: Path) -> None:
    """An emitted resume command must be directly runnable for its mode."""

    tokens = shlex.split(command)
    assert len(tokens) == 5
    assert tokens[0] == sys.executable
    assert tokens[1].endswith("monitoring_production_ops.py")
    args = prodops._build_parser().parse_args(tokens[2:])
    assert args.mode == expected_mode
    assert args.production_config == config_path.expanduser().resolve()
    assert "<config>" not in command
    assert str(config_path.expanduser().resolve()) in command


def test_report_flags_environment_file_only_secret_leak(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An EnvironmentFile-only value is scanned without any setenv (R1 F1)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL=https://envfile-only.invalid/hook\n"
    )
    # The reference is NOT exported into the harness process environment.
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_URL", raising=False)
    config.runner_config_path.parent.mkdir(parents=True, exist_ok=True)
    config.runner_config_path.write_text(
        "contains https://envfile-only.invalid/hook\n", encoding="utf-8"
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "report"]
    )
    assert prodops.cmd_report(args, runner=FakeRunner()) == EXIT_FAIL_CLOSED
    report_text = config.report_path.read_text(encoding="utf-8")
    payload = json.loads(report_text)
    assert "secret-scan" in payload["failures"]
    assert payload["secret_scan"]["hits"]
    assert payload["secret_scan"]["secret_references_checked"] == [
        "TVE_MONITORING_WEBHOOK_URL"
    ]
    # The leak is reported by reference name only; the value stays absent.
    assert "https://envfile-only.invalid/hook" not in report_text


def test_verify_redacts_environment_file_only_secret_from_journal(
    tmp_path: Path, destination: Path
) -> None:
    """A value living only in the EnvironmentFile is redacted from verify."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://envfile-journal.invalid/hook\n"
        "TVE_MONITORING_WEBHOOK_TOKEN=tok-envfile-journal\n",
    )
    prodops._atomic_write(
        destination / config.service_unit_name,
        prodops.desired_unit_bytes(config)[config.service_unit_name],
    )
    prodops._atomic_write(
        destination / config.timer_unit_name,
        prodops.desired_unit_bytes(config)[config.timer_unit_name],
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "verify"]
    )
    runner = FakeRunner(config=config)
    runner.timer_enabled = True
    runner.linger_enabled = True
    runner.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "latest": {"activation_id": "a" * 64},
                    }
                ]
            }
        ),
    )
    runner.add(
        ("journalctl", "--user", "-u", config.service_unit_name),
        "wake with endpoint https://envfile-journal.invalid/hook COMPLETED_NEW\n",
    )
    assert prodops.cmd_verify(args, runner=runner) == EXIT_OK
    record_text = (config.systemd_output_dir / "verify-record.json").read_text(
        encoding="utf-8"
    )
    assert "https://envfile-journal.invalid/hook" not in record_text
    assert "[REDACTED]" in record_text


def test_dual_source_secret_values_are_both_scanned_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process env and EnvironmentFile may differ; both values are covered."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL=https://file-value.invalid/hook\n"
    )
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://process-value.invalid/hook")
    effective = prodops.effective_secret_values(config)
    assert effective == {
        "TVE_MONITORING_WEBHOOK_URL": [
            "https://process-value.invalid/hook",
            "https://file-value.invalid/hook",
        ]
    }
    scan_map = prodops._effective_secret_scan_map(effective)
    assert scan_map["TVE_MONITORING_WEBHOOK_URL"] == "https://process-value.invalid/hook"
    assert scan_map["TVE_MONITORING_WEBHOOK_URL~2"] == "https://file-value.invalid/hook"
    assert prodops.scan_bytes_for_secrets(
        b"leak https://process-value.invalid/hook", scan_map
    ) == ["TVE_MONITORING_WEBHOOK_URL"]
    assert prodops.scan_bytes_for_secrets(
        b"leak https://file-value.invalid/hook", scan_map
    ) == ["TVE_MONITORING_WEBHOOK_URL~2"]
    redacted = prodops.redact_text(
        "a https://file-value.invalid/hook b https://process-value.invalid/hook c",
        scan_map,
    )
    assert "file-value" not in redacted
    assert "process-value" not in redacted
    assert redacted.count("[REDACTED]") == 2


def test_config_rejects_environment_file_outside_private_root(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="production private root"):
        _production_config(
            tmp_path,
            delivery_enabled=True,
            delivery_environment_file=str(tmp_path / "outside" / "secrets.env"),
        )
    root = tmp_path / "production"
    with pytest.raises(Exception, match="production private root"):
        _production_config(
            tmp_path,
            delivery_enabled=True,
            delivery_environment_file=str(root / ".." / "escape.env"),
        )


def test_environment_file_symlink_escape_is_rejected(
    tmp_path: Path, destination: Path
) -> None:
    config, env_file = _delivery_config(tmp_path)
    outside = tmp_path / "outside-secret.env"
    outside.write_text(
        "TVE_MONITORING_WEBHOOK_URL=https://symlink.invalid/hook\n", encoding="utf-8"
    )
    os.chmod(outside, 0o600)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.symlink_to(outside)
    metadata, error = prodops.validate_delivery_environment_file(config)
    assert error is not None
    assert "outside the production private root" in error
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "outside the production private root" in payload["stopped_after"]


def test_environment_file_permissions_boundary(tmp_path: Path) -> None:
    config, env_file = _delivery_config(tmp_path)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "TVE_MONITORING_WEBHOOK_URL=https://perm.invalid/hook\n", encoding="utf-8"
    )
    os.chmod(env_file, 0o644)
    metadata, error = prodops.validate_delivery_environment_file(config)
    assert error is not None
    assert "group/world-accessible" in error
    assert metadata["mode"] == "0644"
    os.chmod(env_file, 0o600)
    metadata, error = prodops.validate_delivery_environment_file(config)
    assert error is None
    assert metadata["mode"] == "0600"


def test_render_refuses_insecure_environment_file_permissions(
    tmp_path: Path, destination: Path
) -> None:
    config, env_file = _delivery_config(tmp_path)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "TVE_MONITORING_WEBHOOK_URL=https://perm.invalid/hook\n", encoding="utf-8"
    )
    os.chmod(env_file, 0o640)
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "group/world-accessible" in payload["stopped_after"]
    assert "never chmods" in payload["human_action"]


def test_render_proceeds_with_owner_private_environment_file(
    tmp_path: Path, destination: Path
) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://healthy.invalid/hook\n"
        "TVE_MONITORING_WEBHOOK_TOKEN=tok-healthy\n",
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    unit_text = (config.systemd_output_dir / config.service_unit_name).read_text(
        encoding="utf-8"
    )
    assert f"EnvironmentFile={env_file}" in unit_text
    assert "https://healthy.invalid/hook" not in unit_text
    assert "tok-healthy" not in unit_text


def test_windows_bootstrap_resume_command_is_exact_and_parseable(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    config_path = tmp_path / "config.json"
    payload = prodops.windows_bootstrap_marker_payload(config, config_path)
    _assert_parser_round_trip(payload["resume_command"], "verify", config_path)


def test_linger_boundary_resume_command_is_exact_and_parseable(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    config_path = tmp_path / "config.json"

    def broken(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if argv[:2] == ["loginctl", "enable-linger"]:
            return subprocess.CompletedProcess(argv, 1, "", "denied")
        if argv[:3] == ["loginctl", "show-user"]:
            return subprocess.CompletedProcess(argv, 0, "Linger=no\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(ManualBoundary) as excinfo:
        ensure_linger(
            config,
            current_user="jelinenaro",
            runner=broken,
            production_config_path=config_path,
        )
    _assert_parser_round_trip(excinfo.value.payload["resume_command"], "apply", config_path)


def test_render_secret_boundary_resume_command_is_exact_and_parseable(
    tmp_path: Path, destination: Path
) -> None:
    config, _env_file = _delivery_config(tmp_path)  # environment file missing
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    _assert_parser_round_trip(excinfo.value.payload["resume_command"], "render", config_path)


def test_delivery_disabled_effective_values_stay_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delivery-disabled behavior stays compatible: no ambient-env scanning."""

    config = _production_config(tmp_path)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://ambient.invalid/hook")
    assert prodops.effective_secret_values(config) == {}
    assert prodops._effective_secret_scan_map({}) == {}
    assert prodops.resolvable_secret_values(config) == {}


# ---------------------------------------------------------------------------
# Phase 6-F-R2: canonical EnvironmentFile semantics and render gating
# ---------------------------------------------------------------------------

# A byte-for-byte sentinel exercising every data character class that must
# survive the canonical parser verbatim (and be seen by every scan path).
_R2_URL = "https://hooks.r2.invalid/a=b?c=d&e=f%20g#frag;sec=1"
_R2_TOKEN = "tok=r2#p;q?w&%z"


def _make_preflight_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host-independent green preflight inputs (read-only host facts faked)."""

    monkeypatch.setattr(
        prodops,
        "load_gate_artifact",
        lambda config, head_sha: {"head_sha": head_sha, "green": True},
    )
    monkeypatch.setattr(
        prodops, "probe_lock_visibility", lambda *a, **k: {"proven": True, "steps": []}
    )
    monkeypatch.setattr(
        prodops,
        "classify_host_topology",
        lambda runner: {
            "pid1": "systemd",
            "wsl2": False,
            "wsl_conf_systemd_boot": None,
            "windows_host_bootstrap_proven": True,
        },
    )


def test_r2_backslash_escape_is_rejected(tmp_path: Path) -> None:
    """A systemd unquoted backslash escape must never become effective (F1)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL=https://x.invalid/h\\ook\n"
    )
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "backslash" in error
    # The file value must not silently feed the effective scan/redaction set.
    assert prodops.effective_secret_values(config) == {}


def test_r2_backslash_newline_continuation_is_rejected(tmp_path: Path) -> None:
    """Backslash-newline continuation (systemd joins the lines) is rejected."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://x.invalid/hook\\\n"
        "TVE_MONITORING_WEBHOOK_TOKEN=tok-1\n",
    )
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "backslash" in error
    assert "tok-1" not in (error or "")


def test_r2_quoted_and_multiline_values_are_rejected(tmp_path: Path) -> None:
    """Single/double-quoted and multiline values are rejected, not parsed."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, 'TVE_MONITORING_WEBHOOK_URL="https://quoted.invalid/hook"\n'
    )
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "quote" in error
    assert "https://quoted.invalid/hook" not in error

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL='https://multi.invalid/hook\nsuffix'\n"
    )
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None
    assert "multi.invalid" not in error


def test_r2_render_missing_required_reference_stops_at_marker_and_writes_nothing(
    tmp_path: Path, destination: Path
) -> None:
    """Render proves referenced-name completeness before any artifact (F2)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(env_file, "TVE_MONITORING_WEBHOOK_TOKEN=tok-present\n")
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "TVE_MONITORING_WEBHOOK_URL" in payload["stopped_after"]
    assert "tok-present" not in payload["stopped_after"]
    _assert_parser_round_trip(payload["resume_command"], "render", config_path)
    # The failure must happen before any render artifact is written.
    assert not config.runner_config_path.exists()
    assert not config.project_config_path.exists()
    assert not (config.systemd_output_dir / config.service_unit_name).exists()
    assert not (config.systemd_output_dir / "render-plan.json").exists()


def test_r2_duplicate_reference_is_rejected(tmp_path: Path) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://dup-1.invalid/hook\n"
        "TVE_MONITORING_WEBHOOK_URL=https://dup-2.invalid/hook\n",
    )
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "duplicate" in error
    assert "dup-1.invalid" not in error and "dup-2.invalid" not in error


def test_r2_unknown_environment_key_is_rejected_without_echoing_it(
    tmp_path: Path,
) -> None:
    """Unrelated environment injection through the credential file is refused."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://x.invalid/hook\n"
        "PATH=/usr/bin:/bin\n",
    )
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "not one of the referenced secret names" in error
    # The reason is line/category based; it never echoes the file content.
    assert "PATH" not in error and "/usr/bin" not in error


def test_r2_unreadable_credential_file_fails_closed_in_render_and_preflight(
    tmp_path: Path,
    destination: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Metadata-valid but unreadable files stop render/preflight precisely."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL=https://x.invalid/hook\n"
    )
    # Simulate an unreadable file deterministically (independent of euid).
    real_read_bytes = Path.read_bytes

    def _unreadable(self: Path) -> bytes:
        if self == env_file:
            raise PermissionError(13, "Permission denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _unreadable)
    metadata, boundary_error = prodops.validate_delivery_environment_file(config)
    assert boundary_error is None  # the metadata boundary alone still holds
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "cannot read" in error
    assert "https://x.invalid/hook" not in error

    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "cannot read" in payload["stopped_after"]
    assert "https://x.invalid/hook" not in payload["stopped_after"]
    assert not config.runner_config_path.exists()
    assert not (config.systemd_output_dir / config.service_unit_name).exists()

    # Preflight reports the same unreadable boundary as a precise marker.
    _make_preflight_deterministic(monkeypatch)
    _write_watchlist(config)
    preflight_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "preflight"]
    )
    preflight_runner = FakeRunner()
    preflight_runner.linger_enabled = True
    assert (
        prodops.cmd_preflight(preflight_args, runner=preflight_runner)
        == prodops.EXIT_OK
    )
    preflight_payload = json.loads(capsys.readouterr().out)
    delivery_checks = {
        item["name"]: item for item in preflight_payload["checks"]
        if item["name"].startswith("delivery.")
    }
    assert (
        delivery_checks["delivery.secret-reference"]["marker"]
        == "MANUAL_SECRET_REFERENCE_REQUIRED"
    )
    assert (
        "cannot read" in delivery_checks["delivery.secret-reference"]["detail"]
    )
    assert "https://x.invalid/hook" not in json.dumps(preflight_payload)


def test_r2_canonical_url_punctuation_is_preserved_and_scanned_byte_for_byte(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`= # ; ? & %` stay literal data in every accepted path (goal 3.7/7.8)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "# production notification credentials\n"
        f"TVE_MONITORING_WEBHOOK_URL={_R2_URL}\n"
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R2_TOKEN}\n",
    )
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_TOKEN", raising=False)
    values, error = environment_file_values(config)
    assert error is None
    assert values == {
        "TVE_MONITORING_WEBHOOK_URL": _R2_URL,
        "TVE_MONITORING_WEBHOOK_TOKEN": _R2_TOKEN,
    }
    effective = prodops.effective_secret_values(config)
    assert effective == {
        "TVE_MONITORING_WEBHOOK_URL": [_R2_URL],
        "TVE_MONITORING_WEBHOOK_TOKEN": [_R2_TOKEN],
    }
    secrets = prodops._effective_secret_scan_map(effective)
    assert prodops.scan_bytes_for_secrets(f"leak {_R2_URL}".encode(), secrets) == [
        "TVE_MONITORING_WEBHOOK_URL"
    ]
    assert prodops.scan_bytes_for_secrets(f"leak {_R2_TOKEN}".encode(), secrets) == [
        "TVE_MONITORING_WEBHOOK_TOKEN"
    ]
    redacted = prodops.redact_text(f"a {_R2_URL} b {_R2_TOKEN} c", secrets)
    assert _R2_URL not in redacted and _R2_TOKEN not in redacted
    assert redacted.count("[REDACTED]") == 2

    # Render proceeds and keeps the values out of every artifact.
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    unit_text = (config.systemd_output_dir / config.service_unit_name).read_text(
        encoding="utf-8"
    )
    assert f"EnvironmentFile={env_file}" in unit_text
    assert _R2_URL not in unit_text and _R2_TOKEN not in unit_text
    plan_text = (config.systemd_output_dir / "render-plan.json").read_text(
        encoding="utf-8"
    )
    assert _R2_URL not in plan_text and _R2_TOKEN not in plan_text


def test_r2_dual_source_mismatch_keeps_both_values_with_canonical_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 dual-source semantics stay intact for canonical file values."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(env_file, f"TVE_MONITORING_WEBHOOK_URL={_R2_URL}\n")
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://process-r2.invalid/h")
    effective = prodops.effective_secret_values(config)
    assert effective == {
        "TVE_MONITORING_WEBHOOK_URL": ["https://process-r2.invalid/h", _R2_URL]
    }
    scan_map = prodops._effective_secret_scan_map(effective)
    assert prodops.scan_bytes_for_secrets(f"x {_R2_URL}".encode(), scan_map) == [
        "TVE_MONITORING_WEBHOOK_URL~2"
    ]


def test_r2_delivery_disabled_render_stays_compatible(
    tmp_path: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monitoring-only production behavior is unchanged by the canonical gate."""

    config = _production_config(tmp_path)
    _write_watchlist(config)
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://ambient.invalid/hook")
    assert prodops.effective_secret_values(config) == {}
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    unit_text = (config.systemd_output_dir / config.service_unit_name).read_text(
        encoding="utf-8"
    )
    assert "EnvironmentFile=" not in unit_text


def test_r2_no_render_artifact_on_rejected_credential_syntax(
    tmp_path: Path, destination: Path
) -> None:
    """A syntax violation stops render before any delivery-enabled unit exists."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, 'TVE_MONITORING_WEBHOOK_URL="https://quoted.invalid/hook"\n'
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "quote" in payload["stopped_after"]
    assert "https://quoted.invalid/hook" not in payload["stopped_after"]
    assert not config.systemd_output_dir.exists() or not any(
        (config.systemd_output_dir / name).exists()
        for name in (config.service_unit_name, config.timer_unit_name, "render-plan.json")
    )
    assert not config.runner_config_path.exists()
    assert not config.project_config_path.exists()


def test_r2_export_whitespace_and_empty_value_forms_are_rejected(
    tmp_path: Path,
) -> None:
    config, env_file = _delivery_config(tmp_path)

    def _reason(content: str) -> str:
        _write_private_env_file(env_file, content)
        values, error = environment_file_values(config)
        assert values == {}
        assert error is not None
        return error

    assert "export" in _reason("export TVE_MONITORING_WEBHOOK_URL=https://x.invalid/h\n")
    whitespace = _reason("TVE_MONITORING_WEBHOOK_URL =https://x.invalid/h\n")
    assert "whitespace" in whitespace
    trailing = _reason("TVE_MONITORING_WEBHOOK_TOKEN=tok-1 \n")
    assert "whitespace" in trailing
    embedded = _reason("TVE_MONITORING_WEBHOOK_TOKEN=tok 1\n")
    assert "whitespace" in embedded
    empty = _reason("TVE_MONITORING_WEBHOOK_TOKEN=\n")
    assert "empty" in empty
    malformed = _reason("TVE_MONITORING_WEBHOOK_TOKEN\n")
    assert "NAME=VALUE" in malformed
    for error in (whitespace, trailing, embedded, empty, malformed):
        assert "https://x.invalid" not in error and "tok" not in error


def test_r2_environment_file_path_control_characters_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(Exception, match="control character"):
        _production_config(
            tmp_path,
            delivery_enabled=True,
            delivery_environment_file=str(tmp_path / "production" / "sec\nret.env"),
        )
    config, _env_file = _delivery_config(tmp_path)
    bad = config.model_copy(
        update={"delivery_environment_file": str(tmp_path / "production" / "ba\x01d.env")}
    )
    _metadata, error = prodops.validate_delivery_environment_file(bad)
    assert error is not None and "control characters" in error


def test_r2_preflight_reports_canonical_violation_precisely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://healthy.invalid/hook\n"
        'TVE_MONITORING_WEBHOOK_TOKEN="tok-preflight"\n',
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "preflight"]
    )
    _make_preflight_deterministic(monkeypatch)
    _write_watchlist(config)
    preflight_runner = FakeRunner()
    preflight_runner.linger_enabled = True
    assert prodops.cmd_preflight(args, runner=preflight_runner) == prodops.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    checks = {item["name"]: item for item in payload["checks"]}
    reference = checks["delivery.secret-reference"]
    assert reference["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "quote" in reference["detail"]
    assert "tok-preflight" not in json.dumps(payload)


def test_r2_delivery_section_rejects_non_canonical_file(tmp_path: Path) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, 'TVE_MONITORING_WEBHOOK_URL="https://section.invalid/hook"\n'
    )
    section = prodops._delivery_section(
        config,
        FakeRunner(),
        "activation-id",
        production_config_path=tmp_path / "config.json",
    )
    assert section["ok"] is False
    marker = section["marker_payload"]
    assert marker["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "quote" in marker["stopped_after"]
    assert "section.invalid" not in json.dumps(section)


def test_r2_canonical_boundary_resume_command_is_parser_valid(
    tmp_path: Path, destination: Path
) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(env_file, "TVE_MONITORING_WEBHOOK_TOKEN=tok-only\n")
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_render(args, runner=FakeRunner())
    _assert_parser_round_trip(excinfo.value.payload["resume_command"], "render", config_path)


# ---------------------------------------------------------------------------
# Phase 6-F-R3: runtime credential drift and service-effective gate hardening
# ---------------------------------------------------------------------------

# Fake sentinels: these values exist only inside tests and temporary files.
_R3_URL = "https://hooks.r3.invalid/a=b?c=d&e=f"
_R3_TOKEN = "tok-r3#p;q?w&%z"


def _gate_call(
    config: ProductionConfigV1, environ: dict[str, str] | None
) -> tuple[int, dict[str, object]]:
    """Invoke the one service-execution gate primitive with injected env."""

    gate = getattr(prodops, "run_credential_gate", None)
    assert gate is not None, "run_credential_gate must exist (R3)"
    return gate(
        environment_file=config.delivery_environment_file,
        production_root=config.production_root,
        referenced_names=prodops._production_secret_reference_names(config),
        environ=environ,
    )


def test_r3_ufeff_value_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """systemd excludes U+FEFF from the whole EnvironmentFile (goal 3)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL=https://x\ufeffinvalid/hook\n"
    )
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_URL", raising=False)
    values, error = environment_file_values(config)
    assert values == {}
    assert error is not None and "systemd-invalid Unicode" in error
    assert "U+FEFF" in error
    assert "invalid/hook" not in error
    assert prodops.effective_secret_values(config) == {}


def test_r3_unicode_noncharacters_rejected(tmp_path: Path) -> None:
    """U+FDD0..U+FDEF and plane-ending noncharacters are rejected (goal 3)."""

    config, env_file = _delivery_config(tmp_path)
    for bad in ("\ufdd0", "\ufdef", "\uffff", "\U0001ffff", "\U0010ffff"):
        _write_private_env_file(env_file, f"TVE_MONITORING_WEBHOOK_TOKEN=tok{bad}r3\n")
        values, error = environment_file_values(config)
        assert values == {}
        assert error is not None and "systemd-invalid Unicode" in error
        assert "tok" not in error and "r3" not in error


def test_r3_unicode_in_comment_rejected_whole_file(tmp_path: Path) -> None:
    """Validation is whole-file: comments cannot carry systemd-invalid Unicode."""

    config, env_file = _delivery_config(tmp_path)
    for comment in ("# note \ufeff", "# note \ufdd0", "# note \uffff", "# note \x00"):
        _write_private_env_file(
            env_file,
            f"{comment}\nTVE_MONITORING_WEBHOOK_URL={_R3_URL}\n"
            f"TVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
        )
        values, error = environment_file_values(config)
        assert values == {}
        assert error is not None and "systemd-invalid Unicode" in error
        assert _R3_URL not in error and _R3_TOKEN not in error


def test_r3_valid_multibyte_unicode_stays_canonical(tmp_path: Path) -> None:
    """Ordinary non-ASCII data is not collateral damage of the parity check."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "# 生产通知凭证（值不进入任何工件）\n"
        "TVE_MONITORING_WEBHOOK_URL=https://例证.invalid/hook\n"
        "TVE_MONITORING_WEBHOOK_TOKEN=令牌-中文-值\n",
    )
    values, error = environment_file_values(config)
    assert error is None
    assert values == {
        "TVE_MONITORING_WEBHOOK_URL": "https://例证.invalid/hook",
        "TVE_MONITORING_WEBHOOK_TOKEN": "令牌-中文-值",
    }


def test_r3_render_then_drift_apply_fails_before_any_mutation(
    tmp_path: Path, destination: Path
) -> None:
    """Post-render drift blocks apply before install/reload/enable (goal 5.1)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    config_path = _write_config_file(tmp_path, config)
    render_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(render_args, runner=FakeRunner()) == EXIT_OK
    # The owner later edits the file into a systemd-valid but non-canonical form.
    _write_private_env_file(
        env_file,
        f'TVE_MONITORING_WEBHOOK_URL="{_R3_URL}"\n'
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    apply_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "apply"]
    )
    runner = FakeRunner(config=config)
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_apply(apply_args, runner=runner)
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "drifted" in payload["stopped_after"]
    assert "quote" in payload["stopped_after"]
    assert _R3_URL not in json.dumps(payload)
    _assert_parser_round_trip(payload["resume_command"], "apply", config_path)
    # Zero system mutation: no install, daemon-reload, enable or linger call.
    assert runner.calls == []
    assert not destination.exists()


def test_r3_drift_after_apply_activate_authorizes_zero_actions(
    tmp_path: Path, destination: Path
) -> None:
    """Post-apply drift blocks activate before any enable/start (goal 5.2)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    config_path = _write_config_file(tmp_path, config)
    render_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(render_args, runner=FakeRunner()) == EXIT_OK
    apply_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "apply"]
    )
    apply_runner = FakeRunner(config=config)
    assert prodops.cmd_apply(apply_args, runner=apply_runner) == EXIT_OK
    # The owner later edits the file into a systemd-valid but non-canonical
    # form (a canonical rotation alone would stay legitimate).
    _write_private_env_file(
        env_file,
        f'TVE_MONITORING_WEBHOOK_URL="https://drifted-r3.invalid/h"\n'
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    activate_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "activate"]
    )
    activate_runner = FakeRunner(config=config)
    with pytest.raises(ManualBoundary) as excinfo:
        prodops.cmd_activate(activate_args, runner=activate_runner)
    payload = excinfo.value.payload
    assert payload["marker"] == "MANUAL_SECRET_REFERENCE_REQUIRED"
    assert "zero" in payload["stopped_after"]
    assert "drifted-r3.invalid" not in json.dumps(payload)
    _assert_parser_round_trip(payload["resume_command"], "activate", config_path)
    # Zero enable and zero start actions were authorized.
    mutating = [
        call
        for call in activate_runner.calls
        if call[:2] == ("systemctl", "--user") and call[2] in {"enable", "start"}
    ]
    assert mutating == []
    assert not activate_runner.timer_enabled
    assert not (config.systemd_output_dir / "activation-record.json").exists()


def test_r3_verify_non_green_on_current_credential_drift(
    tmp_path: Path, destination: Path
) -> None:
    """Verify adds a live current-credential check (goal 5.3)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    prodops._atomic_write(
        destination / config.service_unit_name,
        prodops.desired_unit_bytes(config)[config.service_unit_name],
    )
    prodops._atomic_write(
        destination / config.timer_unit_name,
        prodops.desired_unit_bytes(config)[config.timer_unit_name],
    )
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\n"
        "TVE_MONITORING_WEBHOOK_TOKEN='tok-drifted'\n",
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "verify", "--expect-active"]
    )
    runner = FakeRunner(config=config)
    runner.timer_enabled = True
    runner.linger_enabled = True
    runner.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "latest": {"activation_id": "a" * 64},
                    }
                ]
            }
        ),
    )
    assert prodops.cmd_verify(args, runner=runner) == EXIT_FAIL_CLOSED
    record_text = (config.systemd_output_dir / "verify-record.json").read_text("utf-8")
    payload = json.loads(record_text)
    assert payload["green"] is False
    by_name = {item["name"]: item for item in payload["checks"]}
    credential = by_name["credential.current-contract"]
    assert credential["status"] == "FAIL"
    assert "quote" in credential["detail"]
    assert _R3_TOKEN not in record_text and "tok-drifted" not in record_text
    # The rendered/installed units still carry the pre-start gate.
    assert by_name["service.prestart-gate"]["status"] == "PASS"


def test_r3_report_not_production_deployed_on_current_credential_drift(
    tmp_path: Path,
    destination: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report fails closed on live drift instead of trusting old records (5.4)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    prodops._atomic_write(
        destination / config.service_unit_name,
        prodops.desired_unit_bytes(config)[config.service_unit_name],
    )
    prodops._atomic_write(
        destination / config.timer_unit_name,
        prodops.desired_unit_bytes(config)[config.timer_unit_name],
    )
    config.systemd_output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("apply-record.json", {"applied": True}),
        ("activation-record.json", {"activated": True}),
        ("verify-record.json", {"green": True}),
        ("live-proof-record.json", {"ok": True, "failures": []}),
        ("recover-proof-record.json", {"ok": True, "failures": []}),
    ):
        (config.systemd_output_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    # Drift after every historical record turned green.
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\n"
        "TVE_MONITORING_WEBHOOK_TOKEN='tok-drifted'\n",
    )
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TVE_MONITORING_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setattr(
        prodops,
        "load_gate_artifact",
        lambda config_, head_sha: {"head_sha": head_sha, "green": True},
    )
    monkeypatch.setattr(
        prodops,
        "classify_host_topology",
        lambda runner: {
            "pid1": "systemd",
            "wsl2": False,
            "wsl_conf_systemd_boot": None,
            "windows_host_bootstrap_proven": True,
        },
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "report"]
    )
    runner = FakeRunner(config=config)
    runner.timer_enabled = True
    runner.linger_enabled = True
    assert prodops.cmd_report(args, runner=runner) == EXIT_FAIL_CLOSED
    report_text = config.report_path.read_text(encoding="utf-8")
    payload = json.loads(report_text)
    assert payload["phase_state"] != "PRODUCTION_DEPLOYED"
    assert "current-credential" in payload["failures"]
    assert payload["credential"]["ok"] is False
    assert payload["credential"]["enabled"] is True
    assert payload["credential"]["referenced_names"] == [
        "TVE_MONITORING_WEBHOOK_URL",
        "TVE_MONITORING_WEBHOOK_TOKEN",
    ]
    assert _R3_TOKEN not in report_text and "tok-drifted" not in report_text


def test_r3_deactivate_safe_with_invalid_then_missing_credential(
    tmp_path: Path,
) -> None:
    """Credential validity is never a prerequisite for safe deactivation (5.5)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file, 'TVE_MONITORING_WEBHOOK_URL="https://broken.invalid/h"\n'
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "deactivate"]
    )
    runner = FakeRunner(config=config)
    runner.timer_enabled = True
    assert prodops.cmd_deactivate(args, runner=runner) == EXIT_OK
    record = json.loads(
        (config.systemd_output_dir / "deactivation-record.json").read_text("utf-8")
    )
    assert record["deactivated"] is True
    # And with the credential file gone entirely.
    env_file.unlink()
    assert prodops.cmd_deactivate(args, runner=FakeRunner(config=config)) == EXIT_OK


def test_r3_delivery_unit_prestart_gate_before_unchanged_execstart(
    tmp_path: Path, destination: Path
) -> None:
    """The rendered delivery unit carries the runtime gate ahead of ExecStart."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    unit_text = (config.systemd_output_dir / config.service_unit_name).read_text("utf-8")
    pre_index = unit_text.index("ExecStartPre=")
    start_index = unit_text.index("ExecStart=")
    assert pre_index < start_index
    gate_line = unit_text[pre_index : unit_text.index("\n", pre_index)]
    # Only non-secret facts: executable, script path, environment-file path,
    # production root and the referenced (public) names.
    assert gate_line.startswith(f"ExecStartPre={config.python_executable} ")
    assert str(prodops.CREDENTIAL_GATE_SCRIPT) in gate_line
    assert "--environment-file" in gate_line and str(env_file) in gate_line
    assert "--production-root" in gate_line and str(config.production_root) in gate_line
    assert gate_line.count("--reference") == 2
    assert "TVE_MONITORING_WEBHOOK_URL" in gate_line
    assert "TVE_MONITORING_WEBHOOK_TOKEN" in gate_line
    assert _R3_URL not in unit_text and _R3_TOKEN not in unit_text
    # The delivery ExecStart itself is unchanged.
    exec_line = unit_text[start_index : unit_text.index("\n", start_index)]
    assert "unattended-notify" in exec_line
    assert str(config.runner_config_path) in exec_line
    assert "--network allow" in exec_line
    # The rendered units must satisfy the real systemd unit verifier.
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is not available on this host")
    verify = prodops._systemd_analyze_verify(
        (
            config.systemd_output_dir / config.service_unit_name,
            config.systemd_output_dir / config.timer_unit_name,
        ),
        runner=prodops._default_runner,
    )
    assert verify.ok, verify.stderr


def test_r3_delivery_disabled_unit_has_no_gate(tmp_path: Path, destination: Path) -> None:
    """Monitoring-only units stay byte/semantics compatible: no gate (goal 9.14)."""

    config = _production_config(tmp_path)
    unit = render_service_unit(config, config.runner_config_path)
    assert "ExecStartPre=" not in unit
    assert "monitoring_credential_gate" not in unit
    assert "unattended-run" in unit
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    rendered = (config.systemd_output_dir / config.service_unit_name).read_text("utf-8")
    assert rendered == unit


def test_r3_credential_gate_success_matches_inherited_bytes(
    tmp_path: Path,
) -> None:
    """Canonical file + byte-identical inherited values authorize the service."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    code, payload = _gate_call(
        config,
        {"TVE_MONITORING_WEBHOOK_URL": _R3_URL, "TVE_MONITORING_WEBHOOK_TOKEN": _R3_TOKEN},
    )
    assert code == EXIT_OK
    assert payload["status"] == prodops.CREDENTIAL_GATE_OK
    assert payload["references"] == [
        "TVE_MONITORING_WEBHOOK_URL",
        "TVE_MONITORING_WEBHOOK_TOKEN",
    ]
    assert _R3_URL not in json.dumps(payload) and _R3_TOKEN not in json.dumps(payload)


def test_r3_credential_gate_missing_inherited_reference_fails_leak_free(
    tmp_path: Path,
) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    code, payload = _gate_call(config, {"TVE_MONITORING_WEBHOOK_TOKEN": _R3_TOKEN})
    assert code == EXIT_FAIL_CLOSED
    assert payload["status"] == prodops.CREDENTIAL_GATE_REJECTED
    assert payload["category"] == "ENV_MISSING"
    assert payload["reference"] == "TVE_MONITORING_WEBHOOK_URL"
    assert _R3_URL not in json.dumps(payload)


def test_r3_credential_gate_byte_mismatch_fails_without_either_value(
    tmp_path: Path,
) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    injected = "https://other-owner-edit.invalid/hook"
    code, payload = _gate_call(
        config, {"TVE_MONITORING_WEBHOOK_URL": injected, "TVE_MONITORING_WEBHOOK_TOKEN": _R3_TOKEN}
    )
    assert code == EXIT_FAIL_CLOSED
    assert payload["category"] == "ENV_MISMATCH"
    assert payload["reference"] == "TVE_MONITORING_WEBHOOK_URL"
    serialized = json.dumps(payload)
    assert _R3_URL not in serialized and injected not in serialized


def test_r3_credential_gate_rejects_systemd_valid_but_noncanonical_drift(
    tmp_path: Path, destination: Path
) -> None:
    """Goal 7 runtime invariant: quoted drift blocks even when values equal."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    config_path = _write_config_file(tmp_path, config)
    render_args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(render_args, runner=FakeRunner()) == EXIT_OK
    # systemd accepts quoting and would inject the de-quoted bytes; the TVE
    # canonical parser refuses the file, so the gate must fail closed.
    _write_private_env_file(
        env_file,
        f'TVE_MONITORING_WEBHOOK_URL="{_R3_URL}"\n'
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    code, payload = _gate_call(
        config,
        {"TVE_MONITORING_WEBHOOK_URL": _R3_URL, "TVE_MONITORING_WEBHOOK_TOKEN": _R3_TOKEN},
    )
    assert code == EXIT_FAIL_CLOSED
    assert payload["category"] == "NONCANONICAL_OR_INCOMPLETE"
    assert "quote" in payload["reason"]
    assert _R3_URL not in json.dumps(payload)
    # Structural ordering proof: the failing gate sits ahead of the unchanged
    # unattended-notify ExecStart inside the rendered unit.
    unit_text = (config.systemd_output_dir / config.service_unit_name).read_text("utf-8")
    assert unit_text.index("ExecStartPre=") < unit_text.index("ExecStart=")
    assert "unattended-notify" in unit_text


def test_r3_credential_gate_metadata_boundary_enforced(tmp_path: Path) -> None:
    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    os.chmod(env_file, 0o644)
    code, payload = _gate_call(config, {})
    assert code == EXIT_FAIL_CLOSED
    assert payload["category"] == "METADATA"
    assert "group/world-accessible" in payload["reason"]
    # A missing file is a metadata failure too, never a value probe.
    os.chmod(env_file, 0o600)
    env_file.unlink()
    code, payload = _gate_call(config, {})
    assert code == EXIT_FAIL_CLOSED
    assert payload["category"] == "METADATA"
    assert "does not exist" in payload["reason"]


def test_r3_credential_gate_cli_end_to_end(tmp_path: Path) -> None:
    """The exact ExecStartPre argv works as a standalone command."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R3_URL}\nTVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    argv = list(prodops.credential_gate_argv(config))
    script = Path(argv[1])
    assert script.is_file(), f"gate script missing: {script}"
    base_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"TVE_MONITORING_WEBHOOK_URL", "TVE_MONITORING_WEBHOOK_TOKEN"}
    }
    injected_env = {
        **base_env,
        "TVE_MONITORING_WEBHOOK_URL": _R3_URL,
        "TVE_MONITORING_WEBHOOK_TOKEN": _R3_TOKEN,
    }
    good = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=120,
        env=injected_env,
    )
    assert good.returncode == 0, good.stderr
    assert prodops.CREDENTIAL_GATE_OK in good.stdout
    assert _R3_URL not in good.stdout and _R3_TOKEN not in good.stdout
    _write_private_env_file(
        env_file,
        f'TVE_MONITORING_WEBHOOK_URL="{_R3_URL}"\n'
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R3_TOKEN}\n",
    )
    bad = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=120,
        env=injected_env,
    )
    assert bad.returncode == EXIT_FAIL_CLOSED
    assert prodops.CREDENTIAL_GATE_REJECTED in bad.stdout
    assert _R3_URL not in bad.stdout and _R3_URL not in bad.stderr


def test_r3_recover_proof_probe_requires_byte_equality(tmp_path: Path) -> None:
    """The restart proof now proves equality, not mere presence (goal 8)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        "TVE_MONITORING_WEBHOOK_URL=https://probe-r3.invalid/h\n"
        "TVE_MONITORING_WEBHOOK_TOKEN=tok-probe-r3\n",
    )

    def make_runner(injected: dict[str, str]) -> FakeRunner:
        runner = FakeRunner(config=config)
        runner.injected_environment = injected
        return runner

    # Extend FakeRunner for the systemd-run probe: simulate the service
    # context by running the gate in-process against the injected environment.

    original_call = FakeRunner.__call__

    def _call(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        if argv[:1] == ["systemd-run"]:
            gate = getattr(prodops, "run_credential_gate", None)
            assert gate is not None
            code, payload = gate(
                environment_file=self.config.delivery_environment_file,
                production_root=self.config.production_root,
                referenced_names=prodops._production_secret_reference_names(self.config),
                environ=getattr(self, "injected_environment", {}),
            )
            return subprocess.CompletedProcess(argv, code, json.dumps(payload), "")
        return original_call(self, argv, **kwargs)

    FakeRunner.__call__ = _call  # type: ignore[method-assign]

    try:
        matched = prodops._credential_resolution_probe(
            config,
            make_runner(
                {
                    "TVE_MONITORING_WEBHOOK_URL": "https://probe-r3.invalid/h",
                    "TVE_MONITORING_WEBHOOK_TOKEN": "tok-probe-r3",
                }
            ),
        )
        assert matched["ok"] is True
        # Same references present but one value carries different bytes:
        # presence-only (pre-R3) reported this green; the upgraded probe
        # must not.
        drifted = prodops._credential_resolution_probe(
            config,
            make_runner(
                {
                    "TVE_MONITORING_WEBHOOK_URL": "https://drifted-r3.invalid/h",
                    "TVE_MONITORING_WEBHOOK_TOKEN": "tok-probe-r3",
                }
            ),
        )
        assert drifted["ok"] is False
        assert "drifted-r3.invalid" not in json.dumps(drifted)
        missing = prodops._credential_resolution_probe(config, make_runner({}))
        assert missing["ok"] is False
    finally:
        FakeRunner.__call__ = original_call  # type: ignore[method-assign]


def test_r3_dual_source_scan_semantics_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 dual-source scanning stays intact around the R3 parser (goal 9.13)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(env_file, "TVE_MONITORING_WEBHOOK_URL=https://r3-file.invalid/h\n")
    monkeypatch.setenv("TVE_MONITORING_WEBHOOK_URL", "https://r3-process.invalid/h")
    assert prodops.effective_secret_values(config) == {
        "TVE_MONITORING_WEBHOOK_URL": [
            "https://r3-process.invalid/h",
            "https://r3-file.invalid/h",
        ]
    }
    # A systemd-invalid-Unicode file contributes no file values (fail-safe),
    # while the harness-side value keeps full scan/redaction coverage.
    _write_private_env_file(
        env_file, "TVE_MONITORING_WEBHOOK_URL=https://broken\ufeff-r3.invalid/h\n"
    )
    assert prodops.effective_secret_values(config) == {
        "TVE_MONITORING_WEBHOOK_URL": ["https://r3-process.invalid/h"]
    }


def _systemd_user_manager_usable() -> bool:
    """A reachable user manager is required for the transient proof."""

    if shutil.which("systemd-run") is None or shutil.which("systemctl") is None:
        return False
    try:
        outcome = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return outcome.returncode == 0


@pytest.mark.skipif(
    not _systemd_user_manager_usable(),
    reason="no reachable systemd user manager for the transient pre-start proof",
)
def test_r3_transient_systemd_execstartpre_gate_proof(tmp_path: Path) -> None:
    """Real manager proof: gate failure leaves unattended-notify unexecuted."""

    config, env_file = _delivery_config(tmp_path)
    canonical = "https://transient-r3.invalid/hook"
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={canonical}\nTVE_MONITORING_WEBHOOK_TOKEN=tok-transient-r3\n",
    )
    gate_command = prodops.credential_gate_command(config)
    sentinel = tmp_path / "notify-executed"

    def run_transient() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "systemd-run",
                "--user",
                "--wait",
                "--pipe",
                "--collect",
                f"--unit=tve-r3-proof-{uuid.uuid4().hex[:12]}",
                "-p",
                f"EnvironmentFile={env_file}",
                "-p",
                f"ExecStartPre={gate_command}",
                "/bin/sh",
                "-c",
                f"echo executed > {shlex.quote(str(sentinel))}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

    # Healthy path: the gate passes and the (fake) notify command runs.
    healthy = run_transient()
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr
    assert sentinel.is_file()
    sentinel.unlink()
    # Goal 7: the owner edits the file into a form systemd still accepts
    # (quoting) but the TVE canonical parser refuses.
    _write_private_env_file(
        env_file,
        f'TVE_MONITORING_WEBHOOK_URL="{canonical}"\nTVE_MONITORING_WEBHOOK_TOKEN=tok-transient-r3\n',
    )
    drifted = run_transient()
    assert drifted.returncode != 0
    assert not sentinel.exists(), "unattended-notify must not execute after gate failure"
    assert canonical not in drifted.stdout and canonical not in drifted.stderr


# ---------------------------------------------------------------------------
# Phase 6-F-R4 — production artifact serialization parity
# ---------------------------------------------------------------------------

_R4_URL_VALUE = "https://r4-roundtrip.invalid/hook?a=1#frag"
_R4_TOKEN_VALUE = "tok-r4-roundtrip"

# The parser-significant owner-input matrix from R4 goal section 7.
_R4_EDGE_VALUES = [
    "/opt/tve/pro duction",  # 1 space
    "/opt/tve/pro'duction",  # 2 single quote
    '/opt/tve/pro"duction',  # 3 double quote
    "/opt/tve/pro\\duction",  # 4 backslash
    "/opt/tve/pro$HOME",  # 5 literal dollar sequence resembling a variable
    "/opt/tve/${HOME}/x",  # braced variable form as literal data
    "/opt/tve/pro%n",  # 6 literal valid systemd specifier sequence
    "/opt/tve/100%",  # trailing literal percent
    "/opt/tve/a;b",  # 7 semicolon as ordinary argument data
    "/opt/tve/a#b",  # hash as ordinary argument data
    "/opt/tve/produktör-茅台",  # 8 ordinary non-ASCII path text
    "/opt/tve/a 'b\" c\\d$e%f g",  # every parser-significant class at once
    ";",  # standalone semicolon argument
    "#",  # standalone hash argument
]

# A fixed expansion environment for the test-side oracle so divergence does
# not depend on the test process environment.
_R4_ORACLE_ENV = {"HOME": "/home/oracle", "MYVAR": "oracle-value"}
_R4_ORACLE_SPECIFIERS = {"n": "tve-production-test.service", "h": "/home/oracle"}

_R4_ORACLE_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "'": "'",
    "s": " ",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def _oracle_unescape(ch: str) -> str:
    return _R4_ORACLE_ESCAPES.get(ch, "\\" + ch)


def _oracle_expand_dollar(token: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(token):
        ch = token[i]
        if ch != "$":
            out.append(ch)
            i += 1
            continue
        if i + 1 < len(token) and token[i + 1] == "$":
            out.append("$")
            i += 2
            continue
        if i + 1 < len(token) and token[i + 1] == "{":
            end = token.find("}", i + 2)
            if end != -1:
                out.append(_R4_ORACLE_ENV.get(token[i + 2 : end], ""))
                i = end + 1
                continue
        j = i + 1
        while j < len(token) and (token[j].isalnum() or token[j] == "_"):
            j += 1
        if j > i + 1:
            out.append(_R4_ORACLE_ENV.get(token[i + 1 : j], ""))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _oracle_expand_percent(token: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(token):
        ch = token[i]
        if ch == "%" and i + 1 < len(token):
            nxt = token[i + 1]
            if nxt == "%":
                out.append("%")
                i += 2
                continue
            if nxt in _R4_ORACLE_SPECIFIERS:
                out.append(_R4_ORACLE_SPECIFIERS[nxt])
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _oracle_effective_argv(line: str) -> list[str]:
    """Test-side oracle for the manager-effective Exec command-line argv.

    Models the systemd.syntax(7) quoting grammar and the systemd.service(5)
    dollar/specifier expansion validated against a real systemd 259 user
    manager during R4 development.  It exists to evaluate *rendered bytes*
    independently of the production serializer, so pre-R4 output can be
    shown to diverge from the typed input for the right reason.
    """

    tokens: list[str] = []
    i, n = 0, len(line)
    while i < n:
        while i < n and line[i].isspace():
            i += 1
        if i >= n:
            break
        buf: list[str] = []
        while i < n and not line[i].isspace():
            ch = line[i]
            if ch == "'":
                i += 1
                while i < n and line[i] != "'":
                    buf.append(line[i])
                    i += 1
                i += 1
            elif ch == '"':
                i += 1
                while i < n and line[i] != '"':
                    if line[i] == "\\" and i + 1 < n:
                        i += 1
                        buf.append(_oracle_unescape(line[i]))
                        i += 1
                    else:
                        buf.append(line[i])
                        i += 1
                i += 1
            elif ch == "\\" and i + 1 < n:
                i += 1
                buf.append(_oracle_unescape(line[i]))
                i += 1
            else:
                buf.append(ch)
                i += 1
        tokens.append("".join(buf))
    return [
        _oracle_expand_dollar(_oracle_expand_percent(token)) for token in tokens
    ]


def _oracle_effective_path_value(value: str) -> str:
    """Path directives take the whole line; only ``%`` is parser-active."""

    return _oracle_expand_percent(value)


def _unit_lines(unit_text: str) -> dict[str, str]:
    lines: dict[str, str] = {}
    for line in unit_text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"ExecStartPre", "ExecStart", "EnvironmentFile", "WorkingDirectory"}:
            lines.setdefault(key, value)
    return lines


@pytest.mark.parametrize("value", _R4_EDGE_VALUES)
def test_r4_exec_argument_round_trip(value: str) -> None:
    """Every parser-significant argv element survives systemd serialization."""

    serialized = prodops.systemd_exec_argument(value)
    line = f"/bin/echo {serialized}"
    # The production mirror parser must restore the exact typed value.
    assert prodops.parse_systemd_exec_command(line) == ["/bin/echo", value]
    # The independent test-side oracle must agree.
    assert _oracle_effective_argv(line) == ["/bin/echo", value]
    # Literal dollar/percent data is always doubled, never left raw: every
    # maximal run of expansion characters must have even length.
    runs = re.findall(r"[$%]+", serialized)
    assert all(len(run) % 2 == 0 for run in runs), serialized


def test_r4_gate_command_serializes_systemd_native_not_shlex() -> None:
    """The ExecStartPre line is systemd-native; shlex diverges on $ data."""

    tricky = "/opt/tve/creds $HOME %n space.env"
    argv = ("/usr/bin/python3", "/repo/scripts/gate.py", "--environment-file", tricky)
    command = prodops.systemd_exec_command(argv)
    assert prodops.parse_systemd_exec_command(command) == list(argv)
    assert _oracle_effective_argv(command) == list(argv)
    # shlex.join leaves the dollar sequence raw, which the manager would
    # expand at execution time: the pre-R4 serializer class, not a cosmetic
    # difference.
    shlex_form = shlex.join(argv)
    assert shlex_form != command
    assert "$HOME" in shlex_form
    assert "$HOME" not in command.replace("$$HOME", "")


def _r4_hostile_root(tmp_path: Path) -> Path:
    # Backslash is excluded: it is unrepresentable in the EnvironmentFile
    # path under delivery and rejected at parse time; the offline matrix
    # still covers it for every non-env-file Exec argument.
    root = tmp_path / "pro duction 'q'\"x\"$HOME%n;a#b-茅台"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _r4_delivery_config_with_root(tmp_path: Path, root: Path) -> tuple[ProductionConfigV1, Path]:
    env_file = root / "sec%nrets.env"
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(env_file),
        production_root=str(root),
        working_directory=str(root),
        watchlist_path=str(root / "watch list.json"),
        monitoring_workspace_root=str(root / "work space"),
        delivery_root=str(root / "de livery"),
        delivery_destination_id='dest "quoted" \\id',
    )
    return config, env_file


def test_r4_delivery_unit_exec_and_paths_round_trip(
    tmp_path: Path, destination: Path
) -> None:
    """Rendered Exec/path lines restore the exact typed values (goal 7.1-12)."""

    root = _r4_hostile_root(tmp_path)
    config, env_file = _r4_delivery_config_with_root(tmp_path, root)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R4_URL_VALUE}\n"
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R4_TOKEN_VALUE}\n",
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    unit_text = (config.systemd_output_dir / config.service_unit_name).read_text("utf-8")
    lines = _unit_lines(unit_text)

    # 9: the manager-effective gate argv equals credential_gate_argv exactly.
    gate_line = lines["ExecStartPre"]
    assert prodops.parse_systemd_exec_command(gate_line) == list(
        prodops.credential_gate_argv(config)
    )
    assert _oracle_effective_argv(gate_line) == list(prodops.credential_gate_argv(config))
    # 10: the delivery-enabled main argv keeps its exact argument boundaries.
    exec_line = lines["ExecStart"]
    expected_main = list(
        prodops.main_exec_argv(config, config.runner_config_path.resolve())
    )
    assert prodops.parse_systemd_exec_command(exec_line) == expected_main
    assert _oracle_effective_argv(exec_line) == expected_main
    assert expected_main[4] == "unattended-notify"
    # R3 ordering is preserved: the gate stays ahead of the notify command.
    assert unit_text.index("ExecStartPre=") < unit_text.index("ExecStart=")
    # 12: the EnvironmentFile path survives percent escaping exactly.
    assert _oracle_effective_path_value(lines["EnvironmentFile"]) == str(env_file)
    assert _oracle_effective_path_value(lines["WorkingDirectory"]) == str(root)
    # No secret value ever enters the unit.
    assert _R4_URL_VALUE not in unit_text and _R4_TOKEN_VALUE not in unit_text
    # The rendered units must satisfy the real systemd unit verifier.
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is not available on this host")
    verify = prodops._systemd_analyze_verify(
        (
            config.systemd_output_dir / config.service_unit_name,
            config.systemd_output_dir / config.timer_unit_name,
        ),
        runner=prodops._default_runner,
    )
    assert verify.ok, verify.stderr


def test_r4_delivery_disabled_execstart_exact_argv(tmp_path: Path) -> None:
    """11: monitoring-only units keep the unattended-run argv exactly."""

    config = _production_config(tmp_path)
    unit_text = render_service_unit(config, config.runner_config_path.resolve())
    exec_line = _unit_lines(unit_text)["ExecStart"]
    expected = list(prodops.main_exec_argv(config, config.runner_config_path.resolve()))
    assert expected[4] == "unattended-run"
    assert prodops.parse_systemd_exec_command(exec_line) == expected
    assert _oracle_effective_argv(exec_line) == expected

    # A parser-significant (but executable-representable) interpreter path
    # round-trips too; quotes/backslash/dollar are refused at parse time
    # because systemd cannot represent them in the executable token.
    tricky_dir = tmp_path / "py thon %n;xe"
    tricky_dir.mkdir()
    config = _production_config(tmp_path, python_executable=str(tricky_dir / "python"))
    unit_text = render_service_unit(config, config.runner_config_path.resolve())
    exec_line = _unit_lines(unit_text)["ExecStart"]
    assert prodops.parse_systemd_exec_command(exec_line) == list(
        prodops.main_exec_argv(config, config.runner_config_path.resolve())
    )
    assert _oracle_effective_argv(exec_line) == list(
        prodops.main_exec_argv(config, config.runner_config_path.resolve())
    )


def test_r4_environment_file_path_parity_across_consumers(tmp_path: Path) -> None:
    """12: unit directive, gate argv and validator share one exact path."""

    root = tmp_path / "production"
    root.mkdir()
    env_file = root / "sec%nrets 'quoted'.env"
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R4_URL_VALUE}\n"
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R4_TOKEN_VALUE}\n",
    )
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(env_file),
    )
    unit_text = render_service_unit(config, config.runner_config_path.resolve())
    directive = _unit_lines(unit_text)["EnvironmentFile"]
    assert _oracle_effective_path_value(directive) == str(env_file)
    gate_argv = prodops.credential_gate_argv(config)
    gate_line = prodops.systemd_exec_command(gate_argv)
    parsed = prodops.parse_systemd_exec_command(gate_line)
    assert parsed == list(gate_argv)
    assert parsed[parsed.index("--environment-file") + 1] == str(env_file)
    # The validation primitive resolves the same typed path successfully.
    state = prodops.validate_current_credential(
        environment_file=str(env_file),
        production_root=config.production_root,
        referenced_names=prodops._production_secret_reference_names(config),
    )
    assert state.ok, state.public_reason()


@pytest.mark.parametrize(
    "field,value",
    [
        ("watchlist_path", "/srv/watch 'list'.json"),
        ("watchlist_path", '/srv/watch "list".json'),
        ("watchlist_path", "/srv/watch\\list.json"),
        ("watchlist_path", "/srv/watch$list.json"),
        ("watchlist_path", "/srv/watch%nlist.json"),
        ("watchlist_path", "/srv/watch;n#list.json"),
        ("watchlist_path", "/srv/監視清單.json"),
        ("monitoring_workspace_root", "/srv/pro duction"),
        ("delivery_root", "/srv/de livery"),
        ("delivery_destination_id", 'dest "quoted" \\id'),
    ],
)
def test_r4_project_config_tomllib_round_trip(field: str, value: str) -> None:
    """13: generated project TOML parses back into the exact typed value."""

    config = _production_config(Path("/tmp/r4-unused"), **{field: value})
    text = render_project_config(config)
    parsed = tomllib.loads(text)
    monitoring = parsed["monitoring"]
    # delivery_* fields live in the nested [monitoring.delivery] table.
    table = monitoring["delivery"] if field.startswith("delivery_") else monitoring
    key = {
        "watchlist_path": "watchlist_path",
        "monitoring_workspace_root": "workspace_root",
        "delivery_root": "delivery_root",
        "delivery_destination_id": "destination_id",
    }[field]
    assert table[key] == value, text


def test_r4_project_config_tomllib_round_trip_telegram(tmp_path: Path) -> None:
    """13b: the telegram chat id and env references round-trip exactly."""

    root = tmp_path / "production"
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_transport="telegram-v1",
        delivery_environment_file=str(root / "secrets.env"),
        delivery_telegram_chat_id="-123456",
        delivery_telegram_bot_token_env="TVE_TELEGRAM_BOT_TOKEN",
        delivery_destination_id="prod 'primary'",
    )
    env_file = root / "secrets.env"
    root.mkdir(exist_ok=True)
    _write_private_env_file(env_file, "TVE_TELEGRAM_BOT_TOKEN=tok-r4-telegram\n")
    text = render_project_config(config)
    parsed = tomllib.loads(text)
    delivery = parsed["monitoring"]["delivery"]
    assert delivery["telegram_chat_id"] == "-123456"
    assert delivery["destination_id"] == "prod 'primary'"
    assert delivery["telegram_bot_token_ref"] == {"env": "TVE_TELEGRAM_BOT_TOKEN"}


def test_r4_verify_compares_manager_effective_argv_structurally(
    tmp_path: Path, destination: Path
) -> None:
    """Structural argv proof replaces substring presence (goal section 6)."""

    config, env_file = _delivery_config(tmp_path)
    _write_private_env_file(
        env_file,
        f"TVE_MONITORING_WEBHOOK_URL={_R4_URL_VALUE}\n"
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R4_TOKEN_VALUE}\n",
    )
    for name, desired in prodops.desired_unit_bytes(config).items():
        prodops._atomic_write(destination / name, desired)
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "verify", "--expect-active"]
    )

    healthy = FakeRunner(config=config)
    healthy.timer_enabled = True
    healthy.linger_enabled = True
    healthy.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "latest": {"activation_id": "a" * 64},
                    }
                ]
            }
        ),
    )
    assert prodops.cmd_verify(args, runner=healthy) == EXIT_OK
    record = json.loads(
        (config.systemd_output_dir / "verify-record.json").read_text("utf-8")
    )
    by_name = {item["name"]: item for item in record["checks"]}
    assert by_name["service.effective-execstart"]["status"] == "PASS"
    assert by_name["service.prestart-gate"]["status"] == "PASS"
    assert by_name["service.effective-environmentfile"]["status"] == "PASS"

    # Tamper only the manager-effective pre-start argv (one --reference
    # element dropped).  The textual properties still contain the full
    # expected command, so a substring check stays green; the structural
    # comparison must fail.
    tampered = FakeRunner(config=config)
    tampered.timer_enabled = True
    tampered.linger_enabled = True
    tampered.exec_start_pre_override = list(prodops.credential_gate_argv(config))[:-1]
    tampered.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "latest": {"activation_id": "a" * 64},
                    }
                ]
            }
        ),
    )
    assert prodops.cmd_verify(args, runner=tampered) == EXIT_FAIL_CLOSED
    record = json.loads(
        (config.systemd_output_dir / "verify-record.json").read_text("utf-8")
    )
    by_name = {item["name"]: item for item in record["checks"]}
    assert by_name["service.prestart-gate"]["status"] == "FAIL"
    # ...and the same structural rule for the main ExecStart argv.
    tampered_main = FakeRunner(config=config)
    tampered_main.timer_enabled = True
    tampered_main.linger_enabled = True
    tampered_main.exec_start_override = list(
        prodops.main_exec_argv(config, config.runner_config_path.resolve())
    ) + ["--extra"]
    tampered_main.add(
        (config.python_executable, "-m", "turtle_value_engine", "watch", "unattended-status"),
        json.dumps(
            {
                "runners": [
                    {
                        "runner_id": config.runner_id,
                        "latest": {"activation_id": "a" * 64},
                    }
                ]
            }
        ),
    )
    assert prodops.cmd_verify(args, runner=tampered_main) == EXIT_FAIL_CLOSED


def test_r4_ordinary_render_is_byte_compatible(tmp_path: Path) -> None:
    """14: ordinary inputs keep the exact pre-R4 rendered bytes."""

    root = tmp_path / "production"
    config = _production_config(tmp_path)
    runner_config_path = config.runner_config_path.resolve()
    expected_unit = (
        "[Unit]\n"
        "Description=turtle-value-engine production monitoring cycle "
        f"({config.runner_id}, Phase 6-F persistent owner operations)\n"
        "Documentation=file://"
        f"{config.working_directory}/docs/goals/phase-6-f-persistent-owner-operations.md\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "# Rendered by scripts/monitoring_production_ops.py from explicit non-secret\n"
        "# owner inputs.  No credential value ever appears in this unit; the\n"
        "# optional EnvironmentFile path is the only credential-related fact and\n"
        "# its content stays in the ignored private root with 0600 permissions.\n"
        f"WorkingDirectory={config.working_directory}\n"
        f"ExecStart={config.python_executable} -m turtle_value_engine watch "
        f"unattended-run --runner-config {runner_config_path}\n"
        "TimeoutStartSec=30min\n"
        "# Exit code 3 (LEASE_BUSY) means another live invocation owns the runner\n"
        "# lease and this invocation intentionally performed no work.\n"
        "SuccessExitStatus=3\n"
        "Nice=10\n"
    )
    assert render_service_unit(config, runner_config_path) == expected_unit

    delivery_root = root / "delivery"
    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(root / "secrets.env"),
    )
    gate = prodops.credential_gate_command(config)
    expected_gate = (
        f"{config.python_executable} {prodops.CREDENTIAL_GATE_SCRIPT} "
        f"--environment-file {root / 'secrets.env'} "
        f"--production-root {config.production_root} "
        "--reference TVE_MONITORING_WEBHOOK_URL "
        "--reference TVE_MONITORING_WEBHOOK_TOKEN"
    )
    assert gate == expected_gate

    expected_project = (
        "# Phase 6-F production project configuration (non-secret).\n"
        "# Generated by scripts/monitoring_production_ops.py; isolated production ledger.\n"
        "schema_version = 1\n"
        "\n"
        "[project]\n"
        'id = "turtle-value-engine"\n'
        'environment = "private"\n'
        'timezone = "Asia/Taipei"\n'
        "\n"
        "[monitoring]\n"
        f'watchlist_path = "{config.watchlist_path}"\n'
        f'workspace_root = "{config.monitoring_workspace_root}"\n'
        "\n"
        "[monitoring.delivery]\n"
        "enabled = true\n"
        f'transport = "{config.delivery_transport}"\n'
        f'destination_id = "{config.delivery_destination_id}"\n'
        f'delivery_root = "{delivery_root}"\n'
        "receiver_idempotency_declared = false\n"
        "max_attempts = 5\n"
        "timeout_seconds = 10.0\n"
        "backoff_base_seconds = 60\n"
        "backoff_cap_seconds = 3600\n"
        "max_response_bytes = 65536\n"
        'endpoint_ref = { env = "TVE_MONITORING_WEBHOOK_URL" }\n'
        'auth_token_ref = { env = "TVE_MONITORING_WEBHOOK_TOKEN" }\n'
    )
    assert render_project_config(config) == expected_project


def test_r4_timer_calendar_expression_stays_verbatim(tmp_path: Path) -> None:
    """on_calendar is an intentional systemd expression, never escaped."""

    config = _production_config(tmp_path, on_calendar="*-*-* 04,16:00:00")
    timer_text = render_timer_unit(config)
    assert "OnCalendar=*-*-* 04,16:00:00\n" in timer_text


@pytest.mark.parametrize(
    "field,value",
    [
        ("python_executable", "/usr/bin/pyth\non3"),
        ("working_directory", "/srv/tve\ttab"),
        ("production_root", "/srv/pro\x01duction"),
        ("runner_id", "prod\riction"),
    ],
)
def test_r4_rejects_control_characters_in_unit_fields(field: str, value: str) -> None:
    """Control characters cannot be represented in unit Exec/path lines."""

    with pytest.raises(Exception, match="control character"):
        _production_config(Path("/tmp/r4-unused"), **{field: value})


def test_r4_rejects_non_utf8_text_everywhere() -> None:
    """Lone surrogates cannot be serialized into any generated artifact."""

    with pytest.raises(Exception, match="unicode string"):
        _production_config(Path("/tmp/r4-unused"), watchlist_path="/srv/\ud800x")


@pytest.mark.skipif(
    not _systemd_user_manager_usable(),
    reason="no reachable systemd user manager for the transient argv/gate proof",
)
def test_r4_transient_manager_exact_argv_and_gate_blocking(tmp_path: Path) -> None:
    """Real manager proof: rendered unit runs the exact argv; gate blocks drift.

    The rendered *delivery* unit is executed with a dumper as the python
    executable: the manager must (a) read the ``%``-bearing credential file
    from the exact escaped EnvironmentFile path (otherwise the gate rejects
    the missing references), (b) run the R3 gate before the main command and
    (c) launch the main command with byte-exact argument boundaries.  A
    drifted (quoted) credential file must leave the main command unexecuted.
    """

    # Backslash is unrepresentable in the EnvironmentFile path (the systemd
    # exec-time loader treats it as an escape; rejected at parse time), so
    # the hostile root here keeps space/quote/dollar/percent classes and the
    # backslash class stays covered by the offline round-trip matrix.
    root = tmp_path / "pro duction $HOME%n 'q'\"x\""
    root.mkdir(parents=True)
    # The interpreter path is the systemd Exec executable, which refuses
    # quotes/backslashes/dollars outright (proved by the R4 parse-time
    # rejection); a space-only directory still proves quoted-executable
    # support at runtime while every other path keeps the full matrix.
    dumper_dir = tmp_path / "dum per"
    dumper_dir.mkdir()
    dumper = dumper_dir / "dumper.py"
    dumper.write_text(
        "#!/usr/bin/env python3\n"
        "import json, subprocess, sys\n"
        "from pathlib import Path\n"
        "# Executed as the ExecStartPre gate: delegate to the REAL gate CLI "
        "under the shebang interpreter so drift is actually enforced.\n"
        "if len(sys.argv) > 1 and 'monitoring_credential_gate' in sys.argv[1]:\n"
        "    raised = subprocess.run([sys.executable, *sys.argv[1:]])\n"
        "    sys.exit(raised.returncode)\n"
        "Path(__file__).with_name('main-argv.json').write_text("
        "json.dumps(sys.argv, ensure_ascii=False) + '\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    dumper.chmod(0o755)
    env_file = root / "sec%nrets 'x'.env"
    canonical = (
        f"TVE_MONITORING_WEBHOOK_URL={_R4_URL_VALUE}\n"
        f"TVE_MONITORING_WEBHOOK_TOKEN={_R4_TOKEN_VALUE}\n"
    )
    _write_private_env_file(env_file, canonical)

    config = _production_config(
        tmp_path,
        delivery_enabled=True,
        delivery_environment_file=str(env_file),
        production_root=str(root),
        working_directory=str(root),
        python_executable=str(dumper),
        unit_base_name=f"tve-r4-proof-{uuid.uuid4().hex[:10]}",
    )
    config_path = _write_config_file(tmp_path, config)
    args = prodops._build_parser().parse_args(
        ["--production-config", str(config_path), "render"]
    )
    assert prodops.cmd_render(args, runner=FakeRunner()) == EXIT_OK
    unit_path = config.systemd_output_dir / config.service_unit_name
    verify = prodops._systemd_analyze_verify((unit_path,), runner=prodops._default_runner)
    assert verify.ok, verify.stderr

    link = Path.home() / ".config" / "systemd" / "user" / config.service_unit_name
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["systemctl", "--user", "link", str(unit_path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        started = subprocess.run(
            ["systemctl", "--user", "start", config.service_unit_name],
            capture_output=True, text=True, timeout=180,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        argv_path = dumper_dir / "main-argv.json"
        assert argv_path.is_file(), "the dumper main command must have executed"
        effective = json.loads(argv_path.read_text("utf-8"))
        assert effective == list(
            prodops.main_exec_argv(config, config.runner_config_path.resolve())
        )
        assert effective[4] == "unattended-notify"
        argv_path.unlink()

        # Credential drift (systemd-quoted, TVE-noncanonical) must stop the
        # unit before the main command; the dumper output stays absent.
        _write_private_env_file(
            env_file,
            f'TVE_MONITORING_WEBHOOK_URL="{_R4_URL_VALUE}"\n'
            f"TVE_MONITORING_WEBHOOK_TOKEN={_R4_TOKEN_VALUE}\n",
        )
        drifted = subprocess.run(
            ["systemctl", "--user", "start", config.service_unit_name],
            capture_output=True, text=True, timeout=180,
        )
        assert drifted.returncode != 0
        assert not argv_path.exists(), "unattended-notify must not execute after drift"
        assert _R4_URL_VALUE not in drifted.stdout and _R4_URL_VALUE not in drifted.stderr
    finally:
        subprocess.run(
            ["systemctl", "--user", "stop", config.service_unit_name],
            capture_output=True, timeout=60,
        )
        link.unlink(missing_ok=True)
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=60
        )
