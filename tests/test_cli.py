import json

from turtle_value_engine.cli import main
from turtle_value_engine.models import CDCInput


def test_cdc_cli_emits_json(tmp_path, capsys, year_factory):
    inputs = CDCInput(
        years=[year_factory(f"FY{year}") for year in range(2021, 2026)],
        current_market_cap=1000,
    )
    input_path = tmp_path / "cdc-input.json"
    input_path.write_text(inputs.model_dump_json(), encoding="utf-8")

    exit_code = main(["cdc", "--input", str(input_path), "--profile", "strict-v1"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["normalized_parent_core_cdc"] == 64.0
    assert output["confidence"] == "HIGH"
