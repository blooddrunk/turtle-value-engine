"""Phase 7-C4-C: the single read-only owner-readiness summary.

The user-journey tests here drive the *real* CLI with throwaway
runtime-generated Ed25519 keys (reusing the C4-A executor fixtures) and
prove that ONE zero-write command answers the whole owner-readiness
journey: which published pair is being evaluated and whether its bytes are
verified, what the CDC 14%-pass vs 12%-S-band policy question means with
the 13% behavioural contrast, whether a valid owner decision exists and
whether its authority was freshly re-attested, what the activation store
proves, and which concrete read-only step comes next.

The summary is informational only: it never writes a byte (no --output
exists), never locks, signs, repairs, approves or applies anything, keeps
the established plan/status facts nested as source facts, and its
``summary_is_informational_not_authorization`` literal stays fixed.  The
first tests were written tests-first and failed on the pre-C4-C baseline
(the command did not exist; ``plan-activation``/``activate-profile``
refuse to run without a decision record at all, and ``decision-dossier``
requires a file write), which is the demonstrated operator gap this phase
closes.
"""

import json
import socket
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from jsonschema import Draft202012Validator

from tests.test_activation_execution import (
    BASE_PROFILE_PATH,
    MANIFEST_PATH,
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
from turtle_value_engine.evolution.owner_readiness import (
    JOURNEY_STATE_VALUES,
    OwnerReadinessSummaryV1,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _summary_cli(
    capsys,
    *,
    project_config: Path,
    activation_root: Path | None,
    base_profile: Path = BASE_PROFILE_PATH,
    target_profile: Path = TARGET_PROFILE_PATH,
    release_manifest: Path = MANIFEST_PATH,
    decision_records: list[Path] | None = None,
    policy_exceptions: list[Path] | None = None,
    trust_root: Path | None = None,
    authority_evidence: Path | None = None,
    extra: list[str] | None = None,
):
    argv = [
        "evolution",
        "readiness-summary",
        "--base-profile",
        base_profile,
        "--target-profile",
        target_profile,
        "--release-manifest",
        release_manifest,
        "--project-config",
        project_config,
    ]
    if activation_root is not None:
        argv.extend(["--activation-root", activation_root])
    for path in decision_records or []:
        argv.extend(["--decision-record", path])
    for path in policy_exceptions or []:
        argv.extend(["--policy-exception", path])
    if trust_root is not None:
        argv.extend(["--trust-root", trust_root])
    if authority_evidence is not None:
        argv.extend(["--authority-evidence", authority_evidence])
    argv.extend(extra or [])
    return _cli(capsys, *argv)


def _env_summary(capsys, env: _Env, *, with_store: bool = True, **overrides):
    return _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root if with_store else None,
        decision_records=[env.record_path],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
        **overrides,
    )


def _bare_summary(capsys, env: _Env, *, with_store: bool = True):
    """The journey-start view: no decision, no exception, no trust root."""

    return _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root if with_store else None,
    )


def _observed_paths(env: _Env) -> list[Path]:
    return [
        env.activation_root,
        env.tmp / "bundle",
        env.tmp / "trust-root",
        env.tmp / "decisions",
        env.tmp / "evidence",
        env.tmp / "private",
        env.config_path,
    ]


def _revoke_key(capsys, env: _Env) -> None:
    code, out = _cli(
        capsys,
        "provenance",
        "registry",
        "revoke",
        "--trust-root",
        env.trust_root,
        "--key-id",
        env.key.key_id,
        "--reference",
        "test revocation for the readiness summary",
    )
    assert code == 0, out


