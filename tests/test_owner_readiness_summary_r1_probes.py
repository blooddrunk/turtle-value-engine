"""Phase 7-C4-C-R1: next-step command safety and replay-context fidelity.

Tests-first probes for the three confirmed C4-C operator-facing defects
(``docs/status/phase-7-c4-c-post-closure-review-2026-10-25.md``):

* **F1** — command-looking ``next_steps_zh`` hints contained bare
  ``<占位符>`` fragments.  POSIX shells lex ``<决策记录>`` as an input
  redirection *plus* an output redirection operator, so pasting the hint
  creates files named ``--policy-exception``/``--project-config``/... and
  silently rewrites argv.  Every shell reproduction here runs a no-op
  ``tve`` stub in a disposable sandbox directory — never the real
  activation CLI, never a real ``--apply``.
* **F2** — the advertised readiness-summary retry dropped every
  decision/exception/revocation/trust/evidence/lifecycle input, so
  copy/pasting it after an authenticated inspection could reset the
  observed journey to the unauthenticated journey-start view.
* **F3** — ``plan-activation`` / ``decision-dossier`` require ``--output``
  and persist a file, yet were presented among (and labelled as) read-only
  next steps.

The whole suite was written against pristine main ``3357b81`` where the F1/F2
probes fail with the literal defects above (stray sandbox files, corrupted
stub argv, dropped decision context, mislabelled write commands).
"""

import json
import os
import shlex
import socket
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from tests.test_activation_execution import (
    BASE_PROFILE_PATH,
    BOUNDARY_PATH,
    MANIFEST_PATH,
    OWNER_IDENTITY,
    PRIVATE_CONFIG_TEMPLATE,
    TARGET_PROFILE_PATH,
    _accept_payload,
    _cli,
    _Env,
    _sha,
    _signed_statement,
)
from tests.test_activation_status import (
    _apply_with_fault,
    _assert_zero_writes,
    _tree_snapshot,
)
from tests.test_owner_readiness_summary import (
    _bare_summary,
    _env_summary,
    _observed_paths,
    _revoke_key,
    _second_record,
    _summary_cli,
)

ROOT = Path(__file__).resolve().parents[1]

# The exact bare placeholder fragments the baseline emitted inside
# command-shaped strings (F1); none may ever appear again in any step.
_KNOWN_PLACEHOLDERS = (
    "<决策记录>",
    "<策略例外>",
    "<信任根>",
    "<证据束>",
    "<执行存储>",
    "<你的路径>",
    "<路径>",
    "<占位符>",
)

# The subcommands that may legitimately appear as an executable read-only
# next-step command.  Anything that requires an operator-chosen --output
# (decision-dossier, plan-activation) or an explicit --apply opt-in must
# stay prose, never a paste-ready command string.
_READONLY_SUBCOMMANDS = frozenset(
    {"readiness-summary", "activation-status", "activate-profile"}
)


# ---------------------------------------------------------------------------
# Shared probe helpers
# ---------------------------------------------------------------------------


def _executable_hints(steps: list[str]) -> list[str]:
    """Extract the executable command of every command-bearing step.

    Composition contract (C4-C-R1, hardened by C4-C-R2): when a step
    carries an executable command, that command is the complete final
    segment after the LAST full-width colon ``：`` of the step with
    NOTHING after it — no trailing ``。`` or any other decoration.  This
    extractor performs no stripping of any kind (the pre-R2 form stripped
    a trailing ``。`` and thereby masked the copyability defect; the R2
    probes pin the literal tail).  Anything else mentioning ``tve`` is
    prose and must not start with ``tve `` after the last colon.
    """

    hints: list[str] = []
    for step in steps:
        if "：" not in step:
            continue
        tail = step.rsplit("：", 1)[1]
        if tail.startswith("tve "):
            hints.append(tail)
    return hints


