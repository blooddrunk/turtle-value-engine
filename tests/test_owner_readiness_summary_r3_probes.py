"""Phase 7-C4-C-R3: plan-export argument compatibility and operator handoff.

Tests-first probes for the single confirmed C4-C-R2 post-closure finding
(``docs/status/phase-7-c4-c-r2-post-closure-review-2026-10-25.md`` and
``docs/goals/phase-7-c4-c-r3-plan-activation-argument-parity.md``):

* **F1** — both branches of the ``plan_activation_step`` hint told the
  operator to reuse **all** ``readiness-summary`` inputs for ``tve evolution
  plan-activation``.  The two real argparse subcommands differ:
  ``readiness-summary`` accepts an optional ``--activation-root``;
  ``plan-activation`` does **not** accept it at all, **requires** at least one
  ``--decision-record`` plus ``--output``, and additionally accepts
  reference-inventory flags (``--watchlist``/``--normalized-input``/
  ``--backtest-manifest``/``--surface-snapshot``/``--runner-config``) the
  summary never exposes.  A mechanically copied summary argv therefore dies
  with argparse exit 2, and even after dropping the flag the summary's inputs
  are not necessarily a complete activation-plan inventory.

Every argument-compatibility claim here is proven against the REAL parser
(``_build_parser``) — parser-only ``parse_args`` probes that never invoke any
handler and never write a plan file — plus guidance assertions over a genuine
``ACTIVATION_BLOCKED`` journey driven with and without ``--activation-root``
and through the library branch without replay provenance.  The write
disclosure, literal-tail and read-only contracts hardened by R1/R2 stay
intact: the plan-export step remains prose, never a paste-ready command.

The guidance expectations were written against pristine main ``fdb4ce3``
where they fail on the unqualified reuse claim, while the parser-mismatch
controls pass — confirming the defect is real, not prose speculation.
"""

import argparse
import json
import shlex
import socket
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from tests.test_activation_execution import (
    BASE_PROFILE_PATH,
    BOUNDARY_PATH,
    MANIFEST_PATH,
    PRIVATE_CONFIG_TEMPLATE,
    TARGET_PROFILE_PATH,
    _cli,
    _Env,
)
from tests.test_activation_status import (
    _assert_zero_writes,
    _tree_snapshot,
)
from tests.test_owner_readiness_summary import (
    _env_summary,
    _observed_paths,
    _summary_cli,
)
from tests.test_owner_readiness_summary_r1_probes import (
    _KNOWN_PLACEHOLDERS,
    _PLACEHOLDER_SOURCES,
    _READONLY_SUBCOMMANDS,
    _build_all_journeys,
    _executable_hints,
    _run_hint_with_stub,
)
from tests.test_owner_readiness_summary_r2_probes import (
    _assert_tail_is_a_canonical_command_line,
    _literal_command_tails,
)

# ---------------------------------------------------------------------------
# The documented command-compatibility rule (R3 §2 item 4)
# ---------------------------------------------------------------------------

# Options BOTH commands accept (identical meaning on each side).
SHARED_OPTIONS = frozenset(
    {
        "--base-profile",
        "--target-profile",
        "--release-manifest",
        "--boundary-input",
        "--decision-record",
        "--revocation",
        "--policy-exception",
        "--project-config",
        "--trust-root",
        "--authority-evidence",
        "--signed-revocation",
        "--signed-supersession",
    }
)
# Options only readiness-summary accepts (plan-activation rejects them).
SUMMARY_ONLY_OPTIONS = frozenset({"--activation-root"})
# Options only plan-activation accepts (readiness-summary rejects them).
PLAN_ONLY_OPTIONS = frozenset(
    {
        "--watchlist",
        "--normalized-input",
        "--backtest-manifest",
        "--surface-snapshot",
        "--runner-config",
        "--output",
    }
)
# Options plan-activation marks required (the summary has none of these two).
PLAN_REQUIRED_OPTIONS = frozenset({"--decision-record", "--output"})

_BUILTIN_OPTIONS = frozenset({"-h", "--help"})

# Deterministic parser-probe argv templates.  parse_args never touches the
# filesystem (type=Path only wraps strings) and never dispatches a handler,
# so disposable non-existent paths are safe and no plan file can be written.
_SUMMARY_PROBE_ARGV = [
    "evolution",
    "readiness-summary",
    "--base-profile",
    str(BASE_PROFILE_PATH),
    "--target-profile",
    str(TARGET_PROFILE_PATH),
    "--release-manifest",
    str(MANIFEST_PATH),
    "--project-config",
    "/disposable-r3/project.toml",
]
_PLAN_PROBE_ARGV = [
    "evolution",
    "plan-activation",
    "--base-profile",
    str(BASE_PROFILE_PATH),
    "--target-profile",
    str(TARGET_PROFILE_PATH),
    "--release-manifest",
    str(MANIFEST_PATH),
    "--project-config",
    "/disposable-r3/project.toml",
    "--decision-record",
    "/disposable-r3/record.json",
    "--output",
    "/disposable-r3/plan.json",
]


