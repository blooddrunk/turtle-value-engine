"""Phase 6-F persistent owner production-operations harness.

Turns the already-proven Phase 6-E single-host acceptance chain into an
explicitly owner-authorized, restart-resilient long-lived monitoring
deployment.  This is operational hardening of the closed chain

```text
Phase 6-B bounded acquisition
  -> Phase 6-A planning/cursor commit
  -> Phase 6-C re-analysis boundary
  -> D1 cycle/outbox
  -> D2A/R1 unattended runner + authoritative lease
  -> optional D2B/R1/R2 delivery
  -> D3/R1 read-only operations projection
```

with no change to any of its semantics.  The Phase 6-E acceptance workspace
and this production lifecycle stay strictly separate: the harness refuses to
reuse or promote acceptance roots, runner ids or unit names.

Every mode is explicit and fail-closed:

- ``gate``          run the mandatory deterministic repository gate and bind
                    a green artifact to the current HEAD SHA;
- ``preflight``     non-mutating host/topology/config/secret/linger/lock
                    classification, including native-Linux vs WSL2 detection
                    and the honest Windows-bootstrap capability boundary;
- ``plan``          deterministic, redacted, mutation-free convergence plan
                    stating per resource create/modify/unchanged/enable/
                    linger-enable plus desired hashes and identities;
- ``render``        deterministic owner-specific unit material, production
                    runner/project configuration and ``systemd-analyze
                    verify`` under the private production root only;
- ``apply``/``converge`` install, daemon-reload, enable (never start) the
                    timer, converge linger for user scope and verify the
                    effective state; idempotent;
- ``activate``      the explicit production activation (start the timer);
- ``verify``        inspect the *effective* deployment through ``systemctl
                    show`` / bounded redacted journal slices, never the
                    templates;
- ``live-proof``    one bounded immediate production firing, replay/no-
                    duplicate proof, D3 read-only/non-interference proof,
                    acceptance-root immutability and a secret scan;
- ``recover-proof`` the strongest safe manager refresh (daemon-reload +
                    daemon-reexec), timer stop/start, durable resume with no
                    duplicate activation/cycle/delivery and unchanged
                    configuration identity;
- ``deactivate``    safe, idempotent stop+disable of the production timer;
- ``report``        assemble/validate the secret-free machine-readable
                    production operations report.

Secret discipline: no credential value is ever accepted, printed or
persisted by this script.  Notification is optional; when enabled, the only
typed local credential source is a systemd ``EnvironmentFile`` under the
ignored private root whose *path* (never its content) appears in the unit,
and the render step refuses to continue while that file is absent.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import scripts.monitoring_live_acceptance as acceptance  # noqa: E402
from scripts.monitoring_live_acceptance import (  # noqa: E402
    DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN,
    EXIT_FAIL_CLOSED,
    EXIT_MARKER,
    EXIT_OK,
    MANUAL_SECRET_REFERENCE_REQUIRED,
    MANUAL_SUDO_INSTALL_REQUIRED,
    AcceptanceError,
    CheckLog,
    CommandOutcome,
    CommandRunner,
    ManualBoundary,
    _atomic_write,
    _bounded,
    _default_runner,
    _outcome_public,
    _sha256_bytes,
    _systemctl_show,
    _systemd_analyze_verify,
    _systemd_privilege_available,
    _tracked_files_without_secrets,
    content_tree_hash,
    gate_commands,
    load_gate_artifact,
    probe_lock_visibility,
    redact_text,
    run_command,
    scan_bytes_for_secrets,
    systemctl_prefix,
    systemd_unit_destination_dir,
)
from turtle_value_engine.config import load_project_config  # noqa: E402
from turtle_value_engine.monitoring.canonical import canonical_json_bytes  # noqa: E402
from turtle_value_engine.monitoring.models import WatchlistSpecV1  # noqa: E402
from turtle_value_engine.monitoring_runner.contracts import RunnerConfigV1  # noqa: E402

# ---------------------------------------------------------------------------
# Markers and contracts
# ---------------------------------------------------------------------------

MANUAL_ENABLE_LINGER_REQUIRED = "MANUAL_ENABLE_LINGER_REQUIRED"
WINDOWS_HOST_BOOTSTRAP_UNPROVEN = "WINDOWS_HOST_BOOTSTRAP_UNPROVEN"

CONFIG_CONTRACT = "monitoring_production_config_v1"
REPORT_CONTRACT = "monitoring_production_report_v1"

PROBE_RUNNER_ID = "phase6f-lock-visibility"

# The Phase 6-E acceptance assets this production lifecycle must never
# silently reuse or promote (goal section 4: acceptance != production).
PHASE6E_UNIT_BASENAMES: frozenset[str] = frozenset(
    {"tve-phase6e-acceptance", "turtle-value-monitor"}
)
PHASE6E_ROOT_MARKER = "phase6e"
PHASE6E_ROOT_HINT = str(ROOT / ".tve-private" / "monitoring" / "phase6e")

_LISTING_PATTERN = re.compile(r"^(SH|SZ|BJ)\d{6}$|^(HK)\d{5}$")
_UNIT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_ENV_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ---------------------------------------------------------------------------
# Typed production configuration (owner inputs; non-secret by construction)
# ---------------------------------------------------------------------------


class ProductionConfigV1(BaseModel):
    """Explicit, non-secret owner inputs for one long-lived production run.

    Every path, identity and policy here is a production fact.  The Phase 6-E
    acceptance workspace is never a valid value: roots, runner ids and unit
    names that would collide with acceptance assets are rejected at parse
    time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: StrictStr = CONFIG_CONTRACT
    schema_version: StrictStr = "1.0.0"

    # Deployment shape.
    scope: StrictStr = Field(pattern=r"^(user|system)$")
    service_user: StrictStr | None = None
    python_executable: StrictStr = Field(min_length=1, max_length=4096)
    working_directory: StrictStr = Field(min_length=1, max_length=4096)
    unit_base_name: StrictStr = Field(min_length=1, max_length=120)
    on_calendar: StrictStr = Field(min_length=1, max_length=200)
    randomized_delay_sec: StrictInt = Field(ge=0, le=3600)
    timer_accuracy_sec: StrictInt = Field(default=1, ge=1, le=60)

    # Private operations root (reports, rendered material, gate artifacts).
    production_root: StrictStr = Field(min_length=1, max_length=4096)

    # Production identities and typed roots (explicit; no silent defaults).
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    watchlist_path: StrictStr = Field(min_length=1, max_length=4096)
    monitoring_workspace_root: StrictStr = Field(min_length=1, max_length=512)
    reanalysis_job_root: StrictStr = Field(min_length=1, max_length=512)
    cycle_store_root: StrictStr = Field(min_length=1, max_length=512)
    runner_root: StrictStr = Field(min_length=1, max_length=512)
    cache_dir: StrictStr = Field(min_length=1, max_length=512)
    delivery_root: StrictStr = Field(min_length=1, max_length=512)

    # Network/acquisition policy (Phase 6-B stays opt-in and bounded).
    network_allowed: StrictBool = False
    window_days: StrictInt = Field(ge=1, le=366)
    as_of: datetime | None = None
    acquisition_limit: StrictInt = Field(default=30, ge=1, le=30)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_response_bytes: StrictInt = Field(default=524288, ge=1024, le=8388608)
    lease_ttl_seconds: StrictInt = Field(default=900, ge=1, le=604800)

    # Optional notification (disabled by default; references only).
    delivery_enabled: StrictBool = False
    delivery_transport: StrictStr = Field(
        default="webhook-v1", pattern=r"^(webhook-v1|telegram-v1)$"
    )
    delivery_destination_id: StrictStr = Field(
        default="production-primary", min_length=1, max_length=128
    )
    delivery_endpoint_env: StrictStr = Field(
        default="TVE_MONITORING_WEBHOOK_URL", min_length=1, max_length=256
    )
    delivery_auth_env: StrictStr | None = Field(
        default="TVE_MONITORING_WEBHOOK_TOKEN", min_length=1, max_length=256
    )
    delivery_telegram_bot_token_env: StrictStr = Field(
        default="TVE_MONITORING_TELEGRAM_BOT_TOKEN", min_length=1, max_length=256
    )
    delivery_telegram_chat_id: StrictStr | None = None
    # The one typed local credential source: a private systemd
    # ``EnvironmentFile`` holding the referenced secret values.  Only its
    # path is ever rendered; its content never enters Git, units, argv,
    # configs, ledgers, reports or API payloads.
    delivery_environment_file: StrictStr | None = Field(
        default=None, min_length=1, max_length=4096
    )

    # Read-only D3 projection check inputs.
    snapshot_path: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
    surface_port: StrictInt = Field(default=8899, ge=1024, le=65535)

    require_repo_gate: StrictBool = True

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("as_of must carry an explicit timezone")
        return value.astimezone(UTC)

    @field_validator(
        "delivery_endpoint_env",
        "delivery_auth_env",
        "delivery_telegram_bot_token_env",
    )
    @classmethod
    def _validate_secret_env_name(cls, value: str | None) -> str | None:
        if value is not None and not _SECRET_ENV_PATTERN.fullmatch(value):
            raise ValueError("delivery secret reference must be an environment variable name")
        return value

    def _refuse_phase6e(self, value: str, field_name: str) -> None:
        parts = Path(value).parts
        if PHASE6E_ROOT_MARKER in parts:
            raise ValueError(
                f"{field_name} must not touch the Phase 6-E acceptance tree "
                f"({PHASE6E_ROOT_MARKER} path segment); production and acceptance "
                "workspaces are strictly separate"
            )

    @model_validator(mode="after")
    def _validate_config(self) -> ProductionConfigV1:
        if not _UNIT_NAME_PATTERN.match(self.unit_base_name):
            raise ValueError("unit_base_name is not a valid systemd unit name fragment")
        if self.unit_base_name in PHASE6E_UNIT_BASENAMES or self.unit_base_name.startswith(
            "tve-phase6e"
        ):
            raise ValueError(
                "unit_base_name must not reuse the Phase 6-E acceptance unit namespace"
            )
        if self.runner_id.startswith("phase6e"):
            raise ValueError("runner_id must not reuse the Phase 6-E acceptance namespace")
        if self.scope == "system" and self.service_user is None:
            raise ValueError("scope=system requires an explicit service_user")
        if self.scope == "user" and self.service_user is not None:
            raise ValueError("scope=user must not pin a service_user (it runs as the owner)")
        for name in (
            "python_executable",
            "working_directory",
            "production_root",
            "watchlist_path",
            "monitoring_workspace_root",
            "reanalysis_job_root",
            "cycle_store_root",
            "runner_root",
            "cache_dir",
            "delivery_root",
        ):
            if not Path(getattr(self, name)).is_absolute():
                raise ValueError(f"{name} must be an absolute path")
        for name in (
            "production_root",
            "watchlist_path",
            "monitoring_workspace_root",
            "reanalysis_job_root",
            "cycle_store_root",
            "runner_root",
            "cache_dir",
            "delivery_root",
        ):
            self._refuse_phase6e(getattr(self, name), name)
        if self.delivery_enabled:
            if self.delivery_environment_file is None:
                raise ValueError(
                    "delivery_enabled=true requires delivery_environment_file (the typed "
                    "local credential source; its path is rendered, never its content)"
                )
            if not Path(self.delivery_environment_file).is_absolute():
                raise ValueError("delivery_environment_file must be an absolute path")
            if self.delivery_transport == "telegram-v1":
                if self.delivery_telegram_chat_id is None or not re.fullmatch(
                    r"-?[0-9]+", self.delivery_telegram_chat_id
                ):
                    raise ValueError(
                        "telegram-v1 delivery requires a numeric delivery_telegram_chat_id"
                    )
            elif self.delivery_endpoint_env is None:
                raise ValueError("webhook-v1 delivery requires delivery_endpoint_env")
        else:
            if self.delivery_environment_file is not None:
                raise ValueError(
                    "delivery_environment_file is only meaningful with delivery_enabled=true"
                )
        return self

    # -- derived paths ------------------------------------------------------

    @property
    def systemd_output_dir(self) -> Path:
        return Path(self.production_root) / "systemd"

    @property
    def runner_config_path(self) -> Path:
        return Path(self.production_root) / "runner.json"

    @property
    def project_config_path(self) -> Path:
        return Path(self.production_root) / "project.toml"

    @property
    def service_unit_name(self) -> str:
        return f"{self.unit_base_name}.service"

    @property
    def timer_unit_name(self) -> str:
        return f"{self.unit_base_name}.timer"

    @property
    def report_path(self) -> Path:
        return Path(self.production_root) / "production-report.json"

    @property
    def gate_artifact_path(self) -> Path:
        return Path(self.production_root) / "gate.json"

    @property
    def service_identity(self) -> str:
        return self.service_user if self.scope == "system" else "owner-user-manager"


