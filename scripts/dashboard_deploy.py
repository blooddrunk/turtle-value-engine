"""M6-C2 deployment, preflight, and Cloudflare resource checks.

The command is deliberately explicit about every production input. It never
reads a secret from a repository file and never prints secret values.

Examples:

    python3 scripts/dashboard_deploy.py preflight --project-config .tve-private/project.toml
    python3 scripts/dashboard_deploy.py deploy --project-config .tve-private/project.toml --dry-run
    python3 scripts/dashboard_deploy.py deploy --project-config .tve-private/project.toml --apply
    python3 scripts/dashboard_deploy.py origin --project-config .tve-private/project.toml
    python3 scripts/dashboard_deploy.py verify --project-config .tve-private/project.toml
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "apps" / "dashboard"
BUILD_CONFIG = DASHBOARD / "dist" / "tve_personal_dashboard" / "wrangler.json"
WORKER_NAME = "tve-personal-dashboard"
ORIGIN_CLIENT_ID = "SURFACE_API_ACCESS_CLIENT_ID"
ORIGIN_CLIENT_SECRET = "SURFACE_API_ACCESS_CLIENT_SECRET"
DASHBOARD_CLIENT_ID = "TVE_DASHBOARD_ACCESS_CLIENT_ID"
DASHBOARD_CLIENT_SECRET = "TVE_DASHBOARD_ACCESS_CLIENT_SECRET"
SERVICE_AUTH_DECISION = "non_identity"
ACCOUNT_ID = "CLOUDFLARE_ACCOUNT_ID"
API_TOKEN = "CLOUDFLARE_API_TOKEN"
TUNNEL_ID = "TVE_CLOUDFLARE_TUNNEL_ID"
TUNNEL_NAME = "TVE_CLOUDFLARE_TUNNEL_NAME"
ZONE_ID = "TVE_CLOUDFLARE_ZONE_ID"
DASHBOARD_ZONE_ID = "TVE_DASHBOARD_ZONE_ID"
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_ACCOUNT_ID = re.compile(r"^[0-9a-fA-F]{32}$")
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from turtle_value_engine.config import (  # noqa: E402
    ProjectConfig,
    ProjectConfigError,
    discover_project_config,
)


class DeploymentError(RuntimeError):
    """A safe, user-facing deployment/preflight error."""


@dataclass(frozen=True)
class DeploymentInputs:
    account_id: str | None
    api_token: str | None
    dashboard_hostname: str | None
    dashboard_identity_email: str | None
    dashboard_access_client_id: str | None
    dashboard_access_client_secret: str | None
    surface_origin: str | None
    surface_origin_hostname: str | None
    surface_access_client_id: str | None
    surface_access_client_secret: str | None
    tunnel_id: str | None
    tunnel_name: str | None
    zone_id: str | None
    dashboard_zone_id: str | None
    snapshot_path: str | None
    surface_port: int
    zone_name: str | None = None
    dashboard_access_app_name: str = "tve-private-dashboard"
    origin_access_app_name: str = "tve-private-surface-origin"
    origin_service_token_name: str = "tve-private-dashboard-origin"
    dashboard_smoke_service_token_name: str = "tve-private-dashboard-smoke"
    worker_name: str = WORKER_NAME
    live_surface_id: str | None = None
    expected_surface_sha256: str | None = None


@dataclass(frozen=True)
class ServiceToken:
    token_id: str
    client_id: str
    client_secret: str


def _env(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    return value if value and value.strip() else None


def _configured_secret(
    values: Mapping[str, str],
    config: ProjectConfig | None,
    name: str,
    legacy_name: str,
) -> str | None:
    """Resolve an env-backed secret without ever accepting a config value."""

    legacy = _env(values, legacy_name)
    if legacy:
        return legacy
    if config is None:
        return None
    reference = config.secret_reference(name)
    return _env(values, reference.env)


def _configured_value(
    values: Mapping[str, str], env_name: str, config_value: str | None
) -> str | None:
    return _env(values, env_name) or config_value


def read_inputs(
    environ: Mapping[str, str] | None = None,
    *,
    project_config: ProjectConfig | None = None,
    config_path: str | Path | None = None,
) -> DeploymentInputs:
    values = os.environ if environ is None else environ
    try:
        requested_config = config_path or _env(values, "TVE_PROJECT_CONFIG")
        config = project_config or discover_project_config(requested_config, cwd=ROOT)
    except ProjectConfigError as exc:
        raise DeploymentError(str(exc)) from exc
    raw_port = _env(values, "TVE_SURFACE_PORT") or "8787"
    if _env(values, "TVE_SURFACE_PORT") is None and config is not None:
        raw_port = str(config.surface.port)
    try:
        surface_port = int(raw_port)
    except ValueError:
        surface_port = -1
    tunnel_id = _configured_value(
        values, TUNNEL_ID, config.cloudflare.tunnel_id if config else None
    )
    configured_tunnel_name = config.cloudflare.tunnel_name if config else None
    tunnel_name = _configured_value(values, TUNNEL_NAME, configured_tunnel_name)
    if tunnel_id and not _env(values, TUNNEL_NAME):
        tunnel_name = None
    snapshot = _env(values, "TVE_SURFACE_SNAPSHOT_PATH")
    if snapshot is None and config is not None:
        resolved_snapshot = config.resolved_surface_snapshot()
        snapshot = str(resolved_snapshot) if resolved_snapshot is not None else None
    return DeploymentInputs(
        account_id=_configured_value(
            values, ACCOUNT_ID, config.cloudflare.account_id if config else None
        ),
        api_token=_configured_secret(values, config, "api_token", API_TOKEN),
        dashboard_hostname=_configured_value(
            values,
            "TVE_DASHBOARD_HOSTNAME",
            config.resolved_dashboard_hostname() if config else None,
        ),
        dashboard_identity_email=_configured_value(
            values,
            "TVE_DASHBOARD_ACCESS_EMAIL",
            config.cloudflare.dashboard_access_email if config else None,
        ),
        dashboard_access_client_id=_configured_secret(
            values, config, "dashboard_access_client_id", DASHBOARD_CLIENT_ID
        ),
        dashboard_access_client_secret=_configured_secret(
            values, config, "dashboard_access_client_secret", DASHBOARD_CLIENT_SECRET
        ),
        surface_origin=_configured_value(
            values,
            "TVE_SURFACE_API_ORIGIN",
            config.resolved_origin_url() if config else None,
        ),
        surface_origin_hostname=_configured_value(
            values,
            "TVE_SURFACE_ORIGIN_HOSTNAME",
            config.resolved_origin_hostname() if config else None,
        ),
        surface_access_client_id=_configured_secret(
            values, config, "origin_access_client_id", ORIGIN_CLIENT_ID
        ),
        surface_access_client_secret=_configured_secret(
            values, config, "origin_access_client_secret", ORIGIN_CLIENT_SECRET
        ),
        tunnel_id=tunnel_id,
        tunnel_name=tunnel_name,
        zone_id=_configured_value(
            values, ZONE_ID, config.cloudflare.zone_id if config else None
        ),
        dashboard_zone_id=_configured_value(
            values,
            DASHBOARD_ZONE_ID,
            (
                config.cloudflare.dashboard_zone_id
                if config and config.cloudflare.dashboard_zone_id
                else config.cloudflare.zone_id if config else None
            ),
        ),
        snapshot_path=snapshot,
        surface_port=surface_port,
        zone_name=_configured_value(
            values, "TVE_CLOUDFLARE_ZONE_NAME", config.cloudflare.zone_name if config else None
        ),
        dashboard_access_app_name=(
            config.cloudflare.dashboard_access_app_name
            if config
            else "tve-private-dashboard"
        ),
        origin_access_app_name=(
            config.cloudflare.origin_access_app_name
            if config
            else "tve-private-surface-origin"
        ),
        origin_service_token_name=(
            config.cloudflare.origin_service_token_name
            if config
            else "tve-private-dashboard-origin"
        ),
        dashboard_smoke_service_token_name=(
            config.cloudflare.dashboard_smoke_service_token_name
            if config
            else "tve-private-dashboard-smoke"
        ),
        worker_name=config.dashboard.worker_name if config else WORKER_NAME,
        live_surface_id=_configured_value(
            values, "TVE_LIVE_SURFACE_ID", config.surface.live_surface_id if config else None
        ),
        expected_surface_sha256=_configured_value(
            values,
            "TVE_EXPECTED_SURFACE_SHA256",
            config.surface.expected_surface_sha256 if config else None,
        ),
    )


def is_loopback_hostname(hostname: str) -> bool:
    normalized = hostname.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_hostname(raw_hostname: str | None, label: str) -> list[str]:
    if not raw_hostname:
        return [f"{label} is required"]
    if len(raw_hostname) > 253 or raw_hostname.endswith("."):
        return [f"{label} must be a DNS hostname without a trailing dot"]
    labels = raw_hostname.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(part) for part in labels):
        return [f"{label} must be a DNS hostname, not a URL or wildcard"]
    return []


def validate_remote_origin(raw_origin: str | None, expected_hostname: str | None) -> list[str]:
    if not raw_origin:
        return ["TVE_SURFACE_API_ORIGIN is required"]
    try:
        parsed = urlsplit(raw_origin)
        hostname = parsed.hostname
        parsed_port = parsed.port
    except ValueError:
        return ["TVE_SURFACE_API_ORIGIN is malformed"]
    if parsed.scheme != "https" or not hostname:
        return ["TVE_SURFACE_API_ORIGIN must be an HTTPS remote origin"]
    if is_loopback_hostname(hostname):
        return ["TVE_SURFACE_API_ORIGIN must be remote HTTPS for deployment"]
    if parsed.username or parsed.password or parsed.path not in ("", "/"):
        return ["TVE_SURFACE_API_ORIGIN must not contain userinfo or a path"]
    if parsed.query or parsed.fragment or parsed_port is not None and parsed_port == 0:
        return ["TVE_SURFACE_API_ORIGIN must not contain a query, fragment, or invalid port"]
    if expected_hostname and hostname.lower() != expected_hostname.lower():
        return ["TVE_SURFACE_API_ORIGIN hostname must match TVE_SURFACE_ORIGIN_HOSTNAME"]
    return []


def _validate_credential_pair(
    client_id: str | None, client_secret: str | None, label: str
) -> list[str]:
    if bool(client_id) != bool(client_secret):
        return [f"{label} client ID and client secret must be configured together"]
    if client_id is not None and not client_id.strip():
        return [f"{label} client ID must not be empty or whitespace"]
    if client_secret is not None and not client_secret.strip():
        return [f"{label} client secret must not be empty or whitespace"]
    if client_id is not None and client_id.strip() != client_id:
        return [f"{label} client ID must not contain surrounding whitespace"]
    if client_secret is not None and client_secret.strip() != client_secret:
        return [f"{label} client secret must not contain surrounding whitespace"]
    return []


def validate_inputs(
    inputs: DeploymentInputs,
    *,
    require_cloudflare: bool = True,
    require_live_service_tokens: bool = True,
    allow_missing_surface_service_token: bool = False,
    allow_missing_dashboard_service_token: bool = False,
    require_snapshot: bool = False,
) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_hostname(inputs.dashboard_hostname, "TVE_DASHBOARD_HOSTNAME"))
    errors.extend(
        validate_hostname(inputs.surface_origin_hostname, "TVE_SURFACE_ORIGIN_HOSTNAME")
    )
    if (
        inputs.dashboard_hostname
        and inputs.surface_origin_hostname
        and inputs.dashboard_hostname.lower() == inputs.surface_origin_hostname.lower()
    ):
        errors.append(
            "TVE_DASHBOARD_HOSTNAME and TVE_SURFACE_ORIGIN_HOSTNAME must be different"
        )
    errors.extend(validate_remote_origin(inputs.surface_origin, inputs.surface_origin_hostname))
    errors.extend(
        _validate_credential_pair(
            inputs.surface_access_client_id,
            inputs.surface_access_client_secret,
            "SURFACE_API_ACCESS",
        )
    )
    if (
        not allow_missing_surface_service_token
        and (not inputs.surface_access_client_id or not inputs.surface_access_client_secret)
    ):
        errors.append(
            "SURFACE_API_ACCESS_CLIENT_ID and SURFACE_API_ACCESS_CLIENT_SECRET are required"
        )
    if (
        not inputs.dashboard_identity_email
        or inputs.dashboard_identity_email.strip() != inputs.dashboard_identity_email
        or "@" not in inputs.dashboard_identity_email
    ):
        errors.append("TVE_DASHBOARD_ACCESS_EMAIL must be the owner-selected IdP email")
    if require_live_service_tokens:
        errors.extend(
            _validate_credential_pair(
                inputs.dashboard_access_client_id,
                inputs.dashboard_access_client_secret,
                "TVE_DASHBOARD_ACCESS",
            )
        )
        if (
            not allow_missing_dashboard_service_token
            and (not inputs.dashboard_access_client_id or not inputs.dashboard_access_client_secret)
        ):
            errors.append(
                "TVE_DASHBOARD_ACCESS_CLIENT_ID and "
                "TVE_DASHBOARD_ACCESS_CLIENT_SECRET are required for automated Dashboard live smoke"
            )
    if inputs.surface_port < 1 or inputs.surface_port > 65535:
        errors.append("TVE_SURFACE_PORT must be between 1 and 65535")
    if require_cloudflare:
        if not inputs.account_id or not _ACCOUNT_ID.fullmatch(inputs.account_id):
            errors.append(f"{ACCOUNT_ID} must be a 32-character Cloudflare account ID")
        if not inputs.api_token or not inputs.api_token.strip():
            errors.append(f"{API_TOKEN} must be supplied through the environment or secret manager")
        if inputs.tunnel_id and inputs.tunnel_name:
            errors.append(f"{TUNNEL_ID} and {TUNNEL_NAME} must not both be configured")
        if not inputs.tunnel_id and not inputs.tunnel_name:
            errors.append(f"{TUNNEL_ID} or {TUNNEL_NAME} is required")
        if inputs.tunnel_id and not _UUID.fullmatch(inputs.tunnel_id):
            errors.append(f"{TUNNEL_ID} must be a UUID")
        if not inputs.zone_id:
            errors.append(f"{ZONE_ID} is required to create/check the origin DNS CNAME")
        if not inputs.dashboard_zone_id or not _ACCOUNT_ID.fullmatch(inputs.dashboard_zone_id):
            errors.append(
                f"{DASHBOARD_ZONE_ID} must be a 32-character Cloudflare zone ID"
            )
    if require_snapshot:
        if not inputs.snapshot_path:
            errors.append("TVE_SURFACE_SNAPSHOT_PATH is required for the origin process")
        elif not Path(inputs.snapshot_path).is_file():
            errors.append("TVE_SURFACE_SNAPSHOT_PATH must point to an existing file")
    return errors


def _redact(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _messages(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "Cloudflare API returned a non-JSON error"
    entries = payload.get("errors") or payload.get("messages") or []
    messages = []
    if isinstance(entries, list):
        for entry in entries[:3]:
            if isinstance(entry, dict):
                code = entry.get("code")
                message = entry.get("message")
                if message:
                    messages.append(f"{code}: {message}" if code else str(message))
    return "; ".join(messages) or "Cloudflare API request failed"


class CloudflareAPI:
    def __init__(self, account_id: str, api_token: str, redactions: tuple[str, ...] = ()):
        self.account_id = account_id
        self.api_token = api_token
        self.redactions = redactions

    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"https://api.cloudflare.com/client/v4{path}"
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, method=method, data=body, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            try:
                detail = json.loads(error.read())
            except (OSError, json.JSONDecodeError):
                detail = None
            raise DeploymentError(
                f"Cloudflare API {method} {path} failed with HTTP {error.code}: "
                f"{_redact(_messages(detail), (self.api_token, *self.redactions))}"
            ) from None
        except URLError as error:
            raise DeploymentError(
                f"Cloudflare API {method} {path} was unreachable: {error.reason}"
            ) from None
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            raise DeploymentError(f"Cloudflare API {method} {path} returned invalid JSON") from None
        if not isinstance(decoded, dict) or decoded.get("success") is not True:
            raise DeploymentError(
                f"Cloudflare API {method} {path} failed: "
                f"{_redact(_messages(decoded), (self.api_token, *self.redactions))}"
            )
        return decoded

    def account_path(self, suffix: str) -> str:
        return f"/accounts/{quote(self.account_id, safe='')}{suffix}"

    def zone_path(self, zone_id: str, suffix: str) -> str:
        return f"/zones/{quote(zone_id, safe='')}{suffix}"


def resolve_cloudflare_inputs(inputs: DeploymentInputs) -> DeploymentInputs:
    """Resolve account/zone IDs from the configured zone when possible.

    IDs are Cloudflare resource facts, not user configuration.  The project
    config may cache them, but a token plus a zone name is sufficient for the
    deployment helper to discover them.  This function performs GET requests
    only and never creates or updates a Cloudflare resource.
    """

    if not inputs.api_token or not inputs.zone_name:
        return inputs
    needs_zone = not inputs.zone_id or not inputs.account_id
    needs_dashboard_zone = not inputs.dashboard_zone_id
    if not needs_zone and not needs_dashboard_zone:
        return inputs

    api = CloudflareAPI(inputs.account_id or "", inputs.api_token, (inputs.api_token,))
    query = urlencode({"name": inputs.zone_name, "status": "active", "per_page": 100})
    zones = _complete_list(api.request("GET", f"/zones?{query}"), "Cloudflare zone")
    matches = [
        zone
        for zone in zones
        if isinstance(zone, dict)
        and str(zone.get("name", "")).rstrip(".").lower()
        == inputs.zone_name.rstrip(".").lower()
    ]
    if len(matches) != 1:
        raise DeploymentError(
            f"Cloudflare zone lookup for {inputs.zone_name} returned {len(matches)} exact matches; "
            "refusing to guess account or zone IDs"
        )
    zone = matches[0]
    discovered_zone_id = zone.get("id")
    account = zone.get("account")
    discovered_account_id = account.get("id") if isinstance(account, dict) else None
    if not isinstance(discovered_zone_id, str) or not discovered_zone_id:
        raise DeploymentError("Cloudflare zone lookup did not return a stable zone ID")
    if not isinstance(discovered_account_id, str) or not discovered_account_id:
        raise DeploymentError("Cloudflare zone lookup did not return a stable account ID")
    if inputs.account_id and inputs.account_id.lower() != discovered_account_id.lower():
        raise DeploymentError(
            "configured Cloudflare account ID does not match the selected zone; "
            "refusing to continue"
        )
    if inputs.zone_id and inputs.zone_id.lower() != discovered_zone_id.lower():
        raise DeploymentError(
            "configured Cloudflare zone ID does not match the selected zone; refusing to continue"
        )
    return replace(
        inputs,
        account_id=inputs.account_id or discovered_account_id,
        zone_id=inputs.zone_id or discovered_zone_id,
        dashboard_zone_id=inputs.dashboard_zone_id or discovered_zone_id,
    )


def _result(response: Mapping[str, Any]) -> Any:
    return response.get("result")


def _complete_list(response: Mapping[str, Any], label: str) -> list[Any]:
    result = _result(response)
    if not isinstance(result, list):
        raise DeploymentError(f"{label} list returned an unexpected shape")
    result_info = response.get("result_info")
    total_count = result_info.get("total_count") if isinstance(result_info, dict) else None
    if not isinstance(total_count, int) or total_count != len(result):
        raise DeploymentError(
            f"{label} list is incomplete or lacks reliable pagination metadata; "
            "refusing to continue"
        )
    return result


def _find_service_token(api: CloudflareAPI, client_id: str) -> dict[str, Any] | None:
    result = _complete_list(
        api.request("GET", api.account_path("/access/service_tokens?per_page=100")),
        "Cloudflare service-token",
    )
    for token in result:
        if isinstance(token, dict) and token.get("client_id") == client_id:
            return token
    return None


def ensure_service_token(
    api: CloudflareAPI,
    client_id: str | None,
    client_secret: str | None,
    *,
    name: str,
    create: bool,
) -> ServiceToken:
    if client_id and client_secret:
        token = _find_service_token(api, client_id)
        if token is None or not token.get("id"):
            raise DeploymentError(
                f"service-token client ID for {name} was not found; create it with the documented "
                "Cloudflare Access API or use the explicit create flag"
            )
        return ServiceToken(str(token["id"]), client_id, client_secret)
    if not create:
        raise DeploymentError(
            f"{name} service-token credentials are missing; refusing to create a token implicitly"
        )
    response = api.request(
        "POST",
        api.account_path("/access/service_tokens"),
        {"name": name, "duration": "8760h", "enabled": True},
    )
    token = _result(response)
    if not isinstance(token, dict) or not token.get("id") or not token.get("client_id"):
        raise DeploymentError(f"Cloudflare did not return a usable {name} service token")
    created_secret = token.get("client_secret")
    if not isinstance(created_secret, str) or not created_secret:
        raise DeploymentError(
            f"Cloudflare did not return the one-time {name} client secret; refusing to continue"
        )
    return ServiceToken(str(token["id"]), str(token["client_id"]), created_secret)


def _access_policy(decision: str, include: list[dict[str, Any]]) -> dict[str, Any]:
    return {"decision": decision, "include": include}


def _app_domain(app: Mapping[str, Any]) -> str | None:
    targets = _app_targets(app)
    if targets:
        return targets[0].split("/", 1)[0].lower()
    return None


def _app_targets(app: Mapping[str, Any]) -> list[str]:
    targets: list[str] = []
    domain = app.get("domain")
    if isinstance(domain, str):
        targets.append(domain)
    domains = app.get("self_hosted_domains")
    if isinstance(domains, list):
        targets.extend(target for target in domains if isinstance(target, str))
    return targets


def _target_hostname(target: str) -> str:
    return target.partition("/")[0].rstrip(".").lower()


def _target_covers_hostname(target: str, hostname: str) -> bool:
    expected = hostname.rstrip(".").lower()
    target_host = _target_hostname(target)
    return target_host == expected or (
        target_host.startswith("*.") and expected.endswith(target_host[1:])
    )


def _target_is_exact_hostname(target: str, hostname: str) -> bool:
    _, separator, path = target.partition("/")
    return (
        _target_hostname(target) == hostname.rstrip(".").lower()
        and (not separator or path == "")
    )


def _app_has_exact_hostname(app: Mapping[str, Any], hostname: str) -> bool:
    return any(
        _target_is_exact_hostname(target, hostname) for target in _app_targets(app)
    )


def _app_covers_hostname(app: Mapping[str, Any], hostname: str) -> bool:
    return any(_target_covers_hostname(target, hostname) for target in _app_targets(app))


def _app_has_non_exact_target(app: Mapping[str, Any], hostname: str) -> bool:
    return any(
        _target_covers_hostname(target, hostname)
        and not _target_is_exact_hostname(target, hostname)
        for target in _app_targets(app)
    )


def _verify_access_app_targets(
    apps: list[Any], hostnames: tuple[str, ...]
) -> None:
    relevant_hostnames = tuple(hostname for hostname in hostnames if hostname)
    for app in apps:
        if not isinstance(app, dict):
            continue
        covered = [
            hostname
            for hostname in relevant_hostnames
            if _app_covers_hostname(app, hostname)
        ]
        if len(covered) > 1:
            raise DeploymentError(
                "one Access application overlaps the Dashboard and M6-B origin hostnames; "
                "refusing ambiguous policy configuration"
            )
    for hostname in relevant_hostnames:
        matching = [
            app
            for app in apps
            if isinstance(app, dict) and _app_covers_hostname(app, hostname)
        ]
        exact = [
            app
            for app in matching
            if _app_has_exact_hostname(app, hostname)
        ]
        if len(exact) > 1:
            raise DeploymentError(
                f"multiple exact Access applications cover {hostname}; "
                "refusing ambiguous policy configuration"
            )
        if any(_app_has_non_exact_target(app, hostname) for app in matching):
            raise DeploymentError(
                f"a path or wildcard Access application overlaps {hostname}; "
                "refusing ambiguous policy configuration"
            )
        if len(matching) != len(exact):
            raise DeploymentError(
                f"a path or wildcard Access application overlaps {hostname}; "
                "refusing ambiguous policy configuration"
            )


def ensure_access_app(
    api: CloudflareAPI,
    hostname: str,
    *,
    name: str,
    policies: list[dict[str, Any]],
) -> dict[str, Any]:
    response = api.request("GET", api.account_path("/access/apps?per_page=100"))
    apps = _complete_list(response, "Cloudflare Access application")
    existing = next(
        (
            app
            for app in apps
            if isinstance(app, dict) and _app_has_exact_hostname(app, hostname)
        ),
        None,
    )
    desired = {
        "domain": hostname,
        "type": "self_hosted",
        "name": name,
        "app_launcher_visible": False,
        "auto_redirect_to_identity": False,
        "policies": policies,
    }
    if existing and existing.get("id"):
        existing_id = quote(str(existing["id"]), safe="")
        return _result(
            api.request("PUT", api.account_path(f"/access/apps/{existing_id}"), desired)
        )
    return _result(api.request("POST", api.account_path("/access/apps"), desired))


def _tunnel_ingress(hostname: str, port: int) -> list[dict[str, str]]:
    return [
        {"hostname": hostname, "service": f"http://127.0.0.1:{port}"},
        {"service": "http_status:404"},
    ]


def ensure_tunnel(
    api: CloudflareAPI,
    inputs: DeploymentInputs,
    *,
    create: bool,
) -> str:
    if inputs.tunnel_id:
        tunnel_id = inputs.tunnel_id
        tunnel = _result(
            api.request("GET", api.account_path(f"/cfd_tunnel/{quote(tunnel_id, safe='')}"))
        )
        if not isinstance(tunnel, dict) or tunnel.get("config_src") != "cloudflare":
            raise DeploymentError(
                "the configured tunnel is not remotely managed; use the checked-in local ingress "
                "template or select a cloudflare-managed tunnel"
            )
    elif create and inputs.tunnel_name:
        response = api.request(
            "POST",
            api.account_path("/cfd_tunnel"),
            {"name": inputs.tunnel_name, "config_src": "cloudflare"},
        )
        tunnel = _result(response)
        if not isinstance(tunnel, dict) or not tunnel.get("id"):
            raise DeploymentError("Cloudflare did not return the created tunnel ID")
        tunnel_id = str(tunnel["id"])
    else:
        raise DeploymentError("a tunnel ID is required, or pass --create-tunnel with a tunnel name")
    api.request(
        "PUT",
        api.account_path(f"/cfd_tunnel/{quote(tunnel_id, safe='')}/configurations"),
        {
            "config": {
                "ingress": _tunnel_ingress(
                    inputs.surface_origin_hostname or "", inputs.surface_port
                )
            }
        },
    )
    return tunnel_id


def ensure_origin_dns(api: CloudflareAPI, inputs: DeploymentInputs, tunnel_id: str) -> str:
    if not inputs.zone_id or not inputs.surface_origin_hostname:
        raise DeploymentError("zone ID and origin hostname are required for DNS configuration")
    query = urlencode({"type": "CNAME", "name": inputs.surface_origin_hostname, "per_page": 100})
    path = api.zone_path(inputs.zone_id, f"/dns_records?{query}")
    records = _complete_list(
        api.request("GET", path),
        "Cloudflare DNS record",
    )
    target = f"{tunnel_id}.cfargotunnel.com"
    valid_records = [record for record in records if isinstance(record, dict)]
    if len(valid_records) > 1:
        raise DeploymentError(
            "the origin hostname has multiple CNAME records; refusing ambiguous DNS configuration"
        )
    matching = valid_records[0] if valid_records else None
    payload = {
        "type": "CNAME",
        "name": inputs.surface_origin_hostname,
        "content": target,
        "ttl": 1,
        "proxied": True,
    }
    if matching:
        if (
            matching.get("type") != "CNAME"
            or str(matching.get("content", "")).rstrip(".") != target
        ):
            raise DeploymentError(
                "the origin hostname already has a conflicting DNS record; refusing to overwrite it"
            )
        return str(matching.get("id", ""))
    zone = quote(inputs.zone_id, safe="")
    created = _result(api.request("POST", f"/zones/{zone}/dns_records", payload))
    if not isinstance(created, dict) or not created.get("id"):
        raise DeploymentError("Cloudflare did not return the created origin DNS record")
    return str(created["id"])


def _verify_no_worker_routes(
    api: CloudflareAPI, zone_id: str, worker_name: str = WORKER_NAME
) -> None:
    routes = _complete_list(
        api.request("GET", api.zone_path(zone_id, "/workers/routes?per_page=100")),
        "Dashboard Worker route",
    )
    _check_no_worker_routes(routes, worker_name)


def _check_no_worker_routes(routes: list[Any], worker_name: str = WORKER_NAME) -> None:
    attached = [
        route
        for route in routes
        if isinstance(route, dict) and route.get("script") == worker_name
    ]
    if attached:
        details = ", ".join(
            f"{route.get('id', '<unknown>')}:{route.get('pattern', '<unknown>')}"
            for route in attached
        )
        raise DeploymentError(
            "the Dashboard Worker still has zone routes outside its protected custom domain: "
            + details
        )


def _check_worker_subdomain_disabled(subdomain: Any) -> None:
    if not isinstance(subdomain, dict):
        raise DeploymentError("Worker subdomain response had an unexpected shape")
    if subdomain.get("enabled") is not False or subdomain.get("previews_enabled") is not False:
        raise DeploymentError("workers.dev or Worker preview ingress is not explicitly disabled")


def _verify_pre_mutation_state(
    api: CloudflareAPI,
    dashboard_zone_id: str,
    dashboard_hostname: str,
    surface_origin_hostname: str,
    worker_name: str = WORKER_NAME,
) -> None:
    """Read every alternate-ingress list completely before any live mutation."""

    subdomain = _result(
        api.request("GET", api.account_path(f"/workers/scripts/{worker_name}/subdomain"))
    )
    _check_worker_subdomain_disabled(subdomain)

    domains = _complete_list(
        api.request(
            "GET",
            api.account_path(f"/workers/domains?service={worker_name}&per_page=100"),
        ),
        "Worker domain",
    )
    actual_domains = {
        str(domain.get("hostname", "")).rstrip(".").lower()
        for domain in domains
        if isinstance(domain, dict)
    }
    unexpected_domains = actual_domains - {dashboard_hostname.rstrip(".").lower()}
    if unexpected_domains:
        raise DeploymentError(
            "the Dashboard Worker has alternate custom domains before deployment: "
            + ", ".join(sorted(unexpected_domains))
        )

    apps = _complete_list(
        api.request("GET", api.account_path("/access/apps?per_page=100")),
        "Access application",
    )
    _verify_access_app_targets(apps, (dashboard_hostname, surface_origin_hostname))
    _complete_list(
        api.request("GET", api.account_path("/access/service_tokens?per_page=100")),
        "Cloudflare service-token",
    )
    _complete_list(
        api.request("GET", api.account_path("/cfd_tunnel?per_page=100")),
        "Cloudflare Tunnel",
    )
    routes = _complete_list(
        api.request(
            "GET",
            api.zone_path(dashboard_zone_id, "/workers/routes?per_page=100"),
        ),
        "Dashboard Worker route",
    )
    _check_no_worker_routes(routes, worker_name)


def _run(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    secrets: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
) -> None:
    print("$ " + " ".join(command))
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        env=None if environment is None else dict(environment),
    )
    output = _redact(result.stdout + result.stderr, secrets)
    if output.strip():
        print(output.rstrip())
    if result.returncode != 0:
        raise DeploymentError(f"command exited with {result.returncode}: {command[0]}")


def build_production_worker(inputs: DeploymentInputs) -> Path:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        raise DeploymentError("pnpm is required to build the Dashboard")
    _run([pnpm, "--dir", str(DASHBOARD), "build"], cwd=ROOT)
    if not BUILD_CONFIG.is_file():
        raise DeploymentError(f"Dashboard build did not produce {BUILD_CONFIG}")
    try:
        config = json.loads(BUILD_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentError(f"generated Wrangler config is unreadable: {error}") from None
    config["account_id"] = inputs.account_id
    config["name"] = inputs.worker_name
    config["workers_dev"] = False
    config["preview_urls"] = False
    config["vars"] = {"SURFACE_API_ORIGIN": inputs.surface_origin}
    config["routes"] = [
        {
            "pattern": inputs.dashboard_hostname,
            "custom_domain": True,
            "enabled": True,
            "previews_enabled": False,
        }
    ]
    BUILD_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return BUILD_CONFIG


def deploy_worker(config_path: Path, inputs: DeploymentInputs) -> None:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        raise DeploymentError("pnpm is required to deploy the Dashboard")
    runtime_secrets = tuple(
        value
        for value in (
            inputs.api_token,
            inputs.surface_access_client_id,
            inputs.surface_access_client_secret,
            inputs.dashboard_access_client_id,
            inputs.dashboard_access_client_secret,
        )
        if value
    )
    _run(
        [
            pnpm,
            "exec",
            "wrangler",
            "deploy",
            "--config",
            str(config_path),
            "--no-bundle",
            "--strict",
            "--message",
            "M6-C2 private Dashboard deployment",
        ],
        cwd=DASHBOARD,
        secrets=runtime_secrets,
    )
    for name, value in (
        (ORIGIN_CLIENT_ID, inputs.surface_access_client_id),
        (ORIGIN_CLIENT_SECRET, inputs.surface_access_client_secret),
    ):
        if value is None:
            raise DeploymentError(f"{name} was unexpectedly absent after preflight")
        _run(
            [pnpm, "exec", "wrangler", "secret", "put", name, "--config", str(config_path)],
            cwd=DASHBOARD,
            input_text=value + "\n",
            secrets=(value, inputs.api_token or ""),
        )


def _verify_access_policy(
    api: CloudflareAPI,
    app: Mapping[str, Any],
    *,
    hostname: str,
    required_decisions: set[str],
    exact_decisions: set[str],
    expected_service_token_id: str,
    expected_email: str | None = None,
) -> None:
    app_id = app.get("id")
    if not isinstance(app_id, str) or not app_id:
        raise DeploymentError(f"Access application for {hostname} has no stable ID")
    policies = _result(
        api.request(
            "GET",
            api.account_path(f"/access/apps/{quote(app_id, safe='')}/policies"),
        )
    )
    if not isinstance(policies, list):
        raise DeploymentError(f"Access policies for {hostname} returned an unexpected shape")
    decisions = {
        policy["decision"]
        for policy in policies
        if isinstance(policy, dict) and isinstance(policy.get("decision"), str)
    }
    if (
        "bypass" in decisions
        or not required_decisions.issubset(decisions)
        or decisions != exact_decisions
    ):
        raise DeploymentError(
            f"Access application for {hostname} is not fail-closed: decisions={sorted(decisions)}"
        )
    service_token_ids = {
        str(rule["service_token"]["token_id"])
        for policy in policies
        if isinstance(policy, dict)
        and policy.get("decision") == SERVICE_AUTH_DECISION
        and isinstance(policy.get("include"), list)
        for rule in policy["include"]
        if isinstance(rule, dict)
        and isinstance(rule.get("service_token"), dict)
        and rule["service_token"].get("token_id")
    }
    if expected_service_token_id not in service_token_ids:
        raise DeploymentError(
            f"Access application for {hostname} does not include the expected service token"
        )
    if expected_email is not None:
        emails = {
            str(rule["email"]["email"])
            for policy in policies
            if isinstance(policy, dict)
            and policy.get("decision") == "allow"
            and isinstance(policy.get("include"), list)
            for rule in policy["include"]
            if isinstance(rule, dict)
            and isinstance(rule.get("email"), dict)
            and rule["email"].get("email")
        }
        if expected_email.lower() not in {email.lower() for email in emails}:
            raise DeploymentError(
                f"Access application for {hostname} does not include the selected owner identity"
            )


def verify_cloudflare(
    api: CloudflareAPI,
    inputs: DeploymentInputs,
    tunnel_id: str,
    *,
    origin_token_id: str,
    dashboard_token_id: str,
) -> None:
    subdomain = _result(
        api.request("GET", api.account_path(f"/workers/scripts/{inputs.worker_name}/subdomain"))
    )
    _check_worker_subdomain_disabled(subdomain)

    query = urlencode({"service": inputs.worker_name, "per_page": 100})
    domains = _complete_list(
        api.request("GET", api.account_path(f"/workers/domains?{query}")),
        "Worker domain",
    )
    actual_domains = {
        str(domain.get("hostname", "")).lower()
        for domain in domains
        if isinstance(domain, dict)
    }
    expected_domain = (inputs.dashboard_hostname or "").lower()
    if actual_domains != {expected_domain}:
        raise DeploymentError(
            "Worker custom-domain set does not exactly match the protected Dashboard hostname: "
            + ", ".join(sorted(actual_domains))
        )
    if not inputs.dashboard_zone_id:
        raise DeploymentError("Dashboard zone ID is required for route bypass verification")
    _verify_no_worker_routes(api, inputs.dashboard_zone_id, inputs.worker_name)

    origin_domain = (inputs.surface_origin_hostname or "").lower()
    apps = _complete_list(
        api.request("GET", api.account_path("/access/apps?per_page=100")),
        "Access application",
    )
    _verify_access_app_targets(apps, (expected_domain, origin_domain))
    dashboard_apps = [
        app
        for app in apps
        if isinstance(app, dict) and _app_has_exact_hostname(app, expected_domain)
    ]
    if len(dashboard_apps) != 1:
        raise DeploymentError("the Dashboard hostname has no Access application")
    origin_apps = [
        app
        for app in apps
        if isinstance(app, dict) and _app_has_exact_hostname(app, origin_domain)
    ]
    if len(origin_apps) != 1:
        raise DeploymentError("the M6-B origin hostname has no Access application")
    _verify_access_policy(
        api,
        dashboard_apps[0],
        hostname=expected_domain,
        required_decisions={"allow", SERVICE_AUTH_DECISION},
        exact_decisions={"allow", SERVICE_AUTH_DECISION},
        expected_service_token_id=dashboard_token_id,
        expected_email=inputs.dashboard_identity_email,
    )
    _verify_access_policy(
        api,
        origin_apps[0],
        hostname=origin_domain,
        required_decisions={SERVICE_AUTH_DECISION},
        exact_decisions={SERVICE_AUTH_DECISION},
        expected_service_token_id=origin_token_id,
    )

    tunnel = _result(
        api.request(
            "GET",
            api.account_path(f"/cfd_tunnel/{quote(tunnel_id, safe='')}/configurations"),
        )
    )
    if not isinstance(tunnel, dict) or not isinstance(tunnel.get("config"), dict):
        raise DeploymentError("Tunnel configuration response had an unexpected shape")
    ingress = tunnel["config"].get("ingress")
    if ingress != _tunnel_ingress(inputs.surface_origin_hostname or "", inputs.surface_port):
        raise DeploymentError("Tunnel ingress is not exactly the loopback-only M6-B mapping")


def run_origin(snapshot: str, port: int) -> int:
    snapshot_path = Path(snapshot).expanduser()
    if not snapshot_path.is_file():
        raise DeploymentError("the explicit snapshot path does not exist")
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
    print("Starting loopback-only M6-B origin with an explicit snapshot path")
    return subprocess.call(command, cwd=ROOT)


def _surface_identity(inputs: DeploymentInputs) -> tuple[str, str | None]:
    """Read the public identity fields from the explicit surface snapshot only."""

    surface_id = inputs.live_surface_id
    expected_hash = inputs.expected_surface_sha256
    if inputs.snapshot_path:
        try:
            payload = json.loads(Path(inputs.snapshot_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeploymentError(
                f"cannot read explicit surface snapshot identity: {exc}"
            ) from None
        if not isinstance(payload, dict):
            raise DeploymentError("explicit surface snapshot must contain a JSON object")
        discovered_surface_id = payload.get("surface_id")
        discovered_hash = payload.get("content_sha256")
        if surface_id is None and isinstance(discovered_surface_id, str):
            surface_id = discovered_surface_id
        if expected_hash is None and isinstance(discovered_hash, str):
            expected_hash = discovered_hash
    if not surface_id or not re.fullmatch(r"[0-9a-f]{64}", surface_id):
        raise DeploymentError(
            "TVE_LIVE_SURFACE_ID or a lowercase 64-character surface_id in the explicit "
            "snapshot is required for live smoke"
        )
    if expected_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise DeploymentError(
            "TVE_EXPECTED_SURFACE_SHA256 or snapshot content_sha256 must be a lowercase "
            "64-character hash"
        )
    return surface_id, expected_hash


def run_live_smoke(
    inputs: DeploymentInputs,
    *,
    project_config_path: str | None,
) -> None:
    """Run the standalone live smoke with generated credentials in memory only."""

    surface_id, expected_hash = _surface_identity(inputs)
    environment = dict(os.environ)
    environment.pop(API_TOKEN, None)
    if inputs.dashboard_hostname:
        environment["TVE_DASHBOARD_URL"] = f"https://{inputs.dashboard_hostname}"
    if inputs.surface_origin:
        environment["TVE_SURFACE_API_ORIGIN"] = inputs.surface_origin
    if inputs.surface_access_client_id:
        environment[ORIGIN_CLIENT_ID] = inputs.surface_access_client_id
    if inputs.surface_access_client_secret:
        environment[ORIGIN_CLIENT_SECRET] = inputs.surface_access_client_secret
    if inputs.dashboard_access_client_id:
        environment[DASHBOARD_CLIENT_ID] = inputs.dashboard_access_client_id
    if inputs.dashboard_access_client_secret:
        environment[DASHBOARD_CLIENT_SECRET] = inputs.dashboard_access_client_secret
    environment["TVE_LIVE_SURFACE_ID"] = surface_id
    if expected_hash:
        environment["TVE_EXPECTED_SURFACE_SHA256"] = expected_hash
    command = [sys.executable, str(ROOT / "scripts" / "dashboard_live_smoke.py")]
    if project_config_path:
        command.extend(["--project-config", project_config_path])
    _run(
        command,
        cwd=ROOT,
        environment=environment,
        secrets=tuple(
            value
            for value in (
                inputs.surface_access_client_id,
                inputs.surface_access_client_secret,
                inputs.dashboard_access_client_id,
                inputs.dashboard_access_client_secret,
            )
            if value
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser(
        "preflight", help="validate production inputs without mutation"
    )
    preflight.add_argument("--project-config", default=None)
    deploy = subparsers.add_parser("deploy", help="build and deploy with explicit --apply")
    deploy.add_argument("--project-config", default=None)
    deploy.add_argument("--apply", action="store_true", help="allow Cloudflare mutations")
    deploy.add_argument("--dry-run", action="store_true", help="run Wrangler validation only")
    deploy.add_argument("--create-tunnel", action="store_true")
    deploy.add_argument("--create-origin-service-token", action="store_true")
    deploy.add_argument("--create-dashboard-service-token", action="store_true")
    deploy.add_argument(
        "--live-smoke",
        action="store_true",
        help="run authenticated live smoke using generated service credentials in memory",
    )
    verify = subparsers.add_parser("verify", help="read and verify live Cloudflare resources")
    verify.add_argument("--project-config", default=None)
    verify.add_argument("--tunnel-id", help="override TVE_CLOUDFLARE_TUNNEL_ID")
    origin = subparsers.add_parser("origin", help="serve explicit snapshots on loopback")
    origin.add_argument("--project-config", default=None)
    origin.add_argument("--snapshot", default=None)
    origin.add_argument("--port", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inputs = resolve_cloudflare_inputs(read_inputs(config_path=args.project_config))
        if args.command == "origin":
            snapshot = args.snapshot or inputs.snapshot_path
            port = args.port or inputs.surface_port
            if not snapshot:
                raise DeploymentError("--snapshot or TVE_SURFACE_SNAPSHOT_PATH is required")
            return run_origin(snapshot, port)

        create_origin_token = getattr(args, "create_origin_service_token", False)
        create_dashboard_token = getattr(args, "create_dashboard_service_token", False)
        non_mutating_service_token_check = args.command == "preflight" or (
            args.command == "deploy" and args.dry_run
        )
        errors = validate_inputs(
            inputs,
            require_cloudflare=True,
            require_live_service_tokens=True,
            allow_missing_surface_service_token=(
                create_origin_token or non_mutating_service_token_check
            ),
            allow_missing_dashboard_service_token=(
                create_dashboard_token or non_mutating_service_token_check
            ),
            require_snapshot=args.command in {"preflight", "deploy"},
        )
        if errors:
            print("M6-C2 preflight failed closed:")
            for error in errors:
                print(f"- {error}")
            return 2
        if args.command == "preflight":
            print(
                "M6-C2 preflight passed: HTTPS origin, explicit custom domain, Cloudflare account, "
                "Access identity, Tunnel/DNS inputs and explicit snapshot are present; "
                "service tokens may be supplied or explicitly created during deploy"
            )
            return 0

        account_id = inputs.account_id
        api_token = inputs.api_token
        if account_id is None or api_token is None:
            raise DeploymentError("Cloudflare credentials disappeared after preflight")
        api = CloudflareAPI(
            account_id,
            api_token,
            tuple(
                secret
                for secret in (
                    inputs.surface_access_client_id,
                    inputs.surface_access_client_secret,
                    inputs.dashboard_access_client_id,
                    inputs.dashboard_access_client_secret,
                )
                if secret
            ),
        )
        if args.command == "verify":
            tunnel_id = args.tunnel_id or inputs.tunnel_id
            if tunnel_id is None:
                raise DeploymentError("--tunnel-id or TVE_CLOUDFLARE_TUNNEL_ID is required")
            surface_token = ensure_service_token(
                api,
                inputs.surface_access_client_id,
                inputs.surface_access_client_secret,
                name=inputs.origin_service_token_name,
                create=False,
            )
            dashboard_token = ensure_service_token(
                api,
                inputs.dashboard_access_client_id,
                inputs.dashboard_access_client_secret,
                name=inputs.dashboard_smoke_service_token_name,
                create=False,
            )
            verify_cloudflare(
                api,
                inputs,
                tunnel_id,
                origin_token_id=surface_token.token_id,
                dashboard_token_id=dashboard_token.token_id,
            )
            print(
                f"M6-C2 Cloudflare resource verification passed for Worker {inputs.worker_name}, "
                f"Dashboard {inputs.dashboard_hostname}, origin {inputs.surface_origin_hostname}, "
                f"Tunnel {tunnel_id}"
            )
            return 0
        config_path = build_production_worker(inputs)
        if args.command == "deploy" and args.dry_run:
            pnpm = shutil.which("pnpm")
            if not pnpm:
                raise DeploymentError("pnpm is required for Wrangler dry-run")
            _run(
                [
                    pnpm,
                    "exec",
                    "wrangler",
                    "deploy",
                    "--config",
                    str(config_path),
                    "--no-bundle",
                    "--dry-run",
                    "--strict",
                ],
                cwd=DASHBOARD,
            )
            print("M6-C2 Wrangler dry-run passed; no Cloudflare mutation was attempted")
            return 0
        if not args.apply:
            raise DeploymentError(
                "deploy requires --apply or --dry-run; refusing implicit mutation"
            )
        if (create_origin_token or create_dashboard_token) and not args.live_smoke:
            raise DeploymentError(
                "one-time generated Access secrets would otherwise be lost; add --live-smoke "
                "so the authenticated smoke consumes them in memory"
            )

        # Read checks and Wrangler dry-run happen before any POST/PUT/secret mutation.
        if not inputs.dashboard_zone_id:
            raise DeploymentError("Dashboard zone ID is required for route bypass verification")
        _verify_pre_mutation_state(
            api,
            inputs.dashboard_zone_id,
            inputs.dashboard_hostname or "",
            inputs.surface_origin_hostname or "",
            inputs.worker_name,
        )

        surface_token = ensure_service_token(
            api,
            inputs.surface_access_client_id,
            inputs.surface_access_client_secret,
            name=inputs.origin_service_token_name,
            create=args.create_origin_service_token,
        )
        api.redactions = (*api.redactions, surface_token.client_id, surface_token.client_secret)
        if not inputs.surface_access_client_id or not inputs.surface_access_client_secret:
            inputs = replace(
                inputs,
                surface_access_client_id=surface_token.client_id,
                surface_access_client_secret=surface_token.client_secret,
            )
        dashboard_token = ensure_service_token(
            api,
            inputs.dashboard_access_client_id,
            inputs.dashboard_access_client_secret,
            name=inputs.dashboard_smoke_service_token_name,
            create=create_dashboard_token,
        )
        api.redactions = (*api.redactions, dashboard_token.client_id, dashboard_token.client_secret)
        if not inputs.dashboard_access_client_id or not inputs.dashboard_access_client_secret:
            inputs = replace(
                inputs,
                dashboard_access_client_id=dashboard_token.client_id,
                dashboard_access_client_secret=dashboard_token.client_secret,
            )
        ensure_access_app(
            api,
            inputs.surface_origin_hostname or "",
            name=inputs.origin_access_app_name,
            policies=[
                _access_policy(
                    SERVICE_AUTH_DECISION,
                    [{"service_token": {"token_id": surface_token.token_id}}],
                )
            ],
        )
        ensure_access_app(
            api,
            inputs.dashboard_hostname or "",
            name=inputs.dashboard_access_app_name,
            policies=[
                _access_policy(
                    SERVICE_AUTH_DECISION,
                    [{"service_token": {"token_id": dashboard_token.token_id}}],
                ),
                _access_policy("allow", [{"email": {"email": inputs.dashboard_identity_email}}]),
            ],
        )
        tunnel_id = ensure_tunnel(api, inputs, create=args.create_tunnel)
        dns_record_id = ensure_origin_dns(api, inputs, tunnel_id)
        deploy_worker(config_path, inputs)
        verify_cloudflare(
            api,
            inputs,
            tunnel_id,
            origin_token_id=surface_token.token_id,
            dashboard_token_id=dashboard_token.token_id,
        )
        print(
            f"M6-C2 Cloudflare deployment passed resource checks: Worker={inputs.worker_name}, "
            f"Dashboard={inputs.dashboard_hostname}, origin={inputs.surface_origin_hostname}, "
            f"Tunnel={tunnel_id}, DNS record={dns_record_id}"
        )
        print(
            "Cloudflare resource verification passed; the Dashboard -> Worker -> authenticated "
            "origin -> M6-B live smoke follows."
        )
        if args.live_smoke:
            run_live_smoke(inputs, project_config_path=args.project_config)
            print("M6-C2 live smoke passed")
        return 0
    except DeploymentError as error:
        print(f"M6-C2 deployment failed closed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
