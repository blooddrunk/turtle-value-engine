"""Repeatable M6-C2 live Dashboard -> Worker -> authenticated origin smoke.

All credentials are read from environment variables. The script never prints
request headers, token values, response bodies containing surface data, or
redirect locations. It deliberately does not follow redirects so an Access
login redirect is distinguishable from an authenticated Dashboard response.

Required environment variables:

    TVE_DASHBOARD_URL                 https://dashboard.example.com
    TVE_SURFACE_API_ORIGIN            https://surface.example.com
    SURFACE_API_ACCESS_CLIENT_ID      Worker -> origin service token ID
    SURFACE_API_ACCESS_CLIENT_SECRET  Worker -> origin service token secret
    TVE_DASHBOARD_ACCESS_CLIENT_ID    smoke -> Dashboard Access service token ID
    TVE_DASHBOARD_ACCESS_CLIENT_SECRET smoke -> Dashboard Access service token secret
    TVE_LIVE_SURFACE_ID               known frozen surface ID

Optional:

    TVE_EXPECTED_SURFACE_SHA256       expected hash for the known surface
    TVE_ALT_DASHBOARD_URLS             comma-separated alternate URLs to block
    TVE_ALT_ORIGIN_URLS                comma-separated alternate origin URLs to block
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class LiveSmokeError(RuntimeError):
    """A machine-verifiable live smoke failure."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value and value.strip() else None


def _require(name: str) -> str:
    value = _env(name)
    if not value:
        raise LiveSmokeError(f"{name} is required")
    return value