def _run_hint_with_stub(
    hint: str,
    sandbox: Path,
    *,
    precreate: tuple[str, ...] = (),
):
    """Execute one extracted hint under a no-op ``tve`` stub.

    The stub records the exact argv it received (NUL-separated) and does
    nothing else; any file that appears in the sandbox besides the stub,
    its argv record and the precreated redirect-source placeholders is a
    shell-redirection side effect (F1 evidence).  No repository code and
    no real activation command ever runs here.
    """

    sandbox.mkdir(parents=True, exist_ok=True)
    bin_dir = sandbox / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "tve"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\0' \"$@\" > \"$STUB_OUT\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    for name in precreate:
        (sandbox / name).write_text("placeholder input\n", encoding="utf-8")
    out_file = sandbox / "stub-argv.txt"
    # the stub directory is FIRST on PATH so the displayed ``tve`` resolves
    # to the no-op stub; the system PATH stays available so the shell itself
    # (bash) can be located by the operating system.
    stub_path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    proc = subprocess.run(
        ["bash", "-c", hint],
        cwd=sandbox,
        env={
            "PATH": stub_path,
            "STUB_OUT": str(out_file),
            "HOME": str(sandbox),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    argv: list[str] = []
    if out_file.exists():
        argv = [
            token
            for token in out_file.read_bytes().decode("utf-8").split("\0")
            if token != ""
        ]
    expected_names = {stub.name, out_file.name, *precreate}
    stray = sorted(
        entry.name
        for entry in sandbox.rglob("*")
        if entry.is_file() and entry.name not in expected_names
    )
    return proc.returncode, argv, stray, proc.stderr


_PLACEHOLDER_SOURCES = (
    "决策记录",
    "策略例外",
    "信任根",
    "证据束",
    "执行存储",
    "你的路径.md",
)


def _assert_hint_shell_safe(hint: str, sandbox: Path) -> list[str]:
    """One extracted hint must execute exactly as displayed, with no writes."""

    tokens = shlex.split(hint)
    assert tokens[0] == "tve", hint
    code, argv, stray, stderr = _run_hint_with_stub(
        hint, sandbox, precreate=_PLACEHOLDER_SOURCES
    )
    assert code == 0, f"the displayed command failed under a stub: {stderr}"
    assert argv == tokens[1:], (
        f"the shell reinterpreted the displayed command: {argv} != {tokens[1:]}"
    )
    assert stray == [], f"the displayed command created files: {stray}"
    return tokens


def _parse_hint(hint: str):
    """Parse one extracted hint through the real CLI argument parser."""

    from turtle_value_engine.cli import _build_parser

    tokens = shlex.split(hint)
    return _build_parser().parse_args(tokens[1:])


def _retry_hint(steps: list[str]) -> str:
    hints = [h for h in _executable_hints(steps) if "readiness-summary" in h]
    assert hints, f"no readiness-summary retry hint in {steps}"
    assert len(hints) == 1, f"ambiguous retry hints: {hints}"
    return hints[0]


def _probe_dir(tmp_path: Path) -> Path:
    """A dedicated directory for probe-built inputs.

    The CLI's trust-root separation guard refuses inputs whose parent
    directory also contains the trust root, so probe files live in their
    own subdirectory next to the established ``_Env`` layout.
    """

    directory = tmp_path / "probe-inputs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _distinct_accept_record(capsys, env: _Env, tmp_path: Path) -> Path:
    """A second signed ACCEPT record with a distinct record identity."""

    from turtle_value_engine.providers.models import canonical_json_bytes

    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = _accept_payload(rationale="Second acceptance superseding the first.")
    decision_path = tmp_path / "decision-second.json"
    decision_path.write_bytes(canonical_json_bytes(payload))
    statement = _signed_statement(env.key, decision_path.read_bytes())
    statement_path = tmp_path / "statement-second.json"
    statement_path.write_text(
        json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True)
        + "\n",
        "utf-8",
    )
    record_path = tmp_path / "record-second.json"
    code, out = _cli(
        capsys,
        "evolution",
        "record-decision",
        "--decision-input",
        decision_path,
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        env.exception_path,
        "--signed-statement",
        statement_path,
        "--trust-root",
        env.trust_root,
        "--record-output",
        record_path,
    )
    assert code == 0, out
    return record_path


def _signed_revocation_evidence(env: _Env, tmp_path: Path) -> Path:
    """One key-signed revocation statement over the recorded decision."""

    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerRevocationPayloadV1,
        OwnerSignedRevocationEvidenceV1,
        build_owner_signed_revocation_statement,
        owner_revocation_signature_message,
    )
    from turtle_value_engine.providers.models import canonical_json_bytes

    record = load_decision_record(env.record_path)
    payload = OwnerRevocationPayloadV1(
        revoked_decision_record_id=record.decision_record_id,
        revoked_record_content_sha256=record.content_sha256,
        target_profile_id="strict-v2",
        target_profile_sha256=(
            "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
        ),
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-25",
        rationale="Probe revocation for replay-context fidelity testing.",
        source_revision="c4c-r1-probe",
    )
    statement = build_owner_signed_revocation_statement(
        signature=env.key.private.sign(owner_revocation_signature_message(payload)),
        key_id=env.key.key_id,
        payload=payload,
    )
    evidence = OwnerSignedRevocationEvidenceV1(payload=payload, statement=statement)
    path = tmp_path / "signed-revocation.json"
    path.write_bytes(canonical_json_bytes(evidence.model_dump(mode="json")))
    return path


