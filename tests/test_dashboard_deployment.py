from __future__ import annotations

from scripts.dashboard_deploy import (
    DeploymentInputs,
    _tunnel_ingress,
    validate_inputs,
    validate_remote_origin,
)


def _valid_inputs(**overrides: object) -> DeploymentInputs:
    values: dict[str, object] = {
        "account_id": "a" * 32,
        "api_token": "api-token-from-secret-manager",
        "dashboard_hostname": "dashboard.example.com",
        "dashboard_identity_email": "owner@example.com",
        "dashboard_access_client_id": "dashboard-client-id",
        "dashboard_access_client_secret": "dashboard-client-secret",
        "surface_origin": "https://surface.example.com",
        "surface_origin_hostname": "surface.example.com",
        "surface_access_client_id": "surface-client-id",
        "surface_access_client_secret": "surface-client-secret",
        "tunnel_id": "123e4567-e89b-42d3-a456-426614174000",
        "tunnel_name": None,
        "zone_id": "b" * 32,
        "snapshot_path": None,
        "surface_port": 8787,
    }
    values.update(overrides)
    return DeploymentInputs(**values)  # type: ignore[arg-type]


def test_production_inputs_are_validated_without_resolving_secrets() -> None:
    assert validate_inputs(_valid_inputs()) == []


def test_remote_origin_requires_https_and_exact_origin_shape() -> None:
    for origin in (
        "http://surface.example.com",
        "https://user:password@surface.example.com",
        "https://surface.example.com/path",
        "https://surface.example.com/?query=1",
        "https://surface.example.com/#fragment",
    ):
        assert validate_remote_origin(origin, "surface.example.com")


def test_missing_surface_token_is_only_allowed_for_explicit_create_flow() -> None:
    inputs = _valid_inputs(surface_access_client_id=None, surface_access_client_secret=None)
    errors = validate_inputs(inputs, allow_missing_surface_service_token=True)
    assert errors == []
    assert validate_inputs(inputs)


def test_tunnel_ingress_is_loopback_only_and_has_terminal_404() -> None:
    assert _tunnel_ingress("surface.example.com", 8787) == [
        {"hostname": "surface.example.com", "service": "http://127.0.0.1:8787"},
        {"service": "http_status:404"},
    ]
