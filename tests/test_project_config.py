from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dashboard_deploy import read_inputs
from turtle_value_engine.config import (
    ProjectConfigError,
    load_project_config,
    write_project_config_template,
)


def test_checked_in_project_template_is_valid_and_derives_safe_hostnames() -> None:
    config = load_project_config(Path("config/project.example.toml"))

    assert config.schema_version == 1
    assert config.profiles.default == "strict-v1"
    assert config.network.default_policy == "deny"
    assert config.resolved_dashboard_hostname() is None
    assert config.resolved_origin_hostname() is None
    assert config.surface.snapshot_path == ".tve-private/surface/research-surface.json"
    assert config.secret_reference("api_token").env == "CLOUDFLARE_API_TOKEN"
    assert config.safe_summary()["secret_references"]["api_token"] == "CLOUDFLARE_API_TOKEN"


def test_safe_project_summary_never_contains_resolved_secret(monkeypatch) -> None:
    config = load_project_config(Path("config/project.example.toml"))
    sentinel = "cfut_runtime_secret_sentinel"
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", sentinel)

    assert sentinel not in repr(config.safe_summary())


def test_project_config_derives_cloudflare_values_without_ids_or_secrets(tmp_path: Path) -> None:
    source = Path("config/project.example.toml").read_text(encoding="utf-8")
    configured = source.replace('zone_name = ""', 'zone_name = "private.example.com"').replace(
        'dashboard_access_email = ""', 'dashboard_access_email = "owner@example.com"'
    )
    config_path = tmp_path / ".tve-private" / "project.toml"
    config_path.parent.mkdir()
    config_path.write_text(configured, encoding="utf-8")

    config = load_project_config(config_path)
    assert (
        config.resolved_dashboard_hostname()
        == "tve-private-dashboard.private.example.com"
    )
    assert config.resolved_origin_hostname() == "tve-private-surface.private.example.com"
    assert config.resolved_origin_url() == "https://tve-private-surface.private.example.com"
    assert config.cloudflare.account_id is None
    assert config.secret_value("api_token", {}) is None

    inputs = read_inputs(
        {
            "CLOUDFLARE_API_TOKEN": "token-from-secret-manager",
            "SURFACE_API_ACCESS_CLIENT_ID": "origin-id",
            "SURFACE_API_ACCESS_CLIENT_SECRET": "origin-secret",
            "TVE_DASHBOARD_ACCESS_CLIENT_ID": "dashboard-id",
            "TVE_DASHBOARD_ACCESS_CLIENT_SECRET": "dashboard-secret",
        },
        project_config=config,
    )
    assert inputs.dashboard_hostname == "tve-private-dashboard.private.example.com"
    assert inputs.surface_origin == "https://tve-private-surface.private.example.com"
    assert inputs.surface_origin_hostname == "tve-private-surface.private.example.com"
    assert inputs.tunnel_name == "tve-private-dashboard-origin"
    assert inputs.account_id is None


def test_environment_values_override_project_defaults_but_config_cannot_hold_secret_values(
    tmp_path: Path,
) -> None:
    source = Path("config/project.example.toml").read_text(encoding="utf-8")
    configured = source.replace('zone_name = ""', 'zone_name = "private.example.com"').replace(
        'dashboard_access_email = ""', 'dashboard_access_email = "owner@example.com"'
    )
    config_path = tmp_path / "project.toml"
    config_path.write_text(configured, encoding="utf-8")
    config = load_project_config(config_path)

    inputs = read_inputs(
        {
            "TVE_DASHBOARD_HOSTNAME": "tve-private-dashboard.override.example.com",
            "TVE_SURFACE_API_ORIGIN": "https://tve-private-surface.override.example.com",
            "TVE_SURFACE_ORIGIN_HOSTNAME": "tve-private-surface.override.example.com",
            "TVE_DASHBOARD_ACCESS_EMAIL": "override@example.com",
        },
        project_config=config,
    )
    assert inputs.dashboard_hostname == "tve-private-dashboard.override.example.com"
    assert inputs.surface_origin == "https://tve-private-surface.override.example.com"
    assert inputs.dashboard_identity_email == "override@example.com"

    with pytest.raises(ProjectConfigError, match="refusing to overwrite"):
        write_project_config_template(config_path)


def test_project_config_template_writer_is_explicit_and_reproducible(tmp_path: Path) -> None:
    path = write_project_config_template(tmp_path / ".tve-private/project.toml")
    assert path.is_file()
    assert load_project_config(path).schema_version == 1


def test_project_config_rejects_raw_secret_fields(tmp_path: Path) -> None:
    source = Path("config/project.example.toml").read_text(encoding="utf-8")
    malformed = source.replace(
        'dashboard_access_email = ""',
        'dashboard_access_email = "owner@example.com"\napi_token = "must-not-be-here"',
    )
    path = tmp_path / "project.toml"
    path.write_text(malformed, encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="credential references"):
        load_project_config(path)