def _validate_https_url(raw_url: str, name: str) -> str:
    try:
        parsed = urlsplit(raw_url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise LiveSmokeError(f"{name} is malformed") from None
    if parsed.scheme != "https" or not hostname:
        raise LiveSmokeError(f"{name} must be an HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LiveSmokeError(f"{name} must not contain userinfo, query, or fragment")
    if parsed.path not in ("", "/"):
        raise LiveSmokeError(f"{name} must be an origin URL without a path")
    return raw_url.rstrip("/")


def _request(
    url: str, *, headers: Mapping[str, str] | None = None, method: str = "GET"
) -> HttpResult:
    request = Request(
        url, method=method, headers={"Accept": "application/json", **(headers or {})}
    )
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=10) as response:
            return HttpResult(
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read(),
            )
    except HTTPError as error:
        return HttpResult(
            error.code,
            {key.lower(): value for key, value in error.headers.items()},
            error.read(),
        )
    except URLError as error:
        raise LiveSmokeError(f"request to {url} failed: {error.reason}") from None


def _json(result: HttpResult, label: str) -> object:
    try:
        return json.loads(result.body)
    except json.JSONDecodeError:
        raise LiveSmokeError(f"{label} returned non-JSON HTTP {result.status}") from None


def _assert_blocked(result: HttpResult, label: str) -> None:
    if result.status not in {301, 302, 303, 307, 308, 401, 403}:
        raise LiveSmokeError(
            f"{label} was not blocked by an authentication boundary: HTTP {result.status}"
        )


def _assert_pair(client_id_name: str, client_secret_name: str) -> tuple[str, str]:
    client_id = _env(client_id_name)
    client_secret = _env(client_secret_name)
    if bool(client_id) != bool(client_secret):
        raise LiveSmokeError(
            f"{client_id_name} and {client_secret_name} must be configured together"
        )
    if not client_id or not client_secret:
        raise LiveSmokeError(f"{client_id_name} and {client_secret_name} are required")
    if client_id.strip() != client_id or client_secret.strip() != client_secret:
        raise LiveSmokeError(
            f"{client_id_name} and {client_secret_name} must not contain surrounding whitespace"
        )
    return client_id, client_secret


def _assert_origin_service_auth(origin_url: str, origin_headers: Mapping[str, str]) -> None:
    unauthenticated = _request(origin_url + "/healthz")
    _assert_blocked(unauthenticated, "unauthenticated origin /healthz")
    invalid_credentials = _request(
        origin_url + "/healthz",
        headers={
            "CF-Access-Client-Id": "invalid-m6-c2-client-id",
            "CF-Access-Client-Secret": "invalid-m6-c2-client-secret",
        },
    )
    _assert_blocked(invalid_credentials, "origin /healthz with invalid service credentials")
    authenticated = _request(origin_url + "/healthz", headers=origin_headers)
    if authenticated.status != 200:
        raise LiveSmokeError(
            "service-authenticated origin /healthz returned "
            f"HTTP {authenticated.status}"
        )
    payload = _json(authenticated, "authenticated origin /healthz")
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise LiveSmokeError("authenticated origin /healthz did not return M6-B local health")


def _assert_dashboard_chain(
    dashboard_url: str,
    dashboard_headers: Mapping[str, str],
    surface_id: str,
    expected_hash: str | None,
) -> None:
    unauthenticated_root = _request(dashboard_url + "/")
    _assert_blocked(unauthenticated_root, "unauthenticated Dashboard root")

    root = _request(dashboard_url + "/", headers=dashboard_headers)
    if root.status != 200 or b"Turtle Value Engine" not in root.body:
        raise LiveSmokeError(
            f"authenticated Dashboard root returned HTTP {root.status} "
            "without Dashboard HTML"
        )
    health = _request(dashboard_url + "/api/healthz", headers=dashboard_headers)
    if health.status != 200:
        raise LiveSmokeError(f"authenticated Dashboard /api/healthz returned HTTP {health.status}")
    health_payload = _json(health, "Dashboard /api/healthz")
    if not isinstance(health_payload, dict) or health_payload.get("status") != "ok":
        raise LiveSmokeError("Dashboard /api/healthz did not return M6-B health")

    listed = _request(dashboard_url + "/api/v1/surfaces", headers=dashboard_headers)
    if listed.status != 200:
        raise LiveSmokeError(f"Dashboard list returned HTTP {listed.status}")
    list_payload = _json(listed, "Dashboard surface list")
    if not isinstance(list_payload, dict) or not isinstance(list_payload.get("surfaces"), list):
        raise LiveSmokeError("Dashboard list did not return the M6-B metadata shape")
    ids = {item.get("surface_id") for item in list_payload["surfaces"] if isinstance(item, dict)}
    if surface_id not in ids:
        raise LiveSmokeError("known surface ID was not returned by the live Dashboard list")

    detail_url = dashboard_url + "/api/v1/surfaces/" + surface_id
    detail = _request(detail_url, headers=dashboard_headers)
    if detail.status != 200:
        raise LiveSmokeError(f"known Dashboard detail returned HTTP {detail.status}")
    detail_payload = _json(detail, "Dashboard surface detail")
    if not isinstance(detail_payload, dict):
        raise LiveSmokeError("Dashboard detail did not return a JSON object")
    if detail_payload.get("surface_id") != surface_id:
        raise LiveSmokeError("live Dashboard detail changed the surface_id")
    content_hash = detail_payload.get("content_sha256")
    if not isinstance(content_hash, str) or (expected_hash and content_hash != expected_hash):
        raise LiveSmokeError("live Dashboard detail changed or failed to preserve content_sha256")
    etag = detail.headers.get("etag")
    if not etag:
        raise LiveSmokeError("live Dashboard detail did not return an ETag")
    cached = _request(detail_url, headers={**dashboard_headers, "If-None-Match": etag})
    if cached.status != 304:
        raise LiveSmokeError(
            f"live Dashboard ETag revalidation returned HTTP {cached.status}, expected 304"
        )

    unknown = _request(dashboard_url + "/api/v1/surfaces/" + "0" * 64, headers=dashboard_headers)
    if unknown.status != 404:
        raise LiveSmokeError(f"unknown live surface returned HTTP {unknown.status}, expected 404")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        mutation = _request(
            detail_url,
            headers=dashboard_headers,
            method=method,
        )
        if mutation.status != 405:
            raise LiveSmokeError(
                f"live {method} mutation returned HTTP {mutation.status}, expected 405"
            )


def _csv_urls(name: str) -> list[str]:
    return [value.strip().rstrip("/") for value in (_env(name) or "").split(",") if value.strip()]


def main() -> int:
    try:
        dashboard_url = _validate_https_url(_require("TVE_DASHBOARD_URL"), "TVE_DASHBOARD_URL")
        origin_url = _validate_https_url(
            _require("TVE_SURFACE_API_ORIGIN"), "TVE_SURFACE_API_ORIGIN"
        )
        origin_id, origin_secret = _assert_pair(
            "SURFACE_API_ACCESS_CLIENT_ID", "SURFACE_API_ACCESS_CLIENT_SECRET"
        )
        dashboard_id, dashboard_secret = _assert_pair(
            "TVE_DASHBOARD_ACCESS_CLIENT_ID", "TVE_DASHBOARD_ACCESS_CLIENT_SECRET"
        )
        surface_id = _require("TVE_LIVE_SURFACE_ID")
        if not re.fullmatch(r"[0-9a-f]{64}", surface_id):
            raise LiveSmokeError("TVE_LIVE_SURFACE_ID must be a lowercase 64-character surface ID")
        expected_hash = _env("TVE_EXPECTED_SURFACE_SHA256")
        if expected_hash and not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise LiveSmokeError(
                "TVE_EXPECTED_SURFACE_SHA256 must be a lowercase 64-character hash"
            )

        _assert_origin_service_auth(
            origin_url,
            {
                "CF-Access-Client-Id": origin_id,
                "CF-Access-Client-Secret": origin_secret,
            },
        )
        _assert_dashboard_chain(
            dashboard_url,
            {
                "CF-Access-Client-Id": dashboard_id,
                "CF-Access-Client-Secret": dashboard_secret,
            },
            surface_id,
            expected_hash,
        )
        for alternate in _csv_urls("TVE_ALT_DASHBOARD_URLS"):
            alternate_url = _validate_https_url(alternate, "TVE_ALT_DASHBOARD_URLS")
            _assert_blocked(_request(alternate_url), alternate)
        for alternate in _csv_urls("TVE_ALT_ORIGIN_URLS"):
            _assert_blocked(
                _request(_validate_https_url(alternate, "TVE_ALT_ORIGIN_URLS") + "/healthz"),
                alternate,
            )
        print(
            "M6-C2 live smoke passed: unauthenticated Dashboard/origin blocked; "
            "authenticated Dashboard -> Worker -> origin -> M6-B "
            "health/list/detail/404/mutations/ETag"
        )
        return 0
    except LiveSmokeError as error:
        print(f"M6-C2 live smoke failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
