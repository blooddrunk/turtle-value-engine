"""Deterministic red/green coverage for the workflow action-pin guard.

The pre-change workflow text below reproduces the exact mutable tag references
that `ci/pin-action-shas-issue43-20261030` replaced (checkout@v7.0.1,
setup-python@v7.1.0, setup-node@v7.1.0); the guard must reject it, accept the
pinned repository workflows, and fail closed on every evasion class.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import scripts.check_workflow_action_pins as guard

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

PRE_CHANGE_WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v7.0.1

      - name: Set up Python
        uses: actions/setup-python@v7.1.0
        with:
          python-version: "3.11"
          cache: pip

      - name: Set up Node
        uses: actions/setup-node@v7.1.0
        with:
          node-version: "24"
"""

PINNED_STEP_TEMPLATE = """\
name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: One step
        uses: {reference}
"""

VERIFIED_PINS = {
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
    "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0",
    "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0",
}


def _write(tmp_path: Path, name: str, text: str) -> Path:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    path = workflows / name
    path.write_text(text, encoding="utf-8")
    return workflows


def test_guard_passes_on_repository_workflows() -> None:
    assert guard.main([str(WORKFLOWS)]) == 0


def test_guard_cli_passes_on_repository_workflows() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_workflow_action_pins.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all external 'uses:' references pinned" in result.stdout


def test_ci_workflow_uses_the_verified_pinned_shas() -> None:
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    for pin in VERIFIED_PINS:
        assert pin in text


def test_guard_fails_on_pre_change_mutable_tags(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "ci.yml", PRE_CHANGE_WORKFLOW)
    assert guard.main([str(workflows)]) == 1


def test_guard_reports_every_pre_change_reference(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "ci.yml", PRE_CHANGE_WORKFLOW)
    violations = guard.check_workflow_file(workflows / "ci.yml")
    joined = "\n".join(violations)
    for tag in ("actions/checkout@v7.0.1", "actions/setup-python@v7.1.0",
                "actions/setup-node@v7.1.0"):
        assert tag in joined
    assert "not pinned to a full 40-character commit SHA" in joined


def test_guard_fails_on_mutable_branch_reference(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "branch.yml", PINNED_STEP_TEMPLATE.format(
            reference="actions/checkout@main # v7.0.1"
        )
    )
    assert guard.main([str(workflows)]) == 1


def test_guard_fails_on_major_version_tag(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "major.yml", PINNED_STEP_TEMPLATE.format(
            reference="actions/setup-python@v7 # v7.1.0"
        )
    )
    assert guard.main([str(workflows)]) == 1


def test_guard_fails_on_sha_without_version_comment(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "nocomment.yml",
        PINNED_STEP_TEMPLATE.format(
            reference="actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        ),
    )
    violations = guard.check_workflow_file(workflows / "nocomment.yml")
    assert len(violations) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_uppercase_sha(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "upper.yml",
        PINNED_STEP_TEMPLATE.format(
            reference="actions/checkout@3D3C42E5AAC5BA805825DA76410C181273BA90B1 # v7.0.1"
        ),
    )
    assert guard.main([str(workflows)]) == 1


def test_guard_accepts_pinned_sha_with_version_comment(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "pinned.yml",
        PINNED_STEP_TEMPLATE.format(
            reference=(
                "actions/checkout@"
                "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
            )
        ),
    )
    assert guard.main([str(workflows)]) == 0


def test_guard_skips_local_actions(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "local.yml",
        PINNED_STEP_TEMPLATE.format(reference="./.github/actions/local-tool"),
    )
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_on_docker_reference(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "docker.yml",
        PINNED_STEP_TEMPLATE.format(reference="docker://alpine:3.20 # v3.20"),
    )
    violations = guard.check_workflow_file(workflows / "docker.yml")
    assert len(violations) == 1
    assert "cannot be commit-pinned" in violations[0]


def test_guard_fails_on_reference_without_at(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "noat.yml", PINNED_STEP_TEMPLATE.format(reference="actions/checkout")
    )
    violations = guard.check_workflow_file(workflows / "noat.yml")
    assert len(violations) == 1
    assert "carries no '@ref'" in violations[0]


def test_guard_fails_on_unparseable_yaml(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "broken.yml", "jobs: [unclosed\n  - {")
    violations = guard.check_workflow_file(workflows / "broken.yml")
    assert len(violations) == 1
    assert "unparseable workflow YAML" in violations[0]


def test_guard_fails_on_non_mapping_document(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "list.yml", "- just\n- a\n- list\n")
    violations = guard.check_workflow_file(workflows / "list.yml")
    assert len(violations) == 1
    assert "not a YAML mapping" in violations[0]


def test_guard_fails_when_uses_text_hides_in_run_block(tmp_path: Path) -> None:
    workflow = """\
name: CI
on:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Pinned
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Script echoing action text
        run: |
          set -e
          uses: actions/setup-python@v7.1.0
          echo "$uses"
"""
    workflows = _write(tmp_path, "hidden.yml", workflow)
    violations = guard.check_workflow_file(workflows / "hidden.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to YAML keys" in violation for violation in violations)


def test_guard_fails_when_yaml_value_escapes_line_scan(tmp_path: Path) -> None:
    workflow = (
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Folded\n"
        "        uses: >\n"
        "          actions/checkout@v7.0.1\n"
    )
    workflows = _write(tmp_path, "folded.yml", workflow)
    violations = guard.check_workflow_file(workflows / "folded.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in violation for violation in violations)


def test_guard_fails_when_no_workflow_files_exist(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert guard.main([str(empty)]) == 2


def test_guard_fails_on_missing_path(tmp_path: Path) -> None:
    assert guard.main([str(tmp_path / "does-not-exist")]) == 2
