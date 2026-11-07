"""Issue #65 operator-journey coverage: the complete offline A-share research
chain must be reachable through the real CLI alone.

The journey under test is the one an operator can follow from the README:
``tve analyze`` (with explicit artifact outputs) -> ``tve surface build``
(consuming the analysis, decision trace and research report files) ->
``tve surface validate``.  Before this coverage the two halves existed only
in separate tests: the analyze CLI wrote nothing to disk, and the surface
build CLI was fed by library-built artifacts, so no test proved that an
operator without Python glue could produce a snapshot whose
``decision_trace_reference`` and ``research_report_reference`` are populated.
"""

import json
import socket
import urllib.request
from pathlib import Path

from turtle_value_engine.cli import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "healthy_cash_cow.json"


def _deny_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("the offline journey must make no network request")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)


def test_analyze_cli_emits_artifacts_and_full_surface_chain_is_reachable(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    analysis_path = tmp_path / "analysis.json"
    trace_path = tmp_path / "decision-trace.json"
    report_path = tmp_path / "research-report.json"
    snapshot_path = tmp_path / "snapshot.json"

    assert (
        main(
            [
                "analyze",
                "--input",
                str(FIXTURE),
                "--profile",
                "strict-v1",
                "--output",
                str(analysis_path),
                "--trace-output",
                str(trace_path),
                "--report-output",
                str(report_path),
            ]
        )
        == 0
    )
    stdout_analysis = json.loads(capsys.readouterr().out)
    assert stdout_analysis["profile_id"] == "strict-v1"

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    analysis_id = analysis["analysis_id"]
    assert analysis == stdout_analysis
    # The frozen fixture carries no structured assessment, so the journey must
    # surface the explicit fail-closed states rather than a confident pass.
    assert analysis["gates"]["business_quality"]["status"] == "NOT_EVALUATED"
    assert analysis["decision"]["state"] == "SPECIAL_REVIEW"
    assert trace["contract"] == "decision_trace_v1"
    assert trace["analysis_id"] == analysis_id
    assert report["contract"] == "research_report_v1"
    assert report["analysis"]["analysis_id"] == analysis_id
    assert report["decision_trace"]["analysis_id"] == analysis_id

    assert (
        main(
            [
                "surface",
                "build",
                "--analysis",
                str(analysis_path),
                "--trace",
                str(trace_path),
                "--report",
                str(report_path),
                "--output",
                str(snapshot_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["surface", "validate", "--input", str(snapshot_path)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["analysis_id"] == analysis_id
    assert validated["decision_trace_reference"] is not None
    assert validated["decision_trace_reference"]["artifact_id"] == analysis_id
    assert validated["research_report_reference"] is not None
    assert validated["research_report_reference"]["artifact_id"] is not None

    replay_path = tmp_path / "snapshot-replay.json"
    assert (
        main(
            [
                "surface",
                "build",
                "--analysis",
                str(analysis_path),
                "--trace",
                str(trace_path),
                "--report",
                str(report_path),
                "--output",
                str(replay_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert replay_path.read_bytes() == snapshot_path.read_bytes()


def test_analyze_cli_rejects_colliding_output_paths(tmp_path, capsys, monkeypatch):
    _deny_network(monkeypatch)
    shared = tmp_path / "shared.json"
    exit_code = main(
        [
            "analyze",
            "--input",
            str(FIXTURE),
            "--profile",
            "strict-v1",
            "--output",
            str(shared),
            "--trace-output",
            str(shared),
        ]
    )
    assert exit_code == 2
    assert "must be distinct" in capsys.readouterr().err
    assert not shared.exists()
