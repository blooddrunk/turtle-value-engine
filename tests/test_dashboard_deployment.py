from __future__ import annotations

import json
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
    resolve_cloudflare_inputs,
    run_live_smoke,
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


def test_missing_api_token_does_not_turn_discoverable_ids_into_owner_inputs() -> None:
    errors = validate_inputs(
        _valid_inputs(
            account_id=None,
            api_token=None,
            tunnel_id=None,
            tunnel_name="tve-private-dashboard-origin",
            zone_id=None,
            dashboard_zone_id=None,
        )
    )
    assert errors == [
        "CLOUDFLARE_API_TOKEN must be supplied through the environment or secret manager"
    ]


def test_generated_production_config_contains_no_runtime_secrets(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "wrangler.json"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    monkeypatch.setattr(dashboard_deploy, "BUILD_CONFIG", config_path)
    monkeypatch.setattr(dashboard_deploy, "DASHBOARD", dashboard_dir)
    monkeypatch.setattr(dashboard_deploy.shutil, "which", lambda name: "/usr/bin/pnpm")

    def fake_run(command: list[str], *, cwd: Path, **kwargs: object) -> None:
        assert command == ["/usr/bin/pnpm", "--dir", str(dashboard_dir), "build"]
        assert cwd == Path.cwd()
        config_path.write_text(json.dumps({"assets": {"directory": "./dist/client"}}))

    monkeypatch.setattr(dashboard_deploy, "_run", fake_run)
    inputs = _valid_inputs()
    generated = dashboard_deploy.build_production_worker(inputs)
    payload = json.loads(generated.read_text())
    serialized = json.dumps(payload)

    assert payload["vars"] == {"SURFACE_API_ORIGIN": inputs.surface_origin}
    assert payload["workers_dev"] is False
    assert payload["preview_urls"] is False
    assert payload["routes"] == [
        {
            "pattern": inputs.dashboard_hostname,
            "custom_domain": True,
            "enabled": True,
            "previews_enabled": False,
        }
    ]
    for secret in (
        inputs.api_token,
        inputs.surface_access_client_id,
        inputs.surface_access_client_secret,
        inputs.dashboard_access_client_id,
        inputs.dashboard_access_client_secret,
    ):
        assert secret not in serialized


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


def test_missing_dashboard_token_is_only_allowed_for_explicit_create_flow() -> None:
    inputs = _valid_inputs(
        dashboard_access_client_id=None, dashboard_access_client_secret=None
    )
    assert validate_inputs(inputs, allow_missing_dashboard_service_token=True) == []
    assert validate_inputs(inputs)


def test_live_smoke_uses_snapshot_identity_and_keeps_generated_secrets_out_of_command(
    monkeypatch, tmp_path: Path
) -> None:
    snapshot = tmp_path / "surface.json"
    snapshot.write_text(
        json.dumps({"surface_id": "a" * 64, "content_sha256": "b" * 64}),
        encoding="utf-8",
    )
    inputs = _valid_inputs(
        snapshot_path=str(snapshot),
        live_surface_id=None,
        expected_surface_sha256=None,
    )
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        observed["command"] = command
        observed["environment"] = kwargs["environment"]

    monkeypatch.setattr(dashboard_deploy, "_run", fake_run)
    run_live_smoke(inputs, project_config_path=None)

    command = observed["command"]
    environment = observed["environment"]
    assert isinstance(command, list)
    assert all(secret not in command for secret in (inputs.surface_access_client_secret,))
    assert isinstance(environment, dict)
    assert environment["TVE_LIVE_SURFACE_ID"] == "a" * 64
    assert environment["TVE_EXPECTED_SURFACE_SHA256"] == "b" * 64
    assert environment["SURFACE_API_ACCESS_CLIENT_SECRET"] == inputs.surface_access_client_secret
    assert "CLOUDFLARE_API_TOKEN" not in environment


def test_cloudflare_ids_are_discovered_from_one_configured_zone_without_mutation(monkeypatch):
    class FakeAPI:
        def __init__(self, account_id: str, api_token: str, redactions: tuple[str, ...]):
            assert account_id == ""
            assert api_token == "api-token"
            assert redactions == ("api-token",)

        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            assert path == "/zones?name=example.com&status=active&per_page=100"
            return {
                "success": True,
                "result": [
                    {
                        "id": "b" * 32,
                        "name": "example.com",
                        "account": {"id": "a" * 32},
                    }
                ],
                "result_info": {"total_count": 1},
            }

    monkeypatch.setattr(dashboard_deploy, "CloudflareAPI", FakeAPI)
    resolved = resolve_cloudflare_inputs(
        _valid_inputs(
            account_id=None,
            api_token="api-token",
            zone_id=None,
            dashboard_zone_id=None,
            zone_name="example.com",
        )
    )
    assert resolved.account_id == "a" * 32
    assert resolved.zone_id == "b" * 32
    assert resolved.dashboard_zone_id == "b" * 32


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

    class EmptyWithoutPaginationAPI(FakeAPI):
        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            assert path == f"/zones/{'c' * 32}/workers/routes?per_page=100"
            return {"result": []}

    _verify_no_worker_routes(EmptyWithoutPaginationAPI([]), "c" * 32)

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


def test_pre_mutation_state_allows_first_deploy_missing_worker() -> None:
    class MissingWorkerAPI:
        def account_path(self, suffix: str) -> str:
            return f"/accounts/{'a' * 32}{suffix}"

        def zone_path(self, zone_id: str, suffix: str) -> str:
            return f"/zones/{zone_id}{suffix}"

        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            if path.endswith("/subdomain"):
                raise dashboard_deploy.CloudflareAPIError(
                    "Worker does not exist",
                    method=method,
                    path=path,
                    status=404,
                    codes=("10007",),
                )
            return {"result": [], "result_info": {"total_count": 0}}

    _verify_pre_mutation_state(
        MissingWorkerAPI(),
        "c" * 32,
        "dashboard.example.com",
        "surface.example.com",
    )


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