def _build_real_parser():
    from turtle_value_engine.cli import _build_parser

    return _build_parser()


def _command_subparser(name: str) -> argparse.ArgumentParser:
    """The real ``tve evolution <name>`` subparser, straight from the parser."""

    root = _build_real_parser()
    for action in root._actions:
        if (
            isinstance(action, argparse._SubParsersAction)
            and "evolution" in action.choices
        ):
            evolution = action.choices["evolution"]
            break
    else:
        raise AssertionError("the evolution subcommand parser was not found")
    for action in evolution._actions:
        if (
            isinstance(action, argparse._SubParsersAction)
            and name in action.choices
        ):
            return action.choices[name]
    raise AssertionError(f"the evolution {name} subparser was not found")


def _option_strings(subparser: argparse.ArgumentParser) -> set[str]:
    names: set[str] = set()
    for action in subparser._actions:
        names.update(action.option_strings)
    return names


def _required_option_strings(subparser: argparse.ArgumentParser) -> set[str]:
    names: set[str] = set()
    for action in subparser._actions:
        if action.required:
            names.update(action.option_strings)
    return names


def _without_flag(argv: list[str], flag: str) -> list[str]:
    """A copy of argv with every ``flag value`` pair removed."""

    trimmed: list[str] = []
    skip_value = False
    for token in argv:
        if skip_value:
            skip_value = False
            continue
        if token == flag:
            skip_value = True
            continue
        trimmed.append(token)
    assert flag not in trimmed
    return trimmed


# ---------------------------------------------------------------------------
# §2 item 1/4 — real parser incompatibility, never executing a handler
# ---------------------------------------------------------------------------


def test_parser_rule_documented_compatibility_matches_the_real_parsers():
    """The documented shared/summary-only/plan-only/plan-required rule must
    match the actual parser definitions (a control that confirms the defect:
    the sets genuinely differ exactly as the R3 finding claims)."""

    summary = _option_strings(_command_subparser("readiness-summary"))
    plan = _option_strings(_command_subparser("plan-activation"))

    # every documented shared option exists on BOTH commands
    assert SHARED_OPTIONS <= (summary & plan)
    # nothing beyond the documented shared set (and --help) is accepted by
    # both — a newly shared flag must join this documented rule first
    assert (summary & plan) - _BUILTIN_OPTIONS <= SHARED_OPTIONS
    # the summary-only class is exactly --activation-root
    assert SUMMARY_ONLY_OPTIONS <= (summary - plan)
    assert (summary - plan) - _BUILTIN_OPTIONS <= SUMMARY_ONLY_OPTIONS
    # the plan-only class is exactly the reference inventory plus --output
    assert PLAN_ONLY_OPTIONS <= (plan - summary)
    assert (plan - summary) - _BUILTIN_OPTIONS <= PLAN_ONLY_OPTIONS
    # the required classes differ where the goal says they do
    assert PLAN_REQUIRED_OPTIONS <= _required_option_strings(
        _command_subparser("plan-activation")
    )
    assert _required_option_strings(
        _command_subparser("readiness-summary")
    ) == {"--base-profile", "--target-profile", "--release-manifest", "--project-config"}


def test_plan_parser_rejects_the_summary_only_activation_root():
    """Appending the readiness-only ``--activation-root`` to a complete valid
    plan argv fails with argparse SystemExit(2); the identical argv without
    it parses.  parse_args only — no handler, no plan file."""

    parser = _build_real_parser()
    hostile = _PLAN_PROBE_ARGV + ["--activation-root", "/disposable-r3/activation"]
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(hostile)
    assert excinfo.value.code == 2

    args = parser.parse_args(_PLAN_PROBE_ARGV)
    assert args.evolution_command == "plan-activation"
    # the plan namespace does not even define the summary-only attribute
    assert not hasattr(args, "activation_root")
    assert args.output == Path("/disposable-r3/plan.json")