def _second_record(
    capsys, env: _Env, tmp_path: Path, *, decision: str
) -> Path:
    """Record one additional signed decision through the real CLI path."""

    from turtle_value_engine.providers.models import canonical_json_bytes

    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = _accept_payload(decision=decision)
    if decision == "REJECT":
        # A REJECT binds no exception; the canonical byte form still
        # carries the explicit null fields the model round-trips.
        payload["exception_id"] = None
        payload["exception_content_sha256"] = None
    decision_path = tmp_path / f"decision-{decision.lower()}.json"
    decision_path.write_bytes(canonical_json_bytes(payload))
    # the same registered owner key signs the second decision (one owner,
    # two decisions for the same target -> a genuine conflict)
    statement = _signed_statement(env.key, decision_path.read_bytes())
    statement_path = tmp_path / f"statement-{decision.lower()}.json"
    statement_path.write_text(
        json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True)
        + "\n",
        "utf-8",
    )
    record_path = tmp_path / f"record-{decision.lower()}.json"
    argv = [
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
    ]
    if decision == "ACCEPT_WITH_EXCEPTION":
        argv.extend(["--policy-exception", env.exception_path])
    argv.extend(
        [
            "--signed-statement",
            statement_path,
            "--trust-root",
            env.trust_root,
            "--record-output",
            record_path,
        ]
    )
    code, out = _cli(capsys, *argv)
    assert code == 0, out
    return record_path


# ---------------------------------------------------------------------------
# 1. The user-journey gap: one read-only answer at the journey start
# ---------------------------------------------------------------------------