def load_production_config(path: str | Path) -> ProductionConfigV1:
    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read production config {config_path}: {exc}") from exc
    try:
        config = ProductionConfigV1.model_validate(payload)
    except Exception as exc:
        raise AcceptanceError(f"invalid production config {config_path}: {exc}") from exc
    if config.contract != CONFIG_CONTRACT:
        raise AcceptanceError(f"production config {config_path} has the wrong contract")
    return config


def build_runner_config(config: ProductionConfigV1) -> RunnerConfigV1:
    """The production runner configuration from the typed owner inputs."""

    return RunnerConfigV1(
        runner_id=config.runner_id,
        watchlist_path=config.watchlist_path,
        monitoring_workspace_root=config.monitoring_workspace_root,
        reanalysis_job_root=config.reanalysis_job_root,
        cycle_store_root=config.cycle_store_root,
        runner_root=config.runner_root,
        cache_dir=config.cache_dir,
        network_allowed=config.network_allowed,
        offline_replay=not config.network_allowed,
        window_days=config.window_days,
        as_of=config.as_of,
        acquisition_limit=config.acquisition_limit,
        timeout_seconds=config.timeout_seconds,
        max_response_bytes=config.max_response_bytes,
        lease_ttl_seconds=config.lease_ttl_seconds,
    )


def render_project_config(config: ProductionConfigV1) -> str:
    """The production project TOML (non-secret; secret references only)."""

    text = f"""# Phase 6-F production project configuration (non-secret).
# Generated by scripts/monitoring_production_ops.py; isolated production ledger.
schema_version = 1

[project]
id = "turtle-value-engine"
environment = "private"
timezone = "Asia/Taipei"

[monitoring]
watchlist_path = "{config.watchlist_path}"
workspace_root = "{config.monitoring_workspace_root}"

[monitoring.delivery]
enabled = {"true" if config.delivery_enabled else "false"}
transport = "{config.delivery_transport}"
destination_id = "{config.delivery_destination_id}"
delivery_root = "{config.delivery_root}"
receiver_idempotency_declared = false
max_attempts = 5
timeout_seconds = 10.0
backoff_base_seconds = 60
backoff_cap_seconds = 3600
max_response_bytes = 65536
"""
    if config.delivery_enabled and config.delivery_transport == "telegram-v1":
        text += (
            "telegram_bot_token_ref = "
            f'{{ env = "{config.delivery_telegram_bot_token_env}" }}\n'
            f'telegram_chat_id = "{config.delivery_telegram_chat_id}"\n'
        )
    elif config.delivery_enabled:
        text += f'endpoint_ref = {{ env = "{config.delivery_endpoint_env}" }}\n'
        if config.delivery_auth_env is not None:
            text += f'auth_token_ref = {{ env = "{config.delivery_auth_env}" }}\n'
    return text


# ---------------------------------------------------------------------------
# Systemd rendering (production units)
# ---------------------------------------------------------------------------


def render_service_unit(config: ProductionConfigV1, runner_config_path: Path) -> str:
    """Deterministic production oneshot service unit (no secret values)."""

    environment_line = (
        f"EnvironmentFile={config.delivery_environment_file}\n"
        if config.delivery_enabled
        else ""
    )
    if config.delivery_enabled:
        run_line = (
            f"{config.python_executable} -m turtle_value_engine watch unattended-notify "
            f"--runner-config {runner_config_path} "
            f"--project-config {config.project_config_path.resolve()} --network allow\n"
        )
    else:
        run_line = (
            f"{config.python_executable} -m turtle_value_engine watch unattended-run "
            f"--runner-config {runner_config_path}\n"
        )
    user_line = f"User={config.service_user}\n" if config.scope == "system" else ""
    description = (
        "turtle-value-engine production monitoring cycle "
        f"({config.runner_id}, Phase 6-F persistent owner operations)"
    )
    return (
        "[Unit]\n"
        f"Description={description}\n"
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
        f"{user_line}"
        f"{environment_line}"
        "ExecStart="
        f"{run_line}"
        "TimeoutStartSec=30min\n"
        "# Exit code 3 (LEASE_BUSY) means another live invocation owns the runner\n"
        "# lease and this invocation intentionally performed no work.\n"
        "SuccessExitStatus=3\n"
        "Nice=10\n"
    )


