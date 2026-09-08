import pytest

from .stage_support import EXPECTATIONS, FIXTURE_NAMES, load_stage_results

_EXPECTATION_BY_FIXTURE = {item["fixture"]: item for item in EXPECTATIONS["fixtures"]}


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_documented_fixture_reaches_every_implemented_stage(fixture_name):
    """Use scenario metadata for coverage without treating it as engine output."""

    normalized_input, cdc, net_cash, through_return, valuation, gates = load_stage_results(
        fixture_name
    )
    expectation = _EXPECTATION_BY_FIXTURE[fixture_name]

    assert expectation["engine_validation_status"].startswith("Expected scenario only")
    assert expectation["covers_rules"]
    assert normalized_input.analysis_id
    assert cdc.year_results
    assert net_cash.flags == list(dict.fromkeys(net_cash.flags))
    assert through_return.flags == list(dict.fromkeys(through_return.flags))
    assert valuation.flags == list(dict.fromkeys(valuation.flags))
    assert gates.universe.rules