def test_summary_parser_accepts_the_activation_root_the_plan_rejects():
    """The same ``--activation-root`` option parses fine on readiness-summary
    — the asymmetry the old prose pretended did not exist."""

    parser = _build_real_parser()
    args = parser.parse_args(
        _SUMMARY_PROBE_ARGV + ["--activation-root", "/disposable-r3/activation"]
    )
    assert args.evolution_command == "readiness-summary"
    assert args.activation_root == Path("/disposable-r3/activation")


def test_plan_parser_requires_decision_record_and_output():
    """``--decision-record`` and ``--output`` are plan-required (parse-level
    SystemExit 2 when missing); readiness-summary keeps the record optional
    and defines no ``--output`` at all."""

    parser = _build_real_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(_without_flag(_PLAN_PROBE_ARGV, "--decision-record"))
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(_without_flag(_PLAN_PROBE_ARGV, "--output"))
    assert excinfo.value.code == 2

    # the summary runs with no decision record (the journey-start view) and
    # has no --output option to omit
    args = parser.parse_args(_SUMMARY_PROBE_ARGV)
    assert args.decision_record is None
    assert "--output" not in _option_strings(
        _command_subparser("readiness-summary")
    )


def test_reference_inventory_flags_are_plan_only_and_never_mix():
    """The plan-only reference-inventory options parse on plan-activation and
    are rejected by the summary parser; the option sets cannot be blindly
    reused across the two commands in either direction."""

    parser = _build_real_parser()
    args = parser.parse_args(
        _PLAN_PROBE_ARGV
        + [
            "--watchlist",
            "/disposable-r3/watchlist.json",
            "--runner-config",
            "/disposable-r3/runner.json",
        ]
    )
    assert args.watchlist == [Path("/disposable-r3/watchlist.json")]
    assert args.runner_config == [Path("/disposable-r3/runner.json")]

    for summary_hostile in (
        _SUMMARY_PROBE_ARGV + ["--watchlist", "/disposable-r3/watchlist.json"],
        _SUMMARY_PROBE_ARGV + ["--runner-config", "/disposable-r3/runner.json"],
        _SUMMARY_PROBE_ARGV + ["--output", "/disposable-r3/plan.json"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(summary_hostile)
        assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# §2 item 2 — the guidance on a genuine ACTIVATION_BLOCKED journey
# ---------------------------------------------------------------------------


def _plan_export_steps(steps: list[str]) -> list[str]:
    plan_steps = [step for step in steps if "plan-activation" in step]
    assert plan_steps, "the blocked journey must still explain the plan export"
    return plan_steps


def _assert_argument_compatible_plan_guidance(step: str) -> None:
    """The R3 guidance contract for every plan-activation export step.

    (a) no unqualified reuse-everything claim;
    (b) ``--activation-root`` is explicitly named as NOT a plan option;
    (c) a real ``--decision-record`` and an operator-chosen ``--output``;
    (d) shared source options distinguished from plan-only inventory options;
    (e) the export writes the chosen file (R2 disclosure preserved);
    (f) the summary's inputs are not claimed to be the full plan inventory.
    """

    # (a) the misleading parity claims are gone
    assert "完全相同的输入" not in step, step
    assert "完全相同的全部输入" not in step, step
    assert "全部输入" not in step, step
    if "完全相同" in step:
        # any remaining sameness claim must be explicitly qualified
        assert "--activation-root" in step, step
    # (b) the summary-only option is explicitly excluded
    assert "--activation-root" in step, step
    assert "不接受" in step, step
    assert ("请勿传入" in step) or ("不要传入" in step) or ("必须省略" in step), step
    # (c) required plan inputs and the deliberate output choice
    assert "--decision-record" in step, step
    assert "--output" in step, step
    assert "显式" in step, step
    # (d) shared versus plan-only reference inventory
    assert ("共享" in step) or ("共同" in step), step
    assert "--watchlist" in step, step
    assert "--runner-config" in step, step
    # (e) the write stays disclosed (unchanged R1/R2 rules)
    assert "写入" in step, step
    assert "只读" not in step, step
    assert ("同样" in step) or ("也" in step), step
    # (f) the summary inputs are not a complete plan inventory; the plan
    # parser's own help is the option authority
    assert "不构成完整" in step, step
    assert "--help" in step, step
    # prose only: never a paste-ready command (R1/R2 contract)
    if "：" in step:
        assert not step.rsplit("：", 1)[1].startswith("tve "), step
    for placeholder in _KNOWN_PLACEHOLDERS:
        assert placeholder not in step, step


def _blocked_env(tmp_path: Path, capsys, *, with_root: bool) -> _Env:
    """A verified ACCEPT journey whose config is already the target profile
    (DEFAULT_ALREADY_TARGET) — the genuine ACTIVATION_BLOCKED journey."""

    env = _Env(tmp_path).setup(capsys)
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('"strict-v1"', '"strict-v2"'), "utf-8"
    )
    if with_root:
        env.activation_root.mkdir(parents=True)
    return env


def test_blocked_plan_guidance_with_activation_root_supplied(tmp_path, capsys):
    """Branch 1 of the hint (retry command displayed), driven through the
    real CLI with ``--activation-root`` explicitly supplied: the displayed
    retry tail really carries ``--activation-root``, and the plan-export
    guidance must teach the exclusion instead of advertising full reuse."""

    env = _blocked_env(tmp_path, capsys, with_root=True)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "ACTIVATION_BLOCKED"
    assert payload["activation_root_supplied"] is True
    assert "DEFAULT_ALREADY_TARGET" in payload["plan_blockers"]

    # the conflict the guidance must address is real in THIS journey: the
    # displayed readiness-summary retry tail contains --activation-root
    retry_tails = [
        tail
        for tail in _literal_command_tails(payload["next_steps_zh"])
        if "readiness-summary" in tail
    ]
    assert retry_tails, "the blocked journey still displays its retry command"
    assert any("--activation-root" in tail for tail in retry_tails)

    for step in _plan_export_steps(payload["next_steps_zh"]):
        _assert_argument_compatible_plan_guidance(step)
    assert not any(
        "plan-activation" in hint
        for hint in _executable_hints(payload["next_steps_zh"])
    ), "the plan export was emitted as a paste-ready executable hint"


def test_blocked_plan_guidance_without_activation_root(tmp_path, capsys):
    """Branch 1 again, driven without any ``--activation-root`` (store
    classification skipped): the guidance must still state the same
    argument-compatibility rule rather than assume the reader's invocation."""

    env = _blocked_env(tmp_path, capsys, with_root=False)
    code, out = _env_summary(capsys, env, with_store=False)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "ACTIVATION_BLOCKED"
    assert payload["activation_root_supplied"] is False

    for step in _plan_export_steps(payload["next_steps_zh"]):
        _assert_argument_compatible_plan_guidance(step)
    assert not any(
        "plan-activation" in hint
        for hint in _executable_hints(payload["next_steps_zh"])
    )


def test_blocked_plan_guidance_library_branch_without_replay_inputs(
    tmp_path, capsys
):
    """Branch 2 of the hint (no replay provenance — reachable only through
    the library boundary): the same argument-compatibility contract."""

    from turtle_value_engine.cli import _load_policy_exceptions
    from turtle_value_engine.evolution.owner_decision import (
        load_decision_record_with_bytes,
    )
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )
    from turtle_value_engine.evolution.owner_readiness import (
        summarize_owner_readiness,
    )
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
        load_owner_decision_evidence,
    )

    env = _blocked_env(tmp_path, capsys, with_root=False)
    record, _ = load_decision_record_with_bytes(env.record_path)
    evidence = load_owner_decision_evidence(env.bundle_path)
    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    summary = summarize_owner_readiness(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        project_config_path=env.config_path,
        decision_records=[record],
        policy_exceptions=_load_policy_exceptions([env.exception_path]),
        authority_verifier=SignedOwnerProvenanceVerifier(
            registry=registry,
            statement=evidence.statement,
            decision_input_bytes=evidence.decision_input_bytes,
        ),
        authority_evidence=evidence,
        lifecycle_trust_root=registry,
        activation_root=None,
        replay_inputs=None,
    )
    assert summary.journey_state == "ACTIVATION_BLOCKED"
    for step in _plan_export_steps(summary.next_steps_zh):
        _assert_argument_compatible_plan_guidance(step)