def _revocation_file(env: _Env, tmp_path: Path) -> Path:
    from turtle_value_engine.evolution.owner_decision import (
        DecisionProvenanceV1,
        OwnerAuthorityAssessmentV1,
        OwnerPolicyDecisionRevocationV1,
        load_decision_record,
    )

    record = load_decision_record(env.record_path)
    revocation = OwnerPolicyDecisionRevocationV1.build(
        revoked_decision_record_id=record.decision_record_id,
        target_profile_id="strict-v2",
        target_profile_sha256=(
            "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
        ),
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-25",
        rationale="Probe revocation for replay-context fidelity testing.",
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c4c-r1-probe",
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="probe revocation stays unverified",
        ),
    )
    path = tmp_path / "revocation.json"
    path.write_text(
        json.dumps(revocation.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _signed_supersession_evidence(
    env: _Env, superseded: Path, superseding: Path, tmp_path: Path
) -> Path:
    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerSignedSupersessionEvidenceV1,
        OwnerSupersessionPayloadV1,
        build_owner_signed_supersession_statement,
        owner_supersession_signature_message,
    )
    from turtle_value_engine.providers.models import canonical_json_bytes

    old = load_decision_record(superseded)
    new = load_decision_record(superseding)
    payload = OwnerSupersessionPayloadV1(
        superseded_decision_record_id=old.decision_record_id,
        superseded_record_content_sha256=old.content_sha256,
        superseding_decision_record_id=new.decision_record_id,
        superseding_record_content_sha256=new.content_sha256,
        target_profile_id="strict-v2",
        target_profile_sha256=(
            "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
        ),
        superseded_by=OWNER_IDENTITY,
        superseded_at="2026-10-25",
        rationale="Probe supersession for replay-context fidelity testing.",
        source_revision="c4c-r1-probe",
    )
    statement = build_owner_signed_supersession_statement(
        signature=env.key.private.sign(
            owner_supersession_signature_message(payload)
        ),
        key_id=env.key.key_id,
        payload=payload,
    )
    evidence = OwnerSignedSupersessionEvidenceV1(
        payload=payload, statement=statement
    )
    path = tmp_path / "signed-supersession.json"
    path.write_bytes(canonical_json_bytes(evidence.model_dump(mode="json")))
    return path


def _applied_env(tmp_path: Path, capsys) -> tuple[_Env, Path]:
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt = env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    return env, receipt


# ---------------------------------------------------------------------------
# F1 — bare <placeholder> fragments are shell redirections
# ---------------------------------------------------------------------------


def test_f1_preview_hint_executes_exactly_as_displayed(tmp_path, capsys):
    """The PREVIEW_READY preview hint must reach a stub with the exact
    intended argv — the baseline placeholder form loses every decision
    input to redirections and creates files named after CLI flags."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    hints = [
        hint
        for hint in _executable_hints(payload["next_steps_zh"])
        if "activate-profile" in hint
    ]
    assert hints, "the preview-ready journey must point at the read-only preview"
    tokens = _assert_hint_shell_safe(hints[0], tmp_path / "f1-preview-sandbox")
    # the decision context survived shell interpretation byte-for-byte
    required_values = {
        str(env.record_path),
        str(env.exception_path),
        str(env.trust_root),
        str(env.bundle_path),
        str(env.activation_root),
        str(env.config_path),
    }
    assert required_values <= set(tokens), (
        f"the displayed preview command lost decision context: {tokens}"
    )
    assert "--apply" not in tokens
    assert "--output" not in tokens


def test_f1_no_step_ever_contains_a_bare_placeholder(tmp_path, capsys):
    """None of the known bare placeholder fragments may appear in any
    journey's steps — each is a live shell redirection."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _bare_summary(capsys, env)
    assert code == 0, out
    joined = "\n".join(json.loads(out)["next_steps_zh"])
    for placeholder in _KNOWN_PLACEHOLDERS:
        assert placeholder not in joined, (
            f"a bare shell-redirect placeholder survived in next_steps: "
            f"{placeholder}"
        )
    # every executable hint of the journey-start view is shell-clean
    for hint in _executable_hints(json.loads(out)["next_steps_zh"]):
        _assert_hint_shell_safe(hint, tmp_path / "f1-start-sandbox")


def test_f1_metachar_paths_round_trip_through_every_hint(tmp_path, capsys):
    """Operator-supplied paths containing spaces, quotes, semicolons, dollar
    signs, backticks and redirection characters must survive the displayed
    commands byte-for-byte, without expansion or redirection."""

    hostile = tmp_path / "my private dir; '$HOME' `tick`"
    env = _Env(hostile).setup(capsys)
    inputs = hostile / "inputs with spaces"
    inputs.mkdir(parents=True, exist_ok=True)
    record = inputs / "record 'one'; $.json"
    record.write_bytes(env.record_path.read_bytes())
    exception = inputs / "exception `q`.json"
    exception.write_bytes(env.exception_path.read_bytes())
    # the evidence bundle is a directory (bundle.json plus its component
    # files); the metacharacters live in the copied directory name
    evidence_dir = inputs / "evi;dence '$x' <dir>"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for component in Path(env.bundle_path).parent.iterdir():
        (evidence_dir / component.name).write_bytes(component.read_bytes())
    evidence = evidence_dir / "bundle.json"
    boundary = inputs / "boundary $x.json"
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
    operator_values = (
        str(record),
        str(exception),
        str(evidence),
        str(boundary),
        str(env.trust_root),
        str(env.activation_root),
    )
    for hint in _executable_hints(payload["next_steps_zh"]):
        tokens = _assert_hint_shell_safe(hint, tmp_path / "metachar-sandbox")
        if "readiness-summary" in hint or "activate-profile" in hint:
            # the replay/preview commands quote the operator paths exactly
            for value in operator_values:
                assert value in tokens, f"{hint} lost the operator path {value}"
    # no environment expansion: the literal $-bearing names round-tripped
    # above (any expansion would have changed the stub argv).


# ---------------------------------------------------------------------------
# F2 — the advertised retry must replay the exact observed context
# ---------------------------------------------------------------------------


def test_f2_retry_command_preserves_the_full_verified_context(tmp_path, capsys):
    """Re-running the displayed retry command must reproduce the same
    authenticated PREVIEW_READY observation, not reset the journey."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[env.record_path],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
        extra=["--boundary-input", str(BOUNDARY_PATH)],
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    assert payload["owner_authority_revalidated"] is True

    retry = _retry_hint(payload["next_steps_zh"])
    args = _parse_hint(retry)
    assert [str(p) for p in args.decision_record] == [str(env.record_path)]
    assert [str(p) for p in args.policy_exception] == [str(env.exception_path)]
    assert str(args.trust_root) == str(env.trust_root)
    assert str(args.authority_evidence) == str(env.bundle_path)
    assert str(args.activation_root) == str(env.activation_root)
    assert str(args.boundary_input) == str(BOUNDARY_PATH)

    tokens = shlex.split(retry)
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    replayed = json.loads(out2)
    assert replayed["summary_id"] == payload["summary_id"]
    assert replayed["journey_state"] == "PREVIEW_READY"
    assert replayed["owner_authority_revalidated"] is True
    assert replayed["decision_record_id"] == payload["decision_record_id"]
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_f2_repeatable_inputs_keep_order_and_multiplicity(tmp_path, capsys):
    """Every repeatable option must appear in the retry with its original
    multiplicity and order (decision records, exceptions, revocations and
    signed revocations), and re-running reproduces the same observation."""

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
            "--revocation",
            str(revocation),
            "--revocation",
            str(revocation),
            "--signed-revocation",
            str(signed_revocation),
            "--signed-revocation",
            str(signed_revocation),
        ],
    )
    assert code == 0, out
    payload = json.loads(out)
    tokens = shlex.split(_retry_hint(payload["next_steps_zh"]))

    def _values(tokens: list[str], flag: str) -> list[str]:
        return [
            tokens[index + 1]
            for index, token in enumerate(tokens)
            if token == flag and index + 1 < len(tokens)
        ]

    assert _values(tokens, "--decision-record") == [
        str(env.record_path),
        str(env.record_path),
    ]
    assert _values(tokens, "--policy-exception") == [
        str(env.exception_path),
        str(env.exception_path),
    ]
    assert _values(tokens, "--revocation") == [
        str(revocation),
        str(revocation),
    ]
    assert _values(tokens, "--signed-revocation") == [
        str(signed_revocation),
        str(signed_revocation),
    ]
    args = _parse_hint(_retry_hint(payload["next_steps_zh"]))
    assert [str(p) for p in args.revocation] == [str(revocation)] * 2
    assert [str(p) for p in args.signed_revocation] == [
        str(signed_revocation)
    ] * 2
    # the retry reproduces the exact same (revoked) observation
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    replayed = json.loads(out2)
    assert replayed["summary_id"] == payload["summary_id"]
    assert replayed["journey_state"] == payload["journey_state"]
    assert replayed["informational_blockers"] == payload["informational_blockers"]


def test_f2_signed_supersession_replays(tmp_path, capsys):
    """Signed supersession statements are carried with multiplicity too."""

    env = _Env(tmp_path).setup(capsys)
    probe = _probe_dir(tmp_path)
    superseding = _distinct_accept_record(capsys, env, probe / "second")
    supersession = _signed_supersession_evidence(
        env, env.record_path, superseding, probe
    )
    env.activation_root.mkdir(parents=True)
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[env.record_path, superseding],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
        extra=[
            "--signed-supersession",
            str(supersession),
            "--signed-supersession",
            str(supersession),
        ],
    )
    assert code == 0, out
    payload = json.loads(out)
    tokens = shlex.split(_retry_hint(payload["next_steps_zh"]))
    assert tokens.count("--signed-supersession") == 2
    supersession_positions = [
        index + 1
        for index, token in enumerate(tokens)
        if token == "--signed-supersession"
    ]
    assert [tokens[i] for i in supersession_positions] == [
        str(supersession),
        str(supersession),
    ]
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    replayed = json.loads(out2)
    assert replayed["summary_id"] == payload["summary_id"]
    assert replayed["journey_state"] == payload["journey_state"]
    assert replayed["plan_blockers"] == payload["plan_blockers"]


def test_f2_authority_blocked_retry_keeps_the_context(tmp_path, capsys):
    """After a key revocation the retry must still carry the decision and
    trust inputs so the re-run reproduces OWNER_AUTHORITY_NOT_PROVEN
    instead of resetting to the journey-start view."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    _revoke_key(capsys, env)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "OWNER_AUTHORITY_NOT_PROVEN"
    args = _parse_hint(_retry_hint(payload["next_steps_zh"]))
    assert args.decision_record, "the retry dropped the decision records"
    assert [str(p) for p in args.decision_record] == [str(env.record_path)]
    assert str(args.trust_root) == str(env.trust_root)
    assert str(args.authority_evidence) == str(env.bundle_path)
    tokens = shlex.split(_retry_hint(payload["next_steps_zh"]))
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    replayed = json.loads(out2)
    assert replayed["summary_id"] == payload["summary_id"]
    assert replayed["journey_state"] == "OWNER_AUTHORITY_NOT_PROVEN"


# ---------------------------------------------------------------------------
# F3 — write commands are never presented as read-only
# ---------------------------------------------------------------------------


def _activation_blocked_payload(capsys, tmp_path):
    env = _Env(tmp_path).setup(capsys)
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('"strict-v1"', '"strict-v2"'), "utf-8"
    )
    code, out = _env_summary(capsys, env, with_store=False)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "ACTIVATION_BLOCKED"
    return payload


