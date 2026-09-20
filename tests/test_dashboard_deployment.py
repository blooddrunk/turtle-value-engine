from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.dashboard_deploy as dashboard_deploy
from scripts.dashboard_deploy import (
    SERVICE_AUTH_DECISION,
    DeploymentError,
    DeploymentInputs,
    _access_policy,
    _app_has_exact_hostname,
    _run,
    _tunnel_ingress,
    _verify_access_app_targets,
    _verify_no_worker_routes,
    _verify_pre_mutation_state,
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
        "dashboard_zone_id": "c" * 32,
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

    missing_dashboard_zone = _valid_inputs(dashboard_zone_id=None)
    assert any(
        "TVE_DASHBOARD_ZONE_ID" in error for error in validate_inputs(missing_dashboard_zone)
    )


def test_access_app_verifier_requires_the_exact_hostname_not_a_path_subtree() -> None:
    assert _app_has_exact_hostname({"domain": "dashboard.example.com"}, "dashboard.example.com")
    assert not _app_has_exact_hostname(
        {"domain": "dashboard.example.com/admin"}, "dashboard.example.com"
    )
    with pytest.raises(DeploymentError, match="path or wildcard"):
        _verify_access_app_targets(
            [{"domain": "dashboard.example.com/admin"}],
            ("dashboard.example.com",),
        )
    with pytest.raises(DeploymentError, match="path or wildcard"):
        _verify_access_app_targets(
            [{"domain": "*.example.com"}],
            ("dashboard.example.com",),
        )
    with pytest.raises(DeploymentError, match="path or wildcard"):
        _verify_access_app_targets(
            [
                {
                    "domain": "dashboard.example.com",
                    "self_hosted_domains": ["dashboard.example.com/admin"],
                }
            ],
            ("dashboard.example.com",),
        )


def test_subprocess_output_redacts_runtime_secrets(monkeypatch, capsys) -> None:
    secret = "runtime-secret-value"

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0,
            stdout=f"stdout {secret}\n",
            stderr=f"stderr {secret}\n",
        )

    monkeypatch.setattr(dashboard_deploy.subprocess, "run", fake_run)
    _run(["fake-command"], cwd=Path.cwd(), secrets=(secret,))

    output = capsys.readouterr().out
    assert secret not in output
    assert output.count("<redacted>") == 2


def test_dashboard_route_verifier_fails_closed_on_legacy_worker_routes() -> None:
    class FakeAPI:
        def __init__(self, routes: list[dict[str, str]]) -> None:
            self.routes = routes

        def zone_path(self, zone_id: str, suffix: str) -> str:
            return f"/zones/{zone_id}{suffix}"

        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            assert path == f"/zones/{'c' * 32}/workers/routes?per_page=100"
            return {"result": self.routes, "result_info": {"total_count": len(self.routes)}}

    _verify_no_worker_routes(FakeAPI([]), "c" * 32)
    class PaginatedAPI(FakeAPI):
        def request(self, method: str, path: str) -> dict[str, object]:
            response = super().request(method, path)
            response["result_info"] = {"total_count": len(self.routes) + 1}
            return response

    with pytest.raises(DeploymentError, match="incomplete"):
        _verify_no_worker_routes(PaginatedAPI([]), "c" * 32)
    with pytest.raises(DeploymentError, match="zone routes outside"):
        _verify_no_worker_routes(
            FakeAPI(
                [
                    {
                        "id": "route-1",
                        "pattern": "dashboard.example.com/*",
                        "script": "tve-personal-dashboard",
                    }
                ]
            ),
            "c" * 32,
        )


def test_pre_mutation_state_requires_complete_cloudflare_lists() -> None:
    expected_paths = [
        f"/accounts/{'a' * 32}/workers/scripts/tve-personal-dashboard/subdomain",
        f"/accounts/{'a' * 32}/workers/domains?service=tve-personal-dashboard&per_page=100",
        f"/accounts/{'a' * 32}/access/apps?per_page=100",
        f"/accounts/{'a' * 32}/access/service_tokens?per_page=100",
        f"/accounts/{'a' * 32}/cfd_tunnel?per_page=100",
        f"/zones/{'c' * 32}/workers/routes?per_page=100",
    ]

    class FakeAPI:
        def __init__(self, *, incomplete_path: str | None = None) -> None:
            self.incomplete_path = incomplete_path
            self.paths: list[str] = []

        def account_path(self, suffix: str) -> str:
            return f"/accounts/{'a' * 32}{suffix}"

        def zone_path(self, zone_id: str, suffix: str) -> str:
            return f"/zones/{zone_id}{suffix}"

        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            self.paths.append(path)
            if path.endswith("/subdomain"):
                return {"result": {"enabled": False, "previews_enabled": False}}
            total_count = 2 if path == self.incomplete_path else 0
            return {"result": [], "result_info": {"total_count": total_count}}

    complete = FakeAPI()
    _verify_pre_mutation_state(
        complete,
        "c" * 32,
        "dashboard.example.com",
        "surface.example.com",
    )
    assert complete.paths == expected_paths

    incomplete = FakeAPI(incomplete_path=expected_paths[2])
    with pytest.raises(DeploymentError, match="incomplete"):
        _verify_pre_mutation_state(
            incomplete,
            "c" * 32,
            "dashboard.example.com",
            "surface.example.com",
        )
    assert incomplete.paths == expected_paths[:3]


def test_pre_mutation_state_rejects_alternate_worker_ingress() -> None:
    class FakeAPI:
        def __init__(
            self,
            *,
            subdomain: dict[str, bool] | None = None,
            domains: list[dict[str, str]] | None = None,
        ) -> None:
            self.subdomain = subdomain or {"enabled": False, "previews_enabled": False}
            self.domains = domains or []

        def account_path(self, suffix: str) -> str:
            return f"/accounts/{'a' * 32}{suffix}"

        def zone_path(self, zone_id: str, suffix: str) -> str:
            return f"/zones/{zone_id}{suffix}"

        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            if path.endswith("/subdomain"):
                return {"result": self.subdomain}
            if path.endswith("/workers/domains?service=tve-personal-dashboard&per_page=100"):
                return {
                    "result": self.domains,
                    "result_info": {"total_count": len(self.domains)},
                }
            return {"result": [], "result_info": {"total_count": 0}}

    with pytest.raises(DeploymentError, match="workers.dev"):
        _verify_pre_mutation_state(
            FakeAPI(subdomain={"enabled": True, "previews_enabled": False}),
            "c" * 32,
            "dashboard.example.com",
            "surface.example.com",
        )
    with pytest.raises(DeploymentError, match="explicitly disabled"):
        _verify_pre_mutation_state(
            FakeAPI(subdomain={"enabled": False}),
            "c" * 32,
            "dashboard.example.com",
            "surface.example.com",
        )
    with pytest.raises(DeploymentError, match="alternate custom domains"):
        _verify_pre_mutation_state(
            FakeAPI(domains=[{"hostname": "legacy.example.com"}]),
            "c" * 32,
            "dashboard.example.com",
            "surface.example.com",
        )