# ---------------------------------------------------------------------------
# §2 item 3 — the export step stays prose, even under hostile paths
# ---------------------------------------------------------------------------


def test_plan_guidance_stays_prose_with_hostile_paths(tmp_path, capsys):
    """Unicode/metacharacter input paths must not turn the plan-export prose
    into a paste-ready command, and every executable tail this journey
    displays still parses read-only with no write options."""

    hostile = tmp_path / "私密 目录; '引号' \"双引\" `tick` $HOME"
    env = _Env(hostile).setup(capsys)
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('"strict-v1"', '"strict-v2"'), "utf-8"
    )
    inputs = hostile / "输入 with spaces"
    inputs.mkdir(parents=True, exist_ok=True)
    record = inputs / "决策记录。"
    record.write_bytes(env.record_path.read_bytes())
    exception = inputs / "exception `q` \"d\".json"
    exception.write_bytes(env.exception_path.read_bytes())
    evidence_dir = inputs / "证;据 '$x' <dir>"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for component in Path(env.bundle_path).parent.iterdir():
        (evidence_dir / component.name).write_bytes(component.read_bytes())
    evidence = evidence_dir / "bundle.json"
    boundary = inputs / "boundary $x。"
    boundary.write_bytes(BOUNDARY_PATH.read_bytes())
    env.activation_root.mkdir(parents=True)

    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[record],
        policy_exceptions=[exception],
        trust_root=env.trust_root,
        authority_evidence=evidence,
        extra=["--boundary-input", str(boundary)],
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "ACTIVATION_BLOCKED"

    for step in _plan_export_steps(payload["next_steps_zh"]):
        _assert_argument_compatible_plan_guidance(step)
    hints = _executable_hints(payload["next_steps_zh"])
    assert hints, "the journey still offers a read-only retry"
    for hint in hints:
        tokens = _assert_tail_is_a_canonical_command_line(hint)
        assert tokens[2] in _READONLY_SUBCOMMANDS, hint
        for forbidden in ("--output", "--apply", "--expected-plan-id"):
            assert forbidden not in tokens, (forbidden, hint)
        code_stub, argv, stray, stderr = _run_hint_with_stub(
            hint, tmp_path / "r3-hostile-sandbox", precreate=_PLACEHOLDER_SOURCES
        )
        assert code_stub == 0, stderr
        assert argv == tokens[1:], (hint, argv)
        assert stray == [], (hint, stray)