def test_f3_plan_activation_is_disclosed_as_a_write_command(tmp_path, capsys):
    """plan-activation requires --output and persists a plan file; its hint
    must disclose the write and must never be labelled read-only."""

    payload = _activation_blocked_payload(capsys, tmp_path)
    plan_steps = [
        step for step in payload["next_steps_zh"] if "plan-activation" in step
    ]
    assert plan_steps, "the blocked journey should still explain plan-activation"
    for step in plan_steps:
        assert "只读" not in step, f"write command labelled read-only: {step}"
        assert "--output" in step, f"the required --output is not named: {step}"
        assert "写入" in step, f"the write is not disclosed: {step}"
    assert not any(
        "plan-activation" in hint
        for hint in _executable_hints(payload["next_steps_zh"])
    ), "a write command was emitted as a paste-ready executable hint"


def test_f3_decision_dossier_mentions_disclose_the_write(tmp_path, capsys):
    """Every decision-dossier mention (journey start and REJECT terminal
    view) must disclose that it writes an operator-chosen Markdown file."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _bare_summary(capsys, env)
    assert code == 0, out
    start_steps = json.loads(out)["next_steps_zh"]
    dossier_steps = [s for s in start_steps if "decision-dossier" in s]
    assert dossier_steps
    for step in dossier_steps:
        assert "写入" in step, f"write not disclosed: {step}"

    # the REJECT terminal view mentions the dossier too
    from tests.test_owner_readiness_summary import _reject_env

    _env, record = _reject_env(tmp_path / "reject", capsys)
    code, out = _summary_cli(
        capsys,
        project_config=_env.config_path,
        activation_root=_env.activation_root,
        decision_records=[record],
        trust_root=_env.trust_root,
    )
    assert code == 0, out
    reject_steps = json.loads(out)["next_steps_zh"]
    dossier_steps = [s for s in reject_steps if "decision-dossier" in s]
    assert dossier_steps
    for step in dossier_steps:
        assert "写入" in step, f"write not disclosed: {step}"


# ---------------------------------------------------------------------------
# Honest guidance: every state's executable hints are complete and safe
# ---------------------------------------------------------------------------


def test_every_executable_hint_is_complete_safe_and_readonly(
    tmp_path, capsys
):
    """Across every reachable journey state, each executable hint parses
    through the real CLI parser, names only a read-only subcommand, carries
    no --apply/--output/--expected-* option, and executes under a stub with
    argv exactly as displayed and zero side-effect files."""

    journeys = _build_all_journeys(capsys, tmp_path)
    sandbox = tmp_path / "master-sandbox"
    for name, payload in journeys.items():
        steps = payload["next_steps_zh"]
        for placeholder in _KNOWN_PLACEHOLDERS:
            assert placeholder not in "\n".join(steps), (name, placeholder)
        hints = _executable_hints(steps)
        assert hints, f"{name}: expected at least one executable next step"
        for hint in hints:
            tokens = shlex.split(hint)
            assert tokens[2] in _READONLY_SUBCOMMANDS, (name, hint)
            for forbidden in ("--output", "--apply", "--expected-plan-id"):
                assert forbidden not in tokens, (name, forbidden, hint)
            args = _parse_hint(hint)
            assert getattr(args, "apply", False) is False
            assert getattr(args, "output", None) is None
            assert getattr(args, "expected_plan_id", None) is None
            _assert_hint_shell_safe(hint, sandbox)


def _build_all_journeys(capsys, tmp_path: Path) -> dict[str, dict]:
    journeys: dict[str, dict] = {}

    env = _Env(tmp_path / "start").setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _bare_summary(capsys, env)
    journeys["OWNER_DECISION_REQUIRED"] = json.loads(out)

    env = _Env(tmp_path / "ready").setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _env_summary(capsys, env)
    journeys["PREVIEW_READY"] = json.loads(out)

    env = _Env(tmp_path / "ready-no-root").setup(capsys)
    code, out = _env_summary(capsys, env, with_store=False)
    journeys["PREVIEW_READY_NO_ROOT"] = json.loads(out)

    from tests.test_owner_readiness_summary import _reject_env

    env, record = _reject_env(tmp_path / "reject", capsys)
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[record],
        trust_root=env.trust_root,
    )
    journeys["REJECTED_BY_OWNER"] = json.loads(out)

    env = _Env(tmp_path / "conflict").setup(capsys)
    reject_record = _second_record(
        capsys, env, tmp_path / "conflict-second", decision="REJECT"
    )
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[env.record_path, reject_record],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    journeys["DECISION_CONFLICT"] = json.loads(out)

    env = _Env(tmp_path / "authority").setup(capsys)
    env.activation_root.mkdir(parents=True)
    _revoke_key(capsys, env)
    code, out = _env_summary(capsys, env)
    journeys["OWNER_AUTHORITY_NOT_PROVEN"] = json.loads(out)

    env = _Env(tmp_path / "blocked").setup(capsys)
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('"strict-v1"', '"strict-v2"'), "utf-8"
    )
    code, out = _env_summary(capsys, env, with_store=False)
    journeys["ACTIVATION_BLOCKED"] = json.loads(out)

    env = _Env(tmp_path / "recovery").setup(capsys)
    _apply_with_fault(env, capsys, fault_point="journal_persisted")
    code, out = _env_summary(capsys, env)
    journeys["RECOVERY_PENDING"] = json.loads(out)

    env, receipt = _applied_env(tmp_path / "applied", capsys)
    code, out = _env_summary(capsys, env)
    journeys["ALREADY_APPLIED"] = json.loads(out)

    env, receipt = _applied_env(tmp_path / "rolled", capsys)
    code, out = env.rollback(capsys, receipt)
    assert code == 0, out
    code, out = _env_summary(capsys, env)
    journeys["ROLLED_BACK"] = json.loads(out)

    env, receipt = _applied_env(tmp_path / "attention", capsys)
    tampered = json.loads(receipt.read_text("utf-8"))
    tampered["activated_config_sha256"] = "0" * 64
    receipt.write_text(json.dumps(tampered, indent=2), "utf-8")
    code, out = _env_summary(capsys, env)
    journeys["STORE_NEEDS_ATTENTION"] = json.loads(out)

    env = _Env(tmp_path / "published").setup(capsys)
    tampered_profile = tmp_path / "published" / "strict-v2-tampered.yaml"
    tampered_profile.write_text(
        TARGET_PROFILE_PATH.read_text("utf-8").replace("pass: 0.14", "pass: 0.99"),
        "utf-8",
    )
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        target_profile=tampered_profile,
    )
    journeys["PUBLISHED_PAIR_BLOCKED"] = json.loads(out)

    for name, payload in journeys.items():
        assert payload["journey_state"] in {
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
        }, (name, payload["journey_state"])
    return journeys


def test_preview_hint_without_activation_root_is_prose_not_command(
    tmp_path, capsys
):
    """activate-profile REQUIRES --activation-root; without one the summary
    must not display a purportedly runnable preview command."""

    env = _Env(tmp_path).setup(capsys)
    code, out = _env_summary(capsys, env, with_store=False)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    assert payload["activation_root_supplied"] is False
    preview_hints = [
        hint
        for hint in _executable_hints(payload["next_steps_zh"])
        if "activate-profile" in hint
    ]
    assert preview_hints == [], (
        f"a preview command without the required --activation-root was "
        f"displayed: {preview_hints}"
    )
    joined = "\n".join(payload["next_steps_zh"])
    assert "activate-profile" in joined, "the preview path is still explained"
    assert "--activation-root" in joined or "activation-root" in joined


# ---------------------------------------------------------------------------
# Boundary invariants preserved: zero writes, no network, no secrets
# ---------------------------------------------------------------------------


def test_summary_and_displayed_retry_are_zero_write_and_socket_free(
    tmp_path, capsys, monkeypatch
):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))

    def no_sockets(*args, **kwargs):
        raise AssertionError("the readiness summary constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    code, out = _bare_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    # executing the displayed retry through the real CLI writes nothing
    retry = _retry_hint(payload["next_steps_zh"])
    tokens = shlex.split(retry)
    code2, out2 = _cli(capsys, *tokens[1:])
    assert code2 == 0, out2
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
    # and the sandboxed stub execution leaves no repository trace
    _assert_hint_shell_safe(retry, tmp_path / "sandbox")


def test_displayed_hints_never_leak_private_key_material(tmp_path, capsys):
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


# ---------------------------------------------------------------------------
# Diagnostic only (goal §3): the summary_id store-binding hypothesis
# ---------------------------------------------------------------------------


def test_diagnostic_summary_id_shared_across_distinct_store_problems(
    tmp_path, capsys
):
    """DIAGNOSTIC ONLY — not an R1 acceptance requirement to fix.

    The C4-C review hypothesised that ``summary_id`` binds the store STATUS
    but not the store problems/guidance, so two genuinely different
    observations of the same status could share one ``summary_id``.  This
    probe holds the whole decision context and the store identity fixed and
    only adds one more named store problem between two summaries, proving
    the collision is real: the same ``summary_id`` covers two projections
    with different ``content_sha256`` and different named problems.  The
    identity repair is a separately scoped future task; this test pins the
    observed behaviour so that any change to it is a deliberate contract
    decision.
    """

    env, receipt = _applied_env(tmp_path, capsys)
    tampered = json.loads(receipt.read_text("utf-8"))
    tampered["activated_config_sha256"] = "0" * 64
    receipt.write_text(json.dumps(tampered, indent=2), "utf-8")
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    first = json.loads(out)

    # one additional named problem in the SAME store, same status class:
    # a foreign entry inside the receipts directory
    foreign = env.activation_root / "receipts" / "zzz-foreign-probe.txt"
    foreign.write_text("diagnostic foreign entry\n", encoding="utf-8")
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    second = json.loads(out)

    assert first["activation_store_status"] == second["activation_store_status"]
    assert first["activation_store_problems"] != second[
        "activation_store_problems"
    ], "expected the foreign entry to add a named store problem"
    assert first["content_sha256"] != second["content_sha256"]
    assert first["summary_id"] == second["summary_id"], (
        "the store-problem binding changed; update this diagnostic and the "
        "status record together"
    )
