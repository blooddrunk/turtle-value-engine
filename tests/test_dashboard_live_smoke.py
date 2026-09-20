from __future__ import annotations

import pytest

from scripts.dashboard_live_smoke import (
    LiveSmokeError,
    _assert_distinct_origins,
    _assert_pair,
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
