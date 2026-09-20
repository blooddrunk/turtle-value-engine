from __future__ import annotations

import pytest

from scripts.dashboard_live_smoke import (
    LIVE_SMOKE_USER_AGENT,
    LiveSmokeError,
    _assert_distinct_origins,
    _assert_pair,
    _request,
)


def test_live_smoke_service_credentials_require_a_complete_trimmed_pair(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "client-id")
    monkeypatch.setenv("CLIENT_SECRET", "client-secret")
    assert _assert_pair("CLIENT_ID", "CLIENT_SECRET") == ("client-id", "client-secret")

    monkeypatch.setenv("CLIENT_SECRET", " ")
    with pytest.raises(LiveSmokeError, match="configured together"):
        _assert_pair("CLIENT_ID", "CLIENT_SECRET")

    monkeypatch.setenv("CLIENT_SECRET", "client-secret ")
    with pytest.raises(LiveSmokeError, match="surrounding whitespace"):
        _assert_pair("CLIENT_ID", "CLIENT_SECRET")


def test_live_smoke_requires_distinct_dashboard_and_origin_hostnames():
    _assert_distinct_origins("https://dashboard.example.com", "https://surface.example.com")
    with pytest.raises(LiveSmokeError, match="different hostnames"):
        _assert_distinct_origins(
            "https://dashboard.example.com", "https://DASHBOARD.example.com"
        )


def test_live_smoke_uses_explicit_non_browser_user_agent(monkeypatch):
    observed = {}

    class FakeResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    class FakeOpener:
        def open(self, request, timeout):
            observed["request"] = request
            observed["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(
        "scripts.dashboard_live_smoke.build_opener", lambda handler: FakeOpener()
    )
    result = _request("https://surface.example.com/healthz")

    assert result.status == 200
    assert observed["request"].get_header("User-agent") == LIVE_SMOKE_USER_AGENT
    assert observed["timeout"] == 10
