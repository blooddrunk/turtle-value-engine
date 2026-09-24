"""Phase 6-E owner live unattended acceptance harness.

Automates every machine-verifiable step of the bounded real-host acceptance
of the Phase 6 monitoring chain (6-B acquisition -> 6-A commit -> 6-C
execution -> D1 cycle -> D2A unattended runner -> D2B/R1/R2 delivery ->
D3/R1 read-only projection) so the owner never hand-edits systemd units,
collects logs manually or translates internal states into evidence.

Every mode is explicit and fail-closed:

- ``gate``       run the mandatory deterministic repository gate and persist
                 a green/red artifact bound to the current HEAD SHA;
- ``preflight``  non-mutating host/config/secret/lock-visibility checks;
- ``render``     deterministic owner-specific systemd material plus
                 ``systemd-analyze verify`` plus a redacted install plan
                 (never mutates the system);
- ``apply``      install/enable the rendered units when this process has
                 enough privilege (user scope needs none); otherwise stop at
                 ``MANUAL_SUDO_INSTALL_REQUIRED`` with the exact commands;
- ``verify``     inspect the *effective* installed state through
                 ``systemctl show`` / ``list-timers`` / bounded redacted
                 journal slices, never the templates;
- ``live-smoke`` the bounded live acceptance: isolated workspace, live
                 CNINFO window with a known disclosure, socket-guarded
                 offline replay equality, cursor-commit proof, runner
                 crash/resume/idempotency, generic webhook delivery with
                 duplicate-dispatch proof, D3 API read-only/mutation/no-
                 interference proof and a secret-free acceptance report;
- ``disable``    stop and disable the acceptance timer (artifacts remain);
- ``report``     validate and summarize the persisted acceptance report.

Secret discipline: no credential value is ever accepted from a file this
script owns, printed, or persisted.  Secret references are environment
names only; resolvable values are used solely for absent-from-output scans.
Human boundaries use precise markers with the six required items (command
before the stop, human action, secret boundary, resume command, machine-
verifiable success, remaining unverified boundary).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

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
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from turtle_value_engine.config import ProjectConfigError, load_project_config  # noqa: E402
from turtle_value_engine.monitoring.canonical import canonical_json_bytes  # noqa: E402
from turtle_value_engine.monitoring.models import WatchlistSpecV1  # noqa: E402
from turtle_value_engine.monitoring_runner.contracts import RunnerConfigV1  # noqa: E402

# ---------------------------------------------------------------------------
# Markers and exit codes
# ---------------------------------------------------------------------------

MANUAL_OWNER_INPUT_REQUIRED = "MANUAL_OWNER_INPUT_REQUIRED"
MANUAL_SECRET_REFERENCE_REQUIRED = "MANUAL_SECRET_REFERENCE_REQUIRED"
MANUAL_SUDO_INSTALL_REQUIRED = "MANUAL_SUDO_INSTALL_REQUIRED"
MANUAL_NOTIFICATION_RECEIPT_REQUIRED = "MANUAL_NOTIFICATION_RECEIPT_REQUIRED"
MANUAL_IDP_ACCEPTANCE_REQUIRED = "MANUAL_IDP_ACCEPTANCE_REQUIRED"
DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN = "DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN"

EXIT_OK = 0
EXIT_FAIL_CLOSED = 2
EXIT_MARKER = 5

PROBE_RUNNER_ID = "phase6e-lock-visibility"
REPORT_CONTRACT = "monitoring_live_acceptance_report_v1"
CONFIG_CONTRACT = "monitoring_live_acceptance_config_v1"
_LISTING_PATTERN = re.compile(r"^(SH|SZ|BJ)\d{6}$|^(HK)\d{5}$")
_UNIT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class AcceptanceError(RuntimeError):
    """A safe, fail-closed acceptance error (never carries secret values)."""


class ManualBoundary(AcceptanceError):
    """A precise human boundary with the six required disclosure items."""

    def __init__(
        self,
        marker: str,
        *,
        stopped_after: str,
        human_action: str,
        secret_boundary: str,
        resume_command: str,
        machine_verifiable_success: str,
        remaining_unverified: str,
    ) -> None:
        super().__init__(marker)
        self.marker = marker
        self.payload = {
            "marker": marker,
            "stopped_after": stopped_after,
            "human_action": human_action,
            "secret_boundary": secret_boundary,
            "resume_command": resume_command,
            "machine_verifiable_success": machine_verifiable_success,
            "remaining_unverified": remaining_unverified,
        }


# ---------------------------------------------------------------------------
# Acceptance configuration (owner inputs; non-secret by construction)
# ---------------------------------------------------------------------------


class AcceptanceConfigV1(BaseModel):
    """Explicit, non-secret owner inputs for one Phase 6-E acceptance run."""

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

    # Bounded acceptance workspace (one or two public listings, explicit
    # historical window containing a known disclosure, explicit PIT).
    acceptance_root: StrictStr = Field(min_length=1, max_length=4096)
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    listings: list[StrictStr] = Field(min_length=1, max_length=2)
    published_from: date
    published_to: date
    as_of: datetime
    snapshot_path: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
    surface_port: StrictInt = Field(default=8899, ge=1024, le=65535)

    # Delivery destination (references only).
    delivery_destination_id: StrictStr = Field(
        default="phase6e-acceptance", min_length=1, max_length=128
    )
    delivery_endpoint_env: StrictStr = Field(
        default="TVE_MONITORING_WEBHOOK_URL", min_length=1, max_length=256
    )
    delivery_auth_env: StrictStr | None = Field(
        default="TVE_MONITORING_WEBHOOK_TOKEN", min_length=1, max_length=256
    )
    # ``owner_env`` delivers to the owner-supplied endpoint reference;
    # ``local_https`` runs a harness-local HTTPS receiver (with a
    # harness-generated certificate trusted only inside the delivery
    # subprocess) when the owner reference is not resolvable.
    delivery_receiver: StrictStr = Field(
        default="local_https", pattern=r"^(owner_env|local_https)$"
    )
    local_receiver_port: StrictInt = Field(default=8871, ge=1024, le=65535)

    lease_ttl_seconds: StrictInt = Field(default=900, ge=1, le=604800)
    acquisition_limit: StrictInt = Field(default=30, ge=1, le=30)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_response_bytes: StrictInt = Field(default=524288, ge=1024, le=8388608)
    require_repo_gate: StrictBool = True

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must carry an explicit timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_config(self) -> AcceptanceConfigV1:
        if self.published_from > self.published_to:
            raise ValueError("published_from must not be after published_to")
        if (self.published_to - self.published_from).days > 31:
            raise ValueError("acceptance window must stay bounded (<= 31 days)")
        if not _UNIT_NAME_PATTERN.match(self.unit_base_name):
            raise ValueError("unit_base_name is not a valid systemd unit name fragment")
        for listing in self.listings:
            if not _LISTING_PATTERN.match(listing):
                raise ValueError(f"listing id is not canonical: {listing}")
        if self.scope == "system" and self.service_user is None:
            raise ValueError("scope=system requires an explicit service_user")
        if self.scope == "user" and self.service_user is not None:
            raise ValueError("scope=user must not pin a service_user (it runs as the owner)")
        if self.as_of.date() < self.published_to:
            raise ValueError("as_of must not precede the end of the acquisition window")
        for name in (
            "python_executable",
            "working_directory",
            "acceptance_root",
        ):
            if not Path(getattr(self, name)).is_absolute():
                raise ValueError(f"{name} must be an absolute path")
        return self

    # -- derived paths ------------------------------------------------------

    @property
    def workspace_root(self) -> Path:
        return Path(self.acceptance_root) / "workspace"

    @property
    def watchlist_path(self) -> Path:
        return Path(self.acceptance_root) / "watchlist.json"

    @property
    def runner_live_config_path(self) -> Path:
        return Path(self.acceptance_root) / "runner-live.json"

    @property
    def runner_resume_config_path(self) -> Path:
        return Path(self.acceptance_root) / "runner-resume.json"

    @property
    def project_config_path(self) -> Path:
        return Path(self.acceptance_root) / "project.toml"

    @property
    def delivery_root(self) -> Path:
        return Path(self.acceptance_root) / "delivery"

    @property
    def systemd_output_dir(self) -> Path:
        return Path(self.acceptance_root) / "systemd"

    @property
    def service_unit_name(self) -> str:
        return f"{self.unit_base_name}.service"

    @property
    def timer_unit_name(self) -> str:
        return f"{self.unit_base_name}.timer"

    @property
    def report_path(self) -> Path:
        return Path(self.acceptance_root) / "acceptance-report.json"

    @property
    def gate_artifact_path(self) -> Path:
        return Path(self.acceptance_root) / "gate.json"


def load_acceptance_config(path: str | Path) -> AcceptanceConfigV1:
    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read acceptance config {config_path}: {exc}") from exc
    try:
        config = AcceptanceConfigV1.model_validate(payload)
    except Exception as exc:
        raise AcceptanceError(f"invalid acceptance config {config_path}: {exc}") from exc
    if config.contract != CONFIG_CONTRACT:
        raise AcceptanceError(f"acceptance config {config_path} has the wrong contract")
    return config


# ---------------------------------------------------------------------------
# Command execution plumbing (injectable for deterministic tests)
# ---------------------------------------------------------------------------

CommandRunner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _default_runner(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def run_command(
    argv: Sequence[str],
    *,
    runner: CommandRunner = _default_runner,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> CommandOutcome:
    """Run one allow-listed command; secrets must never appear in ``argv``."""

    for part in argv:
        if not isinstance(part, str):
            raise AcceptanceError(f"command argument is not a string: {part!r}")
    try:
        completed = runner(
            list(argv), cwd=None if cwd is None else str(cwd), env=env, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        return CommandOutcome(tuple(argv), 124, "", str(exc or "timeout"), timed_out=True)
    except FileNotFoundError as exc:
        return CommandOutcome(tuple(argv), 127, "", f"executable not found: {exc}")
    return CommandOutcome(
        tuple(argv),
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
    )


def _bounded(text: str, limit: int = 8000) -> str:
    return (
        text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} bytes truncated]"
    )


def _outcome_public(outcome: CommandOutcome) -> dict[str, object]:
    return {
        "argv": list(outcome.argv),
        "returncode": outcome.returncode,
        "stdout": _bounded(outcome.stdout),
        "stderr": _bounded(outcome.stderr),
        "timed_out": outcome.timed_out,
    }


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def resolvable_secret_values(
    config: AcceptanceConfigV1, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Collect currently resolvable secret *values* by reference name.

    Values are used only for absence scans and redaction; they are never
    printed, persisted or hashed into any artifact.
    """

    environment = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for name in (config.delivery_endpoint_env, config.delivery_auth_env):
        if name is None:
            continue
        raw = environment.get(name, "")
        if raw.strip():
            values[name] = raw
    return values


