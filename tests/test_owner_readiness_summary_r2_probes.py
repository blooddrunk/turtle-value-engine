"""Phase 7-C4-C-R2: executable hint copy boundary and write-step accuracy.

Tests-first probes for the two confirmed C4-C-R1 post-closure findings
(``docs/status/phase-7-c4-c-r1-post-closure-review-2026-10-25.md`` and
``docs/goals/phase-7-c4-c-r2-executable-hint-copy-boundary.md``):

* **F1** — ``_next_steps_zh`` composed complete ``shlex.join`` commands but
  appended the Chinese sentence full stop ``。`` *after* the command.  The
  documented copy contract ("the command is the entire text after the last
  full-width colon and can be pasted directly") therefore handed the shell
  a last argument like ``/tmp/config with spaces.toml。`` — a different,
  non-existent path.  The R1 extractor silently stripped that punctuation
  before parsing, which masked the copyability failure.  Every extraction
  here is **literal**: ``step.rsplit("：", 1)[1]`` with no ``rstrip``/no
  ``strip``/no punctuation removal of any kind, and the extracted text is
  executed through a no-op ``tve`` stub exactly as an operator's paste
  would deliver it — never the real activation CLI, never ``--apply``.
* **F2** — ``decision-dossier --output`` was described as the journey's
  "唯一写文件步骤" (the only file-writing step) while
  ``plan-activation --output`` also writes a file.  Both must be
  unambiguously disclosed as opt-in writes with an operator-chosen output
  path, and neither may be presented as read-only.

The whole suite was written against pristine merged main ``4e00975`` where
the F1 probes fail on the literal last shell argument and the F2 probe
fails on the exclusivity phrase.
"""

import json
import shlex
import socket
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from tests.test_activation_execution import (
    BASE_PROFILE_PATH,
    BOUNDARY_PATH,
    MANIFEST_PATH,
    TARGET_PROFILE_PATH,
    _Env,
    _cli,
)
from tests.test_activation_status import (
    _assert_zero_writes,
    _tree_snapshot,
)
from tests.test_owner_readiness_summary import (
    _bare_summary,
    _env_summary,
    _observed_paths,
    _summary_cli,
)
from tests.test_owner_readiness_summary_r1_probes import (
    _KNOWN_PLACEHOLDERS,
    _PLACEHOLDER_SOURCES,
    _READONLY_SUBCOMMANDS,
    _build_all_journeys,
    _parse_hint,
    _run_hint_with_stub,
)

# The complete set of journey states the summary contract defines; the
# all-journeys probe below must observe every one of them.
_ALL_JOURNEY_STATES = frozenset(
    {
        "OWNER_DECISION_REQUIRED",
        "REJECTED_BY_OWNER",
        "DECISION_CONFLICT",
        "OWNER_AUTHORITY_NOT_PROVEN",
        "PUBLISHED_PAIR_BLOCKED",
        "ACTIVATION_BLOCKED",
        "RECOVERY_PENDING",
        "STORE_NEEDS_ATTENTION",
        "ALREADY_APPLIED",
        "ROLLED_BACK",
        "PREVIEW_READY",
    }
)


# ---------------------------------------------------------------------------
# Shared R2 probe helpers (deliberately literal — no normalization)
# ---------------------------------------------------------------------------


def _literal_command_tails(steps: list[str]) -> list[str]:
    """The literal final segment after the LAST full-width colon ``：`` of
    every command-bearing step — exactly the bytes an operator selects and
    pastes into a shell.

    NOTHING is stripped: no ``rstrip``, no ``strip`` of ``。`` or
    whitespace, no trimming of any decoration.  The R2 composition contract
    is that this exact text is already complete shell input.  A step whose
    post-colon segment does not start with ``tve `` is prose, not a command.
    """

    tails: list[str] = []
    for step in steps:
        if "：" not in step:
            continue
        tail = step.rsplit("：", 1)[1]
        if tail.startswith("tve "):
            tails.append(tail)
    return tails


