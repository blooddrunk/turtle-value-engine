from __future__ import annotations

from scripts.dashboard_deploy import (
    SERVICE_AUTH_DECISION,
    DeploymentInputs,
    _access_policy,
    _app_has_exact_hostname,
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


def test_cloudflare_service_auth_uses_non_identity_api_decision() -> None:
    assert SERVICE_AUTH_DECISION == "non_identity"
    assert _access_policy(SERVICE_AUTH_DECISION, [{"service_token": {"token_id": "token"}}]) == {
        "decision": "non_identity",
        "include": [{"service_token": {"token_id": "token"}}],
    }


def test_production_inputs_reject_ambiguous_or_colliding_boundaries() -> None:
    same_host = _valid_inputs(
        dashboard_hostname="surface.example.com",
        tunnel_name="also-set",
    )
    errors = validate_inputs(same_host)
    assert "TVE_DASHBOARD_HOSTNAME and TVE_SURFACE_ORIGIN_HOSTNAME must be different" in errors
    assert (
        "TVE_CLOUDFLARE_TUNNEL_ID and TVE_CLOUDFLARE_TUNNEL_NAME must not both be configured"
        in errors
    )

    whitespace = _valid_inputs(surface_access_client_id=" ")
    assert any("SURFACE_API_ACCESS client ID" in error for error in validate_inputs(whitespace))


def test_access_app_verifier_requires_the_exact_hostname_not_a_path_subtree() -> None:
    assert _app_has_exact_hostname({"domain": "dashboard.example.com"}, "dashboard.example.com")
    assert not _app_has_exact_hostname(
        {"domain": "dashboard.example.com/admin"}, "dashboard.example.com"
    )
