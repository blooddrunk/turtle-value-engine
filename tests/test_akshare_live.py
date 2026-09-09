"""Opt-in smoke checks for the real AKShare endpoints.

These tests are intentionally skipped unless ``TVE_RUN_AKSHARE_LIVE=1`` is
set.  They are never part of ordinary network-independent CI.
"""

import os

import pytest

from turtle_value_engine.providers import (
    AKShareProvider,
    DataCategory,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("TVE_RUN_AKSHARE_LIVE") != "1",
    reason="live AKShare integration is opt-in via TVE_RUN_AKSHARE_LIVE=1",
)


def test_live_a_quote_endpoint_returns_the_requested_listing():
    record = AKShareProvider().fetch_category(DataCategory.MARKET_QUOTE, "SH600000")
    assert record.request.entity_id == "SH600000"
    assert record.raw_payload is not None


def test_live_h_quote_endpoint_returns_the_requested_listing():
    record = AKShareProvider().fetch_category(DataCategory.MARKET_QUOTE, "HK00700")
    assert record.request.entity_id == "HK00700"
    assert record.raw_payload is not None