def _assert_tail_is_a_canonical_command_line(tail: str) -> list[str]:
    """The literal tail must *be* a ``shlex.join`` product: splitting and
    re-joining it reproduces the text byte-for-byte.

    Any decoration appended after the quoted argv (a trailing sentence
    ``。``, prose, Markdown) changes the split's last argument, so the
    canonical re-join differs and this assertion fails — which is precisely
    the defect an operator's unmodified paste would execute.
    """

    tokens = shlex.split(tail)
    assert tokens[0] == "tve", tail
    rejoined = shlex.join(tokens)
    assert rejoined == tail, (
        f"the displayed command tail carries decoration a pasted copy would "
        f"execute as part of an argument: {tail!r} (canonical form would be "
        f"{rejoined!r})"
    )
    return tokens


def _assert_literal_tail_pastes_exactly(
    tail: str, expected_argv: list[str], sandbox: Path
) -> None:
    """Pasting the literal tail into a shell must invoke a no-op ``tve``
    stub with EXACTLY the intended argv and create zero side-effect files.

    ``expected_argv`` is constructed independently from the known CLI
    inputs, never re-derived from the displayed text.
    """

    code, argv, stray, stderr = _run_hint_with_stub(
        tail, sandbox, precreate=_PLACEHOLDER_SOURCES
    )
    assert code == 0, f"the pasted literal tail failed under a stub: {stderr}"
    assert argv == expected_argv[1:], (
        f"the pasted literal tail reached the stub as {argv} instead of the "
        f"intended {expected_argv[1:]}"
    )
    assert stray == [], f"the pasted literal tail created files: {stray}"


def _retry_tail(steps: list[str]) -> str:
    tails = [t for t in _literal_command_tails(steps) if "readiness-summary" in t]
    assert tails, f"no readiness-summary retry tail in {steps}"
    assert len(tails) == 1, f"ambiguous retry tails: {tails}"
    return tails[0]


def _expected_retry_argv(
    *,
    config: Path | str,
    activation_root: Path | str | None,
    base: Path | str = BASE_PROFILE_PATH,
    target: Path | str = TARGET_PROFILE_PATH,
    manifest: Path | str = MANIFEST_PATH,
    decision_records: tuple[Path | str, ...] = (),
    revocations: tuple[Path | str, ...] = (),
    policy_exceptions: tuple[Path | str, ...] = (),
    trust_root: Path | str | None = None,
    authority_evidence: Path | str | None = None,
    signed_revocations: tuple[Path | str, ...] = (),
    signed_supersessions: tuple[Path | str, ...] = (),
    boundary_input: Path | str | None = None,
) -> list[str]:
    """The independently constructed retry argv (the known CLI inputs in
    the parser's own argument order)."""

    argv = [
        "tve",
        "evolution",
        "readiness-summary",
        "--base-profile",
        str(base),
        "--target-profile",
        str(target),
        "--release-manifest",
        str(manifest),
        "--project-config",
        str(config),
    ]
    if boundary_input is not None:
        argv.extend(["--boundary-input", str(boundary_input)])
    for path in decision_records:
        argv.extend(["--decision-record", str(path)])
    for path in revocations:
        argv.extend(["--revocation", str(path)])
    for path in policy_exceptions:
        argv.extend(["--policy-exception", str(path)])
    if trust_root is not None:
        argv.extend(["--trust-root", str(trust_root)])
    if authority_evidence is not None:
        argv.extend(["--authority-evidence", str(authority_evidence)])
    for path in signed_revocations:
        argv.extend(["--signed-revocation", str(path)])
    for path in signed_supersessions:
        argv.extend(["--signed-supersession", str(path)])
    if activation_root is not None:
        argv.extend(["--activation-root", str(activation_root)])
    return argv


def _expected_status_argv(*, config: Path | str, activation_root: Path | str) -> list[str]:
    return [
        "tve",
        "evolution",
        "activation-status",
        "--project-config",
        str(config),
        "--activation-root",
        str(activation_root),
    ]


def _expected_preview_argv(
    *,
    config: Path | str,
    activation_root: Path | str,
    base: Path | str = BASE_PROFILE_PATH,
    target: Path | str = TARGET_PROFILE_PATH,
    manifest: Path | str = MANIFEST_PATH,
    decision_records: tuple[Path | str, ...] = (),
    policy_exceptions: tuple[Path | str, ...] = (),
    trust_root: Path | str | None = None,
    authority_evidence: Path | str | None = None,
) -> list[str]:
    argv = [
        "tve",
        "evolution",
        "activate-profile",
        "--base-profile",
        str(base),
        "--target-profile",
        str(target),
        "--release-manifest",
        str(manifest),
    ]
    for path in decision_records:
        argv.extend(["--decision-record", str(path)])
    for path in policy_exceptions:
        argv.extend(["--policy-exception", str(path)])
    argv.extend(["--project-config", str(config)])
    if trust_root is not None:
        argv.extend(["--trust-root", str(trust_root)])
    if authority_evidence is not None:
        argv.extend(["--authority-evidence", str(authority_evidence)])
    argv.extend(["--activation-root", str(activation_root)])
    return argv


