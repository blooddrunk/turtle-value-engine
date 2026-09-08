from pathlib import Path

import pytest

from turtle_value_engine.config import ProfileLoadError, load_profile


def test_load_strict_v1_from_repository_rules():
    profile = load_profile("strict-v1")

    assert profile.profile.id == "strict-v1"
    assert profile.cdc.continuity.lookback_years == 5
    assert profile.cdc.yield_bands.pass_ == 0.08
    assert profile.valuation.combine_constraints == "min"
    assert profile.valuation.tiers["turtle_entry"].cdc_yield == 0.10


def test_load_profile_rejects_unknown_yaml_field(tmp_path: Path):
    source = Path("rules/strict-v1.yaml").read_text(encoding="utf-8")
    malformed = source + "\nunknown_section:\n  value: 1\n"
    path = tmp_path / "malformed.yaml"
    path.write_text(malformed, encoding="utf-8")

    with pytest.raises(ProfileLoadError, match="invalid rule profile"):
        load_profile(path)