def test_all_journeys_keep_write_commands_prose_and_readonly_tails(
    tmp_path, capsys
):
    """Across every reachable journey state (the R2 all-journeys contract,
    re-checked from the R3 angle): plan-activation and decision-dossier never
    appear as executable hints, and every displayed tail names only a
    read-only subcommand carrying no write/apply option."""

    journeys = _build_all_journeys(capsys, tmp_path)
    for name, payload in journeys.items():
        steps = payload["next_steps_zh"]
        for writer in ("plan-activation", "decision-dossier"):
            assert not any(
                writer in hint for hint in _executable_hints(steps)
            ), (name, writer)
        for tail in _literal_command_tails(steps):
            tokens = _assert_tail_is_a_canonical_command_line(tail)
            assert tokens[2] in _READONLY_SUBCOMMANDS, (name, tail)
            for forbidden in ("--output", "--apply", "--expected-plan-id"):
                assert forbidden not in tokens, (name, forbidden, tail)


# ---------------------------------------------------------------------------
# §2 item 5 — boundary invariants on the blocked journey (R1/R2 repeats)
# ---------------------------------------------------------------------------


def test_blocked_journey_summary_is_zero_write_and_socket_free(
    tmp_path, capsys, monkeypatch
):
    """The blocked-journey summary with a supplied root writes nothing,
    opens no socket, and leaks no key material; its advertised executable
    hints paste into a stub with the exact argv and zero side effects."""

    env = _blocked_env(tmp_path, capsys, with_root=True)
    before = _tree_snapshot(*_observed_paths(env))

    def no_sockets(*args, **kwargs):
        raise AssertionError("the readiness summary constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))

    assert "PRIVATE KEY" not in out
    assert "BEGIN" not in out
    private_raw = env.key.private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()
    assert private_raw not in out
    for step in payload["next_steps_zh"]:
        assert private_raw not in step

    sandbox = tmp_path / "r3-zero-write-sandbox"
    for hint in _executable_hints(payload["next_steps_zh"]):
        tokens = shlex.split(hint)
        code_stub, argv, stray, stderr = _run_hint_with_stub(
            hint, sandbox, precreate=_PLACEHOLDER_SOURCES
        )
        assert code_stub == 0, stderr
        assert argv == tokens[1:], (hint, argv)
        assert stray == [], (hint, stray)


def test_blocked_journey_real_cli_replay_is_zero_write(tmp_path, capsys):
    """Re-running the literal displayed retry tail through the REAL CLI
    reproduces the same blocked observation and writes nothing."""

    env = _blocked_env(tmp_path, capsys, with_root=True)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)

    tails = [
        tail
        for tail in _literal_command_tails(payload["next_steps_zh"])
        if "readiness-summary" in tail
    ]
    assert tails, "the blocked journey displays its retry command"
    tokens = shlex.split(tails[0])
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    replayed = json.loads(out2)
    assert replayed["summary_id"] == payload["summary_id"]
    assert replayed["content_sha256"] == payload["content_sha256"]
    assert replayed["journey_state"] == payload["journey_state"]
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