# ---------------------------------------------------------------------------
# F1 — the literal copyable tail must be exactly the intended command
# ---------------------------------------------------------------------------


def test_f1_authenticated_retry_tail_is_paste_ready_verbatim(tmp_path, capsys):
    """The PREVIEW_READY retry command must survive a literal copy: the
    text after the last full-width colon splits to the exact expected argv
    and pastes into a stub with byte-identical arguments — the baseline
    delivered ``<activation-root>。`` as the final argument instead."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    assert payload["owner_authority_revalidated"] is True

    tail = _retry_tail(payload["next_steps_zh"])
    expected = _expected_retry_argv(
        config=env.config_path,
        activation_root=env.activation_root,
        decision_records=(env.record_path,),
        policy_exceptions=(env.exception_path,),
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    tokens = _assert_tail_is_a_canonical_command_line(tail)
    assert tokens == expected, (tokens, expected)
    _assert_literal_tail_pastes_exactly(tail, expected, tmp_path / "f1-retry-sandbox")


def test_f1_status_tail_is_paste_ready_verbatim(tmp_path, capsys):
    """The STORE_NEEDS_ATTENTION (and every other) status hint must also
    carry zero decoration after the command — the baseline's trailing ``。``
    corrupted the last path argument of the status command too."""

    from tests.test_owner_readiness_summary_r1_probes import _applied_env

    env, receipt = _applied_env(tmp_path, capsys)
    tampered = json.loads(receipt.read_text("utf-8"))
    tampered["activated_config_sha256"] = "0" * 64
    receipt.write_text(json.dumps(tampered, indent=2), "utf-8")
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "STORE_NEEDS_ATTENTION"

    expected = _expected_status_argv(
        config=env.config_path, activation_root=env.activation_root
    )
    status_tails = [
        t for t in _literal_command_tails(payload["next_steps_zh"])
        if "activation-status" in t
    ]
    assert status_tails, "the attention journey must name the status command"
    for tail in status_tails:
        tokens = _assert_tail_is_a_canonical_command_line(tail)
        assert tokens == expected, (tokens, expected)
        _assert_literal_tail_pastes_exactly(
            tail, expected, tmp_path / "f1-status-sandbox"
        )


def test_f1_preview_tail_is_paste_ready_verbatim(tmp_path, capsys):
    """The PREVIEW_READY read-only preview command tail pastes verbatim."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"

    preview_tails = [
        t for t in _literal_command_tails(payload["next_steps_zh"])
        if "activate-profile" in t
    ]
    assert preview_tails, "the preview-ready journey must show the preview command"
    expected = _expected_preview_argv(
        config=env.config_path,
        activation_root=env.activation_root,
        decision_records=(env.record_path,),
        policy_exceptions=(env.exception_path,),
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    for tail in preview_tails:
        tokens = _assert_tail_is_a_canonical_command_line(tail)
        assert tokens == expected, (tokens, expected)
        _assert_literal_tail_pastes_exactly(
            tail, expected, tmp_path / "f1-preview-sandbox"
        )


def test_f1_journey_start_retry_tail_is_paste_ready_verbatim(tmp_path, capsys):
    """The journey-start (OWNER_DECISION_REQUIRED) retry command — fewer
    replay inputs — must equally paste verbatim."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _bare_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "OWNER_DECISION_REQUIRED"

    tail = _retry_tail(payload["next_steps_zh"])
    expected = _expected_retry_argv(
        config=env.config_path, activation_root=env.activation_root
    )
    tokens = _assert_tail_is_a_canonical_command_line(tail)
    assert tokens == expected, (tokens, expected)
    _assert_literal_tail_pastes_exactly(
        tail, expected, tmp_path / "f1-start-sandbox"
    )


def test_f1_hostile_paths_and_genuine_full_stop_filenames(tmp_path, capsys):
    """Operator paths containing spaces, single AND double quotes, dollar
    signs, backticks, semicolons, redirection characters, Chinese text and
    a GENUINE filename ending in ``。`` must survive the literal tail
    byte-for-byte: the real trailing ``。`` stays inside the quoted path
    (it belongs to that operator-supplied filename), while the sentence
    punctuation must never become a path suffix on any argument."""

    hostile = tmp_path / "私密 目录; '引号' \"双引\" `tick` $HOME"
    env = _Env(hostile).setup(capsys)
    inputs = hostile / "输入 with spaces"
    inputs.mkdir(parents=True, exist_ok=True)
    # a genuine decision record whose whole filename ends with a full stop
    record = inputs / "决策记录。"
    record.write_bytes(env.record_path.read_bytes())
    exception = inputs / "exception `q` \"d\".json"
    exception.write_bytes(env.exception_path.read_bytes())
    # the evidence bundle is a directory; the metacharacters live in the
    # copied directory name
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
    assert payload["journey_state"] == "PREVIEW_READY"

    expected_retry = _expected_retry_argv(
        config=env.config_path,
        activation_root=env.activation_root,
        decision_records=(record,),
        policy_exceptions=(exception,),
        trust_root=env.trust_root,
        authority_evidence=evidence,
        boundary_input=boundary,
    )
    # the genuine full-stop filename survives as its own exact argv entry
    assert str(record) in expected_retry
    assert str(record).endswith("。")

    tail = _retry_tail(payload["next_steps_zh"])
    tokens = _assert_tail_is_a_canonical_command_line(tail)
    assert tokens == expected_retry, (tokens, expected_retry)
    _assert_literal_tail_pastes_exactly(
        tail, expected_retry, tmp_path / "f1-hostile-sandbox"
    )

    preview_tails = [
        t for t in _literal_command_tails(payload["next_steps_zh"])
        if "activate-profile" in t
    ]
    expected_preview = _expected_preview_argv(
        config=env.config_path,
        activation_root=env.activation_root,
        decision_records=(record,),
        policy_exceptions=(exception,),
        trust_root=env.trust_root,
        authority_evidence=evidence,
    )
    for preview_tail in preview_tails:
        tokens = _assert_tail_is_a_canonical_command_line(preview_tail)
        assert tokens == expected_preview, (tokens, expected_preview)
        _assert_literal_tail_pastes_exactly(
            preview_tail, expected_preview, tmp_path / "f1-hostile-sandbox"
        )


def test_f1_no_command_tail_ends_with_sentence_punctuation_after_the_command(
    tmp_path, capsys
):
    """No prose step in any journey may leave text after a displayed
    command's final quoted argument — and no prose step may masquerade as
    a command (start with ``tve `` right after the last colon)."""

    journeys = _build_all_journeys(capsys, tmp_path)
    for name, payload in journeys.items():
        for step in payload["next_steps_zh"]:
            if "：" not in step:
                continue
            tail = step.rsplit("：", 1)[1]
            mentions_tve = "tve " in tail
            if tail.startswith("tve "):
                # a real command: canonical and paste-ready (covered in
                # depth by the tests above; assert the shape here too)
                _assert_tail_is_a_canonical_command_line(tail)
            else:
                assert not mentions_tve or not tail.startswith("tve"), (
                    f"{name}: prose masquerading as a command: {step}"
                )


def test_f1_all_journeys_tails_are_complete_safe_and_literally_copyable(
    tmp_path, capsys
):
    """Across ALL eleven journey states every literal command tail parses
    through the real CLI parser, names only a read-only subcommand, carries
    no ``--apply``/``--output``/``--expected-*`` option, is a canonical
    ``shlex.join`` line, and pastes into a no-op stub with the exact
    displayed argv and zero side-effect files."""

    journeys = _build_all_journeys(capsys, tmp_path)
    observed_states = set()
    sandbox = tmp_path / "r2-master-sandbox"
    for name, payload in journeys.items():
        observed_states.add(payload["journey_state"])
        steps = payload["next_steps_zh"]
        for placeholder in _KNOWN_PLACEHOLDERS:
            assert placeholder not in "\n".join(steps), (name, placeholder)
        tails = _literal_command_tails(steps)
        assert tails, f"{name}: expected at least one executable next step"
        for tail in tails:
            tokens = _assert_tail_is_a_canonical_command_line(tail)
            assert tokens[2] in _READONLY_SUBCOMMANDS, (name, tail)
            for forbidden in ("--output", "--apply", "--expected-plan-id"):
                assert forbidden not in tokens, (name, forbidden, tail)
            args = _parse_hint(tail)
            assert getattr(args, "apply", False) is False
            assert getattr(args, "output", None) is None
            assert getattr(args, "expected_plan_id", None) is None
            # the no-op stub receives exactly the displayed token vector
            code, argv, stray, stderr = _run_hint_with_stub(
                tail, sandbox, precreate=_PLACEHOLDER_SOURCES
            )
            assert code == 0, (name, stderr)
            assert argv == tokens[1:], (name, tail, argv)
            assert stray == [], (name, tail, stray)
    assert observed_states >= _ALL_JOURNEY_STATES, (
        f"journey states not exercised: {_ALL_JOURNEY_STATES - observed_states}"
    )


# ---------------------------------------------------------------------------
# Replay fidelity through the literal tail (order, multiplicity, identity)
# ---------------------------------------------------------------------------


def test_literal_retry_tail_replays_the_exact_observation(tmp_path, capsys):
    """Executing the literal retry tail through the REAL CLI (read-only)
    must reproduce the identical summary identity and observation — on the
    baseline the decorated last path made the replay fail closed instead."""

    from tests.test_owner_readiness_summary_r1_probes import (
        _probe_dir,
        _revocation_file,
        _signed_revocation_evidence,
        _signed_supersession_evidence,
        _distinct_accept_record,
    )

    env = _Env(tmp_path).setup(capsys)
    probe = _probe_dir(tmp_path)
    revocation = _revocation_file(env, probe)
    signed_revocation = _signed_revocation_evidence(env, probe)
    superseding = _distinct_accept_record(capsys, env, probe / "second")
    supersession = _signed_supersession_evidence(
        env, env.record_path, superseding, probe
    )
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[env.record_path, env.record_path],
        policy_exceptions=[env.exception_path, env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
        extra=[
            "--boundary-input", str(BOUNDARY_PATH),
            "--revocation", str(revocation),
            "--revocation", str(revocation),
            "--signed-revocation", str(signed_revocation),
            "--signed-revocation", str(signed_revocation),
            "--signed-supersession", str(supersession),
            "--signed-supersession", str(supersession),
        ],
    )
    assert code == 0, out
    payload = json.loads(out)

    tail = _retry_tail(payload["next_steps_zh"])
    expected = _expected_retry_argv(
        config=env.config_path,
        activation_root=env.activation_root,
        decision_records=(env.record_path, env.record_path),
        revocations=(revocation, revocation),
        policy_exceptions=(env.exception_path, env.exception_path),
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
        signed_revocations=(signed_revocation, signed_revocation),
        signed_supersessions=(supersession, supersession),
        boundary_input=BOUNDARY_PATH,
    )
    tokens = _assert_tail_is_a_canonical_command_line(tail)
    assert tokens == expected, (tokens, expected)
    _assert_literal_tail_pastes_exactly(
        tail, expected, tmp_path / "replay-stub-sandbox"
    )

    # the real CLI replay of the literal tail reproduces the observation
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    replayed = json.loads(out2)
    assert replayed["summary_id"] == payload["summary_id"]
    assert replayed["content_sha256"] == payload["content_sha256"]
    assert replayed["journey_state"] == payload["journey_state"]
    assert replayed["owner_authority_revalidated"] == (
        payload["owner_authority_revalidated"]
    )
    assert replayed["informational_blockers"] == payload["informational_blockers"]
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_repeatable_inputs_keep_order_and_multiplicity_in_the_literal_tail(
    tmp_path, capsys
):
    """Every repeatable option keeps its per-option order and multiplicity
    inside the literally copied tail."""

    from tests.test_owner_readiness_summary_r1_probes import (
        _probe_dir,
        _revocation_file,
        _signed_revocation_evidence,
    )

    env = _Env(tmp_path).setup(capsys)
    probe = _probe_dir(tmp_path)
    revocation = _revocation_file(env, probe)
    signed_revocation = _signed_revocation_evidence(env, probe)
    env.activation_root.mkdir(parents=True)
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[env.record_path, env.record_path],
        policy_exceptions=[env.exception_path, env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
        extra=[
            "--revocation", str(revocation),
            "--revocation", str(revocation),
            "--signed-revocation", str(signed_revocation),
        ],
    )
    assert code == 0, out
    payload = json.loads(out)
    tokens = shlex.split(_retry_tail(payload["next_steps_zh"]))

    def _values(token_list: list[str], flag: str) -> list[str]:
        return [
            token_list[index + 1]
            for index, token in enumerate(token_list)
            if token == flag and index + 1 < len(token_list)
        ]

    assert _values(tokens, "--decision-record") == [
        str(env.record_path),
        str(env.record_path),
    ]
    assert _values(tokens, "--policy-exception") == [
        str(env.exception_path),
        str(env.exception_path),
    ]
    assert _values(tokens, "--revocation") == [str(revocation), str(revocation)]
    assert _values(tokens, "--signed-revocation") == [str(signed_revocation)]


# ---------------------------------------------------------------------------
# F2 — write-step accuracy
# ---------------------------------------------------------------------------


def test_f2_no_write_command_step_claims_to_be_the_sole_write_step(
    tmp_path, capsys
):
    """Neither decision-dossier nor plan-activation may be described as the
    journey's ONLY file-writing step — both write (the baseline dossier
    step claimed ``唯一写文件步骤``)."""

    journeys = _build_all_journeys(capsys, tmp_path)
    offenders: list[tuple[str, str]] = []
    for name, payload in journeys.items():
        for step in payload["next_steps_zh"]:
            if "decision-dossier" in step or "plan-activation" in step:
                if "唯一" in step:
                    offenders.append((name, step))
    assert offenders == [], (
        f"a write command was described with an exclusivity claim: {offenders}"
    )


def test_f2_both_write_commands_disclose_their_write_and_output_choice(
    tmp_path, capsys
):
    """decision-dossier --output writes the operator-chosen Markdown file;
    plan-activation --output ALSO writes an operator-chosen plan file.  Both
    steps must disclose the write, name --output and the operator's path
    choice, and neither may be labelled read-only."""

    journeys = _build_all_journeys(capsys, tmp_path)
    dossier_steps: list[str] = []
    plan_steps: list[str] = []
    for name, payload in journeys.items():
        for step in payload["next_steps_zh"]:
            if "decision-dossier" in step:
                dossier_steps.append(step)
            if "plan-activation" in step:
                plan_steps.append(step)
    assert dossier_steps, "the journey start must still explain decision-dossier"
    assert plan_steps, "the blocked journey must still explain plan-activation"
    for step in dossier_steps:
        assert "写入" in step, f"the dossier write is not disclosed: {step}"
        assert "--output" in step, f"the required --output is not named: {step}"
        assert "只读" not in step, f"a write command was labelled read-only: {step}"
    for step in plan_steps:
        assert "写入" in step, f"the plan write is not disclosed: {step}"
        assert "--output" in step, f"the required --output is not named: {step}"
        assert "只读" not in step, f"a write command was labelled read-only: {step}"
        # plan-activation writes TOO — the disclosure must not present it as
        # the only/first write of the journey
        assert ("同样" in step) or ("也" in step), (
            f"the plan write is not framed as an additional write: {step}"
        )


# ---------------------------------------------------------------------------
# Boundary invariants preserved: zero writes, no network, no secrets
# ---------------------------------------------------------------------------


def test_summary_and_literal_tails_are_zero_write_and_socket_free(
    tmp_path, capsys, monkeypatch
):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))

    def no_sockets(*args, **kwargs):
        raise AssertionError("the readiness summary constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)

    # executing the LITERAL displayed retry through the real CLI writes
    # nothing anywhere the journey observes
    tail = _retry_tail(payload["next_steps_zh"])
    tokens = shlex.split(tail)
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))

    # and the literal tail pasted into a sandboxed stub leaves no trace
    expected = _expected_retry_argv(
        config=env.config_path,
        activation_root=env.activation_root,
        decision_records=(env.record_path,),
        policy_exceptions=(env.exception_path,),
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    _assert_literal_tail_pastes_exactly(tail, expected, tmp_path / "sandbox")


def test_displayed_output_and_literal_tails_never_leak_private_key_material(
    tmp_path, capsys
):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    assert "PRIVATE KEY" not in out
    assert "BEGIN" not in out
    private_raw = env.key.private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()
    assert private_raw not in out
    for tail in _literal_command_tails(json.loads(out)["next_steps_zh"]):
        assert private_raw not in tail