def render_timer_unit(config: ProductionConfigV1) -> str:
    return (
        "[Unit]\n"
        "Description=Schedule the turtle-value-engine production monitoring cycle\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar={config.on_calendar}\n"
        "Persistent=true\n"
        f"Unit={config.service_unit_name}\n"
        f"RandomizedDelaySec={config.randomized_delay_sec}s\n"
        f"AccuracySec={config.timer_accuracy_sec}s\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def desired_unit_bytes(config: ProductionConfigV1) -> dict[str, bytes]:
    runner_config_path = config.runner_config_path.resolve()
    return {
        config.service_unit_name: render_service_unit(config, runner_config_path).encode("utf-8"),
        config.timer_unit_name: render_timer_unit(config).encode("utf-8"),
    }


def desired_runner_config_bytes(config: ProductionConfigV1) -> bytes:
    return (
        build_runner_config(config).model_dump_json(indent=2, warnings=False).encode("utf-8")
        + b"\n"
    )


def desired_project_config_bytes(config: ProductionConfigV1) -> bytes:
    return render_project_config(config).encode("utf-8")


# ---------------------------------------------------------------------------
# Host topology classification (native Linux vs WSL2, Windows bootstrap)
# ---------------------------------------------------------------------------


def classify_topology_from_facts(
    *,
    sys_platform: str,
    kernel_release: str,
    proc_version: str,
    pid1_comm: str,
    wsl_conf_text: str | None,
    interop_available: bool,
) -> dict[str, object]:
    """Pure topology classification from injectable host facts."""

    is_wsl = "microsoft" in (kernel_release + " " + proc_version).lower()
    wsl_systemd_boot: bool | None = None
    if wsl_conf_text is not None:
        in_boot = False
        for raw_line in wsl_conf_text.splitlines():
            line = raw_line.strip()
            if line.startswith("["):
                in_boot = line.lower().startswith("[boot]")
                continue
            if in_boot and "=" in line:
                key, _, value = line.partition("=")
                if key.strip().lower() == "systemd":
                    wsl_systemd_boot = value.strip().lower() == "true"
    # Linux-side evidence (systemd as PID 1, [boot] systemd=true in
    # /etc/wsl.conf) proves the distro user manager starts whenever the
    # distro runs.  Nothing readable from inside the distro proves the
    # Windows host auto-starts this distro after a Windows reboot, so the
    # bootstrap capability boundary stays explicit rather than inferred.
    windows_bootstrap_proven = False
    persistence_claim = (
        "persistent while the WSL distro/user manager is running "
        "(Linux systemd PID 1 with linger; Windows-reboot distro autostart "
        "not claimed)"
        if is_wsl
        else "persistent through host reboots via the native Linux system manager"
    )
    if not is_wsl:
        windows_bootstrap_proven = True  # not applicable on native Linux
    return {
        "sys_platform": sys_platform,
        "kernel_release": kernel_release,
        "wsl2": is_wsl,
        "pid1": pid1_comm,
        "wsl_conf_systemd_boot": wsl_systemd_boot,
        "windows_interop_available": interop_available if is_wsl else None,
        "windows_host_bootstrap_proven": windows_bootstrap_proven,
        "persistence_claim": persistence_claim,
    }


def classify_host_topology(runner: CommandRunner = _default_runner) -> dict[str, object]:
    proc_version = ""
    try:
        proc_version = Path("/proc/version").read_text(encoding="utf-8")
    except OSError:
        proc_version = ""
    try:
        pid1_comm = Path("/proc/1/comm").read_text(encoding="utf-8").strip()
    except OSError:
        pid1_comm = "unknown"
    wsl_conf_text: str | None = None
    try:
        wsl_conf_text = Path("/etc/wsl.conf").read_text(encoding="utf-8")
    except OSError:
        wsl_conf_text = None
    interop = bool(os.environ.get("WSL_INTEROP")) and Path("/run/WSL").is_dir()
    facts = classify_topology_from_facts(
        sys_platform=sys.platform,
        kernel_release=platform.release(),
        proc_version=proc_version,
        pid1_comm=pid1_comm,
        wsl_conf_text=wsl_conf_text,
        interop_available=interop,
    )
    version_outcome = run_command(("systemctl", "--version"), runner=runner)
    facts["systemd_version"] = _bounded(
        (version_outcome.stdout.splitlines() or ["unavailable"])[0], 120
    )
    return facts


def windows_bootstrap_marker_payload(config: ProductionConfigV1) -> dict[str, object]:
    """The precise WSL capability boundary (six disclosure items)."""

    marker = ManualBoundary(
        WINDOWS_HOST_BOOTSTRAP_UNPROVEN,
        stopped_after=(
            "preflight/verify topology classification on the real deployment host: "
            "Linux-side evidence (systemd PID 1, /etc/wsl.conf) cannot prove that "
            "the Windows host auto-starts this WSL distro after a Windows reboot"
        ),
        human_action=(
            "optional: register a Windows-side logon/startup task that starts this "
            "distro (e.g. an owner-created scheduled task running "
            "`wsl.exe -d <DistroName>`) if unattended Windows-reboot autostart is "
            "wanted; this is a Windows-owner action, not a Linux-side edit"
        ),
        secret_boundary="no secret is involved in the bootstrap registration",
        resume_command=(
            _resume_command("<config>", "verify")
            + " (after the Windows-side registration exists; the topology "
            "classifier records the interop probe result in every report)"
        ),
        machine_verifiable_success=(
            "a future topology probe that can read a Windows-side autostart "
            "registration for this distro through interop flips "
            "windows_host_bootstrap_proven to true"
        ),
        remaining_unverified=(
            "Windows-reboot autostart of the WSL distro itself; everything on the "
            "Linux side (linger, timer, units, runner durability) remains proven"
        ),
    )
    return marker.payload


# ---------------------------------------------------------------------------
# Linger (user-scope persistence)
# ---------------------------------------------------------------------------


def linger_state(user: str, runner: CommandRunner = _default_runner) -> str | None:
    outcome = run_command(("loginctl", "show-user", user, "-p", "Linger"), runner=runner)
    if not outcome.ok:
        return None
    for line in outcome.stdout.splitlines():
        if line.startswith("Linger="):
            return line.partition("=")[2].strip()
    return None


def enable_linger(user: str, runner: CommandRunner = _default_runner) -> CommandOutcome:
    # The explicit username matters: the argument-less form resolves the
    # calling session and fails on hosts without a controlling TTY (WSL2).
    return run_command(("loginctl", "enable-linger", user), runner=runner)


def ensure_linger(
    config: ProductionConfigV1,
    *,
    current_user: str | None = None,
    runner: CommandRunner = _default_runner,
) -> dict[str, object]:
    """Verify linger for user scope, enabling it automatically when allowed."""

    if config.scope != "user":
        return {"applicable": False, "scope": config.scope}
    user = current_user or config.service_user or getpass_user()
    before = linger_state(user, runner)
    if before == "yes":
        return {"applicable": True, "user": user, "state_before": before, "action": "unchanged"}
    outcome = enable_linger(user, runner=runner)
    after = linger_state(user, runner)
    if outcome.ok and after == "yes":
        return {
            "applicable": True,
            "user": user,
            "state_before": before,
            "action": "enabled",
            "state_after": after,
        }
    raise ManualBoundary(
        MANUAL_ENABLE_LINGER_REQUIRED,
        stopped_after=(
            f"apply: user-scope production persistence requires Linger=yes for "
            f"{user}, but `loginctl enable-linger {user}` did not establish it "
            f"(rc={outcome.returncode}, Linger={after})"
        ),
        human_action=(
            f"run `sudo loginctl enable-linger {user}` (or ask an administrator to) "
            "so the user systemd manager keeps running after the last login session"
        ),
        secret_boundary="no secret is involved; this is a systemd user-manager property",
        resume_command=_resume_command("<config>", "apply"),
        machine_verifiable_success=(
            f"`loginctl show-user {user} -p Linger` reports Linger=yes and the "
            "resumed apply exits 0"
        ),
        remaining_unverified=(
            "unattended production persistence outside an interactive login "
            "(the timer only runs while the user manager is alive)"
        ),
    )


def getpass_user() -> str:
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


def _resume_command(production_config_path: str | Path, mode: str) -> str:
    """A directly runnable resume command using the actual input config."""

    return shlex.join(
        (
            sys.executable,
            str(Path(__file__).resolve()),
            "--production-config",
            str(Path(production_config_path).expanduser().resolve()),
            mode,
        )
    )


# ---------------------------------------------------------------------------
# Deterministic plan (mutation-free convergence projection)
# ---------------------------------------------------------------------------

_ACTION_CREATE = "create"
_ACTION_MODIFY = "modify"
_ACTION_UNCHANGED = "unchanged"


def _file_action(existing: Path, desired: bytes) -> tuple[str, str | None]:
    if not existing.is_file():
        return _ACTION_CREATE, None
    installed_sha = _sha256_bytes(existing.read_bytes())
    if existing.read_bytes() == desired:
        return _ACTION_UNCHANGED, installed_sha
    return _ACTION_MODIFY, installed_sha


def compute_plan(
    config: ProductionConfigV1, runner: CommandRunner = _default_runner
) -> dict[str, object]:
    """Deterministic, redacted, mutation-free convergence plan."""

    desired_units = desired_unit_bytes(config)
    destination = systemd_unit_destination_dir(config)
    resources: list[dict[str, object]] = []
    for name, desired in desired_units.items():
        action, installed_sha = _file_action(destination / name, desired)
        resources.append(
            {
                "resource": f"unit-file:{name}",
                "action": action,
                "path": str(destination / name),
                "desired_sha256": _sha256_bytes(desired),
                "installed_sha256": installed_sha,
                "desired_bytes": len(desired),
            }
        )
    for label, path, desired in (
        ("runner-config", config.runner_config_path, desired_runner_config_bytes(config)),
        ("project-config", config.project_config_path, desired_project_config_bytes(config)),
    ):
        action, installed_sha = _file_action(path, desired)
        resources.append(
            {
                "resource": label,
                "action": action,
                "path": str(path),
                "desired_sha256": _sha256_bytes(desired),
                "installed_sha256": installed_sha,
                "desired_bytes": len(desired),
            }
        )

    timer_props = _systemctl_show(
        config,
        config.timer_unit_name,
        ("UnitFileState", "ActiveState"),
        runner,
    )
    unit_file_state = timer_props.get("UnitFileState", "")
    resources.append(
        {
            "resource": "timer-enable",
            "action": "enable" if unit_file_state != "enabled" else "unchanged",
            "unit": config.timer_unit_name,
            "effective_unit_file_state": unit_file_state or "absent",
        }
    )
    # Activation is deliberately excluded from apply: the timer is enabled,
    # never started, by configuration installation.
    resources.append(
        {
            "resource": "timer-start",
            "action": "explicit-activation-required",
            "unit": config.timer_unit_name,
            "effective_active_state": timer_props.get("ActiveState", "") or "unknown",
            "note": "apply never starts the timer; run the activate mode explicitly",
        }
    )
    if config.scope == "user":
        user = config.service_user or getpass_user()
        state = linger_state(user, runner)
        resources.append(
            {
                "resource": "linger",
                "action": "enable" if state != "yes" else "unchanged",
                "user": user,
                "effective_linger": state or "unknown",
            }
        )
    service_props = _systemctl_show(
        config,
        config.service_unit_name,
        ("ExecStart", "WorkingDirectory", "User"),
        runner,
    )
    return {
        "contract": "monitoring_production_plan_v1",
        "generated_for_head": acceptance._git_head(ROOT, runner),
        "scope": config.scope,
        "service_user": config.service_user,
        "service_identity": config.service_identity,
        "on_calendar": config.on_calendar,
        "randomized_delay_sec": config.randomized_delay_sec,
        "network_policy": "explicit-opt-in" if config.network_allowed else "offline-replay",
        "window_days": config.window_days,
        "delivery": {
            "enabled": config.delivery_enabled,
            "transport": config.delivery_transport if config.delivery_enabled else None,
            "environment_file": config.delivery_environment_file
            if config.delivery_enabled
            else None,
        },
        "runner_id": config.runner_id,
        "watchlist_path": config.watchlist_path,
        "runner_config_path": str(config.runner_config_path),
        "effective_service_properties": service_props,
        "resources": resources,
        "mutation_performed": False,
        "contains_secrets": False,
    }


def cmd_plan(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    plan = compute_plan(config, runner=runner)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Preflight (non-mutating)
# ---------------------------------------------------------------------------


def _production_secret_reference_names(config: ProductionConfigV1) -> list[str]:
    if not config.delivery_enabled:
        return []
    names = [config.delivery_endpoint_env, config.delivery_auth_env]
    if config.delivery_transport == "telegram-v1":
        names = [config.delivery_telegram_bot_token_env]
    return [name for name in names if name is not None]


def resolvable_secret_values(
    config: ProductionConfigV1, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Currently resolvable secret values by reference (scans/redaction only)."""

    environment = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for name in _production_secret_reference_names(config):
        raw = environment.get(name, "")
        if raw.strip():
            values[name] = raw
    return values


def environment_file_values(
    config: ProductionConfigV1
) -> tuple[dict[str, str], str | None]:
    """Parse KEY=VALUE lines from the delivery environment file (memory only).

    Values never leave this process except inside absence scans/redaction.
    Returns (values, error) where error explains an unreadable file.
    """

    assert config.delivery_environment_file is not None
    path = Path(config.delivery_environment_file)
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values, None


def cmd_preflight(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    log = CheckLog()

    log.add("host.linux", sys.platform.startswith("linux"), f"sys.platform={sys.platform}")
    log.add(
        "host.python",
        sys.version_info >= (3, 11),
        f"interpreter={sys.executable} version={sys.version.split()[0]}",
    )
    systemd_version = run_command(("systemctl", "--version"), runner=runner)
    log.add(
        "host.systemd-present",
        systemd_version.ok,
        _bounded(systemd_version.stdout.splitlines()[0] if systemd_version.stdout else "", 120),
    )
    systemd_state = run_command(("systemctl", "is-system-running"), runner=runner)
    log.add(
        "host.systemd-running",
        systemd_state.ok or systemd_state.stdout.strip() == "degraded",
        f"is-system-running={systemd_state.stdout.strip() or systemd_state.stderr.strip()}",
    )
    log.add("host.proc-locks-readable", os.access("/proc/locks", os.R_OK), "/proc/locks")

    head_sha = acceptance._git_head(ROOT, runner)
    tree_clean = acceptance._git_clean(ROOT, runner)
    log.add("repo.head", bool(re.fullmatch(r"[0-9a-f]{40}", head_sha)), head_sha)
    log.add(
        "repo.working-tree",
        tree_clean or not args.require_clean_tree,
        "clean" if tree_clean else "dirty (pass --require-clean-tree to enforce)",
    )
    if config.require_repo_gate and not args.skip_gate:
        try:
            artifact = load_gate_artifact(config, head_sha=head_sha)
            log.add("repo.gate-artifact", True, f"green at {artifact['head_sha']}")
        except AcceptanceError as exc:
            log.add("repo.gate-artifact", False, str(exc))
    else:
        log.add_marker(
            "repo.gate-artifact",
            acceptance.MANUAL_OWNER_INPUT_REQUIRED,
            "repo gate check skipped by explicit flag",
        )

    # Typed inputs: the production watchlist is an existing owner file.
    watchlist_path = Path(config.watchlist_path)
    if watchlist_path.is_file():
        try:
            watchlist = WatchlistSpecV1.build(
                **json.loads(watchlist_path.read_text(encoding="utf-8"))
            )
            entries = [entry.listing_id for entry in watchlist.entries]
            bad_entries = [item for item in entries if not _LISTING_PATTERN.match(item)]
            log.add(
                "config.watchlist",
                not bad_entries,
                f"watchlist_id={watchlist.watchlist_id} entries={entries}",
            )
        except Exception as exc:
            log.add("config.watchlist", False, f"invalid watchlist: {exc}")
    else:
        log.add("config.watchlist", False, f"missing production watchlist: {watchlist_path}")

    try:
        runner_config = build_runner_config(config)
        log.add(
            "config.runner",
            True,
            f"runner_id={runner_config.runner_id} network_allowed="
            f"{runner_config.network_allowed} window_days={runner_config.window_days}",
        )
    except Exception as exc:
        log.add("config.runner", False, f"cannot build runner config: {exc}")

    # Roots are private (never a tracked-worktree path outside .tve-private).
    inside_worktree = False
    try:
        Path(config.production_root).relative_to(ROOT)
        inside_worktree = True
    except ValueError:
        inside_worktree = False
    private = (not inside_worktree) or ".tve-private" in Path(config.production_root).parts
    probe_dir = Path(config.production_root)
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    log.add(
        "config.roots-private-writable",
        private and os.access(probe_dir, os.W_OK | os.X_OK),
        f"production_root={config.production_root} writable_probe={probe_dir} "
        f"inside_worktree={inside_worktree}",
    )

    # Topology classification (native vs WSL2, PID 1, Windows bootstrap).
    topology = classify_host_topology(runner)
    topology_ok = (
        topology["pid1"] == "systemd"
        and (not topology["wsl2"] or topology["wsl_conf_systemd_boot"] is True)
    )
    log.add(
        "host.topology",
        bool(topology_ok),
        json.dumps(topology, ensure_ascii=False),
    )
    if topology["wsl2"] and not topology["windows_host_bootstrap_proven"]:
        # Capability boundary, not a deployment blocker: the persistence claim
        # is narrowed, and the exact marker travels into every report.
        log.add_marker(
            "host.windows-bootstrap",
            WINDOWS_HOST_BOOTSTRAP_UNPROVEN,
            "Linux-side evidence cannot prove Windows-reboot distro autostart; the "
            "persistence claim stays narrowed to the running distro/user manager",
        )

    # Linger classification (user scope): state now + what apply would do.
    if config.scope == "user":
        user = config.service_user or getpass_user()
        state = linger_state(user, runner)
        log.add(
            "host.linger",
            state == "yes",
            f"Linger={state or 'unknown'} for {user}; "
            + (
                "already persistent"
                if state == "yes"
                else "apply will attempt `loginctl enable-linger` automatically"
            ),
        )

    # Delivery: optional; references and the typed environment file only.
    if config.delivery_enabled:
        env_file = Path(config.delivery_environment_file or "")
        log.add(
            "delivery.environment-file",
            env_file.is_file(),
            f"path={env_file} (content never read into any artifact)",
        )
        values, error = environment_file_values(config)
        missing = [
            name for name in _production_secret_reference_names(config) if not values.get(name)
        ]
        if error is not None:
            log.add_marker(
                "delivery.secret-reference",
                MANUAL_SECRET_REFERENCE_REQUIRED,
                f"cannot read {env_file}: {error}; create the file with the "
                f"referenced values ({', '.join(_production_secret_reference_names(config))})",
            )
        elif missing:
            log.add_marker(
                "delivery.secret-reference",
                MANUAL_SECRET_REFERENCE_REQUIRED,
                f"{env_file} exists but does not define: {', '.join(missing)}",
            )
        else:
            log.add(
                "delivery.secret-reference",
                True,
                "every referenced secret resolves from the typed environment file "
                "(values not shown)",
            )
    else:
        log.add(
            "delivery",
            True,
            "notification disabled (monitoring-only production deployment)",
        )

    secrets = resolvable_secret_values(config)
    tracked = _tracked_files_without_secrets(runner, secrets)
    log.add(
        "secrets.tracked-files-clean",
        bool(tracked["clean"]),
        json.dumps(tracked, ensure_ascii=False),
    )

    reference_verify = _systemd_analyze_verify(
        (
            ROOT / "deploy/monitoring/turtle-value-monitor.service",
            ROOT / "deploy/monitoring/turtle-value-monitor.timer",
        ),
        runner=runner,
    )
    log.add(
        "systemd.reference-units-verify",
        reference_verify.ok,
        _bounded(reference_verify.stderr or "ok", 400),
    )

    if config.snapshot_path is None:
        log.add_marker(
            "surface.snapshot",
            acceptance.MANUAL_OWNER_INPUT_REQUIRED,
            "no snapshot_path configured; the D3 read-only check will be skipped",
        )
    elif Path(config.snapshot_path).is_file():
        log.add("surface.snapshot", True, config.snapshot_path)
    else:
        log.add("surface.snapshot", False, f"snapshot missing: {config.snapshot_path}")

    lock = probe_lock_visibility(config, Path(config.runner_root), runner=runner)
    if lock["proven"] is True:
        log.add("lock.visibility", True, json.dumps(lock["steps"], ensure_ascii=False))
    else:
        log.add(
            "lock.visibility",
            False,
            json.dumps(lock, ensure_ascii=False),
            marker=DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN,
        )

    payload = {
        "head_sha": head_sha,
        "topology": topology,
        "checks": log.checks,
        "green": not log.failed,
        "markers": [item["marker"] for item in log.checks if item["marker"] is not None],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not log.failed else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Gate (same mandatory deterministic gate, bound to the production root)
# ---------------------------------------------------------------------------


def cmd_gate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    records: list[dict[str, object]] = []
    green = True
    for name, argv, extra_env in gate_commands(args.python):
        env = dict(os.environ)
        env.update(extra_env)
        outcome = run_command(argv, runner=runner, cwd=ROOT, env=env, timeout=args.timeout)
        record: dict[str, object] = {
            "name": name,
            "argv": list(argv),
            "returncode": outcome.returncode,
            "timed_out": outcome.timed_out,
            "stdout_tail": _bounded(outcome.stdout, 2000),
            "stderr_tail": _bounded(outcome.stderr, 2000),
        }
        records.append(record)
        if not outcome.ok:
            green = False
            if args.fail_fast:
                break
    artifact = {
        "head_sha": acceptance._git_head(ROOT, runner),
        "working_tree_clean": acceptance._git_clean(ROOT, runner),
        "green": green,
        "commands": records,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(config.gate_artifact_path, canonical_json_bytes(artifact) + b"\n")
    print(
        json.dumps(
            {
                "gate": "GREEN" if green else "RED",
                "head_sha": artifact["head_sha"],
                "working_tree_clean": artifact["working_tree_clean"],
                "artifact": str(config.gate_artifact_path),
                "failures": [
                    record["name"]
                    for record in records
                    if int(record["returncode"]) != 0 or record["timed_out"]
                ],
            },
            indent=2,
        )
    )
    return EXIT_OK if green else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Render (deterministic material under the private production root)
# ---------------------------------------------------------------------------


def cmd_render(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    output_dir = config.systemd_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if config.delivery_enabled:
        env_file = Path(config.delivery_environment_file or "")
        if not env_file.is_file():
            raise ManualBoundary(
                MANUAL_SECRET_REFERENCE_REQUIRED,
                stopped_after=(
                    "render: delivery is enabled but the typed local credential "
                    f"source {env_file} does not exist; the rendered unit would "
                    "reference a required EnvironmentFile that cannot load"
                ),
                human_action=(
                    f"create {env_file} (mode 0600, owner-only) containing the "
                    f"referenced values: "
                    f"{', '.join(_production_secret_reference_names(config))}. "
                    "Do not paste any value into chat, Git or documents"
                ),
                secret_boundary=(
                    "the environment file lives only in the ignored private root; "
                    "its values are never rendered, committed, logged or projected"
                ),
                resume_command=(
                    f"{Path(sys.argv[0]).name} render --production-config "
                    f"{args.production_config}"
                ),
                machine_verifiable_success=(
                    "render exits 0, the unit carries exactly the EnvironmentFile "
                    "path, and the file defines every referenced name (checked "
                    "without printing values)"
                ),
                remaining_unverified=(
                    "production notification delivery and post-restart credential "
                    "resolvability for the service identity"
                ),
            )

    runner_config_bytes = desired_runner_config_bytes(config)
    project_config_bytes = desired_project_config_bytes(config)
    _atomic_write(config.runner_config_path, runner_config_bytes)
    _atomic_write(config.project_config_path, project_config_bytes)
    RunnerConfigV1.model_validate(json.loads(runner_config_bytes.decode("utf-8")))
    load_project_config(config.project_config_path)

    desired_units = desired_unit_bytes(config)
    written: list[dict[str, object]] = []
    for name, content in desired_units.items():
        path = output_dir / name
        _atomic_write(path, content)
        written.append(
            {"path": str(path), "sha256": _sha256_bytes(content), "bytes": len(content)}
        )
    verify = _systemd_analyze_verify(
        (output_dir / config.service_unit_name, output_dir / config.timer_unit_name),
        runner=runner,
    )
    destination = systemd_unit_destination_dir(config)
    install_commands = (
        [
            [
                "sudo",
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0644",
                str(output_dir / config.service_unit_name),
                str(destination / config.service_unit_name),
            ],
            [
                "sudo",
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0644",
                str(output_dir / config.timer_unit_name),
                str(destination / config.timer_unit_name),
            ],
            ["sudo", "systemctl", "daemon-reload"],
            ["sudo", "systemctl", "enable", config.timer_unit_name],
        ]
        if config.scope == "system"
        else [
            [
                "install",
                "-m",
                "0644",
                str(output_dir / config.service_unit_name),
                str(destination / config.service_unit_name),
            ],
            [
                "install",
                "-m",
                "0644",
                str(output_dir / config.timer_unit_name),
                str(destination / config.timer_unit_name),
            ],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", config.timer_unit_name],
        ]
    )
    plan = {
        "scope": config.scope,
        "service_user": config.service_user,
        "on_calendar": config.on_calendar,
        "unit_files": written,
        "runner_config": {
            "path": str(config.runner_config_path),
            "sha256": _sha256_bytes(runner_config_bytes),
        },
        "project_config": {
            "path": str(config.project_config_path),
            "sha256": _sha256_bytes(project_config_bytes),
        },
        "destinations": [
            str(destination / config.service_unit_name),
            str(destination / config.timer_unit_name),
        ],
        "delivery_environment_file": config.delivery_environment_file
        if config.delivery_enabled
        else None,
        "verify": _outcome_public(verify),
        "install_commands": install_commands,
        "activation_note": "apply enables the timer without starting it; activation is explicit",
        "contains_secrets": False,
        "system_mutation_performed": False,
    }
    _atomic_write(output_dir / "render-plan.json", canonical_json_bytes(plan) + b"\n")
    print(json.dumps(plan, indent=2))
    if not verify.ok:
        print("systemd-analyze verify failed on the rendered units", file=sys.stderr)
        return EXIT_FAIL_CLOSED
    return EXIT_OK


# ---------------------------------------------------------------------------
# Apply / converge (idempotent; never starts recurring work)
# ---------------------------------------------------------------------------


def _install_argv(config: ProductionConfigV1, source: Path, target: Path) -> tuple[str, ...]:
    if config.scope == "user":
        return ("install", "-m", "0644", str(source), str(target))
    return (
        "sudo",
        "install",
        "-o",
        "root",
        "-g",
        "root",
        "-m",
        "0644",
        str(source),
        str(target),
    )


def cmd_apply(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    output_dir = config.systemd_output_dir
    desired_units = desired_unit_bytes(config)
    for name in desired_units:
        if not (output_dir / name).is_file():
            raise AcceptanceError(f"rendered unit missing: {output_dir / name}; run render first")
    # The rendered bytes must equal the desired bytes for this configuration.
    for name, desired in desired_units.items():
        rendered = (output_dir / name).read_bytes()
        if rendered != desired:
            raise AcceptanceError(
                f"rendered unit {name} does not match the current configuration; rerun render"
            )

    destination = systemd_unit_destination_dir(config)
    if not _systemd_privilege_available(config, runner=runner):
        raise ManualBoundary(
            MANUAL_SUDO_INSTALL_REQUIRED,
            stopped_after=(
                f"rendered and verified units exist at {output_dir}; "
                "non-interactive installation privilege for scope=system is "
                "unavailable (this process is not root and `sudo -n true` fails)"
            ),
            human_action=(
                "run the exact install/enable commands from "
                f"{output_dir / 'render-plan.json'} field install_commands as the "
                "owner (four commands: two `sudo install`, `sudo systemctl "
                f"daemon-reload`, `sudo systemctl enable {config.timer_unit_name}`)"
            ),
            secret_boundary=(
                "none of the unit files or commands carries a credential; do not "
                "add environment files with secrets to the units"
            ),
            resume_command=_resume_command(args.production_config, "apply"),
            machine_verifiable_success=(
                f"`{_resume_command(args.production_config, 'verify')}` "
                "exits 0: installed file hashes equal "
                "the rendered hashes, `systemctl show` reports the timer "
                "UnitFileState=enabled, and the effective ExecStart equals the "
                "rendered command"
            ),
            remaining_unverified=(
                "systemd-scheduled unattended production execution at the "
                "configured cadence on the system bus"
            ),
        )

    actions: list[dict[str, object]] = []
    for name, desired in desired_units.items():
        source = output_dir / name
        target = destination / name
        current = target.read_bytes() if target.is_file() else None
        if current == desired:
            actions.append({"resource": f"unit-file:{name}", "action": "unchanged"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        outcome = run_command(_install_argv(config, source, target), runner=runner)
        if not outcome.ok:
            print(json.dumps({"applied": False, "actions": actions}, indent=2))
            return EXIT_FAIL_CLOSED
        if not target.is_file() or target.read_bytes() != desired:
            raise AcceptanceError(
                f"install reported success but {target} is missing or diverged"
            )
        actions.append(
            {
                "resource": f"unit-file:{name}",
                "action": "modified" if current is not None else "installed",
            }
        )
    reload = run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
    if not reload.ok:
        print(json.dumps({"applied": False, "actions": actions}, indent=2))
        return EXIT_FAIL_CLOSED
    actions.append({"resource": "daemon-reload", "action": "performed"})

    timer_state = _systemctl_show(
        config, config.timer_unit_name, ("UnitFileState",), runner
    ).get("UnitFileState", "")
    if timer_state != "enabled":
        # Enable only; activation (start) stays a separate explicit command.
        enable = run_command(
            (*systemctl_prefix(config), "enable", config.timer_unit_name), runner=runner
        )
        if not enable.ok:
            print(json.dumps({"applied": False, "actions": actions}, indent=2))
            return EXIT_FAIL_CLOSED
        actions.append({"resource": "timer-enable", "action": "enabled"})
    else:
        actions.append({"resource": "timer-enable", "action": "unchanged"})

    linger = ensure_linger(config, runner=runner)
    actions.append({"resource": "linger", "action": linger.get("action", "not-applicable")})

    effective = _effective_state(config, runner)
    converged = effective["units_match"] is True and effective["timer_enabled"] is True
    record = {
        "applied": bool(converged),
        "scope": config.scope,
        "destination": str(destination),
        "actions": actions,
        "linger": linger,
        "effective": effective,
        "applied_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(output_dir / "apply-record.json", canonical_json_bytes(record) + b"\n")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return EXIT_OK if converged else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Effective-state inspection
# ---------------------------------------------------------------------------


def _effective_state(
    config: ProductionConfigV1, runner: CommandRunner = _default_runner
) -> dict[str, object]:
    destination = systemd_unit_destination_dir(config)
    desired_units = desired_unit_bytes(config)
    units: dict[str, object] = {}
    units_match = True
    for name, desired in desired_units.items():
        installed = destination / name
        if not installed.is_file():
            units[name] = {"installed": False, "sha256": None, "matches_desired": False}
            units_match = False
            continue
        content = installed.read_bytes()
        matches = content == desired
        units_match = units_match and matches
        units[name] = {
            "installed": True,
            "sha256": _sha256_bytes(content),
            "desired_sha256": _sha256_bytes(desired),
            "matches_desired": matches,
        }
    timer_props = _systemctl_show(
        config,
        config.timer_unit_name,
        (
            "ActiveState",
            "UnitFileState",
            "Persistent",
            "LastTriggerUSec",
            "NextElapseUSecRealtime",
        ),
        runner,
    )
    service_props = _systemctl_show(
        config,
        config.service_unit_name,
        ("ExecStart", "WorkingDirectory", "User", "Result", "ExecMainStatus"),
        runner,
    )
    return {
        "units": units,
        "units_match": units_match,
        "timer_properties": timer_props,
        "timer_enabled": timer_props.get("UnitFileState") == "enabled",
        "timer_active": timer_props.get("ActiveState") == "active",
        "service_properties": service_props,
    }


def cmd_verify(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    checks = CheckLog()
    state = _effective_state(config, runner)
    for name, unit_state in state["units"].items():  # type: ignore[union-attr]
        checks.add(
            f"install.{name}",
            bool(unit_state.get("matches_desired")),  # type: ignore[union-attr]
            json.dumps(unit_state, ensure_ascii=False),
        )
    expected_exec = (
        f"{config.python_executable} -m turtle_value_engine watch unattended-notify "
        f"--runner-config {config.runner_config_path.resolve()}"
        if config.delivery_enabled
        else f"{config.python_executable} -m turtle_value_engine watch unattended-run "
        f"--runner-config {config.runner_config_path.resolve()}"
    )
    exec_start = str(state["service_properties"].get("ExecStart", ""))  # type: ignore[union-attr]
    checks.add("service.effective-execstart", expected_exec in exec_start, exec_start[:400])
    working_directory = str(
        state["service_properties"].get("WorkingDirectory", "")  # type: ignore[union-attr]
    )
    checks.add(
        "service.effective-workingdirectory",
        working_directory == config.working_directory,
        working_directory,
    )
    timer_props: dict[str, str] = state["timer_properties"]  # type: ignore[assignment]
    checks.add(
        "timer.enabled", timer_props.get("UnitFileState") == "enabled", str(timer_props)
    )
    checks.add(
        "timer.persistent",
        timer_props.get("Persistent", "").lower() == "yes",
        f"Persistent={timer_props.get('Persistent', '')}",
    )
    if args.expect_active:
        checks.add(
            "timer.active", timer_props.get("ActiveState") == "active", str(timer_props)
        )
        checks.add(
            "timer.next-trigger",
            bool(timer_props.get("NextElapseUSecRealtime", "").strip()),
            f"NextElapseUSecRealtime={timer_props.get('NextElapseUSecRealtime', '')}",
        )
    if config.scope == "user":
        user = config.service_user or getpass_user()
        linger = linger_state(user, runner)
        checks.add("linger", linger == "yes", f"Linger={linger or 'unknown'} for {user}")

    status = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            config.runner_root,
            "--runner-id",
            config.runner_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    runner_state: dict[str, object] | None = None
    if status.ok:
        try:
            runner_state = json.loads(status.stdout)
        except json.JSONDecodeError:
            runner_state = None
    if isinstance(runner_state, dict):
        latest = None
        for item in runner_state.get("runners", []):  # type: ignore[union-attr]
            if item.get("runner_id") == config.runner_id and item.get("latest") is not None:
                latest = item["latest"]
        checks.add(
            "runner.latest-receipt",
            latest is not None,
            "none" if latest is None else f"activation_id={latest.get('activation_id')}",
        )
    else:
        checks.add("runner.latest-receipt", False, _bounded(status.stderr, 400))

    journal_argv = (
        (
            "journalctl",
            "--user",
            "-u",
            config.service_unit_name,
            "-n",
            "40",
            "--no-pager",
            "-o",
            "cat",
        )
        if config.scope == "user"
        else (
            "journalctl",
            "-u",
            config.service_unit_name,
            "-n",
            "40",
            "--no-pager",
            "-o",
            "cat",
        )
    )
    journal = run_command(journal_argv, runner=runner)
    redacted_journal = redact_text(
        _bounded(journal.stdout, 6000), resolvable_secret_values(config)
    )
    checks.add("service.journal", journal.returncode in (0, 1), redacted_journal)

    payload = {
        "checks": checks.checks,
        "green": not checks.failed,
        "effective_state": state,
        "runner_state": runner_state,
        "journal_redacted": redacted_journal,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(
        config.systemd_output_dir / "verify-record.json", canonical_json_bytes(payload) + b"\n"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not checks.failed else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Explicit activation / safe deactivation
# ---------------------------------------------------------------------------


def _require_applied(config: ProductionConfigV1) -> dict[str, object]:
    path = config.systemd_output_dir / "apply-record.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"no readable apply record ({path}); run apply first: {exc}")
    if record.get("applied") is not True:
        raise AcceptanceError("apply record does not record a converged apply; run apply first")
    return record


def cmd_activate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    _require_applied(config)
    state = _systemctl_show(config, config.timer_unit_name, ("ActiveState",), runner)
    started = False
    if state.get("ActiveState") != "active":
        start = run_command(
            (*systemctl_prefix(config), "start", config.timer_unit_name), runner=runner
        )
        if not start.ok:
            print(
                json.dumps({"activated": False, "start": _outcome_public(start)}, indent=2)
            )
            return EXIT_FAIL_CLOSED
        started = True
    props = _systemctl_show(
        config,
        config.timer_unit_name,
        ("ActiveState", "UnitFileState", "NextElapseUSecRealtime"),
        runner,
    )
    activated = (
        props.get("ActiveState") == "active"
        and props.get("UnitFileState") == "enabled"
        and bool(props.get("NextElapseUSecRealtime", "").strip())
    )
    record = {
        "activated": bool(activated),
        "started_by_activate": started,
        "timer_properties": props,
        "activated_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(
        config.systemd_output_dir / "activation-record.json", canonical_json_bytes(record) + b"\n"
    )
    print(json.dumps(record, indent=2))
    return EXIT_OK if activated else EXIT_FAIL_CLOSED


def cmd_deactivate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    if not _systemd_privilege_available(config, runner=runner):
        raise AcceptanceError("insufficient privilege to disable the production timer")
    props_before = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState", "UnitFileState"), runner
    )
    disable = run_command(
        (*systemctl_prefix(config), "disable", "--now", config.timer_unit_name), runner=runner
    )
    props_after = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState", "UnitFileState"), runner
    )
    record = {
        "deactivated": bool(
            disable.ok
            and props_after.get("ActiveState") != "active"
            and props_after.get("UnitFileState") == "disabled"
        ),
        "idempotent_rerun_ok": True,
        "before": props_before,
        "records": _outcome_public(disable),
        "after": props_after,
        "units_left_installed": not args.remove_units,
        "deactivated_at": datetime.now(UTC).isoformat(),
    }
    if args.remove_units:
        destination = systemd_unit_destination_dir(config)
        removals: list[str] = []
        for name in (config.service_unit_name, config.timer_unit_name):
            target = destination / name
            if target.is_file():
                target.unlink()
                removals.append(str(target))
        run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
        record["removed_unit_files"] = removals
    _atomic_write(
        config.systemd_output_dir / "deactivation-record.json",
        canonical_json_bytes(record) + b"\n",
    )
    print(json.dumps(record, indent=2))
    return EXIT_OK if record["deactivated"] else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Bounded live production proof
# ---------------------------------------------------------------------------


def _unattended_latest(
    config: ProductionConfigV1, runner: CommandRunner
) -> dict[str, object] | None:
    outcome = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            config.runner_root,
            "--runner-id",
            config.runner_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    if not outcome.ok:
        return None
    try:
        payload = json.loads(outcome.stdout)
    except json.JSONDecodeError:
        return None
    for item in payload.get("runners", []):
        if item.get("runner_id") == config.runner_id:
            return item
    return None


def _service_wake(
    config: ProductionConfigV1, runner: CommandRunner, *, wait_seconds: float
) -> dict[str, object]:
    """One bounded immediate service firing through the real unit."""

    initial = _systemctl_show(
        config, config.service_unit_name, ("ExecMainStartTimestamp",), runner
    ).get("ExecMainStartTimestamp", "")
    start = run_command(
        (*systemctl_prefix(config), "start", config.service_unit_name), runner=runner
    )
    if not start.ok:
        return {"ok": False, "stage": "systemctl-start", "outcome": _outcome_public(start)}
    deadline = time.monotonic() + wait_seconds
    final_start = initial
    completed = False
    while time.monotonic() < deadline:
        props = _systemctl_show(
            config,
            config.service_unit_name,
            ("ExecMainStartTimestamp", "ActiveState", "Result", "ExecMainStatus"),
            runner,
        )
        if props.get("ExecMainStartTimestamp", "") != initial and initial != "":
            final_start = props.get("ExecMainStartTimestamp", "")
        if initial == "" and props.get("ExecMainStartTimestamp", ""):
            final_start = props.get("ExecMainStartTimestamp", "")
        if props.get("ActiveState") == "inactive" and props.get("Result", ""):
            completed = True
            result = props
            break
        time.sleep(0.5)
    else:
        result = _systemctl_show(
            config, config.service_unit_name, ("Result", "ExecMainStatus"), runner
        )
    journal_argv = (
        (
            "journalctl",
            "--user",
            "-u",
            config.service_unit_name,
            "-n",
            "20",
            "--no-pager",
            "-o",
            "cat",
        )
        if config.scope == "user"
        else ("journalctl", "-u", config.service_unit_name, "-n", "20", "--no-pager", "-o", "cat")
    )
    journal = redact_text(
        _bounded(run_command(journal_argv, runner=runner).stdout, 4000),
        resolvable_secret_values(config),
    )
    return {
        "ok": bool(
            completed
            and final_start
            and result.get("Result") == "success"
            and result.get("ExecMainStatus") in {"0", "3"}
        ),
        "exec_main_start_timestamp": final_start,
        "service_result": dict(result),
        "journal_redacted": journal,
        "classification_seen": "COMPLETED_" in journal,
    }


def _acceptance_roots_immutability(
    before: Mapping[str, tuple[str, int]]
) -> dict[str, object]:
    roots = {
        "phase6e": Path(ROOT / ".tve-private" / "monitoring" / "phase6e"),
    }
    after = {
        name: content_tree_hash(path) if path.exists() else ("absent", 0)
        for name, path in roots.items()
    }
    unchanged = all(name in before and after[name] == before[name] for name in roots)
    return {
        "roots": {
            name: {"before": list(before.get(name, ())), "after": list(after[name])}
            for name in roots
        },
        "ok": unchanged,
        "unchanged": unchanged,
    }


def _d3_readonly_section(
    config: ProductionConfigV1,
    runner: CommandRunner,
    *,
    monitored_tree_before: tuple[str, int],
) -> dict[str, object]:
    if config.snapshot_path is None or not Path(config.snapshot_path).is_file():
        return {
            "ok": False,
            "skipped": True,
            "reason": f"validated surface snapshot missing ({config.snapshot_path})",
        }
    import urllib.error
    import urllib.request

    server = subprocess.Popen(
        [
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "surface",
            "serve",
            "--snapshot",
            str(Path(config.snapshot_path).resolve()),
            "--port",
            str(config.surface_port),
            "--monitoring-runner-config",
            str(config.runner_config_path.resolve()),
            "--monitoring-project-config",
            str(config.project_config_path.resolve()),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )

    def request(method: str, data: bytes | None = None) -> tuple[int, bytes]:
        url = f"http://127.0.0.1:{config.surface_port}/v1/monitoring/operations"
        req = urllib.request.Request(url, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    try:
        deadline = time.monotonic() + 30
        ready = False
        import socket as socket_module

        while time.monotonic() < deadline:
            try:
                with socket_module.create_connection(
                    ("127.0.0.1", config.surface_port), timeout=1
                ):
                    ready = True
                    break
            except OSError:
                time.sleep(0.2)
        if not ready:
            return {"ok": False, "reason": "surface server did not listen"}
        status_code, body = request("GET")
        for _ in range(3):
            request("GET")
        mutations = {
            method: request(method, b"{}")[0]
            for method in ("POST", "PUT", "PATCH", "DELETE")
        }
        monitored_tree_after = content_tree_hash(_monitored_root(config))
        secrets = resolvable_secret_values(config)
        payload_text = body.decode("utf-8", errors="replace")
        secret_hits = scan_bytes_for_secrets(body, secrets)
        path_leaks = [
            item
            for item in (
                config.production_root,
                config.project_config_path,
                config.runner_config_path,
                "holder_token",
            )
            if item and item in payload_text
        ]
        ok = (
            status_code == 200
            and all(code == 405 for code in mutations.values())
            and monitored_tree_after == monitored_tree_before
            and not secret_hits
            and not path_leaks
        )
        return {
            "ok": bool(ok),
            "http_status": status_code,
            "mutation_methods": mutations,
            "mutations_rejected": all(code == 405 for code in mutations.values()),
            "monitored_tree_unchanged": monitored_tree_after == monitored_tree_before,
            "secret_scan_hits": secret_hits,
            "path_leaks": path_leaks,
        }
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)


def _monitored_root(config: ProductionConfigV1) -> Path:
    """One parent covering every production runtime root (for tree hashing)."""

    roots = [
        Path(config.monitoring_workspace_root),
        Path(config.reanalysis_job_root),
        Path(config.cycle_store_root),
        Path(config.runner_root),
        Path(config.cache_dir),
        Path(config.delivery_root),
    ]
    common = roots[0]
    for path in roots[1:]:
        common = Path(os.path.commonpath((str(common), str(path))))
    return common


def _delivery_section(
    config: ProductionConfigV1,
    runner: CommandRunner,
    activation_id: str,
    *,
    production_config_path: str | Path,
) -> dict[str, object]:
    """Optional production delivery proof (enabled configurations only)."""

    values, error = environment_file_values(config)
    needed = _production_secret_reference_names(config)
    if error is not None or any(not values.get(name) for name in needed):
        missing = [name for name in needed if not values.get(name)]
        marker = ManualBoundary(
            MANUAL_SECRET_REFERENCE_REQUIRED,
            stopped_after=(
                "live-proof delivery step: delivery is enabled but the typed "
                "environment file does not resolve every referenced secret "
                f"({'missing: ' + ', '.join(missing) if missing else error})"
            ),
            human_action=(
                f"fill {config.delivery_environment_file} with the referenced "
                f"values ({', '.join(needed)}); never paste values into chat or Git"
            ),
            secret_boundary=(
                "values stay in the ignored private environment file and in "
                "process memory only"
            ),
            resume_command=_resume_command(production_config_path, "live-proof"),
            machine_verifiable_success=(
                "`tve watch deliver ... --network allow` returns DELIVERED (or NOOP "
                "with no alert outbox), delivery-status reports pointer CURRENT, and "
                "repeating the identity authorizes zero additional dispatch slots"
            ),
            remaining_unverified=(
                "production notification delivery to the owner destination and its "
                "durable accounting"
            ),
        )
        return {"ok": False, "skipped": True, "marker_payload": marker.payload}

    def deliver() -> tuple[CommandOutcome, dict[str, object] | None]:
        outcome = run_command(
            (
                config.python_executable,
                "-m",
                "turtle_value_engine",
                "watch",
                "deliver",
                "--runner-config",
                str(config.runner_config_path),
                "--project-config",
                str(config.project_config_path),
                "--activation-id",
                activation_id,
                "--network",
                "allow",
            ),
            runner=runner,
            cwd=ROOT,
            timeout=180,
        )
        try:
            payload = json.loads(outcome.stdout) if outcome.stdout.strip() else None
        except json.JSONDecodeError:
            payload = None
        return outcome, payload

    first_outcome, first = deliver()
    if first_outcome.returncode != 0 or first is None or first.get("classification") not in {
        "DELIVERED",
        "NOOP",
    }:
        return {"ok": False, "first": _outcome_public(first_outcome), "payload": first}
    if first.get("classification") == "NOOP":
        return {
            "ok": True,
            "classification": "NOOP",
            "note": "terminal activation carries no alert outbox; zero requests",
        }
    delivery_id = str(first.get("delivery_id"))
    second_outcome, second = deliver()
    duplicate_free = (
        second is not None
        and second.get("reused") is True
        and second.get("http_requests") == 0
    )
    return {
        "ok": bool(duplicate_free),
        "delivery_id": delivery_id,
        "first_classification": first.get("classification"),
        "repeat": {
            "reused": None if second is None else second.get("reused"),
            "http_requests": None if second is None else second.get("http_requests"),
        },
    }


def cmd_live_proof(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    _require_applied(config)
    activation_record_path = config.systemd_output_dir / "activation-record.json"
    if not activation_record_path.is_file():
        raise AcceptanceError("timer was never activated; run activate first")
    report: dict[str, object] = {"contract": REPORT_CONTRACT + ".live-proof"}

    # Acceptance/production separation: the Phase 6-E tree must not change.
    phase6e_root = ROOT / ".tve-private" / "monitoring" / "phase6e"
    acceptance_before = {
        "phase6e": content_tree_hash(phase6e_root) if phase6e_root.exists() else ("absent", 0)
    }

    monitored_before = content_tree_hash(_monitored_root(config))
    activations_before = _count_activation_files(config)

    wake = _service_wake(config, runner, wait_seconds=args.wake_wait_seconds)
    report["bounded_firing"] = wake
    report["first_firing_effects"] = {
        "activation_files_before": activations_before,
        "activation_files_after": _count_activation_files(config),
        "exactly_one_new_activation": _count_activation_files(config)
        == activations_before + 1,
        "monitored_tree_changed_by_firing": content_tree_hash(_monitored_root(config))
        != monitored_before,
    }
    latest = _unattended_latest(config, runner)
    receipt_ok = False
    receipt_identity: dict[str, object] = {}
    if latest is not None and latest.get("latest") is not None:
        latest_receipt = latest["latest"]
        receipt_identity = {
            "activation_id": latest_receipt.get("activation_id"),
            "classification": latest_receipt.get("classification"),
        }
        receipt_ok = str(latest_receipt.get("classification", "")).startswith("COMPLETED_")
    report["runner_receipt"] = {"ok": receipt_ok, **receipt_identity}

    runner_config_sha = _sha256_bytes(config.runner_config_path.read_bytes())
    desired_runner_sha = _sha256_bytes(desired_runner_config_bytes(config))
    report["configuration_identity"] = {
        "ok": runner_config_sha == desired_runner_sha,
        "runner_config_sha256": runner_config_sha,
        "desired_runner_config_sha256": desired_runner_sha,
    }

    activations_after_first = _count_activation_files(config)
    cycle_names_after_first = _cycle_store_names(config)

    replay = _service_wake(config, runner, wait_seconds=args.wake_wait_seconds)
    latest_after_replay = _unattended_latest(config, runner)
    replay_reused = (
        latest_after_replay is not None
        and latest_after_replay.get("latest") is not None
        and latest_after_replay["latest"].get("activation_id")
        == receipt_identity.get("activation_id")
        and str(latest_after_replay["latest"].get("classification", "")).startswith(
            "COMPLETED_"
        )
    )
    # Duplicate-freeness gates on identity-level facts (activation file count,
    # cycle-store file set, terminal latest identity); a byte-level tree hash
    # is recorded as evidence but never gates, because durable pointer/lease
    # rewrites are allowed to touch bytes without manufacturing work.
    report["replay"] = {
        "ok": bool(
            replay.get("ok")
            and replay_reused
            and _count_activation_files(config) == activations_after_first
            and _cycle_store_names(config) == cycle_names_after_first
        ),
        "classification_still_terminal": bool(replay_reused),
        "activation_count_unchanged": _count_activation_files(config)
        == activations_after_first,
        "cycle_store_unchanged": _cycle_store_names(config) == cycle_names_after_first,
        "monitored_tree_sha256_after_replay": content_tree_hash(_monitored_root(config))[0],
    }

    d3 = _d3_readonly_section(config, runner, monitored_tree_before=content_tree_hash(
        _monitored_root(config)
    ))
    report["d3_readonly"] = d3

    # The lock probe mutates its own probe slot under the runner root, so it
    # runs after the D3 immutability window, never inside it.
    lock = probe_lock_visibility(config, Path(config.runner_root), runner=runner)
    report["lock_visibility"] = {"ok": lock.get("proven") is True, "proven": lock.get("proven")}

    if config.delivery_enabled:
        assert receipt_identity.get("activation_id") is not None
        report["delivery"] = _delivery_section(
            config,
            runner,
            str(receipt_identity["activation_id"]),
            production_config_path=args.production_config,
        )
    else:
        report["delivery"] = {
            "ok": True,
            "enabled": False,
            "note": "monitoring-only production deployment (notification disabled)",
        }

    immutability = _acceptance_roots_immutability(acceptance_before)
    report["acceptance_roots_unchanged"] = immutability

    secrets = resolvable_secret_values(config)
    scanned: list[str] = []
    hits: list[str] = []
    for path in sorted(Path(config.production_root).rglob("*")):
        if path.is_file() and path.suffix in {".json", ".toml", ".py", ".service", ".timer"}:
            scanned.append(str(path))
            found = scan_bytes_for_secrets(path.read_bytes(), secrets)
            hits.extend(f"{path.name}:{name}" for name in found)
    report["secret_scan"] = {
        "scanned_files": scanned,
        "secret_references_checked": sorted(secrets),
        "hits": hits,
    }

    failures = [
        name
        for name, section in report.items()
        if isinstance(section, Mapping) and section.get("ok") is False
    ]
    report["failures"] = failures
    report["proved_at"] = datetime.now(UTC).isoformat()
    serialized = canonical_json_bytes(report)
    if scan_bytes_for_secrets(serialized, secrets):
        raise AcceptanceError("live-proof report would contain secret values; refusing")
    _atomic_write(config.systemd_output_dir / "live-proof-record.json", serialized + b"\n")
    print(
        json.dumps(
            {
                "failures": failures,
                "record": str(config.systemd_output_dir / "live-proof-record.json"),
            },
            indent=2,
        )
    )
    return EXIT_OK if not failures else EXIT_FAIL_CLOSED


def _count_activation_files(config: ProductionConfigV1) -> int:
    activations = Path(config.runner_root) / "activations"
    return len(list(activations.glob("*.json"))) if activations.is_dir() else 0


def _cycle_store_names(config: ProductionConfigV1) -> list[str]:
    root = Path(config.cycle_store_root)
    if not root.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


# ---------------------------------------------------------------------------
# Restart / recovery proof
# ---------------------------------------------------------------------------


def cmd_recover_proof(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    _require_applied(config)
    report: dict[str, object] = {"contract": REPORT_CONTRACT + ".recover-proof"}

    identity_before = {
        "runner_config_sha256": _sha256_bytes(config.runner_config_path.read_bytes()),
        "service_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.service_unit_name).read_bytes()
        ),
        "timer_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.timer_unit_name).read_bytes()
        ),
    }
    activations_before = _count_activation_files(config)
    cycle_names_before = _cycle_store_names(config)

    # Strongest safe manager refresh: daemon-reload then daemon-reexec.
    reload = run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
    reexec = run_command((*systemctl_prefix(config), "daemon-reexec"), runner=runner)
    report["manager_refresh"] = {
        "daemon-reload": _outcome_public(reload),
        "daemon-reexec": _outcome_public(reexec),
        "ok": reload.ok and reexec.ok,
    }

    stop = run_command((*systemctl_prefix(config), "stop", config.timer_unit_name), runner=runner)
    stopped_state = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState",), runner
    )
    start = run_command((*systemctl_prefix(config), "start", config.timer_unit_name), runner=runner)
    final_timer = _systemctl_show(
        config,
        config.timer_unit_name,
        ("ActiveState", "UnitFileState", "NextElapseUSecRealtime"),
        runner,
    )
    report["timer_stop_start"] = {
        "stop": _outcome_public(stop),
        "stopped_state": stopped_state,
        "start": _outcome_public(start),
        "final_properties": final_timer,
        "ok": bool(
            stop.ok
            and stopped_state.get("ActiveState") == "inactive"
            and start.ok
            and final_timer.get("ActiveState") == "active"
            and final_timer.get("UnitFileState") == "enabled"
        ),
    }

    wake = _service_wake(config, runner, wait_seconds=args.wake_wait_seconds)
    latest = _unattended_latest(config, runner)
    resumed_terminal = (
        latest is not None
        and latest.get("latest") is not None
        and str(latest["latest"].get("classification", "")).startswith("COMPLETED_")
    )
    report["durable_resume"] = {
        "wake": {key: wake.get(key) for key in ("ok", "service_result")},
        "latest_classification": None
        if latest is None or latest.get("latest") is None
        else latest["latest"].get("classification"),
        "ok": bool(wake.get("ok") and resumed_terminal),
        "no_duplicate_activation": _count_activation_files(config) == activations_before,
        "cycle_store_unchanged": _cycle_store_names(config) == cycle_names_before,
        "monitored_tree_sha256_after": content_tree_hash(_monitored_root(config))[0],
    }

    identity_after = {
        "runner_config_sha256": _sha256_bytes(config.runner_config_path.read_bytes()),
        "service_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.service_unit_name).read_bytes()
        ),
        "timer_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.timer_unit_name).read_bytes()
        ),
    }
    report["configuration_identity_unchanged"] = identity_before == identity_after
    report["configuration_identity"] = identity_after

    if config.scope == "user":
        user = config.service_user or getpass_user()
        report["linger_after_recovery"] = linger_state(user, runner)

    if config.delivery_enabled:
        # The service identity must resolve the typed credential source after
        # the manager refresh: run one bounded service-context check that
        # only reports presence, never values.
        needed = _production_secret_reference_names(config)
        check_source = (
            "import os, sys\n"
            f"missing = [name for name in {needed!r} if not os.environ.get(name)]\n"
            "print('MISSING:' + ','.join(missing) if missing else 'RESOLVED')\n"
            "sys.exit(0 if not missing else 3)\n"
        )
        probe = run_command(
            (
                "systemd-run",
                *(("--user",) if config.scope == "user" else ()),
                "--wait",
                "--pipe",
                "--collect",
                "-p",
                f"EnvironmentFile={config.delivery_environment_file}",
                config.python_executable,
                "-c",
                check_source,
            ),
            runner=runner,
            timeout=120,
        )
        report["credential_resolution_after_restart"] = {
            "ok": probe.ok and "RESOLVED" in probe.stdout,
            "stdout_tail": _bounded(probe.stdout, 200),
            "returncode": probe.returncode,
        }
    else:
        report["credential_resolution_after_restart"] = {
            "ok": True,
            "enabled": False,
            "note": "notification disabled; no credential to resolve",
        }

    failures = [
        name
        for name, section in report.items()
        if isinstance(section, Mapping) and section.get("ok") is False
    ]
    if report.get("configuration_identity_unchanged") is not True:
        failures.append("configuration_identity")
    report["failures"] = failures
    report["proved_at"] = datetime.now(UTC).isoformat()
    serialized = canonical_json_bytes(report)
    if scan_bytes_for_secrets(serialized, resolvable_secret_values(config)):
        raise AcceptanceError("recover-proof report would contain secret values; refusing")
    _atomic_write(config.systemd_output_dir / "recover-proof-record.json", serialized + b"\n")
    print(
        json.dumps(
            {
                "failures": failures,
                "record": str(config.systemd_output_dir / "recover-proof-record.json"),
            },
            indent=2,
        )
    )
    return EXIT_OK if not failures else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Secret-free production operations report
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    head_sha = acceptance._git_head(ROOT, runner)
    topology = classify_host_topology(runner)
    secrets = resolvable_secret_values(config)

    def _load_record(name: str) -> dict[str, object] | None:
        path = config.systemd_output_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    gate_summary: dict[str, object] | None = None
    if config.require_repo_gate:
        try:
            artifact = load_gate_artifact(config, head_sha=head_sha)
            gate_summary = {"head_sha": artifact["head_sha"], "green": artifact["green"]}
        except AcceptanceError as exc:
            gate_summary = {"green": False, "error": str(exc)}

    effective = _effective_state(config, runner)
    linger_facts: dict[str, object] | None = None
    if config.scope == "user":
        user = config.service_user or getpass_user()
        linger_facts = {"user": user, "linger": linger_state(user, runner)}

    markers: list[dict[str, object]] = []
    if topology["wsl2"] and not topology["windows_host_bootstrap_proven"]:
        markers.append(windows_bootstrap_marker_payload(config))

    report = {
        "contract": REPORT_CONTRACT,
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation": {
            "head_sha": head_sha,
            "working_tree_clean": acceptance._git_clean(ROOT, runner),
            "gate": gate_summary,
        },
        "host": topology,
        "deployment": {
            "scope": config.scope,
            "service_identity": config.service_identity,
            "unit_base_name": config.unit_base_name,
            "on_calendar": config.on_calendar,
            "randomized_delay_sec": config.randomized_delay_sec,
            "network_policy": "explicit-opt-in" if config.network_allowed else "offline-replay",
            "window_days": config.window_days,
        },
        "configuration": {
            "runner_id": config.runner_id,
            "watchlist_path": config.watchlist_path,
            "runner_config_sha256": _sha256_bytes(config.runner_config_path.read_bytes())
            if config.runner_config_path.is_file()
            else None,
            "desired_runner_config_sha256": _sha256_bytes(desired_runner_config_bytes(config)),
            "delivery_enabled": config.delivery_enabled,
            "delivery_transport": config.delivery_transport if config.delivery_enabled else None,
        },
        "desired_effective_units": effective,
        "linger": linger_facts,
        "records": {
            "apply": _load_record("apply-record.json"),
            "activation": _load_record("activation-record.json"),
            "verify": _load_record("verify-record.json"),
            "live_proof": _load_record("live-proof-record.json"),
            "recover_proof": _load_record("recover-proof-record.json"),
            "deactivation": _load_record("deactivation-record.json"),
        },
        "markers": markers,
    }

    failures: list[str] = []
    if gate_summary is not None and gate_summary.get("green") is not True:
        failures.append("gate")
    for record_name in ("apply", "activation", "verify", "live_proof", "recover_proof"):
        record = report["records"][record_name]  # type: ignore[index]
        if not isinstance(record, Mapping):
            failures.append(f"missing-record:{record_name}")
        elif record_name == "apply" and record.get("applied") is not True:
            failures.append("apply")
        elif record_name == "activation" and record.get("activated") is not True:
            failures.append("activation")
        elif record_name == "verify" and record.get("green") is not True:
            failures.append("verify")
        elif isinstance(record, Mapping) and record.get("failures"):
            failures.append(record_name)
    if effective.get("units_match") is not True:
        failures.append("effective-units")
    if effective.get("timer_enabled") is not True:
        failures.append("timer-enabled")
    if linger_facts is not None and linger_facts.get("linger") != "yes":
        failures.append("linger")

    # Final secret scan across every persisted production artifact.
    scanned: list[str] = []
    hits: list[str] = []
    for path in sorted(Path(config.production_root).rglob("*")):
        if path.is_file() and path.suffix in {".json", ".toml", ".service", ".timer"}:
            scanned.append(str(path))
            found = scan_bytes_for_secrets(path.read_bytes(), secrets)
            hits.extend(f"{path.name}:{name}" for name in found)
    report["secret_scan"] = {
        "scanned_files": scanned,
        "secret_references_checked": sorted(secrets),
        "hits": hits,
    }
    if hits:
        failures.append("secret-scan")

    marker_names = [item.get("marker") for item in markers]
    blocking_markers = [name for name in marker_names if name != WINDOWS_HOST_BOOTSTRAP_UNPROVEN]
    report["failures"] = sorted(set(failures))
    report["phase_state"] = (
        "PRODUCTION_DEPLOYED"
        if not failures and not blocking_markers
        else "READY_FOR_OWNER_AUTHORIZED_PHASE_6F"
    )
    # WINDOWS_HOST_BOOTSTRAP_UNPROVEN narrows the persistence claim but does
    # not block production closure on a WSL host (goal section 11).

    serialized = canonical_json_bytes(report)
    if scan_bytes_for_secrets(serialized, secrets):
        raise AcceptanceError("production report would contain secret values; refusing")
    _atomic_write(config.report_path, serialized + b"\n")
    print(
        json.dumps(
            {
                "phase_state": report["phase_state"],
                "failures": report["failures"],
                "markers": marker_names,
                "report": str(config.report_path),
            },
            indent=2,
        )
    )
    return EXIT_OK if not failures and not blocking_markers else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitoring_production_ops.py",
        description="Phase 6-F persistent owner production-operations harness",
    )
    parser.add_argument(
        "--production-config", required=True, type=Path, help="non-secret production config JSON"
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    gate = subparsers.add_parser("gate", help="run the mandatory deterministic repository gate")
    gate.add_argument("--python", default=sys.executable)
    gate.add_argument("--fail-fast", action="store_true")
    gate.add_argument("--timeout", type=float, default=1800)

    preflight = subparsers.add_parser("preflight", help="non-mutating classification/checks")
    preflight.add_argument("--skip-gate", action="store_true")
    preflight.add_argument("--require-clean-tree", action="store_true")

    subparsers.add_parser("plan", help="deterministic mutation-free convergence plan")
    subparsers.add_parser("render", help="render production units/config (private root only)")
    subparsers.add_parser("apply", help="install/enable/converge (never starts)")
    subparsers.add_parser("converge", help="alias of apply")
    subparsers.add_parser("activate", help="explicit production activation (start the timer)")
    verify = subparsers.add_parser("verify", help="verify the effective installed state")
    verify.add_argument("--expect-active", action="store_true")
    live_proof = subparsers.add_parser(
        "live-proof", help="bounded production firing/replay/D3 proof"
    )
    live_proof.add_argument("--wake-wait-seconds", type=float, default=120)
    recover = subparsers.add_parser(
        "recover-proof", help="manager refresh + durable resume proof"
    )
    recover.add_argument("--wake-wait-seconds", type=float, default=120)
    deactivate = subparsers.add_parser("deactivate", help="stop+disable the production timer")
    deactivate.add_argument(
        "--remove-units", action="store_true", help="also uninstall the unit files"
    )
    subparsers.add_parser("report", help="assemble/validate the production operations report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "gate": cmd_gate,
        "preflight": cmd_preflight,
        "plan": cmd_plan,
        "render": cmd_render,
        "apply": cmd_apply,
        "converge": cmd_apply,
        "activate": cmd_activate,
        "verify": cmd_verify,
        "live-proof": cmd_live_proof,
        "recover-proof": cmd_recover_proof,
        "deactivate": cmd_deactivate,
        "report": cmd_report,
    }
    try:
        return handlers[args.mode](args)
    except ManualBoundary as exc:
        print(json.dumps(exc.payload, indent=2))
        return EXIT_MARKER
    except AcceptanceError as exc:
        print(f"monitoring_production_ops: {exc}", file=sys.stderr)
        return EXIT_FAIL_CLOSED


if __name__ == "__main__":
    raise SystemExit(main())
