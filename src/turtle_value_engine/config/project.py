"""Versioned project runtime configuration.

The strategy profile loader in :mod:`turtle_value_engine.config.loader` is
deliberately separate from this module.  Rule profiles define investment
semantics; the project configuration defines runtime paths, network policy,
provider/storage extensions and deployment facts.  The latter may contain
credential *references*, but never credential values.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY = re.compile(
    r"(?:secret|token|password|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"signed[_-]?url|authorization|bearer|client[_-]?id)",
    re.IGNORECASE,
)


class ProjectConfigError(ValueError):
    """Raised when the project runtime configuration is missing or invalid."""


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _validate_hostname(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if len(value) > 253 or value.endswith("."):
        raise ValueError(f"{label} must be a DNS hostname without a trailing dot")
    labels = value.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(part) for part in labels):
        raise ValueError(f"{label} must be a DNS hostname, not a URL or wildcard")
    return value.lower()


def _validate_subdomain(value: str, label: str) -> str:
    if not _HOST_LABEL.fullmatch(value):
        raise ValueError(f"{label} must be a single DNS label")
    return value.lower()


class SecretReference(BaseModel):
    """A reference to a secret held by the process environment/secret manager."""

    model_config = ConfigDict(extra="forbid")

    env: str = Field(min_length=1)

    @field_validator("env")
    @classmethod
    def validate_env_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("env must be a valid environment variable name")
        return value


class ProjectIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = "turtle-value-engine"
    environment: str = "private"
    timezone: str = "Asia/Taipei"


class ProfileSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: str = "strict-v1"


class ProjectPaths(BaseModel):
    """Project-root-relative paths shared by later phases."""

    model_config = ConfigDict(extra="forbid")

    private_root: str = ".tve-private"
    cache_root: str = ".tve-cache"
    historical_root: str = ".tve-private/historical"
    artifact_root: str = ".tve-private/artifacts"
    reports_root: str = ".tve-private/reports"


class NetworkSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_policy: Literal["deny", "allow"] = "deny"
    allow_live_cloudflare: bool = False


class SurfaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_path: str | None = None
    port: int = Field(default=8787, ge=1, le=65535)
    live_surface_id: str | None = None
    expected_surface_sha256: str | None = None

    _blank_snapshot = field_validator(
        "snapshot_path", "live_surface_id", "expected_surface_sha256", mode="before"
    )(_blank_to_none)

    @field_validator("live_surface_id")
    @classmethod
    def validate_surface_id(cls, value: str | None) -> str | None:
        if value is not None and not _HASH.fullmatch(value):
            raise ValueError("live_surface_id must be a lowercase 64-character hash")
        return value

    @field_validator("expected_surface_sha256")
    @classmethod
    def validate_surface_hash(cls, value: str | None) -> str | None:
        if value is not None and not _HASH.fullmatch(value):
            raise ValueError("expected_surface_sha256 must be a lowercase 64-character hash")
        return value


class CloudflareSecretReferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_token: SecretReference = Field(
        default_factory=lambda: SecretReference(env="CLOUDFLARE_API_TOKEN")
    )
    origin_access_client_id: SecretReference = Field(
        default_factory=lambda: SecretReference(env="SURFACE_API_ACCESS_CLIENT_ID")
    )
    origin_access_client_secret: SecretReference = Field(
        default_factory=lambda: SecretReference(env="SURFACE_API_ACCESS_CLIENT_SECRET")
    )
    dashboard_access_client_id: SecretReference = Field(
        default_factory=lambda: SecretReference(env="TVE_DASHBOARD_ACCESS_CLIENT_ID")
    )
    dashboard_access_client_secret: SecretReference = Field(
        default_factory=lambda: SecretReference(env="TVE_DASHBOARD_ACCESS_CLIENT_SECRET")
    )
    tunnel_connector_token: SecretReference = Field(
        default_factory=lambda: SecretReference(env="TVE_CLOUDFLARE_TUNNEL_TOKEN")
    )


class CloudflareSettings(BaseModel):
    """Non-secret Cloudflare facts and deterministic resource names."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    zone_name: str | None = None
    account_id: str | None = None
    zone_id: str | None = None
    dashboard_zone_id: str | None = None
    dashboard_subdomain: str = "tve-private-dashboard"
    origin_subdomain: str = "tve-private-surface"
    dashboard_hostname: str | None = None
    origin_hostname: str | None = None
    origin_url: str | None = None
    tunnel_id: str | None = None
    tunnel_name: str = "tve-private-dashboard-origin"
    dashboard_access_email: str | None = None
    dashboard_access_app_name: str = "tve-private-dashboard"
    origin_access_app_name: str = "tve-private-surface-origin"
    origin_service_token_name: str = "tve-private-dashboard-origin"
    dashboard_smoke_service_token_name: str = "tve-private-dashboard-smoke"
    secret_refs: CloudflareSecretReferences = Field(default_factory=CloudflareSecretReferences)

    _blank_optional = field_validator(
        "zone_name",
        "account_id",
        "zone_id",
        "dashboard_zone_id",
        "dashboard_hostname",
        "origin_hostname",
        "origin_url",
        "tunnel_id",
        "dashboard_access_email",
        mode="before",
    )(_blank_to_none)

    @field_validator("zone_name", "dashboard_hostname", "origin_hostname")
    @classmethod
    def validate_hostnames(cls, value: str | None, info: Any) -> str | None:
        return _validate_hostname(value, str(info.field_name))

    @field_validator("dashboard_subdomain", "origin_subdomain")
    @classmethod
    def validate_subdomains(cls, value: str, info: Any) -> str:
        return _validate_subdomain(value, str(info.field_name))

    @field_validator("dashboard_access_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and ("@" not in value or value.strip() != value):
            raise ValueError("dashboard_access_email must be an owner-selected email")
        return value


class DashboardSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_name: str = "tve-personal-dashboard"


class MonitoringDeliverySettings(BaseModel):
    """Non-secret Phase 6-D2B notification-delivery policy (checked-in safe).

    Only policy facts and secret *references* live here.  The webhook
    endpoint and bearer token are resolved from their referenced environment
    entries in process memory at call time and may never be persisted.  The
    checked-in example stays disabled; live delivery additionally requires
    the explicit ``--network allow`` CLI opt-in.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    transport: Literal["webhook-v1"] = "webhook-v1"
    destination_id: str = Field(default="owner-primary", min_length=1, max_length=128)
    delivery_root: str = ".tve-private/monitoring/delivery"
    endpoint_ref: SecretReference | None = None
    auth_token_ref: SecretReference | None = None
    receiver_idempotency_declared: bool = False
    max_attempts: int = Field(default=5, ge=1, le=20)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    backoff_base_seconds: int = Field(default=60, ge=0, le=3600)
    backoff_cap_seconds: int = Field(default=3600, ge=1, le=86400)
    max_response_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @field_validator("delivery_root")
    @classmethod
    def _validate_delivery_root(cls, value: str) -> str:
        if value is None or not value.strip():
            raise ValueError("delivery_root must not be blank")
        return value

    @field_validator("destination_id")
    @classmethod
    def _validate_destination_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("destination_id must not be blank")
        return value

    @model_validator(mode="after")
    def _validate_backoff(self) -> MonitoringDeliverySettings:
        if self.backoff_cap_seconds < self.backoff_base_seconds:
            raise ValueError("backoff_cap_seconds must not be below backoff_base_seconds")
        return self


class MonitoringSettings(BaseModel):
    """Non-secret watchlist monitoring defaults (Phase 6-A/6-B).

    Phase 6-A is offline-only: there is deliberately no schedule, webhook,
    notification or provider-credential field here.  ``event_impact_policy``
    accepts only the versioned monitoring policy shipped with the engine so
    an unknown policy id fails closed instead of silently changing impact
    semantics.  Phase 6-B adds only a non-secret raw-cache directory for the
    opt-in live acquisition command; network access itself stays
    deny-by-default and is never implied by configuration.  Phase 6-D2B adds
    the nested ``delivery`` policy object, which carries only non-secret
    policy plus secret references and stays disabled by default.
    """

    model_config = ConfigDict(extra="forbid")

    watchlist_path: str | None = None
    workspace_root: str | None = None
    event_impact_policy: Literal["event-impact-v1"] = "event-impact-v1"
    acquisition_cache_dir: str = ".tve-private/monitoring/provider-cache"
    delivery: MonitoringDeliverySettings = Field(default_factory=MonitoringDeliverySettings)

    _blank_optional = field_validator(
        "watchlist_path", "workspace_root", mode="before"
    )(_blank_to_none)

    @field_validator("acquisition_cache_dir")
    @classmethod
    def _validate_cache_dir(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("acquisition_cache_dir must not be blank")
        return value


class ProjectConfig(BaseModel):
    """Versioned, non-secret configuration shared by all runtime phases."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project: ProjectIdentity = Field(default_factory=ProjectIdentity)
    profiles: ProfileSettings = Field(default_factory=ProfileSettings)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    surface: SurfaceSettings = Field(default_factory=SurfaceSettings)
    cloudflare: CloudflareSettings = Field(default_factory=CloudflareSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    providers: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)

    _source_path: Path | None = PrivateAttr(default=None)
    _project_root: Path = PrivateAttr(default_factory=Path.cwd)

    def resolved_dashboard_hostname(self) -> str | None:
        cloudflare = self.cloudflare
        if cloudflare.dashboard_hostname:
            return cloudflare.dashboard_hostname
        if cloudflare.zone_name:
            return f"{cloudflare.dashboard_subdomain}.{cloudflare.zone_name}"
        return None

    def resolved_origin_hostname(self) -> str | None:
        cloudflare = self.cloudflare
        if cloudflare.origin_hostname:
            return cloudflare.origin_hostname
        if cloudflare.zone_name:
            return f"{cloudflare.origin_subdomain}.{cloudflare.zone_name}"
        return None

    def resolved_origin_url(self) -> str | None:
        return self.cloudflare.origin_url or (
            f"https://{hostname}" if (hostname := self.resolved_origin_hostname()) else None
        )

    def resolved_dashboard_url(self) -> str | None:
        hostname = self.resolved_dashboard_hostname()
        return f"https://{hostname}" if hostname else None

    def resolve_path(self, raw_path: str | None) -> Path | None:
        if raw_path is None:
            return None
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else self._project_root / path

    def resolved_surface_snapshot(self) -> Path | None:
        return self.resolve_path(self.surface.snapshot_path)

    def secret_reference(self, name: str) -> SecretReference:
        references = self.cloudflare.secret_refs
        try:
            return getattr(references, name)
        except AttributeError:
            raise ProjectConfigError(f"unknown Cloudflare secret reference: {name}") from None

    def secret_value(self, name: str, environ: dict[str, str] | None = None) -> str | None:
        """Resolve one named secret without ever storing it in the config model."""

        values = os.environ if environ is None else environ
        raw = values.get(self.secret_reference(name).env)
        return raw if raw and raw.strip() else None

    def safe_summary(self) -> dict[str, Any]:
        """Return an output-safe summary containing references, never secret values."""

        cloudflare = self.cloudflare
        return {
            "schema_version": self.schema_version,
            "project_id": self.project.id,
            "environment": self.project.environment,
            "default_profile": self.profiles.default,
            "network_policy": self.network.default_policy,
            "dashboard_hostname": self.resolved_dashboard_hostname(),
            "origin_hostname": self.resolved_origin_hostname(),
            "origin_url": self.resolved_origin_url(),
            "tunnel_name": cloudflare.tunnel_name,
            "monitoring": {
                "watchlist_path": self.monitoring.watchlist_path,
                "workspace_root": self.monitoring.workspace_root,
                "event_impact_policy": self.monitoring.event_impact_policy,
                "delivery": {
                    "enabled": self.monitoring.delivery.enabled,
                    "transport": self.monitoring.delivery.transport,
                    "destination_id": self.monitoring.delivery.destination_id,
                    "delivery_root": self.monitoring.delivery.delivery_root,
                    "endpoint_ref": None
                    if self.monitoring.delivery.endpoint_ref is None
                    else self.monitoring.delivery.endpoint_ref.env,
                    "auth_token_ref": None
                    if self.monitoring.delivery.auth_token_ref is None
                    else self.monitoring.delivery.auth_token_ref.env,
                },
            },
            "secret_references": {
                name: self.secret_reference(name).env
                for name in (
                    "api_token",
                    "origin_access_client_id",
                    "origin_access_client_secret",
                    "dashboard_access_client_id",
                    "dashboard_access_client_secret",
                    "tunnel_connector_token",
                )
            },
        }


def _project_root_for(path: Path) -> Path:
    if path.parent.name in {".tve-private", "config"}:
        return path.parent.parent
    return path.parent


def _reject_raw_secret_fields(value: Any, path: tuple[str, ...] = ()) -> None:
    """Reject scalar credential material while allowing explicit references."""

    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            reference_path = (
                key_text == "secret_refs"
                or
                "secret_refs" in path
                or key_text.endswith(("_ref", "_reference", "_name"))
            )
            if _SECRET_KEY.search(key_text) and not reference_path:
                raise ProjectConfigError(
                    "project config may contain credential references, not raw secret values "
                    f"(field: {'.'.join((*path, key_text))})"
                )
            _reject_raw_secret_fields(child, (*path, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_raw_secret_fields(child, (*path, str(index)))


def load_project_config(path: str | Path) -> ProjectConfig:
    """Load and validate a TOML project config from an explicit path."""

    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ProjectConfigError(
            f"project config not found: {config_path}; copy config/project.example.toml "
            "to .tve-private/project.toml"
        )
    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise ProjectConfigError(f"cannot read project config {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProjectConfigError(f"invalid TOML in project config {config_path}: {exc}") from exc
    _reject_raw_secret_fields(raw)
    try:
        config = ProjectConfig.model_validate(raw)
    except Exception as exc:
        raise ProjectConfigError(f"invalid project config {config_path}: {exc}") from exc
    config._source_path = config_path.resolve()
    config._project_root = _project_root_for(config._source_path)
    return config


def discover_project_config(
    path: str | Path | None = None, *, cwd: Path | None = None
) -> ProjectConfig | None:
    """Load an explicit/default project config, preserving env-only compatibility.

    A path supplied by the caller or ``TVE_PROJECT_CONFIG`` is mandatory and
    therefore raises a precise error when missing.  With no explicit path, the
    conventional private file is optional so existing offline commands and CI
    remain usable without a local deployment configuration.
    """

    root = cwd or Path.cwd()
    requested = path or os.environ.get("TVE_PROJECT_CONFIG")
    if requested:
        requested_path = Path(requested).expanduser()
        if not requested_path.is_absolute():
            requested_path = root / requested_path
        return load_project_config(requested_path)
    candidate = root / ".tve-private" / "project.toml"
    return load_project_config(candidate) if candidate.is_file() else None


PROJECT_CONFIG_TEMPLATE = """# Project-wide turtle-value-engine runtime configuration.
# Copy this file to .tve-private/project.toml.  Keep this file free of secrets.
# Later phases extend this same file; do not create a phase-specific config.
schema_version = 1

[project]
id = "turtle-value-engine"
environment = "private"
timezone = "Asia/Taipei"

[profiles]
default = "strict-v1"

[paths]
private_root = ".tve-private"
cache_root = ".tve-cache"
historical_root = ".tve-private/historical"
artifact_root = ".tve-private/artifacts"
reports_root = ".tve-private/reports"

[network]
default_policy = "deny"
allow_live_cloudflare = false

[surface]
# Set this to the validated ResearchSurfaceSnapshotV1 to serve.
snapshot_path = ".tve-private/surface/research-surface.json"
port = 8787
live_surface_id = ""
expected_surface_sha256 = ""

[cloudflare]
enabled = true
# Set only the zone name you own in Cloudflare, for example "example.com".
zone_name = ""
# These IDs are discovered automatically from the API token when omitted.
account_id = ""
zone_id = ""
dashboard_zone_id = ""
dashboard_subdomain = "tve-private-dashboard"
origin_subdomain = "tve-private-surface"
dashboard_hostname = ""
origin_hostname = ""
origin_url = ""
tunnel_id = ""
tunnel_name = "tve-private-dashboard-origin"
# Set the email/identity allowed by the Dashboard Access policy.
dashboard_access_email = ""
dashboard_access_app_name = "tve-private-dashboard"
origin_access_app_name = "tve-private-surface-origin"
origin_service_token_name = "tve-private-dashboard-origin"
dashboard_smoke_service_token_name = "tve-private-dashboard-smoke"

[cloudflare.secret_refs]
# References only: values are resolved from the process environment/secret manager.
api_token = { env = "CLOUDFLARE_API_TOKEN" }
origin_access_client_id = { env = "SURFACE_API_ACCESS_CLIENT_ID" }
origin_access_client_secret = { env = "SURFACE_API_ACCESS_CLIENT_SECRET" }
dashboard_access_client_id = { env = "TVE_DASHBOARD_ACCESS_CLIENT_ID" }
dashboard_access_client_secret = { env = "TVE_DASHBOARD_ACCESS_CLIENT_SECRET" }
tunnel_connector_token = { env = "TVE_CLOUDFLARE_TUNNEL_TOKEN" }

[dashboard]
worker_name = "tve-personal-dashboard"

[monitoring]
# Phase 6-A offline watchlist monitoring (no schedule, notification or secret).
watchlist_path = ".tve-private/monitoring/watchlist.json"
workspace_root = ".tve-private/monitoring"
event_impact_policy = "event-impact-v1"
# Phase 6-B opt-in live acquisition raw cache (non-secret path only; the
# live commands still require an explicit --network=allow flag).
acquisition_cache_dir = ".tve-private/monitoring/provider-cache"

[monitoring.delivery]
# Phase 6-D2B notification delivery policy (non-secret; disabled by default).
# A live delivery additionally requires `tve watch deliver --network allow`
# and a resolved endpoint from the referenced environment entry.
enabled = false
transport = "webhook-v1"
destination_id = "owner-primary"
delivery_root = ".tve-private/monitoring/delivery"
endpoint_ref = { env = "TVE_MONITORING_WEBHOOK_URL" }
# Optional bearer token for the webhook receiver (reference only).
# auth_token_ref = { env = "TVE_MONITORING_WEBHOOK_TOKEN" }
receiver_idempotency_declared = false
max_attempts = 5
timeout_seconds = 10.0
backoff_base_seconds = 60
backoff_cap_seconds = 3600
max_response_bytes = 65536

# Future provider/storage-specific settings belong under these named sections;
# they must still contain non-secret values or secret references only.
[providers]
[storage]
[extensions]
"""


def project_config_template() -> str:
    """Return the checked-in template, with a package-safe fallback."""

    template_path = Path(__file__).resolve().parents[3] / "config" / "project.example.toml"
    if template_path.is_file():
        try:
            return template_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return PROJECT_CONFIG_TEMPLATE


def write_project_config_template(path: str | Path, *, force: bool = False) -> Path:
    """Create a private project config from the safe checked-in template."""

    target = Path(path).expanduser()
    if target.exists() and not force:
        raise ProjectConfigError(f"refusing to overwrite existing project config: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(project_config_template(), encoding="utf-8")
    return target