def scan_bytes_for_secrets(data: bytes, secrets: Mapping[str, str]) -> list[str]:
    """Return the reference names whose resolved value occurs in ``data``."""

    hits: list[str] = []
    for name, value in secrets.items():
        if value and value.encode("utf-8") in data:
            hits.append(name)
    return hits


def redact_text(text: str, secrets: Mapping[str, str]) -> str:
    redacted = text
    for value in secrets.values():
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def content_tree_hash(root: Path) -> tuple[str, int]:
    """Hash the content-addressed shape of a tree (mtimes ignored)."""

    digest = hashlib.sha256()
    files = 0
    if not root.exists():
        return ("absent", 0)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_bytes(content).encode("ascii"))
        digest.update(b"\0")
        files += 1
    return (digest.hexdigest(), files)


# ---------------------------------------------------------------------------
# Deterministic repository gate
# ---------------------------------------------------------------------------

CI_BUNDLE_SENTINELS: tuple[tuple[str, str], ...] = (
    ("CLOUDFLARE_API_TOKEN", "ci-client-bundle-api-token-sentinel"),
    ("SURFACE_API_ACCESS_CLIENT_ID", "ci-client-bundle-origin-id-sentinel"),
    ("SURFACE_API_ACCESS_CLIENT_SECRET", "ci-client-bundle-origin-secret-sentinel"),
    ("TVE_DASHBOARD_ACCESS_CLIENT_ID", "ci-client-bundle-dashboard-id-sentinel"),
    ("TVE_DASHBOARD_ACCESS_CLIENT_SECRET", "ci-client-bundle-dashboard-secret-sentinel"),
)


def gate_commands(python: str) -> list[tuple[str, tuple[str, ...], dict[str, str]]]:
    """The exact mandatory deterministic gate from the Phase 6-E goal.

    The monitoring-suite glob is expanded here (no shell is involved) so the
    command the gate records is the same set of files CI's shell glob would
    select.
    """

    pnpm = "pnpm"
    monitoring_files = tuple(sorted(glob.glob("tests/test_monitoring*.py", root_dir=str(ROOT))))
    if not monitoring_files:
        raise AcceptanceError("no tests/test_monitoring*.py files found to gate")
    return [
        ("ruff", (python, "-m", "ruff", "check", "."), {}),
        (
            "config-validate",
            (
                python,
                "-m",
                "turtle_value_engine",
                "config",
                "validate",
                "--input",
                "config/project.example.toml",
            ),
            {},
        ),
        ("monitoring-suite", (python, "-m", "pytest", *monitoring_files), {}),
        ("python-suite", (python, "-m", "pytest"), {}),
        (
            "surface-openapi-check",
            (python, "scripts/export_surface_openapi.py", "--check"),
            {},
        ),
        (
            "dashboard-install",
            (pnpm, "--dir", "apps/dashboard", "install", "--frozen-lockfile"),
            {},
        ),
        ("dashboard-api-check", (pnpm, "--dir", "apps/dashboard", "api:check"), {}),
        ("dashboard-types-check", (pnpm, "--dir", "apps/dashboard", "types:check"), {}),
        ("dashboard-lint", (pnpm, "--dir", "apps/dashboard", "lint"), {}),
        ("dashboard-typecheck", (pnpm, "--dir", "apps/dashboard", "typecheck"), {}),
        ("dashboard-test", (pnpm, "--dir", "apps/dashboard", "test", "--run"), {}),
        ("dashboard-build", (pnpm, "--dir", "apps/dashboard", "build"), dict(CI_BUNDLE_SENTINELS)),
        (
            "dashboard-security-client-bundle",
            (pnpm, "--dir", "apps/dashboard", "security:client-bundle"),
            dict(CI_BUNDLE_SENTINELS),
        ),
        (
            "wrangler-strict-dry-run",
            (
                pnpm,
                "--dir",
                "apps/dashboard",
                "exec",
                "wrangler",
                "deploy",
                "--dry-run",
                "--config",
                "wrangler.jsonc",
                "--strict",
            ),
            {},
        ),
        (
            "cross-stack-smoke",
            (python, "scripts/dashboard_cross_stack_smoke.py"),
            {},
        ),
        (
            "systemd-verify-reference",
            (
                "systemd-analyze",
                "verify",
                "deploy/monitoring/turtle-value-monitor.service",
                "deploy/monitoring/turtle-value-monitor.timer",
            ),
            {},
        ),
    ]


def _git_head(cwd: Path, runner: CommandRunner) -> str:
    outcome = run_command(("git", "rev-parse", "HEAD"), runner=runner, cwd=cwd)
    if not outcome.ok:
        raise AcceptanceError("cannot resolve repository HEAD")
    return outcome.stdout.strip()


def _git_clean(cwd: Path, runner: CommandRunner) -> bool:
    outcome = run_command(("git", "status", "--porcelain"), runner=runner, cwd=cwd)
    if not outcome.ok:
        raise AcceptanceError("cannot inspect repository working tree")
    return outcome.stdout.strip() == ""


def cmd_gate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
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
        "head_sha": _git_head(ROOT, runner),
        "working_tree_clean": _git_clean(ROOT, runner),
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


def load_gate_artifact(config: AcceptanceConfigV1, *, head_sha: str) -> dict[str, object]:
    path = config.gate_artifact_path
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        gate_hint = path.parent / "acceptance-config.json"
        raise AcceptanceError(
            f"repo gate artifact missing or unreadable ({path}); run the gate "
            f"mode with --acceptance-config {gate_hint} first: {exc}"
        ) from exc
    if artifact.get("head_sha") != head_sha:
        raise AcceptanceError(
            "repo gate artifact was produced for a different HEAD SHA "
            f"({artifact.get('head_sha')} != {head_sha}); rerun the gate after the current revision"
        )
    if artifact.get("green") is not True:
        raise AcceptanceError("repo gate artifact is not green; fix the deterministic gate first")
    return artifact


# ---------------------------------------------------------------------------
# Systemd rendering
# ---------------------------------------------------------------------------


def render_service_unit(config: AcceptanceConfigV1, runner_config_path: Path) -> str:
    user_line = f"User={config.service_user}\n" if config.scope == "system" else ""
    description = (
        "turtle-value-engine Phase 6-E acceptance monitoring cycle "
        f"({config.runner_id})"
    )
    return (
        "[Unit]\n"
        f"Description={description}\n"
        "Documentation=file://"
        f"{config.working_directory}/docs/goals/phase-6-e-owner-live-unattended-acceptance.md\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "# Rendered by scripts/monitoring_live_acceptance.py from explicit non-secret\n"
        "# owner inputs.  No credential value ever appears in this unit; the runner\n"
        "# configuration it references is likewise non-secret.\n"
        f"WorkingDirectory={config.working_directory}\n"
        f"{user_line}"
        "ExecStart="
        f"{config.python_executable} -m turtle_value_engine watch unattended-run "
        f"--runner-config {runner_config_path}\n"
        "TimeoutStartSec=30min\n"
        "# Exit code 3 (LEASE_BUSY) means another live invocation owns the runner\n"
        "# lease and this invocation intentionally performed no work.\n"
        "SuccessExitStatus=3\n"
        "Nice=10\n"
    )


def render_timer_unit(config: AcceptanceConfigV1) -> str:
    return (
        "[Unit]\n"
        "Description=Schedule the turtle-value-engine Phase 6-E acceptance monitoring cycle\n"
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


def systemd_unit_destination_dir(config: AcceptanceConfigV1) -> Path:
    if config.scope == "user":
        return Path.home() / ".config" / "systemd" / "user"
    return Path("/etc/systemd/system")


def systemctl_prefix(config: AcceptanceConfigV1) -> tuple[str, ...]:
    return ("systemctl", "--user") if config.scope == "user" else ("systemctl",)


def _systemd_analyze_verify(paths: Sequence[Path], runner: CommandRunner) -> CommandOutcome:
    return run_command(("systemd-analyze", "verify", *(str(path) for path in paths)), runner=runner)


def cmd_render(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
    output_dir = config.systemd_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    service_path = output_dir / config.service_unit_name
    timer_path = output_dir / config.timer_unit_name
    runner_config_path = config.runner_live_config_path.resolve()
    service_content = render_service_unit(config, runner_config_path).encode("utf-8")
    timer_content = render_timer_unit(config).encode("utf-8")
    if not runner_config_path.is_file() and not args.allow_missing_runner_config:
        raise AcceptanceError(
            f"runner config {runner_config_path} does not exist yet; run live-smoke "
            "materialization first or pass --allow-missing-runner-config"
        )
    _atomic_write(service_path, service_content)
    _atomic_write(timer_path, timer_content)
    verify = _systemd_analyze_verify((service_path, timer_path), runner=runner)
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
                str(service_path),
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
                str(timer_path),
                str(destination / config.timer_unit_name),
            ],
            ["sudo", "systemctl", "daemon-reload"],
            ["sudo", "systemctl", "enable", "--now", config.timer_unit_name],
        ]
        if config.scope == "system"
        else [
            [
                "install",
                "-m",
                "0644",
                str(service_path),
                str(destination / config.service_unit_name),
            ],
            [
                "install",
                "-m",
                "0644",
                str(timer_path),
                str(destination / config.timer_unit_name),
            ],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", config.timer_unit_name],
        ]
    )
    plan = {
        "scope": config.scope,
        "service_user": config.service_user,
        "on_calendar": config.on_calendar,
        "files": [
            {
                "path": str(service_path),
                "sha256": _sha256_bytes(service_content),
                "bytes": len(service_content),
            },
            {
                "path": str(timer_path),
                "sha256": _sha256_bytes(timer_content),
                "bytes": len(timer_content),
            },
        ],
        "destinations": [
            str(destination / config.service_unit_name),
            str(destination / config.timer_unit_name),
        ],
        "verify": _outcome_public(verify),
        "install_commands": install_commands,
        "contains_secrets": False,
        "mutation_of_system_performed": False,
    }
    _atomic_write(output_dir / "render-plan.json", canonical_json_bytes(plan) + b"\n")
    print(json.dumps(plan, indent=2))
    if not verify.ok:
        print("systemd-analyze verify failed on the rendered units", file=sys.stderr)
        return EXIT_FAIL_CLOSED
    return EXIT_OK


# ---------------------------------------------------------------------------
# Preflight (non-mutating)
# ---------------------------------------------------------------------------

# Holder: takes the real authoritative lease via RunnerLease.held() and keeps
# it until told to release; this is the same exclusive flock a real runner
# invocation would own.
_HOLD_LOCK_SOURCE = r"""
import sys
from turtle_value_engine.monitoring_runner import RunnerLease
root, runner_id, ttl = sys.argv[1], sys.argv[2], int(sys.argv[3])
lease = RunnerLease(root, runner_id, ttl_seconds=ttl)
with lease.held() as handle:
    handle.record(None)
    print("HELD", flush=True)
    line = sys.stdin.readline()
    if line.strip() != "release":
        print("BAD_SIGNAL", flush=True)
        raise SystemExit(3)
print("RELEASED", flush=True)
"""

