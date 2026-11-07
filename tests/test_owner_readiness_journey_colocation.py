"""CI efficiency R3: the all-journeys corpus consumers must stay colocated.

Efficiency R2 made the eleven-state journey corpus a per-process cache
(``_shared_all_journeys`` in ``tests/test_owner_readiness_summary_r1_probes``)
so its several-seconds build is paid once per process instead of once per
test. Under ``pytest -n auto`` (the full CI mode) one *process* is one xdist
*worker*, and the default ``load`` distribution scatters the consumer tests
across workers — each drawing worker rebuilds the corpus from scratch.
Measured on the R5 main tree, the six consumers take 7.52 s sequentially
(one build) but 12.02 s at ``-n 4`` (four builds): the duplication costs
more wall time than running every consumer sequentially after one build, and
on the CI runner the duplicate builds are visible as two ~21 s tests in the
``--durations`` output.

The fix pins every consumer into one ``pytest.mark.xdist_group`` so xdist
routes them all to the same worker (exactly one build per run). The marker
is inert without ``-n``, so sequential and focused runs are unchanged. This
module keeps that contract honest: an AST scan over every
``tests/test_owner_readiness_summary*.py`` module finds each ``test_``
function that calls ``_shared_all_journeys`` and fails closed when any
consumer is missing the shared group mark, carries a foreign group name, or
when the detector itself rots (the detected set must equal the known six).
"""

import ast
import importlib
from pathlib import Path

from tests.test_owner_readiness_summary_r1_probes import (
    JOURNEY_CORPUS_XDIST_GROUP,
)

_TESTS_DIR = Path(__file__).resolve().parent

# The six corpus consumers at the time this contract was introduced. The
# equality assertion below is deliberate: a new consumer must extend this
# set (and carry the mark), and a removed consumer must shrink it, so the
# detector can never silently match nothing.
_EXPECTED_CONSUMERS = {
    "test_owner_readiness_summary_r1_probes.py::test_every_executable_hint_is_complete_safe_and_readonly",
    "test_owner_readiness_summary_r2_probes.py::test_f1_no_command_tail_ends_with_sentence_punctuation_after_the_command",
    "test_owner_readiness_summary_r2_probes.py::test_f1_all_journeys_tails_are_complete_safe_and_literally_copyable",
    "test_owner_readiness_summary_r2_probes.py::test_f2_no_write_command_step_claims_to_be_the_sole_write_step",
    "test_owner_readiness_summary_r2_probes.py::test_f2_both_write_commands_disclose_their_write_and_output_choice",
    "test_owner_readiness_summary_r3_probes.py::test_all_journeys_keep_write_commands_prose_and_readonly_tails",
}


def _calls_shared_all_journeys(function_node: ast.FunctionDef) -> bool:
    """True when the function body calls ``_shared_all_journeys``."""

    for node in ast.walk(function_node):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "_shared_all_journeys":
                return True
    return False


def _consumer_ids() -> set[str]:
    """AST-scan every journey-summary module for corpus consumers."""

    consumers: set[str] = set()
    for path in sorted(_TESTS_DIR.glob("test_owner_readiness_summary*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")
                and _calls_shared_all_journeys(node)
            ):
                consumers.add(f"{path.name}::{node.name}")
    return consumers


def _consumer_function(module_file: str, function_name: str):
    module = importlib.import_module(f"tests.{module_file[:-3]}")
    return getattr(module, function_name)


def _xdist_group_names(function) -> set[str]:
    marks = getattr(function, "pytestmark", [])
    names: set[str] = set()
    for mark in marks:
        if mark.name == "xdist_group":
            names.update(mark.args)
            if "name" in mark.kwargs:
                names.add(mark.kwargs["name"])
    return names


def test_detected_consumers_are_exactly_the_known_set():
    """The AST detector must find the six real consumers — no silent rot."""

    assert _consumer_ids() == _EXPECTED_CONSUMERS


def test_every_corpus_consumer_shares_the_single_xdist_group():
    """Each consumer carries exactly the canonical ``xdist_group`` mark.

    One shared group name routes every consumer to one xdist worker, so the
    per-process corpus cache is built exactly once per ``-n auto`` run; a
    missing or divergent mark would reintroduce per-worker duplicate builds.
    """

    for consumer_id in sorted(_consumer_ids()):
        module_file, function_name = consumer_id.split("::")
        function = _consumer_function(module_file, function_name)
        names = _xdist_group_names(function)
        assert names == {JOURNEY_CORPUS_XDIST_GROUP}, (
            f"{consumer_id}: expected exactly the shared xdist group "
            f"{JOURNEY_CORPUS_XDIST_GROUP!r}, found {sorted(names)}; a "
            "consumer outside the group rebuilds the journey corpus on "
            "another worker under -n auto"
        )
