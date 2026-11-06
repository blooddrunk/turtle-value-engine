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

import pytest

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


# --- Issue #45 F1: duplicate refs must not collapse the YAML-vs-raw view ---


def test_guard_fails_on_duplicate_quoted_key_hiding_unannotated_occurrence(
    tmp_path: Path,
) -> None:
    """One annotated plain ``uses:`` plus one quoted ``'uses':`` with the same
    pinned SHA and no version comment: PyYAML parses both action steps but the
    raw line scanner only sees the plain key, so occurrence counts diverge and
    the untraceable second occurrence must fail closed (Issue #45 F1)."""
    workflow = """\
name: Guard Repro
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: annotated
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: missing annotation, quoted key
        'uses': actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
    workflows = _write(tmp_path, "dup-quoted.yml", workflow)
    violations = guard.check_workflow_file(workflows / "dup-quoted.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in violation for violation in violations)


def test_guard_accepts_repeated_pinned_references_with_annotations(
    tmp_path: Path,
) -> None:
    """Positive control: the same pinned SHA declared twice as ordinary
    ``uses:`` lines, each carrying its own complete version comment, stays
    clean; only a scanner-invisible encoding of a repeated reference fails."""
    workflow = """\
name: Guard Repro Repeated
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: first use
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: second use
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""
    workflows = _write(tmp_path, "repeated.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_on_duplicate_ref_hidden_in_run_block(tmp_path: Path) -> None:
    """A run-block ``uses:`` line repeating a legitimately pinned reference
    used to cancel out against the set-based comparison; the multiset view
    must report the scanner-only occurrence (Issue #45 F1 variant)."""
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
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
          echo "$uses"
"""
    workflows = _write(tmp_path, "dup-run-block.yml", workflow)
    violations = guard.check_workflow_file(workflows / "dup-run-block.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to YAML keys" in violation for violation in violations)


# --- Issue #45 F2: version annotations must be complete vX.Y.Z ---


def _annotated_workflow(reference: str, comment: str) -> str:
    return PINNED_STEP_TEMPLATE.format(reference=f"{reference} {comment}")


def test_guard_fails_on_truncated_two_component_version_comment(
    tmp_path: Path,
) -> None:
    workflows = _write(
        tmp_path, "truncated.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "# v7.1"
        ),
    )
    violations = guard.check_workflow_file(workflows / "truncated.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_malformed_version_comment_suffix(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "malformed.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "# v7.1abc"
        ),
    )
    violations = guard.check_workflow_file(workflows / "malformed.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_four_component_version_comment(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "fourcomp.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "# v7.0.1.4"
        ),
    )
    violations = guard.check_workflow_file(workflows / "fourcomp.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_version_comment_with_trailing_text(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "trailing.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "# v7.0.1 pinned upstream tag",
        ),
    )
    violations = guard.check_workflow_file(workflows / "trailing.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_accepts_no_space_version_comment(tmp_path: Path) -> None:
    """Positive control: a compact ``#v7.0.1`` annotation with no space after
    the hash remains supported valid syntax."""
    workflows = _write(
        tmp_path, "compact.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "#v7.0.1"
        ),
    )
    assert guard.main([str(workflows)]) == 0


# --- Issue #47 F3: a decoy line cannot authorize a different real occurrence ---


def test_guard_fails_on_decoy_annotating_quoted_key_real_action(
    tmp_path: Path,
) -> None:
    """The actual action step is a quoted ``'uses':`` key without a version
    comment; an annotated ``uses:`` decoy line inside a ``run: |`` block
    repeats the same pinned reference. Value-based Counters balance, but the
    decoy must not authorize the real occurrence: the guard must fail closed
    on both the scanner-invisible real line and the YAML-invisible decoy
    (Issue #47 F3, fixture A)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: real action
        'uses': actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0
      - name: decoy line, not an action
        run: |
          uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
"""
    workflows = _write(tmp_path, "decoy-quoted.yml", workflow)
    violations = guard.check_workflow_file(workflows / "decoy-quoted.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in v for v in violations), violations
    assert any("invisible to YAML keys" in v for v in violations), violations


def test_guard_fails_on_decoy_annotating_folded_scalar_real_action(
    tmp_path: Path,
) -> None:
    """The actual action step is a folded scalar whose effective value cannot
    carry a same-line annotation; an annotated decoy line inside a ``run: |``
    block repeats the same pinned reference. The decoy must not authorize the
    folded occurrence: the guard must fail closed on both (Issue #47 F3,
    fixture B)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: real folded action
        uses: >-
          actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0
      - name: decoy line, not an action
        run: |
          uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
"""
    workflows = _write(tmp_path, "decoy-folded.yml", workflow)
    violations = guard.check_workflow_file(workflows / "decoy-folded.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in v for v in violations), violations
    assert any("invisible to YAML keys" in v for v in violations), violations


def test_guard_accepts_distinct_annotated_references(tmp_path: Path) -> None:
    """Positive control: several genuinely distinct external actions, each an
    ordinary single-line ``uses:`` carrying its own pinned SHA and complete
    same-line version comment, stays clean under occurrence-level binding."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Set up Python
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
      - name: Set up Node
        uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
"""
    workflows = _write(tmp_path, "distinct.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_on_duplicate_uses_key_in_one_step(tmp_path: Path) -> None:
    """Two ``uses`` keys inside the same step mapping are an ambiguous
    encoding (PyYAML keeps only the last): the guard must fail closed instead
    of letting either occurrence authorize the other."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: ambiguous step
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
"""
    workflows = _write(tmp_path, "dup-key.yml", workflow)
    violations = guard.check_workflow_file(workflows / "dup-key.yml")
    assert guard.main([str(workflows)]) == 1
    assert len(violations) >= 1
    joined = "\n".join(violations)
    assert "uses" in joined


# --- Issue #49 F4/F5: alias-graph robustness and source fidelity ---


def test_guard_fails_on_alias_shared_action_mapping(tmp_path: Path) -> None:
    """F4: PyYAML aliases reuse node objects, so a step mapping anchored once
    and referenced twice makes two *effective* ``uses`` occurrences share one
    annotated source line. A single annotation must not authorize multiple
    action references; the guard must fail closed with an alias diagnostic
    anchored at the shared ``uses`` line (Issue #49 F4)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - &shared
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - *shared
"""
    workflows = _write(tmp_path, "alias-shared.yml", workflow)
    violations = guard.check_workflow_file(workflows / "alias-shared.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "alias-shared.yml"
    shared = [v for v in violations if "alias" in v and "shared" in v]
    assert shared, violations
    assert any(v.startswith(f"{path}:7:") for v in shared), violations


def test_guard_fails_on_cyclic_alias_graph_with_controlled_diagnostic(
    tmp_path: Path,
) -> None:
    """F5: an anchor referenced inside its own definition composes into a
    cyclic node graph. The guard must reject it with a controlled
    ``path:line`` diagnostic and exit 1, never an uncaught RecursionError
    (Issue #49 F5)."""
    workflow = """\
name: CI
metadata: &cycle [*cycle]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""
    workflows = _write(tmp_path, "cycle.yml", workflow)
    violations = guard.check_workflow_file(workflows / "cycle.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "cycle.yml"
    cyclic = [v for v in violations if "cyclic" in v]
    assert cyclic, violations
    assert any(v.startswith(f"{path}:2:") for v in cyclic), violations


def test_guard_bounds_alias_fanout_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5 resource budget: a doubling-layer alias DAG has a tiny unique-node
    set but an exponential number of root-to-node paths. The collector must
    visit each composed node O(1) times (memoized), keeping the traversal
    linear in nodes plus edges; the pre-R3 collector made 786,420 recursive
    calls on this exact 17-layer fixture. Bounded structurally by counting
    visitor invocations, not by timing."""
    lines = [
        "name: CI",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        " # v7.0.1",
        "layers:",
        "  l0: &l0 [0]",
    ]
    lines.extend(f"  l{i}: &l{i} [*l{i - 1}, *l{i - 1}]" for i in range(1, 18))
    workflows = _write(tmp_path, "fanout.yml", "\n".join(lines) + "\n")

    calls = 0
    original = guard._collect_yaml_use_occurrences

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(guard, "_collect_yaml_use_occurrences", counting)
    assert guard.main([str(workflows)]) == 0
    assert calls <= 200, f"alias fan-out traversal made {calls} node visits"


def test_guard_accepts_harmless_reused_non_uses_anchor(tmp_path: Path) -> None:
    """Positive control: reusing a YAML anchor that contains no ``uses`` key
    (a shared env block) is harmless and must stay clean."""
    workflow = """\
name: CI
configs:
  env: &env-config
    PYTHONHASHSEED: "0"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: first
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        env: *env-config
      - name: second
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        env: *env-config
"""
    workflows = _write(tmp_path, "harmless-anchor.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_accepts_dead_anchor_on_pinned_step(tmp_path: Path) -> None:
    """Positive control: an anchor defined on a legitimately pinned step but
    never referenced by any alias is harmless (only alias *sharing* of a
    ``uses``-bearing subtree is rejected)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - &step
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""
    workflows = _write(tmp_path, "dead-anchor.yml", workflow)
    assert guard.main([str(workflows)]) == 0