# Runner-context contention check: the authoritative held() path must see a
# live holder as busy, and must be able to acquire once the holder left.
_CONTEND_LOCK_SOURCE = r"""
import sys
from turtle_value_engine.monitoring_runner import RunnerLease, RunnerLeaseBusyError
root, runner_id, expect = sys.argv[1], sys.argv[2], sys.argv[3]
lease = RunnerLease(root, runner_id)
try:
    with lease.held():
        print("ACQUIRED", flush=True)
        raise SystemExit(0 if expect == "free" else 4)
except RunnerLeaseBusyError:
    print("BUSY", flush=True)
    raise SystemExit(0 if expect == "held" else 5)
"""


@dataclass(slots=True)
class CheckLog:
    checks: list[dict[str, object]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, *, marker: str | None = None) -> None:
        self.checks.append(
            {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail, "marker": marker}
        )

    def add_marker(self, name: str, marker: str, detail: str) -> None:
        self.checks.append({"name": name, "status": "MARKER", "detail": detail, "marker": marker})

    @property
    def failed(self) -> list[dict[str, object]]:
        return [item for item in self.checks if item["status"] == "FAIL"]


def probe_lock_visibility(
    config: AcceptanceConfigV1,
    runner_root: Path,
    *,
    runner: CommandRunner = _default_runner,
    python: str | None = None,
) -> dict[str, object]:
    """Prove runner and observer contexts see the same authoritative flock.

    Uses one private acceptance lease slot, a real ``RunnerLease.held()``
    holder subprocess (the authoritative runner code path), the read-only
    ``tve watch unattended-status`` CLI as the D3/status observation context,
    and a second runner-context subprocess that must classify the slot as
    busy while held and acquirable after release.  The observer never takes
    any OS lock (that is the D3-R1 passive ``/proc/locks`` probe).
    """

    python = python or config.python_executable
    slot_root = runner_root
    slot_root.mkdir(parents=True, exist_ok=True)
    steps: dict[str, object] = {}

    try:
        holder = subprocess.Popen(
            [
                python,
                "-c",
                _HOLD_LOCK_SOURCE,
                str(slot_root),
                PROBE_RUNNER_ID,
                str(config.lease_ttl_seconds),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT),
        )
    except (FileNotFoundError, OSError) as exc:
        return {
            "proven": False,
            "failure": "holder-subprocess-did-not-start",
            "holder_stderr": f"{type(exc).__name__}: {exc}",
            "steps": steps,
        }
    try:
        held_line = holder.stdout.readline() if holder.stdout else ""
        if held_line.strip() != "HELD":
            stderr = holder.stderr.read() if holder.stderr else ""
            return {
                "proven": False,
                "failure": "holder-subprocess-did-not-acquire",
                "holder_stderr": _bounded(stderr),
                "steps": steps,
            }
        observer_held = run_command(
            (
                python,
                "-m",
                "turtle_value_engine",
                "watch",
                "unattended-status",
                "--runner-root",
                str(slot_root),
                "--runner-id",
                PROBE_RUNNER_ID,
            ),
            runner=runner,
            cwd=ROOT,
            timeout=60,
        )
        try:
            observer_payload = json.loads(observer_held.stdout)
            observed_held_state = observer_payload["runners"][0]["lease"]["state"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            observed_held_state = f"UNPARSEABLE(rc={observer_held.returncode})"
        steps["observer_while_held"] = observed_held_state

        contention = run_command(
            (
                python,
                "-c",
                _CONTEND_LOCK_SOURCE,
                str(slot_root),
                PROBE_RUNNER_ID,
                "held",
            ),
            runner=runner,
            cwd=ROOT,
            timeout=60,
        )
        steps["runner_context_while_held"] = (
            contention.stdout.strip() or f"rc={contention.returncode}"
        )

        if holder.stdin:
            holder.stdin.write("release\n")
            holder.stdin.flush()
        released = holder.wait(timeout=30)
        steps["holder_exit"] = released

        observer_free = run_command(
            (
                python,
                "-m",
                "turtle_value_engine",
                "watch",
                "unattended-status",
                "--runner-root",
                str(slot_root),
                "--runner-id",
                PROBE_RUNNER_ID,
            ),
            runner=runner,
            cwd=ROOT,
            timeout=60,
        )
        try:
            observer_payload = json.loads(observer_free.stdout)
            observed_free_state = observer_payload["runners"][0]["lease"]["state"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            observed_free_state = f"UNPARSEABLE(rc={observer_free.returncode})"
        steps["observer_after_release"] = observed_free_state

        acquire_free = run_command(
            (
                python,
                "-c",
                _CONTEND_LOCK_SOURCE,
                str(slot_root),
                PROBE_RUNNER_ID,
                "free",
            ),
            runner=runner,
            cwd=ROOT,
            timeout=60,
        )
        steps["runner_context_after_release"] = (
            acquire_free.stdout.strip() or f"rc={acquire_free.returncode}"
        )

        # The observer proved LIVE while held and non-live after release,
        # and the runner context proved busy while held and acquirable after.
        proven = (
            observed_held_state == "LIVE"
            and observed_free_state in {"ABANDONED", "FREE"}
            and contention.stdout.strip() == "BUSY"
            and acquire_free.stdout.strip() == "ACQUIRED"
            and released == 0
        )
        return {
            "proven": proven,
            "failure": None if proven else "contexts-disagree",
            "steps": steps,
            "observer_acquired_lock": False,
        }
    finally:
        if holder.poll() is None:
            if holder.stdin:
                try:
                    holder.stdin.write("release\n")
                    holder.stdin.flush()
                except OSError:
                    pass
            try:
                holder.wait(timeout=10)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait(timeout=10)


def _tracked_files_without_secrets(
    runner: CommandRunner, secrets: Mapping[str, str]
) -> dict[str, object]:
    listing = run_command(("git", "ls-files", "-z"), runner=runner, cwd=ROOT)
    if not listing.ok:
        return {"clean": False, "detail": "cannot enumerate tracked files"}
    hits: list[str] = []
    checked = 0
    for raw_name in listing.stdout.split("\0"):
        if not raw_name:
            continue
        path = ROOT / raw_name
        try:
            if path.stat().st_size > 1_000_000:
                continue
            content = path.read_bytes()
        except OSError:
            continue
        checked += 1
        found = scan_bytes_for_secrets(content, secrets)
        if found:
            hits.extend(f"{raw_name}:{name}" for name in found)
    return {"clean": not hits, "detail": f"scanned {checked} tracked files", "hits": hits}


def cmd_preflight(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
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
        _bounded(
            systemd_version.stdout.splitlines()[0]
            if systemd_version.stdout
            else systemd_version.stderr,
            200,
        ),
    )
    systemd_state = run_command(("systemctl", "is-system-running"), runner=runner)
    log.add(
        "host.systemd-running",
        systemd_state.ok or systemd_state.stdout.strip() == "degraded",
        f"is-system-running={systemd_state.stdout.strip() or systemd_state.stderr.strip()}",
    )
    analyze = run_command(("systemd-analyze", "--version"), runner=runner)
    log.add(
        "host.systemd-analyze",
        analyze.ok,
        _bounded(analyze.stdout.splitlines()[0] if analyze.stdout else analyze.stderr, 200),
    )
    proc_locks = Path("/proc/locks")
    log.add(
        "host.proc-locks-readable",
        proc_locks.is_file() and os.access(proc_locks, os.R_OK),
        str(proc_locks),
    )

    head_sha = _git_head(ROOT, runner)
    tree_clean = _git_clean(ROOT, runner)
    log.add("repo.head", bool(re.fullmatch(r"[0-9a-f]{40}", head_sha)), head_sha)
    log.add(
        "repo.working-tree",
        tree_clean or not args.require_clean_tree,
        "clean"
        if tree_clean
        else "dirty (expected during active Phase 6-E work; pass --require-clean-tree to enforce)",
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
            MANUAL_OWNER_INPUT_REQUIRED,
            "repo gate check skipped by explicit flag",
        )

    # Typed configuration inputs.
    runner_live = config.runner_live_config_path
    if runner_live.is_file():
        try:
            parsed = RunnerConfigV1.model_validate(
                json.loads(runner_live.read_text(encoding="utf-8"))
            )
            log.add(
                "config.runner-live",
                True,
                f"runner_id={parsed.runner_id} network_allowed={parsed.network_allowed}",
            )
            if parsed.network_allowed:
                inside_acceptance = (
                    Path(parsed.monitoring_workspace_root)
                    .resolve()
                    .is_relative_to(Path(config.acceptance_root).resolve())
                )
                isolation_detail = (
                    "network_allowed=true is confined to the acceptance workspace"
                    if inside_acceptance
                    else "network_allowed=true outside the acceptance root is "
                    "not permitted for acceptance"
                )
                log.add("config.live-optin-isolated", inside_acceptance, isolation_detail)
        except Exception as exc:
            log.add("config.runner-live", False, f"invalid runner config: {exc}")
    else:
        log.add_marker(
            "config.runner-live",
            MANUAL_OWNER_INPUT_REQUIRED,
            f"{runner_live} not materialized yet; run live-smoke materialization (offline) first",
        )
    if config.watchlist_path.is_file():
        try:
            watchlist = WatchlistSpecV1.build(
                **json.loads(config.watchlist_path.read_text(encoding="utf-8"))
            )
            entries = [entry.listing_id for entry in watchlist.entries]
            log.add(
                "config.watchlist",
                len(watchlist.entries) <= 2,
                f"watchlist_id={watchlist.watchlist_id} entries={entries}",
            )
        except Exception as exc:
            log.add("config.watchlist", False, f"invalid watchlist: {exc}")
    else:
        log.add_marker(
            "config.watchlist",
            MANUAL_OWNER_INPUT_REQUIRED,
            f"{config.watchlist_path} not materialized yet",
        )

    # Runtime roots are private (never inside the tracked worktree outside
    # .tve-private) and writable by the current/service identity.
    root_parent = Path(config.acceptance_root)
    probe_dir = root_parent
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    acceptance_path = Path(config.acceptance_root)
    try:
        acceptance_path.relative_to(ROOT)
        inside_worktree = True
    except ValueError:
        inside_worktree = False
    private = (not inside_worktree) or ".tve-private" in acceptance_path.parts
    log.add(
        "config.roots-private-writable",
        private and os.access(probe_dir, os.W_OK | os.X_OK),
        f"acceptance_root={config.acceptance_root} writable_probe={probe_dir} "
        f"inside_worktree={inside_worktree}",
    )

    if config.project_config_path.is_file():
        try:
            project = load_project_config(config.project_config_path)
            delivery = project.monitoring.delivery
            endpoint_ref_env = (
                None if delivery.endpoint_ref is None else delivery.endpoint_ref.env
            )
            log.add(
                "config.project-delivery",
                True,
                f"enabled={delivery.enabled} destination_id={delivery.destination_id} "
                f"endpoint_ref={endpoint_ref_env}",
            )
        except ProjectConfigError as exc:
            log.add("config.project-delivery", False, str(exc))
    else:
        log.add_marker(
            "config.project-delivery",
            MANUAL_OWNER_INPUT_REQUIRED,
            "acceptance project.toml not materialized yet",
        )

    # Secret references: presence only, never values.
    secrets = resolvable_secret_values(config)
    endpoint_present = config.delivery_endpoint_env in secrets
    if endpoint_present:
        log.add(
            "secrets.delivery-endpoint",
            True,
            f"{config.delivery_endpoint_env} resolves (value not shown)",
        )
    else:
        log.add_marker(
            "secrets.delivery-endpoint",
            MANUAL_SECRET_REFERENCE_REQUIRED,
            f"{config.delivery_endpoint_env} is not resolvable in this environment; "
            f"live-smoke will use the harness-local HTTPS receiver "
            f"({config.delivery_receiver}) and record the owner-endpoint remainder",
        )
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

    snapshot = None if config.snapshot_path is None else Path(config.snapshot_path)
    if snapshot is None:
        log.add_marker(
            "surface.snapshot",
            MANUAL_OWNER_INPUT_REQUIRED,
            "no snapshot_path configured; D3 API section will be skipped",
        )
    elif snapshot.is_file():
        log.add("surface.snapshot", True, str(snapshot))
    else:
        log.add("surface.snapshot", False, f"snapshot missing: {snapshot}")

    lock = probe_lock_visibility(config, Path(config.acceptance_root) / "runner", runner=runner)
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
        "checks": log.checks,
        "green": not log.failed,
        "markers": [item["marker"] for item in log.checks if item["marker"] is not None],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not log.failed else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Apply / verify / disable
# ---------------------------------------------------------------------------


def _systemd_privilege_available(
    config: AcceptanceConfigV1, runner: CommandRunner = _default_runner
) -> bool:
    if config.scope == "user":
        return True
    if os.geteuid() == 0:
        return True
    return run_command(("sudo", "-n", "true"), runner=runner).ok


def cmd_apply(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
    output_dir = config.systemd_output_dir
    service_source = output_dir / config.service_unit_name
    timer_source = output_dir / config.timer_unit_name
    for path in (service_source, timer_source):
        if not path.is_file():
            raise AcceptanceError(f"rendered unit missing: {path}; run render first")
    destination = systemd_unit_destination_dir(config)
    if not _systemd_privilege_available(config, runner=runner):
        raise ManualBoundary(
            MANUAL_SUDO_INSTALL_REQUIRED,
            stopped_after=(
                f"rendered and verified units exist at {service_source} and {timer_source}; "
                "non-interactive installation privilege for scope=system is unavailable "
                "(this process is not root and `sudo -n true` fails)"
            ),
            human_action=(
                "run the exact install/enable commands from "
                f"{output_dir / 'render-plan.json'} field install_commands as the owner "
                "(four commands: two `sudo install`, `sudo systemctl daemon-reload`, "
                f"`sudo systemctl enable --now {config.timer_unit_name}`)"
            ),
            secret_boundary=(
                "none of the unit files or commands carries a credential; do not add "
                "environment files with secrets to the units"
            ),
            resume_command=(
                f"{Path(sys.argv[0]).name} verify --acceptance-config {args.acceptance_config}"
            ),
            machine_verifiable_success=(
                f"`{Path(sys.argv[0]).name} verify --acceptance-config {args.acceptance_config}` "
                "exits 0: installed file hashes equal the rendered hashes, "
                f"`systemctl show {config.timer_unit_name}` reports ActiveState=active and "
                "UnitFileState=enabled, and the effective ExecStart equals the rendered command"
            ),
            remaining_unverified=(
                "systemd-scheduled unattended execution at the configured cadence on the "
                "system bus (user-scope proof, if performed, does not substitute)"
            ),
        )
    records: list[dict[str, object]] = []
    for source in (service_source, timer_source):
        target = destination / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        install_argv = (
            ("install", "-m", "0644", str(source), str(target))
            if config.scope == "user"
            else (
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
        )
        outcome = run_command(install_argv, runner=runner)
        records.append(_outcome_public(outcome))
        if not outcome.ok:
            print(json.dumps({"applied": False, "records": records}, indent=2))
            return EXIT_FAIL_CLOSED
        if not target.is_file():
            # An install that reports success without producing the file is a
            # classified failure, never an unhandled crash.
            raise AcceptanceError(
                f"install reported success but {target} does not exist"
            )
        if target.read_bytes() != source.read_bytes():
            raise AcceptanceError(f"installed unit {target} does not match rendered bytes")
    reload = run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
    records.append(_outcome_public(reload))
    # Enable without starting: deterministic sequencing keeps the timer from
    # stealing the first classification (COMPLETED_NEW) from the harness.
    # `live-smoke` starts the timer explicitly in its systemd-observation
    # section; `--start-timer` opts into immediate production behaviour.
    enable_argv = (*systemctl_prefix(config), "enable", config.timer_unit_name)
    if args.start_timer:
        enable_argv = (*systemctl_prefix(config), "enable", "--now", config.timer_unit_name)
    enable = run_command(enable_argv, runner=runner)
    records.append(_outcome_public(enable))
    applied = reload.ok and enable.ok
    record = {
        "applied": applied,
        "scope": config.scope,
        "destination": str(destination),
        "records": records,
        "applied_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(output_dir / "apply-record.json", canonical_json_bytes(record) + b"\n")
    print(json.dumps(record, indent=2))
    return EXIT_OK if applied else EXIT_FAIL_CLOSED


def _systemctl_show(
    config: AcceptanceConfigV1, unit: str, properties: Sequence[str], runner: CommandRunner
) -> dict[str, str]:
    outcome = run_command(
        (
            *systemctl_prefix(config),
            "show",
            unit,
            "--no-pager",
            *(f"--property={name}" for name in properties),
        ),
        runner=runner,
    )
    values: dict[str, str] = {}
    for line in outcome.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def cmd_verify(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
    destination = systemd_unit_destination_dir(config)
    checks = CheckLog()

    installed_service = destination / config.service_unit_name
    installed_timer = destination / config.timer_unit_name
    rendered_service = config.systemd_output_dir / config.service_unit_name
    rendered_timer = config.systemd_output_dir / config.timer_unit_name
    for installed, rendered in (
        (installed_service, rendered_service),
        (installed_timer, rendered_timer),
    ):
        if not installed.is_file():
            checks.add("install.file", False, f"missing {installed}")
        else:
            match = installed.read_bytes() == rendered.read_bytes()
            digest = _sha256_bytes(installed.read_bytes())
            checks.add(
                "install.hash",
                match,
                f"{installed.name} sha256={digest} equals_rendered={match}",
            )

    service_props = _systemctl_show(
        config,
        config.service_unit_name,
        (
            "ExecStart",
            "WorkingDirectory",
            "User",
            "Result",
            "ExecMainStatus",
            "NInvocations",
            "ActiveState",
        ),
        runner,
    )
    expected_exec = (
        f"{config.python_executable} -m turtle_value_engine watch unattended-run "
        f"--runner-config {config.runner_live_config_path.resolve()}"
    )
    exec_start = service_props.get("ExecStart", "")
    checks.add(
        "service.effective-execstart",
        expected_exec in exec_start,
        f"ExecStart={exec_start[:400]}",
    )
    checks.add(
        "service.effective-workingdirectory",
        service_props.get("WorkingDirectory", "") == config.working_directory,
        f"WorkingDirectory={service_props.get('WorkingDirectory', '')}",
    )

    timer_props = _systemctl_show(
        config,
        config.timer_unit_name,
        ("ActiveState", "UnitFileState", "LastTriggerUSec", "NextElapseUSecRealtime"),
        runner,
    )
    checks.add(
        "timer.active",
        timer_props.get("ActiveState") == "active",
        json.dumps(timer_props),
    )
    checks.add(
        "timer.enabled",
        timer_props.get("UnitFileState") == "enabled",
        f"UnitFileState={timer_props.get('UnitFileState', '')}",
    )

    secrets = resolvable_secret_values(config)
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
        else ("journalctl", "-u", config.service_unit_name, "-n", "40", "--no-pager", "-o", "cat")
    )
    journal = run_command(journal_argv, runner=runner)
    redacted_journal = redact_text(_bounded(journal.stdout, 6000), secrets)
    checks.add("service.journal", journal.returncode in (0, 1), redacted_journal)

    status = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            str(Path(config.acceptance_root) / "runner"),
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    runner_state: dict[str, object] | None = None
    if status.ok:
        runner_state = json.loads(status.stdout)
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

    payload = {
        "checks": checks.checks,
        "green": not checks.failed,
        "service_properties": service_props,
        "timer_properties": timer_props,
        "journal_redacted": redacted_journal,
        "runner_state": runner_state,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(
        config.systemd_output_dir / "verify-record.json", canonical_json_bytes(payload) + b"\n"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not checks.failed else EXIT_FAIL_CLOSED


def cmd_disable(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
    if not _systemd_privilege_available(config, runner=runner):
        raise AcceptanceError("insufficient privilege to disable the acceptance timer")
    disable = run_command(
        (*systemctl_prefix(config), "disable", "--now", config.timer_unit_name), runner=runner
    )
    props = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState", "UnitFileState"), runner
    )
    payload = {
        "disabled": disable.ok and props.get("ActiveState") != "active",
        "records": _outcome_public(disable),
        "timer_properties": props,
        "disabled_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(
        config.systemd_output_dir / "disable-record.json", canonical_json_bytes(payload) + b"\n"
    )
    print(json.dumps(payload, indent=2))
    return EXIT_OK if payload["disabled"] else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Live smoke (bounded real acceptance)
# ---------------------------------------------------------------------------

# Runs the offline replay with every outbound socket path hard-blocked at
# Python level *before* the CLI executes, so a byte-identical replay proves
# zero network usage rather than trusting a flag.
_SOCKET_GUARD_SOURCE_TEMPLATE = r"""
import socket
import sys

def _blocked(*args, **kwargs):
    raise AssertionError("SOCKET_CONNECT_ATTEMPTED")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

from turtle_value_engine.cli import main

raise SystemExit(main(sys.argv[1:]))
"""

# Harness-local HTTPS webhook receiver: bounded, records a machine-readable
# receipt journal (method, path, idempotency key, body hash), never logs
# bearer tokens.
_LOCAL_RECEIVER_SOURCE = r"""
import hashlib
import json
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

certfile, keyfile, port, journal_path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        import datetime as datetime_module

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        record = {
            "received_at": datetime_module.datetime.now(
                datetime_module.UTC
            ).isoformat(),
            "method": "POST",
            "path": self.path,
            "idempotency_key": self.headers.get("Idempotency-Key"),
            "delivery_id_header": self.headers.get("X-TVE-Delivery-Id"),
            "authorization_present": bool(self.headers.get("Authorization")),
            "body_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
        }
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        payload = b'{"received": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        return

server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile, keyfile)
server.socket = context.wrap_socket(server.socket, server_side=True)
print("RECEIVER_READY", flush=True)
server.serve_forever()
"""


def _tve(
    python: str,
    *argv: str,
    runner: CommandRunner,
    cwd: Path = ROOT,
    env: Mapping[str, str] | None = None,
    timeout: float = 300,
) -> CommandOutcome:
    return run_command(
        (python, "-m", "turtle_value_engine", *argv),
        runner=runner,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )


def _materialize_workspace(config: AcceptanceConfigV1) -> dict[str, object]:
    root = Path(config.acceptance_root)
    root.mkdir(parents=True, exist_ok=True)
    watchlist = WatchlistSpecV1.build(
        watchlist_id=config.watchlist_id,
        profile_id="strict-v1",
        entries=[{"listing_id": listing} for listing in config.listings],
    )
    _atomic_write(config.watchlist_path, watchlist.canonical_bytes() + b"\n")

    def runner_config(*, network_allowed: bool, as_of: datetime) -> RunnerConfigV1:
        return RunnerConfigV1(
            runner_id=config.runner_id,
            watchlist_path=str(config.watchlist_path),
            monitoring_workspace_root=str(config.workspace_root),
            reanalysis_job_root=str(root / "reanalysis"),
            cycle_store_root=str(root / "cycles"),
            runner_root=str(root / "runner"),
            cache_dir=str(root / "provider-cache"),
            network_allowed=network_allowed,
            offline_replay=not network_allowed,
            published_from=config.published_from,
            published_to=config.published_to,
            as_of=as_of,
            acquisition_limit=config.acquisition_limit,
            timeout_seconds=config.timeout_seconds,
            max_response_bytes=config.max_response_bytes,
            lease_ttl_seconds=config.lease_ttl_seconds,
        )

    live = runner_config(network_allowed=True, as_of=config.as_of)
    resume = runner_config(network_allowed=True, as_of=config.as_of + timedelta(hours=1))
    _atomic_write(
        config.runner_live_config_path,
        live.model_dump_json(indent=2, warnings=False).encode() + b"\n",
    )
    _atomic_write(
        config.runner_resume_config_path,
        resume.model_dump_json(indent=2, warnings=False).encode() + b"\n",
    )

    delivery_root = config.delivery_root.resolve()
    project_toml = f"""# Phase 6-E acceptance-only project configuration (non-secret).
# Generated by scripts/monitoring_live_acceptance.py; isolated delivery ledger.
schema_version = 1

[project]
id = "turtle-value-engine"
environment = "private"
timezone = "Asia/Taipei"

[monitoring]
watchlist_path = "{config.watchlist_path}"
workspace_root = "{config.workspace_root}"

[monitoring.delivery]
enabled = true
transport = "webhook-v1"
destination_id = "{config.delivery_destination_id}"
delivery_root = "{delivery_root}"
endpoint_ref = {{ env = "{config.delivery_endpoint_env}" }}
receiver_idempotency_declared = false
max_attempts = 5
timeout_seconds = 10.0
backoff_base_seconds = 60
backoff_cap_seconds = 3600
max_response_bytes = 65536
"""
    if config.delivery_auth_env is not None:
        project_toml += f'auth_token_ref = {{ env = "{config.delivery_auth_env}" }}\n'
    _atomic_write(config.project_config_path, project_toml.encode("utf-8"))
    load_project_config(config.project_config_path)  # fail now if invalid

    return {
        "acceptance_root": str(root),
        "watchlist_id": watchlist.watchlist_id,
        "watchlist_content_sha256": watchlist.content_sha256,
        "listings": list(config.listings),
        "published_from": config.published_from.isoformat(),
        "published_to": config.published_to.isoformat(),
        "as_of": config.as_of.isoformat(),
        "runner_live_config": str(config.runner_live_config_path),
        "runner_resume_config": str(config.runner_resume_config_path),
    }


def _watch_status(
    config: AcceptanceConfigV1, python: str, runner: CommandRunner
) -> dict[str, object] | None:
    outcome = _tve(
        python,
        "watch",
        "status",
        "--workspace",
        str(config.workspace_root),
        "--watchlist-id",
        config.watchlist_id,
        runner=runner,
    )
    if not outcome.ok:
        return None
    try:
        return json.loads(outcome.stdout)
    except json.JSONDecodeError:
        return None


def _unattended_run(
    config: AcceptanceConfigV1, python: str, runner_config: Path, runner: CommandRunner
) -> tuple[CommandOutcome, dict[str, object] | None]:
    output_path = runner_config.with_name(runner_config.stem + "-last-run.json")
    outcome = _tve(
        python,
        "watch",
        "unattended-run",
        "--runner-config",
        str(runner_config),
        "--output",
        str(output_path),
        runner=runner,
        timeout=600,
    )
    payload = None
    if outcome.stdout.strip():
        try:
            payload = json.loads(outcome.stdout)
        except json.JSONDecodeError:
            payload = None
    return outcome, payload


def _generate_local_tls_material(directory: Path, runner: CommandRunner) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / "receiver-key.pem"
    cert = directory / "receiver-cert.pem"
    outcome = run_command(
        (
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "2",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ),
        runner=runner,
    )
    if not outcome.ok or not cert.is_file() or not key.is_file():
        raise AcceptanceError(
            f"cannot generate harness-local TLS material: openssl rc={outcome.returncode}"
        )
    return cert, key


class _LocalReceiver:
    def __init__(
        self, python: str, cert: Path, key: Path, port: int, journal: Path, runner: CommandRunner
    ) -> None:
        self._python = python
        self._runner = runner
        self._journal = journal
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("", encoding="utf-8")
        self._process = subprocess.Popen(
            [python, "-c", _LOCAL_RECEIVER_SOURCE, str(cert), str(key), str(port), str(journal)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT),
        )
        self.port = port
        ready = self._process.stdout.readline() if self._process.stdout else ""
        if ready.strip() != "RECEIVER_READY":
            self.stop()
            raise AcceptanceError("local HTTPS receiver did not become ready")

    def endpoint(self) -> str:
        return f"https://127.0.0.1:{self.port}/hook"

    def requests(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for line in self._journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def stop(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)


def _http_request(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    ca_file: Path | None = None,
    timeout: float = 30,
) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    context = None
    if ca_file is not None:
        import ssl

        context = ssl.create_default_context(cafile=str(ca_file))
    request = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _wait_for_port(port: int, timeout: float = 30.0) -> bool:
    import socket as socket_module

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket_module.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _delivery_status(
    config: AcceptanceConfigV1, python: str, delivery_id: str, runner: CommandRunner
) -> dict[str, object]:
    outcome = _tve(
        python,
        "watch",
        "delivery-status",
        "--delivery-root",
        str(config.delivery_root),
        "--delivery-id",
        delivery_id,
        runner=runner,
    )
    if not outcome.ok:
        raise AcceptanceError(
            f"delivery-status failed: rc={outcome.returncode} {_bounded(outcome.stderr, 400)}"
        )
    payload = json.loads(outcome.stdout)
    deliveries = payload.get("deliveries") if isinstance(payload, dict) else None
    if not isinstance(deliveries, list) or len(deliveries) != 1:
        raise AcceptanceError("delivery-status did not return exactly one delivery record")
    return deliveries[0]


def _marker_payload_from_exception(exc: ManualBoundary) -> dict[str, object]:
    return exc.payload


def cmd_live_smoke(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
    if args.network != "allow":
        raise AcceptanceError(
            "live-smoke requires the explicit --network allow opt-in (Phase 6-B/D2B boundary)"
        )
    python = config.python_executable
    report: dict[str, object] = {
        "contract": REPORT_CONTRACT,
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation": {},
        "host": {},
        "markers": [],
        "phase_state": None,
    }
    markers: list[dict[str, object]] = []

    def record_marker(payload: dict[str, object]) -> None:
        markers.append(payload)
        report["markers"] = markers

    # 0. Implementation identity and gate.
    head_sha = _git_head(ROOT, runner)
    report["implementation"] = {
        "head_sha": head_sha,
        "working_tree_clean": _git_clean(ROOT, runner),
    }
    if config.require_repo_gate and not args.skip_gate:
        gate = load_gate_artifact(config, head_sha=head_sha)
        report["implementation"]["gate"] = {"head_sha": gate["head_sha"], "green": gate["green"]}
    report["host"] = {
        "sys_platform": sys.platform,
        "python": python,
        "python_version": subprocess.run(
            (python, "--version"), capture_output=True, text=True
        ).stdout.strip(),
        "systemd": run_command(("systemctl", "--version"), runner=runner).stdout.splitlines()[0]
        if run_command(("systemctl", "--version"), runner=runner).ok
        else "unavailable",
        "pid1": Path("/proc/1/comm").read_text().strip()
        if Path("/proc/1/comm").is_file()
        else "unknown",
        "proc_locks_readable": os.access("/proc/locks", os.R_OK),
    }

    # Fresh-workspace policy: a consumed acceptance root must be acknowledged.
    existing_receipts = Path(config.acceptance_root) / "runner" / "receipts"
    if (
        existing_receipts.is_dir()
        and any(existing_receipts.iterdir())
        and not args.allow_existing
    ):
        raise AcceptanceError(
            f"acceptance workspace already contains terminal receipts "
            f"({existing_receipts}); archive or remove the acceptance root, "
            "or pass --allow-existing to prove reuse semantics"
        )

    # 1. Materialize the isolated acceptance workspace (typed, idempotent).
    report["workspace"] = _materialize_workspace(config)

    # 2. Lock visibility on this exact deployment topology.
    lock = probe_lock_visibility(config, Path(config.acceptance_root) / "runner", runner=runner)
    report["lock_visibility"] = lock
    if lock["proven"] is not True:
        marker = ManualBoundary(
            DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN,
            stopped_after="live-smoke lock-visibility probe on the real deployment host",
            human_action=(
                "move the runner and the D3/status observer onto one shared "
                "host/kernel view (single-host Linux/systemd), or scope a "
                "separate portability task"
            ),
            secret_boundary="none",
            resume_command=(
                f"{Path(sys.argv[0]).name} live-smoke --acceptance-config "
                f"{args.acceptance_config} --network allow"
            ),
            machine_verifiable_success=(
                "lock_visibility.proven == true with observer LIVE while held "
                "and non-live after release"
            ),
            remaining_unverified="the whole live acceptance (fail-closed before any live mutation)",
        )
        record_marker(_marker_payload_from_exception(marker))
        report["phase_state"] = "READY_FOR_OWNER_AUTHORIZED_PHASE_6E"
        _finish_report(config, report)
        return EXIT_FAIL_CLOSED

    # 3. Cursor before anything: fresh workspace has no committed state.
    status_before = _watch_status(config, python, runner)
    report["cursor"] = {
        "before_anything": None if status_before is None else _state_identity(status_before)
    }
    live_batch_path = Path(config.acceptance_root) / "live-batch.json"
    replay_batch_path = Path(config.acceptance_root) / "replay-batch.json"

    # 4. Live bounded CNINFO acquisition (Phase 6-B opt-in path).
    acquire = _tve(
        python,
        "watch",
        "acquire-events",
        "--watchlist",
        str(config.watchlist_path),
        "--from",
        config.published_from.isoformat(),
        "--to",
        config.published_to.isoformat(),
        "--limit",
        str(config.acquisition_limit),
        "--cache-dir",
        str(Path(config.acceptance_root) / "provider-cache"),
        "--network",
        "allow",
        "--output",
        str(live_batch_path),
        runner=runner,
        timeout=300,
    )
    if not acquire.ok:
        report["live_acquisition"] = {"ok": False, "outcome": _outcome_public(acquire)}
        _fail(report, "live acquisition failed")
        _finish_report(config, report)
        return EXIT_FAIL_CLOSED
    live_payload = json.loads(live_batch_path.read_text(encoding="utf-8"))
    event_types: dict[str, int] = {}
    for event in live_payload.get("events", []):
        event_types[event["event_type"]] = event_types.get(event["event_type"], 0) + 1
    raw_cache_dir = Path(config.acceptance_root) / "provider-cache"
    raw_files = (
        sum(1 for path in raw_cache_dir.rglob("*") if path.is_file())
        if raw_cache_dir.is_dir()
        else 0
    )
    report["live_acquisition"] = {
        "ok": True,
        "network_mode": "allow",
        "batch_id": live_payload.get("batch_id"),
        "content_sha256": live_payload.get("content_sha256"),
        "event_count": len(live_payload.get("events", [])),
        "event_type_counts": event_types,
        "raw_cache_files": raw_files,
        "raw_cache_confined_to_acceptance_root": True,
        "window": {
            "published_from": config.published_from.isoformat(),
            "published_to": config.published_to.isoformat(),
        },
    }
    status_after_acquire = _watch_status(config, python, runner)
    report["cursor"]["after_acquire"] = (
        None if status_after_acquire is None else _state_identity(status_after_acquire)
    )
    report["cursor"]["acquire_did_not_commit"] = status_after_acquire == status_before

    # 5. Offline replay with sockets hard-blocked; byte-identical proof.
    guard_dir = Path(config.acceptance_root) / "guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    guard_script = guard_dir / "socket_guard.py"
    guard_script.write_text(_SOCKET_GUARD_SOURCE_TEMPLATE, encoding="utf-8")
    guard_outcome = run_command(
        (
            python,
            str(guard_script),
            "watch",
            "acquire-events",
            "--watchlist",
            str(config.watchlist_path),
            "--from",
            config.published_from.isoformat(),
            "--to",
            config.published_to.isoformat(),
            "--cache-dir",
            str(raw_cache_dir),
            "--from-cache",
            "--output",
            str(replay_batch_path),
        ),
        runner=runner,
        cwd=ROOT,
        timeout=300,
    )
    replay_identical = (
        guard_outcome.ok
        and replay_batch_path.is_file()
        and replay_batch_path.read_bytes() == live_batch_path.read_bytes()
        and "SOCKET_CONNECT_ATTEMPTED" not in guard_outcome.stderr
    )
    unshare_available = run_command(("unshare", "--net", "true"), runner=runner).ok
    mechanism = (
        "python-connect-guard (unshare --net unavailable on this host)"
        if not unshare_available
        else "python-connect-guard (unshare --net available but unused: the "
        "guard is stricter for a CLI subprocess)"
    )
    report["offline_replay"] = {
        "ok": replay_identical,
        "socket_block_mechanism": mechanism,
        "batch_bytes_identical": replay_batch_path.is_file()
        and replay_batch_path.read_bytes() == live_batch_path.read_bytes(),
        "returncode": guard_outcome.returncode,
        "stderr_tail": _bounded(guard_outcome.stderr, 600),
    }
    if not replay_identical:
        _fail(report, "offline socket-blocked replay is not byte-identical")
        _finish_report(config, report)
        return EXIT_FAIL_CLOSED

    # 6. First unattended run (live acquisition through D1 and atomic commit).
    run1_outcome, run1 = _unattended_run(config, python, config.runner_live_config_path, runner)
    if run1 is None or run1.get("classification") != "COMPLETED_NEW":
        report["runner"] = {
            "run1": {"ok": False, "outcome": _outcome_public(run1_outcome), "payload": run1}
        }
        _fail(report, "first unattended run did not complete as COMPLETED_NEW")
        _finish_report(config, report)
        return EXIT_FAIL_CLOSED
    status_after_commit = _watch_status(config, python, runner)
    cursor_advanced = (
        status_after_commit is not None
        and _state_identity(status_after_commit) is not None
        and status_after_commit != status_after_acquire
    )
    report["cursor"].update(
        {
            "after_commit": None
            if status_after_commit is None
            else _state_identity(status_after_commit),
            "committed_only_after_cycle": cursor_advanced,
        }
    )
    report["runner"] = {
        "run1": {
            "ok": True,
            "classification": run1["classification"],
            "activation_id": run1["activation_id"],
            "cycle_id": run1["cycle_id"],
            "as_of": run1["as_of"],
            "d1_status": run1["d1_status"],
            "result_content_sha256": run1["result_content_sha256"],
            "alert_batch_id": run1["alert_batch_id"],
            "alert_batch_content_sha256": run1["alert_batch_content_sha256"],
        }
    }

    # 7. Idempotent rerun: same identities, no duplicate D1 work.
    cycle_files_before = sorted(
        path.name for path in (Path(config.acceptance_root) / "cycles").rglob("*") if path.is_file()
    )
    run2_outcome, run2 = _unattended_run(config, python, config.runner_live_config_path, runner)
    cycle_files_after = sorted(
        path.name for path in (Path(config.acceptance_root) / "cycles").rglob("*") if path.is_file()
    )
    status_after_rerun = _watch_status(config, python, runner)
    reuse_ok = (
        run2 is not None
        and run2.get("classification") == "COMPLETED_REUSED"
        and run2.get("activation_id") == run1["activation_id"]
        and run2.get("cycle_id") == run1["cycle_id"]
        and cycle_files_before == cycle_files_after
        and (status_after_rerun == status_after_commit)
    )
    report["runner"]["idempotent_rerun"] = {
        "ok": reuse_ok,
        "classification": None if run2 is None else run2.get("classification"),
        "same_activation": None
        if run2 is None
        else run2.get("activation_id") == run1["activation_id"],
        "cycle_store_unchanged": cycle_files_before == cycle_files_after,
        "state_unchanged": status_after_rerun == status_after_commit,
    }

    # 8. Crash/resume proof: kill a real invocation after the durable intent.
    crash = _crash_resume_proof(config, python, runner)
    report["runner"]["crash_resume"] = crash

    # The delivery/D3 sections target the runner's *latest* terminal
    # activation, which is what the D3 projection exposes.
    terminal_activation: dict[str, object] = run1
    crash_is_terminal = (
        crash.get("ok")
        and crash.get("same_activation_resumed")
        and crash.get("killed_after_intent")
    )
    if crash_is_terminal:
        terminal_activation = dict(run1)
        terminal_activation["activation_id"] = str(crash["killed_after_intent"]).removesuffix(
            ".json"
        )
        terminal_activation["classification"] = crash.get("resume_classification")
    report["runner"]["terminal_activation_for_delivery"] = terminal_activation.get("activation_id")

    # 9. Delivery through the existing generic HTTPS webhook boundary.
    report["delivery"] = _delivery_section(
        config, python, runner, terminal_activation, record_marker
    )

    # 10. Read-only D3 operations API on the real surface server.
    report["operations_api"] = _operations_api_section(
        config, python, runner, report, terminal_activation
    )

    # 11. systemd-scheduled execution at cadence, if applied.
    report["systemd_observed"] = _systemd_observation_section(config, runner, args)

    # 12. Final secret scan over every generated artifact.
    secrets = resolvable_secret_values(config)
    scanned: list[str] = []
    hits: list[str] = []
    for path in sorted(Path(config.acceptance_root).rglob("*")):
        if path.is_file() and path.suffix in {".json", ".toml", ".py", ".service", ".timer"}:
            scanned.append(str(path))
            found = scan_bytes_for_secrets(path.read_bytes(), secrets)
            hits.extend(f"{path.name}:{name}" for name in found)
    report["secret_scan"] = {
        "scanned_files": scanned,
        "secret_references_checked": sorted(secrets),
        "hits": hits,
    }

    hard_failures = _collect_failures(report)
    owner_marker_names = {
        item["marker"]
        for item in markers
        if item.get("marker")
        in {
            MANUAL_SECRET_REFERENCE_REQUIRED,
            MANUAL_SUDO_INSTALL_REQUIRED,
            MANUAL_NOTIFICATION_RECEIPT_REQUIRED,
            MANUAL_IDP_ACCEPTANCE_REQUIRED,
            MANUAL_OWNER_INPUT_REQUIRED,
        }
    }
    report["phase_state"] = (
        "READY_FOR_OWNER_AUTHORIZED_PHASE_6E"
        if owner_marker_names or hard_failures
        else "LIVE_ACCEPTANCE_COMPLETE"
    )
    _finish_report(config, report)
    print(
        json.dumps(
            {
                "phase_state": report["phase_state"],
                "failures": hard_failures,
                "markers": [item.get("marker") for item in markers],
                "report": str(config.report_path),
            },
            indent=2,
        )
    )
    return EXIT_FAIL_CLOSED if hard_failures else EXIT_OK


def _state_identity(status: dict[str, object]) -> dict[str, object] | None:
    """Extract the committed-state identity (or ``None`` while NOT_AVAILABLE)."""

    if not isinstance(status, dict) or status.get("availability") != "AVAILABLE":
        return None
    return {
        "state_id": status.get("state_id"),
        "last_committed_run_id": status.get("last_committed_run_id"),
    }


def _fail(report: dict[str, object], reason: str) -> None:
    failures = report.setdefault("failures", [])
    failures.append(reason)  # type: ignore[union-attr]


def _collect_failures(report: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    sections = (
        "lock_visibility",
        "live_acquisition",
        "offline_replay",
        "runner",
        "delivery",
        "operations_api",
        "systemd_observed",
        "secret_scan",
    )
    for section in sections:
        value = report.get(section)
        if isinstance(value, Mapping) and value.get("ok") is False:
            failures.append(section)
    cursor = report.get("cursor")
    if isinstance(cursor, Mapping) and (
        cursor.get("committed_only_after_cycle") is False
        or cursor.get("acquire_did_not_commit") is False
    ):
        failures.append("cursor")
    if isinstance(report.get("failures"), list):
        failures.extend(str(item) for item in report["failures"])  # type: ignore[literal-type]
    return sorted(set(failures))


def _crash_resume_proof(
    config: AcceptanceConfigV1, python: str, runner: CommandRunner
) -> dict[str, object]:
    """Kill a live invocation right after its durable intent, then resume."""

    resume_config = config.runner_resume_config_path
    runner_root = Path(config.acceptance_root) / "runner"
    intents_before = (
        {path.name for path in (runner_root / "activations").glob("*.json")}
        if (runner_root / "activations").is_dir()
        else set()
    )
    output_path = resume_config.with_name(resume_config.stem + "-last-run.json")
    process = subprocess.Popen(
        [
            python,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-run",
            "--runner-config",
            str(resume_config),
            "--output",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        start_new_session=True,
    )
    killed = False
    new_intent: str | None = None
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            intents_now = (
                {path.name for path in (runner_root / "activations").glob("*.json")}
                if (runner_root / "activations").is_dir()
                else set()
            )
            fresh = intents_now - intents_before
            if fresh and process.poll() is None:
                new_intent = sorted(fresh)[0]
                os.killpg(process.pid, 9)
                killed = True
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)
        process.wait(timeout=60)
    except ProcessLookupError:
        pass
    if not killed:
        # The invocation finished before the intent could be interrupted;
        # record honestly and still prove no duplicate activation below.
        payload = None
        if output_path.is_file():
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = None
        return {
            "ok": False,
            "injected": False,
            "reason": "controlled interruption window missed; process completed first",
            "completed_classification": None if payload is None else payload.get("classification"),
            "duplicate_free": _count_activations(runner_root) == len(intents_before) + 1,
        }
    lease_after_kill = run_command(
        (
            python,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            str(runner_root),
            "--runner-id",
            config.runner_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    lease_state = "UNPARSEABLE"
    unfinished_after_kill: list[str] = []
    try:
        status_payload = json.loads(lease_after_kill.stdout)
        for item in status_payload["runners"]:
            if item["runner_id"] == config.runner_id:
                lease_state = item["lease"]["state"]
                unfinished_after_kill = item["unfinished_activation_ids"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    resume_outcome, resumed = _unattended_run(config, python, resume_config, runner)
    resumed_ok = (
        resumed is not None
        and resumed.get("classification") in {"COMPLETED_RESUMED", "COMPLETED_REPAIRED"}
        and resumed.get("activation_id") == new_intent.removesuffix(".json")
    )
    return {
        "ok": resumed_ok,
        "injected": True,
        "killed_after_intent": new_intent,
        "lease_state_after_kill": lease_state,
        "lease_kernel_released": lease_state == "ABANDONED",
        "unfinished_after_kill": unfinished_after_kill,
        "resume_classification": None if resumed is None else resumed.get("classification"),
        "same_activation_resumed": None
        if resumed is None
        else resumed.get("activation_id") == new_intent.removesuffix(".json"),
        "outcome": None if resumed_ok else _outcome_public(resume_outcome),
    }


def _count_activations(runner_root: Path) -> int:
    directory = runner_root / "activations"
    return len(list(directory.glob("*.json"))) if directory.is_dir() else 0


def _delivery_section(
    config: AcceptanceConfigV1,
    python: str,
    runner: CommandRunner,
    terminal_run: dict[str, object],
    record_marker: Callable[[dict[str, object]], None],
) -> dict[str, object]:
    secrets = resolvable_secret_values(config)
    owner_endpoint = secrets.get(config.delivery_endpoint_env)
    activation_id = terminal_run.get("activation_id")
    receiver = None
    extra_env: dict[str, str] = {}
    receiver_mode: str

    if owner_endpoint:
        receiver_mode = "owner_env"
    elif config.delivery_receiver == "local_https":
        receiver_mode = "local_https"
        cert, key = _generate_local_tls_material(Path(config.acceptance_root) / "receiver", runner)
        receiver = _LocalReceiver(
            python,
            cert,
            key,
            config.local_receiver_port,
            Path(config.acceptance_root) / "receiver" / "journal.jsonl",
            runner,
        )
        extra_env[config.delivery_endpoint_env] = receiver.endpoint()
        extra_env["SSL_CERT_FILE"] = str(cert)
    else:
        record_marker(
            _marker_payload_from_exception(
                ManualBoundary(
                    MANUAL_SECRET_REFERENCE_REQUIRED,
                    stopped_after=(
                        "live-smoke delivery step: the terminal activation "
                        f"{activation_id} exists with an alert outbox, but the endpoint "
                        f"reference {config.delivery_endpoint_env} resolves to nothing and "
                        "delivery_receiver=owner_env forbids the harness-local receiver"
                    ),
                    human_action=(
                        "make the owner webhook endpoint available in the approved secret "
                        f"manager/environment under {config.delivery_endpoint_env} "
                        "(optionally the bearer token under "
                        f"{config.delivery_auth_env}) without revealing either value here"
                    ),
                    secret_boundary=(
                        f"the {config.delivery_endpoint_env} value (and optional "
                        f"{config.delivery_auth_env} value) must stay out of Git, committed "
                        "documents, chat and this report"
                    ),
                    resume_command=(
                        f"{Path(sys.argv[0]).name} live-smoke --acceptance-config "
                        f"{Path(config.acceptance_root) / 'acceptance-config.json'}"
                        " --network allow --allow-existing"
                    ),
                    machine_verifiable_success=(
                        "`tve watch deliver ... --network allow` returns classification "
                        "DELIVERED, delivery-status reports pointer CURRENT, and the repeated "
                        "identity authorizes zero additional dispatch slots"
                    ),
                    remaining_unverified=(
                        "real webhook delivery to the owner destination and its durable "
                        "delivery accounting (ledger idempotency mechanics are proven only "
                        "when a receiver is available)"
                    ),
                )
            )
        )
        return {"ok": False, "skipped": True, "marker": MANUAL_SECRET_REFERENCE_REQUIRED}

    deliver_env = dict(os.environ)
    deliver_env.update(extra_env)
    first = _tve(
        python,
        "watch",
        "deliver",
        "--runner-config",
        str(config.runner_live_config_path),
        "--project-config",
        str(config.project_config_path),
        "--activation-id",
        str(activation_id),
        "--network",
        "allow",
        runner=runner,
        env=deliver_env,
        timeout=180,
    )
    try:
        first_payload = json.loads(first.stdout) if first.stdout.strip() else None
    except json.JSONDecodeError:
        first_payload = None
    if (
        first.returncode != 0
        or first_payload is None
        or first_payload.get("classification") not in {"DELIVERED", "NOOP"}
    ):
        if receiver is not None:
            receiver.stop()
        return {
            "ok": False,
            "receiver_mode": receiver_mode,
            "first": _outcome_public(first),
            "payload": first_payload,
        }
    delivery_id = first_payload["delivery_id"]
    status_first = _delivery_status(config, python, delivery_id, runner)

    second = _tve(
        python,
        "watch",
        "deliver",
        "--runner-config",
        str(config.runner_live_config_path),
        "--project-config",
        str(config.project_config_path),
        "--activation-id",
        str(activation_id),
        "--network",
        "allow",
        runner=runner,
        env=deliver_env,
        timeout=180,
    )
    try:
        second_payload = json.loads(second.stdout) if second.stdout.strip() else None
    except json.JSONDecodeError:
        second_payload = None
    status_second = _delivery_status(config, python, delivery_id, runner)

    receiver_requests: list[dict[str, object]] = []
    receipt_match = None
    if receiver is not None:
        receiver_requests = receiver.requests()
        receipt_match = {
            "requests_total": len(receiver_requests),
            "matching_idempotency_keys": sum(
                1 for item in receiver_requests if item.get("idempotency_key") == delivery_id
            ),
        }
        receiver.stop()

    duplicate_free = (
        second_payload is not None
        and second_payload.get("reused") is True
        and second_payload.get("http_requests") == 0
        and status_second.get("state", {}).get("attempt_count")
        == status_first.get("state", {}).get("attempt_count")
    )
    if receiver_mode == "local_https":
        record_marker(
            _marker_payload_from_exception(
                ManualBoundary(
                    MANUAL_SECRET_REFERENCE_REQUIRED,
                    stopped_after=(
                        "live-smoke delivery step completed against the harness-local HTTPS "
                        f"receiver (delivery_id={delivery_id}, state DELIVERED) because the "
                        f"owner endpoint reference {config.delivery_endpoint_env} was not "
                        "resolvable in this environment"
                    ),
                    human_action=(
                        "supply the owner webhook endpoint through the approved secret "
                        f"manager/environment entry {config.delivery_endpoint_env} and rerun "
                        "the delivery section against it"
                    ),
                    secret_boundary=(
                        f"the {config.delivery_endpoint_env} value (and optional "
                        f"{config.delivery_auth_env} value) must stay out of Git, committed "
                        "documents, chat and this report"
                    ),
                    resume_command=(
                        f"{Path(sys.argv[0]).name} live-smoke --acceptance-config "
                        f"{Path(config.acceptance_root) / 'acceptance-config.json'}"
                        " --network allow --allow-existing"
                    ),
                    machine_verifiable_success=(
                        "deliver to the owner endpoint returns DELIVERED with pointer CURRENT, "
                        "and the repeated identity authorizes zero additional dispatch slots"
                    ),
                    remaining_unverified=(
                        "delivery of the acceptance alert outbox to the owner's real "
                        "destination (the D2B ledger mechanics were proven against the "
                        "harness-local receiver)"
                    ),
                )
            )
        )
    return {
        "ok": bool(duplicate_free),
        "receiver_mode": receiver_mode,
        "delivery_id": delivery_id,
        "state_after_first": status_first.get("state"),
        "pointer_status": status_first.get("pointer_status"),
        "attempt_count": status_first.get("state", {}).get("attempt_count"),
        "dispatch_claim_count": status_second.get("dispatch_claim_count"),
        "unresolved_claim_numbers": status_second.get("unresolved_claim_numbers"),
        "repeat": {
            "reused": None if second_payload is None else second_payload.get("reused"),
            "http_requests": None
            if second_payload is None
            else second_payload.get("http_requests"),
            "attempt_count_unchanged": duplicate_free,
        },
        "receiver_receipt": receipt_match,
    }


def _operations_api_section(
    config: AcceptanceConfigV1,
    python: str,
    runner: CommandRunner,
    report: dict[str, object],
    terminal_activation: Mapping[str, object],
) -> dict[str, object]:
    from turtle_value_engine.monitoring_operations.contracts import MonitoringOperationsProjectionV1

    if config.snapshot_path is None or not Path(config.snapshot_path).is_file():
        return {
            "ok": False,
            "skipped": True,
            "marker": MANUAL_OWNER_INPUT_REQUIRED,
            "reason": f"validated surface snapshot missing ({config.snapshot_path})",
        }
    port = config.surface_port
    server = subprocess.Popen(
        [
            python,
            "-m",
            "turtle_value_engine",
            "surface",
            "serve",
            "--snapshot",
            str(Path(config.snapshot_path).resolve()),
            "--port",
            str(port),
            "--monitoring-runner-config",
            str(config.runner_live_config_path.resolve()),
            "--monitoring-project-config",
            str(config.project_config_path.resolve()),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )
    try:
        if not _wait_for_port(port, timeout=30):
            return {"ok": False, "skipped": False, "reason": "surface server did not listen"}
        url = f"http://127.0.0.1:{port}/v1/monitoring/operations"
        tree_before, files_before = content_tree_hash(Path(config.acceptance_root))
        status_code, body = _http_request("GET", url)
        validated = None
        if status_code == 200:
            try:
                validated = MonitoringOperationsProjectionV1.model_validate(json.loads(body))
            except Exception:
                validated = None
        # Repeated read-only polling must not mutate one byte.
        for _ in range(3):
            _http_request("GET", url)
        tree_after, files_after = content_tree_hash(Path(config.acceptance_root))
        mutation_results = {}
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            code, _ = _http_request(method, url, data=b"{}")
            mutation_results[method] = code
        mutations_rejected = all(code == 405 for code in mutation_results.values())

        secrets = resolvable_secret_values(config)
        payload_text = body.decode("utf-8", errors="replace")
        secret_hits = scan_bytes_for_secrets(body, secrets)
        forbidden_strings = [
            str(Path(config.acceptance_root)),
            str(config.project_config_path.resolve()),
            "127.0.0.1:" + str(config.local_receiver_port),
            "holder_token",
        ]
        path_leaks = [item for item in forbidden_strings if item and item in payload_text]

        delivery_section = report.get("delivery")
        delivered_id = (
            delivery_section.get("delivery_id")
            if isinstance(delivery_section, Mapping)
            else None
        )
        delivery_ids: list[str] = (
            [] if validated is None else [item.delivery_id for item in validated.deliveries]
        )
        activation_matches = (
            validated is not None
            and validated.activation is not None
            and validated.activation.activation_id == terminal_activation.get("activation_id")
        )
        delivery_projected = delivered_id is None or delivered_id in delivery_ids
        ok = (
            status_code == 200
            and validated is not None
            and activation_matches
            and delivery_projected
            and mutations_rejected
            and tree_before == tree_after
            and files_before == files_after
            and not secret_hits
            and not path_leaks
            and validated is not None
            and validated.runner.lease_state in {"ABANDONED", "FREE"}
        )
        return {
            "ok": bool(ok),
            "http_status": status_code,
            "projection_contract_valid": validated is not None,
            "activation_matches_terminal_receipt": bool(activation_matches),
            "lease_state": None if validated is None else validated.runner.lease_state,
            "mutation_methods": mutation_results,
            "mutations_rejected": bool(mutations_rejected),
            "polling_immutability": tree_before == tree_after and files_before == files_after,
            "delivery_ids_projected": delivery_ids,
            "delivered_identity_projected": bool(delivery_projected),
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


def _systemd_observation_section(
    config: AcceptanceConfigV1,
    runner: CommandRunner,
    args: argparse.Namespace,
) -> dict[str, object]:
    apply_record = config.systemd_output_dir / "apply-record.json"
    if not apply_record.is_file():
        return {
            "ok": False,
            "skipped": True,
            "marker": MANUAL_SUDO_INSTALL_REQUIRED if config.scope == "system" else None,
            "reason": "units were not applied (no apply-record.json); run apply first",
        }
    try:
        applied = json.loads(apply_record.read_text(encoding="utf-8")).get("applied") is True
    except (OSError, json.JSONDecodeError):
        applied = False
    if not applied:
        return {
            "ok": False,
            "skipped": True,
            "marker": MANUAL_SUDO_INSTALL_REQUIRED if config.scope == "system" else None,
            "reason": "apply-record.json does not record a successful apply",
        }
    # Start the (enabled but not yet running) timer deterministically now;
    # scope=system without privilege cannot, which stays an owner boundary.
    timer_state = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState",), runner
    )
    timer_started_by_harness = False
    if timer_state.get("ActiveState") != "active":
        if config.scope == "system" and not _systemd_privilege_available(config, runner=runner):
            return {
                "ok": False,
                "skipped": True,
                "marker": MANUAL_SUDO_INSTALL_REQUIRED,
                "reason": "timer is not active and starting a system timer needs privilege",
            }
        start = run_command(
            (*systemctl_prefix(config), "start", config.timer_unit_name), runner=runner
        )
        timer_started_by_harness = start.ok
        if not start.ok:
            return {
                "ok": False,
                "skipped": False,
                "reason": f"cannot start timer: rc={start.returncode}",
            }
    # Fire detection: the service's ExecMainStartTimestamp changes on every
    # timer-driven start.  (NInvocations is not reported by every systemd
    # build, so it cannot be the detection signal.)
    initial_start = _systemctl_show(
        config, config.service_unit_name, ("ExecMainStartTimestamp",), runner
    ).get("ExecMainStartTimestamp", "")
    deadline = time.monotonic() + args.timer_wait_seconds
    fired = False
    final_start = initial_start
    while time.monotonic() < deadline:
        current_start = _systemctl_show(
            config, config.service_unit_name, ("ExecMainStartTimestamp",), runner
        ).get("ExecMainStartTimestamp", "")
        if current_start and current_start != initial_start:
            fired = True
            final_start = current_start
            break
        time.sleep(2)
    journal = run_command(
        (
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
            else (
                "journalctl",
                "-u",
                config.service_unit_name,
                "-n",
                "20",
                "--no-pager",
                "-o",
                "cat",
            )
        ),
        runner=runner,
    )
    redacted = redact_text(_bounded(journal.stdout, 4000), resolvable_secret_values(config))
    classification_seen = "COMPLETED_" in redacted
    status = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            str(Path(config.acceptance_root) / "runner"),
            "--runner-id",
            config.runner_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    activation_counts: dict[str, int] = {}
    if status.ok:
        try:
            for item in json.loads(status.stdout)["runners"]:
                activation_counts[item["runner_id"]] = len(
                    item.get("unfinished_activation_ids", [])
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return {
        "ok": bool(fired and classification_seen and not any(activation_counts.values())),
        "scope": config.scope,
        "timer_started_by_harness": timer_started_by_harness,
        "timer_fired": fired,
        "service_exec_main_start_timestamp": final_start,
        "service_journal_redacted": redacted,
        "classification_seen_in_journal": classification_seen,
        "no_unfinished_activations": not any(activation_counts.values()),
    }


def _finish_report(config: AcceptanceConfigV1, report: dict[str, object]) -> None:
    report["failures"] = _collect_failures(report)
    secrets = resolvable_secret_values(config)
    serialized = canonical_json_bytes(report)
    hits = scan_bytes_for_secrets(serialized, secrets)
    if hits:
        raise AcceptanceError(
            "acceptance report would contain resolved secret values "
            f"({sorted(hits)}); refusing to persist"
        )
    _atomic_write(config.report_path, serialized + b"\n")


def cmd_report(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_acceptance_config(args.acceptance_config)
    path = config.report_path
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read acceptance report {path}: {exc}") from exc
    if report.get("contract") != REPORT_CONTRACT:
        raise AcceptanceError(f"acceptance report {path} has the wrong contract")
    secrets = resolvable_secret_values(config)
    hits = scan_bytes_for_secrets(path.read_bytes(), secrets)
    summary = {
        "report": str(path),
        "phase_state": report.get("phase_state"),
        "failures": report.get("failures"),
        "markers": [item.get("marker") for item in report.get("markers", [])],
        "secret_scan_hits": hits,
    }
    print(json.dumps(summary, indent=2))
    return EXIT_OK if not hits and not report.get("failures") else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitoring_live_acceptance.py",
        description="Phase 6-E owner live unattended acceptance harness",
    )
    parser.add_argument(
        "--acceptance-config", required=True, type=Path, help="non-secret acceptance config JSON"
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    gate = subparsers.add_parser("gate", help="run the mandatory deterministic repository gate")
    gate.add_argument("--python", default=sys.executable)
    gate.add_argument("--fail-fast", action="store_true")
    gate.add_argument("--timeout", type=float, default=1800)

    preflight = subparsers.add_parser("preflight", help="non-mutating host/config/lock checks")
    preflight.add_argument("--skip-gate", action="store_true")
    preflight.add_argument("--require-clean-tree", action="store_true")

    render = subparsers.add_parser(
        "render", help="render owner-specific systemd units (no mutation)"
    )
    render.add_argument("--allow-missing-runner-config", action="store_true")

    apply_parser = subparsers.add_parser("apply", help="install/enable the rendered units")
    apply_parser.add_argument(
        "--start-timer",
        action="store_true",
        help="also start the timer now (production behaviour); by default it is "
        "only enabled, and live-smoke starts it deterministically",
    )
    subparsers.add_parser("verify", help="verify the effective installed state")
    subparsers.add_parser("disable", help="stop and disable the acceptance timer")

    live_smoke = subparsers.add_parser("live-smoke", help="bounded real live acceptance + report")
    live_smoke.add_argument("--network", choices=("deny", "allow"), default="deny")
    live_smoke.add_argument("--skip-gate", action="store_true")
    live_smoke.add_argument("--allow-existing", action="store_true")
    live_smoke.add_argument("--timer-wait-seconds", type=float, default=150)

    subparsers.add_parser("report", help="validate and summarize the acceptance report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "gate": cmd_gate,
        "preflight": cmd_preflight,
        "render": cmd_render,
        "apply": cmd_apply,
        "verify": cmd_verify,
        "disable": cmd_disable,
        "live-smoke": cmd_live_smoke,
        "report": cmd_report,
    }
    try:
        return handlers[args.mode](args)
    except ManualBoundary as exc:
        print(json.dumps(exc.payload, indent=2))
        return EXIT_MARKER
    except AcceptanceError as exc:
        print(f"monitoring_live_acceptance: {exc}", file=sys.stderr)
        return EXIT_FAIL_CLOSED


if __name__ == "__main__":
    raise SystemExit(main())