def test_journey_start_single_read_only_answer(tmp_path, capsys):
    """No decision, no exception, empty store: ONE command answers all six
    required determinations and writes nothing anywhere."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _bare_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)

    # (1) which pair and manifest are being evaluated
    assert payload["contract"] == "owner_readiness_summary_v1"
    assert payload["base_profile_id"] == "strict-v1"
    assert payload["target_profile_id"] == "strict-v2"
    assert payload["release_manifest_id"].startswith(
        "versioned-profile-release-candidate-"
    )
    # (2) published bytes / identities verified
    assert payload["published_bytes_verified"] is True
    assert payload["audit_activation_readiness"] == "POLICY_DECISION_REQUIRED"
    # (3) the CDC policy question with the 14/12 discrepancy and 13% contrast
    question = "\n".join(payload["policy_question_zh"])
    assert "0.14" in question and "0.12" in question
    contrast = "\n".join(payload["behavior_contrast_zh"])
    assert "13.0" in contrast
    assert "WATCH" in contrast
    # (4) no valid owner decision; nothing claims revalidated authority
    assert payload["decision_authority_state"] == "NO_DECISION"
    assert payload["decision"] is None
    assert payload["owner_authority_revalidated"] is False
    # (5) activation state: blocked on the missing decision, empty store
    assert payload["journey_state"] == "OWNER_DECISION_REQUIRED"
    assert "NO_OWNER_DECISION_RECORD" in payload["plan_blockers"]
    assert payload["activation_store_status"] == "NO_HISTORY"
    assert payload["current_default_profile"] == "strict-v1"
    assert payload["project_config_sha256"] == _sha(env.config_path)
    # (6) concrete next steps naming read-only commands
    steps = "\n".join(payload["next_steps_zh"])
    assert "decision-dossier" in steps
    assert "readiness-summary" in steps
    assert "activate-profile" in steps
    # informational blockers never claim authorization
    assert "OWNER_DECISION_REQUIRED" in payload["informational_blockers"]
    assert payload["summary_is_informational_not_authorization"] is True
    assert payload["automatic_activation_allowed"] is False
    assert payload["execution_performed"] is False
    assert payload["requires_human_policy_approval"] is True

    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
    # stable repeated output over unchanged bytes
    code2, out2 = _bare_summary(capsys, env)
    assert code2 == 0 and out2 == out


def test_journey_start_without_any_store_supplied(tmp_path, capsys):
    """--activation-root is optional; the journey answer still works."""

    env = _Env(tmp_path).setup(capsys)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _bare_summary(capsys, env, with_store=False)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["activation_root_supplied"] is False
    assert payload["activation_store_status"] is None
    assert payload["journey_state"] == "OWNER_DECISION_REQUIRED"
    assert not env.activation_root.exists(), "no store may be created"
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_missing_store_directory_stays_missing(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _bare_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["activation_store_status"] == "NO_HISTORY"
    assert not env.activation_root.exists(), "the missing store stays missing"
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# 2. Authenticated ACCEPT: fresh preview facts, no automatic application
# ---------------------------------------------------------------------------


def test_authenticated_accept_preview_ready(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    assert payload["plan_state"] == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert payload["decision"] == "ACCEPT_WITH_EXCEPTION"
    assert payload["decision_record_id"].startswith("owner-policy-decision-")
    # authority was RE-attested by the actual existing verification path
    assert payload["owner_authority_revalidated"] is True
    assert payload["decision_authority_state"] == "ACCEPT_VERIFIED"
    assert payload["activation_store_status"] == "NO_HISTORY"
    steps = "\n".join(payload["next_steps_zh"])
    assert "activate-profile" in steps
    assert "--apply" not in steps, "next steps are read-only command hints"
    assert payload["execution_performed"] is False
    assert _sha(env.config_path) == before[str(env.config_path)]
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
    # the summary does not replace the real preview: the executor preview
    # still works afterwards and derives the same READY state
    preview_code, preview_out = env.preview(capsys)
    assert preview_code == 0, preview_out
    assert json.loads(preview_out)["preview_state"] == "READY_FOR_APPLY"


def test_authenticated_accept_without_store_does_not_create_it(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _env_summary(capsys, env, with_store=False)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    assert payload["activation_store_status"] is None
    assert not env.activation_root.exists()


# ---------------------------------------------------------------------------
# 3. REJECT / revoked / conflicting / unverified authority
# ---------------------------------------------------------------------------


def _reject_env(tmp_path, capsys) -> tuple[_Env, Path]:
    from turtle_value_engine.providers.models import canonical_json_bytes

    env = _Env(tmp_path).setup(capsys)
    bundle = tmp_path / "reject-bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    payload = _accept_payload(decision="REJECT")
    # canonical REJECT bytes carry explicit null exception fields
    payload["exception_id"] = None
    payload["exception_content_sha256"] = None
    decision_path = bundle / "decision-reject.json"
    decision_path.write_bytes(canonical_json_bytes(payload))
    statement = _signed_statement(env.key, decision_path.read_bytes())
    statement_path = bundle / "statement-reject.json"
    statement_path.write_text(
        json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True)
        + "\n",
        "utf-8",
    )
    record_path = bundle / "record-reject.json"
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
        "--signed-statement",
        statement_path,
        "--trust-root",
        env.trust_root,
        "--record-output",
        record_path,
    )
    assert code == 0, out
    return env, record_path


def test_reject_decision_is_terminal_information(tmp_path, capsys):
    env, record_path = _reject_env(tmp_path, capsys)
    env.activation_root.mkdir(parents=True)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[record_path],
        trust_root=env.trust_root,
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "REJECTED_BY_OWNER"
    assert payload["decision"] == "REJECT"
    assert "DECISION_IS_REJECT" in payload["plan_blockers"]
    # the plan re-attests only ACCEPT_VERIFIED claims; a REJECT authorizes
    # nothing, so no authority re-attestation is claimed for it
    assert payload["owner_authority_revalidated"] is False
    steps = "\n".join(payload["next_steps_zh"])
    assert "strict-v1" in steps
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_revoked_key_blocks_authority_informationally(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    _revoke_key(capsys, env)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "OWNER_AUTHORITY_NOT_PROVEN"
    assert "OWNER_AUTHORITY_NOT_PROVEN" in payload["informational_blockers"]
    assert any(
        blocker.startswith("OWNER_AUTHORITY_REVERIFICATION")
        for blocker in payload["plan_blockers"]
    )
    assert payload["owner_authority_revalidated"] is False
    assert payload["decision"] == "ACCEPT_WITH_EXCEPTION"
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_accept_without_trust_root_never_claims_authority(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        decision_records=[env.record_path],
        policy_exceptions=[env.exception_path],
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "OWNER_AUTHORITY_NOT_PROVEN"
    assert payload["owner_authority_revalidated"] is False
    assert "OWNER_AUTHORITY_REVERIFICATION_REQUIRED" in payload["plan_blockers"]


def test_conflicting_accept_and_reject_is_a_named_conflict(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    reject_record = _second_record(capsys, env, env.tmp / "second", decision="REJECT")
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        decision_records=[env.record_path, reject_record],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "DECISION_CONFLICT"
    assert "DECISIONS_CONFLICTING" in payload["plan_blockers"]
    assert payload["owner_authority_revalidated"] is False


# ---------------------------------------------------------------------------
# 4. Activation-store states observed honestly
# ---------------------------------------------------------------------------


def _applied_env(tmp_path, capsys) -> tuple[_Env, Path]:
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    return env, receipt_path


def test_already_applied_state(tmp_path, capsys):
    env, receipt_path = _applied_env(tmp_path, capsys)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["activation_store_status"] == "ACTIVATED_VERIFIED"
    assert payload["journey_state"] == "ALREADY_APPLIED"
    assert payload["current_default_profile"] == "strict-v2"
    steps = "\n".join(payload["next_steps_zh"])
    assert "rollback-activation" in steps
    assert payload["owner_authority_revalidated"] is True
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_rolled_back_state(tmp_path, capsys):
    env, receipt_path = _applied_env(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["activation_store_status"] == "ROLLED_BACK_VERIFIED"
    assert payload["journey_state"] == "ROLLED_BACK"
    assert payload["current_default_profile"] == "strict-v1"
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_interrupted_apply_reports_recovery_pending(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    _apply_with_fault(env, capsys, fault_point="journal_persisted")
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["activation_store_status"] == "APPLY_RESUMABLE"
    assert payload["journey_state"] == "RECOVERY_PENDING"
    steps = "\n".join(payload["next_steps_zh"])
    assert "activation-status" in steps
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_corrupt_store_reports_needs_attention(tmp_path, capsys):
    env, receipt_path = _applied_env(tmp_path, capsys)
    tampered = json.loads(receipt_path.read_text("utf-8"))
    tampered["activated_config_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(tampered, indent=2), "utf-8")
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "STORE_NEEDS_ATTENTION"
    assert payload["activation_store_status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert payload["activation_store_problems"], "the named problems are surfaced"
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_config_already_target_without_history(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('"strict-v1"', '"strict-v2"'), "utf-8"
    )
    code, out = _env_summary(capsys, env, with_store=False)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["current_default_profile"] == "strict-v2"
    assert payload["journey_state"] == "ACTIVATION_BLOCKED"
    assert "DEFAULT_ALREADY_TARGET" in payload["plan_blockers"]


# ---------------------------------------------------------------------------
# 5. Input guards: classified exit 2, zero writes, no tracebacks
# ---------------------------------------------------------------------------


def test_missing_target_profile_is_classified_exit_2(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        target_profile=env.tmp / "does-not-exist.yaml",
    )
    assert code == 2, out
    assert "Traceback" not in out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_symlinked_profile_is_classified_exit_2(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    link = env.tmp / "target-link.yaml"
    link.symlink_to(TARGET_PROFILE_PATH)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        target_profile=link,
    )
    assert code == 2, out
    assert "Traceback" not in out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_malformed_decision_record_is_classified_exit_2(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    bad = env.tmp / "bad-record.json"
    bad.write_text('{"contract": "not-a-record"}', "utf-8")
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        decision_records=[bad],
    )
    assert code == 2, out
    assert "Traceback" not in out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_missing_project_config_is_classified_exit_2(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _summary_cli(
        capsys,
        project_config=env.tmp / "missing-config.toml",
        activation_root=None,
    )
    assert code == 2, out
    assert "Traceback" not in out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_evidence_without_trust_root_is_classified_exit_2(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        decision_records=[env.record_path],
        authority_evidence=env.bundle_path,
    )
    assert code == 2, out
    assert "--trust-root" in out


# ---------------------------------------------------------------------------
# 6. Boundary invariants: no network, no secrets, no authority claims
# ---------------------------------------------------------------------------


def test_summary_socket_free_execution(tmp_path, capsys, monkeypatch):
    env = _Env(tmp_path).setup(capsys)

    def no_sockets(*args, **kwargs):
        raise AssertionError("the readiness summary constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    code, out = _bare_summary(capsys, env)
    assert code == 0, out


def test_output_carries_no_secret_material(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    assert "PRIVATE KEY" not in out
    assert "BEGIN" not in out
    # the throwaway private key material itself never appears anywhere
    private_raw = env.key.private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()
    assert private_raw not in out
    # no synthetic owner identity claim beyond the recorded record's facts
    payload = json.loads(out)
    assert payload["owner_authority_revalidated"] is True  # genuinely re-attested
    assert payload["summary_is_informational_not_authorization"] is True


def test_fixed_literals_never_authorize(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _bare_summary(capsys, env)
    payload = json.loads(out)
    assert payload["requires_human_policy_approval"] is True
    assert payload["automatic_activation_allowed"] is False
    assert payload["execution_performed"] is False
    assert payload["summary_is_informational_not_authorization"] is True
    assert payload["read_only_observation"] is True


def test_journey_states_are_the_documented_enumeration():
    assert JOURNEY_STATE_VALUES == frozenset(
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


def test_published_pair_blocked_when_bytes_diverge(tmp_path, capsys):
    """A tampered target profile yields the PUBLISHED_PAIR_BLOCKED journey."""

    env = _Env(tmp_path).setup(capsys)
    tampered = env.tmp / "strict-v2-tampered.yaml"
    tampered.write_text(
        TARGET_PROFILE_PATH.read_text("utf-8").replace("pass: 0.14", "pass: 0.99"),
        "utf-8",
    )
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=None,
        target_profile=tampered,
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["published_bytes_verified"] is False
    assert payload["audit_activation_readiness"] == "BLOCKED_FOR_ACTIVATION"
    assert payload["journey_state"] == "PUBLISHED_PAIR_BLOCKED"


# ---------------------------------------------------------------------------
# 7. Compatibility: the executor journey keeps working around the summary
# ---------------------------------------------------------------------------


def test_genuine_apply_rollback_still_work_after_summary(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["journey_state"] == "PREVIEW_READY"
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    applied = json.loads(out)
    assert applied["status"] == "ACTIVATED"
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    # idempotent repeat after another summary
    code, out = _env_summary(capsys, env)
    assert code == 0, out
    assert json.loads(out)["journey_state"] == "ALREADY_APPLIED"
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    assert json.loads(out)["status"] == "COMPLETED_ALREADY"
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ROLLED_BACK"


def test_summary_id_deterministic_and_bound(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code1, out1 = _env_summary(capsys, env)
    code2, out2 = _env_summary(capsys, env)
    assert out1 == out2
    payload = json.loads(out1)
    assert payload["summary_id"].startswith("owner-readiness-summary-")
    # a different config changes the observed facts and the summary identity
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('id = "turtle-value-engine"', 'id = "other"'),
        "utf-8",
    )
    code3, out3 = _env_summary(capsys, env)
    assert json.loads(out3)["summary_id"] != payload["summary_id"]


# ---------------------------------------------------------------------------
# 8. Contract surface
# ---------------------------------------------------------------------------


def test_summary_model_rejects_authorization_fields(tmp_path):
    """No field can turn the summary into an authorization artifact."""

    model_fields = set(OwnerReadinessSummaryV1.model_fields)
    assert "approval" not in model_fields
    assert "authorized" not in model_fields
    literals = OwnerReadinessSummaryV1.model_fields[
        "summary_is_informational_not_authorization"
    ]
    assert literals.annotation.__args__[0] is True


def test_summary_checked_in_schema_has_drift_parity():
    schema = json.loads(
        (ROOT / "schemas" / "owner-readiness-summary.schema.json").read_text("utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert schema == OwnerReadinessSummaryV1.model_json_schema()


def test_cli_help_documents_read_only_contract(capsys):
    from turtle_value_engine.cli import _build_parser

    parser = _build_parser()
    argv = [
        "evolution",
        "readiness-summary",
        "--base-profile",
        "a",
        "--target-profile",
        "b",
        "--release-manifest",
        "c",
        "--project-config",
        "d",
    ]
    args = parser.parse_args(argv)
    assert args.base_profile == Path("a")
    assert args.activation_root is None
    assert args.decision_record is None or list(args.decision_record) == []
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["evolution", "readiness-summary"])
    assert excinfo.value.code == 2


def test_real_subprocess_journey_smoke(tmp_path, capsys):
    """One literal python -m invocation through the real CLI entry point."""

    env = _Env(tmp_path).setup(capsys)
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "turtle_value_engine",
            "evolution",
            "readiness-summary",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(TARGET_PROFILE_PATH),
            "--release-manifest",
            str(MANIFEST_PATH),
            "--project-config",
            str(env.config_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["journey_state"] == "OWNER_DECISION_REQUIRED"
    assert payload["summary_is_informational_not_authorization"] is True
    assert not env.activation_root.exists()
