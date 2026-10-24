"""Phase 7-C4-B: read-only activation status and disposable operator rehearsal.

Two test families, both fully deterministic and disposable:

* **Classification fixtures** (goal §2 items 1–8): every status class is
  built from real persisted artifacts — a genuine signed apply/rollback
  through the real CLI with throwaway runtime Ed25519 keys, or a library
  fault-hook crash at a named executor fault point — and then classified by
  the real ``tve evolution activation-status`` CLI.  Every case additionally
  proves the inspection wrote zero bytes: the complete file/entry state of
  the activation store, the config and the config's parent directory
  (staging files) is snapshotted before and after each invocation, and
  repeated invocations produce byte-identical stdout.
* **Operator rehearsal** (goal §4): one subprocess-driven
  preview → apply → status → rollback → status walkthrough over a
  space-carrying private tree using the literal ``python -m
  turtle_value_engine`` boundary, plus the three deterministic injected
  faults (journal-persisted, config-replaced-before-receipt,
  restored-before-rollback-outcome) verified against the CLI status without
  any recovery being performed by the status command itself.

No real owner key material, no network, no sleeps, no uncontrolled
concurrency.  ``rules/strict-v1.yaml``, ``rules/strict-v2.yaml``, the
release manifest and ``config/project.example.toml`` stay byte-identical.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.test_activation_execution import (
    BASE_PROFILE_PATH,
    CONFIG_TEMPLATE_SHA256,
    MANIFEST_FILE_SHA256,
    MANIFEST_PATH,
    PRIVATE_CONFIG_TEMPLATE,
    STRICT_V1_SHA256,
    STRICT_V2_SHA256,
    TARGET_PROFILE_PATH,
    _accept_payload,
    _activated_bytes,
    _boundary,
    _cli,
    _Env,
    _sha,
    _signed_statement,
)
from turtle_value_engine.evolution.activation_execution import (
    ActivationExecutionError,
)
from turtle_value_engine.evolution.activation_status import (
    ACTIVATION_STATUS_VALUES,
    ProfileActivationStatusV1,
    inspect_activation_status,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _status_cli(
    capsys, activation_root: Path, project_config: Path, receipt: Path | None = None
):
    argv = [
        "evolution",
        "activation-status",
        "--activation-root",
        activation_root,
        "--project-config",
        project_config,
    ]
    if receipt is not None:
        argv.extend(["--receipt", receipt])
    code, out = _cli(capsys, *argv)
    return code, out


def _env_status(capsys, env: _Env, receipt: Path | None = None):
    return _status_cli(
        capsys, env.activation_root, env.config_path, receipt=receipt
    )


def _tree_snapshot(*roots: Path) -> dict[str, str]:
    """Complete file-and-entry state: every path -> sha256 (or kind marker)."""

    state: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            state[str(root)] = "<missing>"
            continue
        if root.is_file():
            state[str(root)] = _sha(root)
            continue
        state[str(root)] = "<dir>"
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                state[str(path)] = "<symlink>"
            elif path.is_file():
                state[str(path)] = _sha(path)
            elif path.is_dir():
                state[str(path)] = "<dir>"
            else:
                state[str(path)] = "<other>"
    return state


def _state_diff(before: dict[str, str], after: dict[str, str]) -> dict[str, tuple]:
    diff = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            diff[key] = (before.get(key), after.get(key))
    return diff


def _assert_zero_writes(before: dict[str, str], after: dict[str, str]) -> None:
    diff = _state_diff(before, after)
    assert diff == {}, f"the read-only status command changed state: {diff}"


def _observed_paths(env: _Env) -> list[Path]:
    return [env.activation_root, env.config_path.parent, env.config_path]


class _Crash(Exception):
    """Deterministic injected fault (library-only hook)."""


def _library_apply_inputs(env: _Env, record_path: Path | None = None,
                          bundle_path: Path | None = None) -> dict:
    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
        load_owner_decision_evidence,
    )

    evidence = load_owner_decision_evidence(bundle_path or env.bundle_path)
    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    verifier = SignedOwnerProvenanceVerifier(
        registry=registry,
        statement=evidence.statement,
        decision_input_bytes=evidence.decision_input_bytes,
    )
    return {
        "activation_root": env.activation_root,
        "base_profile_path": BASE_PROFILE_PATH,
        "target_profile_path": TARGET_PROFILE_PATH,
        "release_manifest_path": MANIFEST_PATH,
        "boundary_input": _boundary(),
        "decision_records": [load_decision_record(record_path or env.record_path)],
        "revocations": [],
        "policy_exceptions": [env.exception],
        "authority_verifier": verifier,
        "authority_evidence": evidence,
        "signed_revocations": [],
        "signed_supersessions": [],
        "lifecycle_trust_root": registry,
        "project_config_path": env.config_path,
    }


def _apply_with_fault(env: _Env, capsys, fault_point: str, **input_overrides) -> None:
    from turtle_value_engine.evolution.activation_execution import (
        apply_profile_activation,
    )

    preview = env.ready_preview(capsys)
    common = _library_apply_inputs(env, **input_overrides)
    with pytest.raises(_Crash):
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=preview["original_config_sha256"],
            fault_hook=lambda point: (_ for _ in ()).throw(_Crash())
            if point == fault_point
            else None,
            **common,
        )


def _rollback_with_fault(receipt_path: Path, env: _Env, fault_point: str) -> None:
    from turtle_value_engine.evolution.activation_execution import (
        rollback_profile_activation,
    )

    with pytest.raises(_Crash):
        rollback_profile_activation(
            receipt_path=receipt_path,
            activation_root=env.activation_root,
            fault_hook=lambda point: (_ for _ in ()).throw(_Crash())
            if point == fault_point
            else None,
        )


def _applied(tmp_path: Path, capsys) -> tuple[_Env, Path, str, str, dict]:
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    activated_sha = _sha(env.config_path)
    return env, receipt_path, original_sha, activated_sha, preview


def _apply_over_config(env: _Env, capsys, config_path: Path):
    """A real library apply targeting another config in the same store."""

    from turtle_value_engine.evolution.activation_execution import (
        apply_profile_activation,
        preview_profile_activation,
    )

    common = _library_apply_inputs(env)
    common["project_config_path"] = config_path
    preview = preview_profile_activation(**common)
    result = apply_profile_activation(
        expected_plan_id=preview.plan_id,
        expected_config_sha256=preview.original_config_sha256,
        **common,
    )
    assert result.status == "ACTIVATED"
    return result


def _single_file(directory: Path, pattern: str = "*") -> Path:
    matches = sorted(directory.glob(pattern))
    assert len(matches) == 1, matches
    return matches[0]


def _single_rollback_outcome(directory: Path) -> Path:
    """The one ``*.json`` outcome, excluding its ``*.intent.json`` sibling."""

    matches = [
        path
        for path in sorted(directory.glob("*.json"))
        if not path.name.endswith(".intent.json")
    ]
    assert len(matches) == 1, matches
    return matches[0]


# ---------------------------------------------------------------------------
# 1. NO_HISTORY (goal §2 item 1)
# ---------------------------------------------------------------------------


def test_status_no_history_missing_root_creates_nothing(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["activation_root_present"] is False
    assert payload["relevant_histories"] == 0
    assert payload["unrelated_histories"] == 0
    assert payload["problems"] == []
    assert payload["current_default_profile"] == "strict-v1"
    assert payload["current_config_sha256"] == _sha(env.config_path)
    assert payload["owner_authority_revalidated"] is False
    assert payload["global_atomic_snapshot_claimed"] is False
    assert payload["read_only_observation"] is True
    assert payload["execution_performed"] is False
    assert payload["guidance_zh"], payload
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
    assert not env.activation_root.exists(), "the missing store must stay missing"


def test_status_no_history_empty_existing_root(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["activation_root_present"] is True


def test_status_no_history_locks_only_is_no_history(tmp_path, capsys):
    """Leftover lock entries are operational state, not activation history."""

    env = _Env(tmp_path).setup(capsys)
    locks = env.activation_root / "locks"
    locks.mkdir(parents=True)
    (locks / "deadbeef.lock").write_bytes(b"")
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["problems"] == []


# ---------------------------------------------------------------------------
# 2. ACTIVATED_VERIFIED (goal §2 item 2)
# ---------------------------------------------------------------------------


def test_status_activated_verified(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert payload["problems"] == []
    assert payload["pending_activation_ids"] == []
    assert payload["relevant_histories"] == 1
    focal = payload["focal"]
    receipt_payload = json.loads(receipt_path.read_text("utf-8"))
    assert focal["activation_id"] == receipt_payload["activation_id"]
    assert focal["receipt_present"] is True
    assert focal["journal_present"] is True
    assert focal["before_image_present"] is True
    assert focal["activated_config_sha256"] == activated_sha
    assert focal["prior_config_sha256"] == original_sha
    assert focal["activated_default_profile"] == "strict-v2"
    assert focal["prior_default_profile"] == "strict-v1"
    assert focal["rollback_id"]
    assert focal["rollback_outcome_present"] is False
    assert focal["rollback_intent_present"] is False
    assert payload["current_default_profile"] == "strict-v2"
    assert any("激活已完成" in line for line in payload["guidance_zh"])

    code2, out2 = _env_status(capsys, env)
    assert code2 == 0
    assert out2 == out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# 3. ROLLED_BACK_VERIFIED (goal §2 item 3)
# ---------------------------------------------------------------------------


def test_status_rolled_back_verified(tmp_path, capsys):
    env, receipt_path, original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK_VERIFIED"
    assert payload["problems"] == []
    focal = payload["focal"]
    assert focal["rollback_outcome_present"] is True
    assert focal["rollback_intent_present"] is True
    assert focal["receipt_present"] is True
    assert payload["current_default_profile"] == "strict-v1"
    assert payload["current_config_sha256"] == original_sha
    assert any("回滚已完成" in line for line in payload["guidance_zh"])
    code2, out2 = _env_status(capsys, env)
    assert out2 == out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# 4. RECEIPT_FINALIZATION_PENDING (goal §2 item 4)
# ---------------------------------------------------------------------------


def test_status_receipt_finalization_pending_from_injected_fault(tmp_path, capsys):
    """Crash at the real fault point: config replaced, receipt not published."""

    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    _apply_with_fault(env, capsys, "config_replaced")
    assert _sha(env.config_path) != original_sha, "the replace really happened"
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "RECEIPT_FINALIZATION_PENDING"
    assert payload["problems"] == []
    assert payload["pending_activation_ids"]
    focal = payload["focal"]
    assert focal["receipt_present"] is False
    assert focal["journal_present"] is True
    assert focal["before_image_present"] is True
    assert any("回执尚未发布" in line for line in payload["guidance_zh"])
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
    code2, out2 = _env_status(capsys, env)
    assert out2 == out


def test_status_receipt_finalization_pending_from_deleted_receipt(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    receipt_path.unlink()
    code, out = _env_status(capsys, env)
    assert code == 1, out
    assert json.loads(out)["status"] == "RECEIPT_FINALIZATION_PENDING"


# ---------------------------------------------------------------------------
# 5. APPLY_RESUMABLE (goal §2 item 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fault_point", ["journal_persisted", "before_image_persisted"]
)
def test_status_apply_resumable(tmp_path, capsys, fault_point):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    _apply_with_fault(env, capsys, fault_point)
    assert _sha(env.config_path) == original_sha, "config still holds prior bytes"
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "APPLY_RESUMABLE"
    assert payload["problems"] == []
    assert payload["pending_activation_ids"]
    focal = payload["focal"]
    assert focal["receipt_present"] is False
    assert focal["journal_present"] is True
    if fault_point == "before_image_persisted":
        assert focal["before_image_present"] is True
    assert any("重新执行同一 apply" in line for line in payload["guidance_zh"])
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# 6. ROLLBACK_FINALIZATION_PENDING (goal §2 item 6)
# ---------------------------------------------------------------------------


def test_status_rollback_finalization_pending_from_injected_fault(tmp_path, capsys):
    """Crash at the real fault point: restored before rollback outcome."""

    env, receipt_path, original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    _rollback_with_fault(receipt_path, env, "config_restored")
    assert _sha(env.config_path) == original_sha, "the restore really happened"
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLBACK_FINALIZATION_PENDING"
    assert payload["problems"] == []
    focal = payload["focal"]
    assert focal["receipt_present"] is True
    assert focal["rollback_intent_present"] is True
    assert focal["rollback_outcome_present"] is False
    assert any("回滚结果尚未发布" in line for line in payload["guidance_zh"])
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
    code2, out2 = _env_status(capsys, env)
    assert out2 == out


def test_status_activated_verified_with_rollback_intent_pending_restore(
    tmp_path, capsys
):
    """Crash between rollback intent persistence and the restore itself."""

    env, receipt_path, original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    _rollback_with_fault(receipt_path, env, "rollback_intent_persisted")
    assert _sha(env.config_path) != original_sha, "config still activated"
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert "ROLLBACK_INTENT_PENDING_RESTORE" in payload["observations"]


def test_status_prior_bytes_without_durable_rollback_proof_is_diverged(
    tmp_path, capsys
):
    """Owner-reverted bytes (no intent/outcome) never become a verified state."""

    env, receipt_path, original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    image = _single_file(env.activation_root / "before-images")
    env.config_path.write_bytes(image.read_bytes())
    assert _sha(env.config_path) == original_sha
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CONFIG_DIVERGED"
    assert "RESTORED_WITHOUT_DURABLE_PROOF" in payload["observations"]


# ---------------------------------------------------------------------------
# 7. CONFIG_DIVERGED and AMBIGUOUS_HISTORY (goal §2 item 7)
# ---------------------------------------------------------------------------


def test_status_config_diverged_after_manual_edit(tmp_path, capsys):
    env, _receipt_path, _original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace(
            'environment = "private"', 'environment = "private2"'
        ),
        "utf-8",
    )
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CONFIG_DIVERGED"
    assert "POST_ACTIVATION_CONFIG_DIVERGED" in payload["observations"]
    assert any("不一致" in line for line in payload["guidance_zh"])
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_status_config_diverged_with_unfinished_intent(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    _apply_with_fault(env, capsys, "journal_persisted")
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace(
            'id = "turtle-value-engine"', 'id = "someone-else"'
        ),
        "utf-8",
    )
    assert _sha(env.config_path) != original_sha
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CONFIG_DIVERGED"
    assert "UNFINISHED_INTENT_CONFIG_DIVERGED" in payload["observations"]


def test_status_ambiguous_history_two_unfinished_intents(tmp_path, capsys):
    """Two genuinely different signed decisions leave two unfinished journals."""

    from turtle_value_engine.providers.models import canonical_json_bytes

    env = _Env(tmp_path).setup(capsys)

    # A second, genuinely different signed decision (different rationale and
    # decided_at) over the same audit/profiles: different record id -> a
    # different plan id -> a different deterministic activation id.
    second_payload = _accept_payload(
        rationale="A second, different owner rationale.",
        decided_at="2026-10-23",
    )
    second_decision = env.submission / "decision-input-2.json"
    second_decision.write_bytes(canonical_json_bytes(second_payload))
    second_statement = _signed_statement(env.key, second_decision.read_bytes())
    second_statement_path = env.submission / "statement-2.json"
    second_statement_path.write_text(
        json.dumps(
            json.loads(second_statement.model_dump_json()),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "utf-8",
    )
    second_record = env.decisions / "record-2.json"
    code, out = _cli(
        capsys,
        "evolution",
        "record-decision",
        "--decision-input",
        second_decision,
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        env.exception_path,
        "--signed-statement",
        second_statement_path,
        "--trust-root",
        env.trust_root,
        "--evidence-root",
        env.tmp / "evidence2",
        "--record-output",
        second_record,
    )
    assert code == 0, out
    bundle2_path = Path(json.loads(out)["evidence_bundle"]["path"])

    # First unfinished intent: a genuine crash at the journal-persisted point.
    _apply_with_fault(env, capsys, "journal_persisted")
    first_journal = _single_file(env.activation_root / "journal", "*.json")

    # Second unfinished intent for the SAME config, differently bound.  The
    # executor itself refuses this combination (ACTIVATION_INTENT_CONFLICT —
    # proven below), so exactly like the apply-side AMBIGUOUS classification
    # this state can only be left by an external actor: derive the genuine
    # second receipt through the public derivation boundary and persist its
    # canonical journal bytes by hand.
    from turtle_value_engine.evolution.activation_execution import (
        _build_intent,
        _derive_execution,
        apply_profile_activation,
        build_activation_receipt,
        preview_profile_activation,
    )

    common = _library_apply_inputs(env, record_path=second_record,
                                   bundle_path=bundle2_path)
    preview2 = preview_profile_activation(**common)
    with pytest.raises(Exception, match="ACTIVATION_INTENT_CONFLICT"):
        apply_profile_activation(
            expected_plan_id=preview2.plan_id,
            expected_config_sha256=preview2.original_config_sha256,
            **common,
        )
    derive_kwargs = {
        key: value
        for key, value in common.items()
        if key != "activation_root"
    }
    derived = _derive_execution(**derive_kwargs)
    receipt2 = build_activation_receipt(
        plan=derived.plan,
        evidence=derived.evidence,
        project_config_path=env.config_path,
        edited=derived.edited,
    )
    assert receipt2.activation_id != first_journal.stem
    (env.activation_root / "journal" / f"{receipt2.activation_id}.json").write_bytes(
        _build_intent(receipt2).serialized_bytes()
    )
    assert len(list((env.activation_root / "journal").iterdir())) == 2

    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "AMBIGUOUS_HISTORY"
    assert len(payload["pending_activation_ids"]) == 2
    assert any("多份未完成" in line for line in payload["guidance_zh"])
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# 8. CORRUPT_OR_UNVERIFIABLE (goal §2 item 8)
# ---------------------------------------------------------------------------


def test_status_corrupt_missing_before_image(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    _single_file(env.activation_root / "before-images").unlink()
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(p.startswith("BEFORE_IMAGE_MISSING:") for p in payload["problems"])


def test_status_corrupt_tampered_before_image(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    image = _single_file(env.activation_root / "before-images")
    image.write_bytes(image.read_bytes() + b"\n# tampered\n")
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("BEFORE_IMAGE_HASH_MISMATCH:") for p in payload["problems"]
    )
    assert payload["focal"]["before_image_present"] is False


def test_status_corrupt_tampered_receipt(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    payload = json.loads(receipt_path.read_text("utf-8"))
    payload["prior_default_profile"] = "strict-v9"
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(p.startswith("RECEIPT_CORRUPT:") for p in result["problems"])


def test_status_corrupt_missing_journal_for_receipt(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    activation_id = json.loads(receipt_path.read_text("utf-8"))["activation_id"]
    (env.activation_root / "journal" / f"{activation_id}.json").unlink()
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("RECEIPT_WITHOUT_JOURNAL:") for p in result["problems"]
    )


def test_status_corrupt_journal_receipt_mismatch(tmp_path, capsys):
    """A journal whose embedded receipt differs from the published one."""

    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    activation_id = json.loads(receipt_path.read_text("utf-8"))["activation_id"]
    journal_path = env.activation_root / "journal" / f"{activation_id}.json"
    journal = json.loads(journal_path.read_text("utf-8"))
    journal["receipt"]["rollback_reference"] = "tampered reference"
    journal_path.write_text(
        json.dumps(journal, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("JOURNAL_CORRUPT:") for p in result["problems"]
    ) or any(
        p.startswith("RECEIPT_JOURNAL_MISMATCH:") for p in result["problems"]
    )


def test_status_corrupt_journal_foreign_entry(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    (env.activation_root / "journal" / "notes.txt").write_text("x")
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("JOURNAL_DIR_FOREIGN_ENTRY:") for p in result["problems"]
    )


def test_status_corrupt_receipts_nonregular_entry(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    fifo = env.activation_root / "receipts" / "pipe.json"
    os.mkfifo(fifo)
    try:
        code, out = _env_status(capsys, env)
        assert code == 1, out
        result = json.loads(out)
        assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
        assert any(
            p.startswith("RECEIPTS_DIR_FOREIGN_ENTRY:")
            for p in result["problems"]
        )
    finally:
        fifo.unlink()


@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="platform without symlink support"
)
def test_status_corrupt_symlinked_journal_file(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    activation_id = json.loads(receipt_path.read_text("utf-8"))["activation_id"]
    journal_path = env.activation_root / "journal" / f"{activation_id}.json"
    outside = env.tmp / "outside-journal.json"
    outside.write_bytes(journal_path.read_bytes())
    journal_path.unlink()
    journal_path.symlink_to(outside)
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("JOURNAL_FILE_SYMLINK:") for p in result["problems"]
    )


@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="platform without symlink support"
)
def test_status_corrupt_symlinked_before_image(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    image = _single_file(env.activation_root / "before-images")
    outside = env.tmp / "outside-image.toml"
    outside.write_bytes(image.read_bytes())
    image.unlink()
    image.symlink_to(outside)
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("BEFORE_IMAGE_FILE_SYMLINK:") for p in result["problems"]
    )


def test_status_corrupt_forged_rollback_association(tmp_path, capsys):
    """A valid, parseable rollback outcome bound to no known activation."""

    from turtle_value_engine.providers.models import canonical_json_bytes
    from turtle_value_engine.providers.normalization import deterministic_id

    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    receipt = json.loads(receipt_path.read_text("utf-8"))
    fields = {
        "contract": "profile_activation_rollback_v1",
        "schema_version": "1.0.0",
        "activation_id": "profile-activation-execution-foreign-unknown",
        "receipt_content_sha256": "0" * 64,
        "project_config_path": receipt["project_config_path"],
        "restored_config_sha256": receipt["prior_config_sha256"],
        "restored_default_profile": receipt["prior_default_profile"],
        "before_image_sha256": receipt["before_image_sha256"],
        "outcome": "ROLLED_BACK",
        "rollback_was_explicit_opt_in": True,
    }
    fields["rollback_id"] = deterministic_id(
        "profile-activation-rollback",
        fields["activation_id"],
        fields["receipt_content_sha256"],
        fields["project_config_path"],
        fields["restored_config_sha256"],
    )
    fields["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {k: v for k, v in fields.items() if k != "content_sha256"}
        )
    ).hexdigest()
    forged = env.activation_root / "rollbacks" / f"{fields['rollback_id']}.json"
    forged.parent.mkdir(parents=True, exist_ok=True)
    forged.write_text(json.dumps(fields, indent=2, sort_keys=True) + "\n", "utf-8")
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("ROLLBACK_UNASSOCIATED:") for p in result["problems"]
    )


def test_status_corrupt_tampered_rollback_outcome(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    outcome = _single_rollback_outcome(env.activation_root / "rollbacks")
    payload = json.loads(outcome.read_text("utf-8"))
    payload["restored_default_profile"] = "strict-v9"
    outcome.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        p.startswith("ROLLBACK_OUTCOME_CORRUPT:") for p in result["problems"]
    )


def test_status_corrupt_root_foreign_entry(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    (env.activation_root / "stray-dir").mkdir()
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert "ACTIVATION_ROOT_FOREIGN_ENTRY:stray-dir" in result["problems"]


def test_status_corrupt_never_reports_verified_green(tmp_path, capsys):
    """Corruption coexisting with activated bytes still blocks the green."""

    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    receipt_payload = json.loads(receipt_path.read_text("utf-8"))
    (env.activation_root / "journal" / "extra.json").write_text("{}\n")
    code, out = _env_status(capsys, env)
    assert code == 1, out
    result = json.loads(out)
    assert result["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert result["focal"]["activation_id"] == receipt_payload["activation_id"]
    del receipt_payload


# ---------------------------------------------------------------------------
# Refusals (unusable input: CLI exit class 2)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="platform without symlink support"
)
def test_status_refuses_symlinked_activation_root(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    real = env.tmp / "real-root"
    real.mkdir()
    env.activation_root.symlink_to(real)
    with pytest.raises(ActivationExecutionError) as raised:
        inspect_activation_status(
            activation_root=env.activation_root,
            project_config_path=env.config_path,
        )
    assert raised.value.code == "ACTIVATION_ROOT_SYMLINK"


@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="platform without symlink support"
)
def test_status_refuses_symlinked_store_directory(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    outside = env.tmp / "outside-store"
    outside.mkdir()
    journal = env.activation_root / "journal"
    for entry in list(journal.iterdir()):
        entry.rename(outside / entry.name)
    journal.rmdir()
    journal.symlink_to(outside)
    with pytest.raises(ActivationExecutionError) as raised:
        inspect_activation_status(
            activation_root=env.activation_root,
            project_config_path=env.config_path,
        )
    assert raised.value.code == "ACTIVATION_STORE_SYMLINK"


def test_status_refuses_protected_activation_root(tmp_path, capsys):
    with pytest.raises(ActivationExecutionError) as raised:
        inspect_activation_status(
            activation_root=ROOT / "rules",
            project_config_path=tmp_path / "project.toml",
        )
    assert raised.value.code == "ACTIVATION_ROOT_PROTECTED"


def test_status_refuses_missing_and_protected_config(tmp_path, capsys):
    with pytest.raises(ActivationExecutionError) as raised:
        inspect_activation_status(
            activation_root=tmp_path / "activation",
            project_config_path=tmp_path / "missing.toml",
        )
    assert raised.value.code == "CONFIG_PATH_UNAVAILABLE"
    with pytest.raises(ActivationExecutionError) as raised:
        inspect_activation_status(
            activation_root=tmp_path / "activation",
            project_config_path=ROOT / "config" / "project.example.toml",
        )
    assert raised.value.code == "CONFIG_PATH_PROTECTED"


@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="platform without symlink support"
)
def test_status_refuses_symlinked_config_cli_exit_2(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    real = env.tmp / "real-config.toml"
    real.write_text(PRIVATE_CONFIG_TEMPLATE, "utf-8")
    env.config_path.unlink()
    env.config_path.symlink_to(real)
    code, out = _env_status(capsys, env)
    assert code == 2, out
    assert "CONFIG_PATH_SYMLINK" in out


# ---------------------------------------------------------------------------
# Unrelated histories and --receipt inspection
# ---------------------------------------------------------------------------


def test_status_scopes_evidence_to_requested_config(tmp_path, capsys):
    """Another config's completed activation is not this config's history."""

    env = _Env(tmp_path).setup(capsys)
    other_root = tmp_path / "other private"
    other_config = other_root / "project.toml"
    other_config.parent.mkdir(parents=True)
    other_config.write_text(PRIVATE_CONFIG_TEMPLATE, "utf-8")

    result = _apply_over_config(env, capsys, other_config)
    assert other_config.read_bytes() == _activated_bytes()

    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["relevant_histories"] == 0
    assert payload["unrelated_histories"] == 1
    assert "UNRELATED_HISTORIES_PRESENT" in payload["observations"]

    code, out = _status_cli(capsys, env.activation_root, other_config)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert payload["relevant_histories"] == 1
    assert payload["unrelated_histories"] == 0
    assert payload["focal"]["activation_id"] == result.receipt.activation_id


def test_status_receipt_inspection_current_receipt(tmp_path, capsys):
    env, receipt_path, _original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env, receipt=receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    inspection = payload["receipt_inspection"]
    assert inspection["activation_id"] == payload["focal"]["activation_id"]
    assert inspection["relevant_to_config"] is True
    assert inspection["current_config_matches_activated"] is True
    assert inspection["journal_present"] is True
    assert inspection["before_image_verified"] is True
    assert inspection["store_copy_present"] is True
    assert inspection["store_copy_matches"] is True
    assert inspection["rollback_outcome_present"] is False
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_status_receipt_inspection_rolled_back_receipt(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    code, out = _env_status(capsys, env, receipt=receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK_VERIFIED"
    inspection = payload["receipt_inspection"]
    assert inspection["current_config_matches_activated"] is False
    assert inspection["rollback_outcome_present"] is True


def test_status_receipt_inspection_outside_copy(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    exported = env.tmp / "exported receipt.json"
    exported.write_bytes(receipt_path.read_bytes())
    code, out = _env_status(capsys, env, receipt=exported)
    assert code == 0, out
    payload = json.loads(out)
    inspection = payload["receipt_inspection"]
    assert inspection["store_copy_present"] is True
    assert inspection["store_copy_matches"] is True
    assert inspection["receipt_path"].endswith("exported receipt.json")


def test_status_receipt_inspection_invalid_receipt(tmp_path, capsys):
    env, _receipt_path, *_rest = _applied(tmp_path, capsys)
    invalid = env.tmp / "invalid receipt.json"
    invalid.write_text("{}\n", "utf-8")
    with pytest.raises(ActivationExecutionError) as raised:
        inspect_activation_status(
            activation_root=env.activation_root,
            project_config_path=env.config_path,
            receipt_path=invalid,
        )
    assert raised.value.code == "RECEIPT_INVALID"


def test_status_receipt_inspection_unrelated_receipt(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    other_root = tmp_path / "other private"
    other_config = other_root / "project.toml"
    other_config.parent.mkdir(parents=True)
    other_config.write_text(PRIVATE_CONFIG_TEMPLATE, "utf-8")

    result = _apply_over_config(env, capsys, other_config)
    other_receipt = (
        env.activation_root / "receipts" / f"{result.receipt.activation_id}.json"
    )
    code, out = _env_status(capsys, env, receipt=other_receipt)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    inspection = payload["receipt_inspection"]
    assert inspection["relevant_to_config"] is False
    assert inspection["current_config_matches_activated"] is False
    assert inspection["journal_present"] is False


# ---------------------------------------------------------------------------
# Config readability observations
# ---------------------------------------------------------------------------


def test_status_unparseable_config_observed_not_hidden(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.config_path.write_text("not = [valid toml\n", "utf-8")
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert "CURRENT_CONFIG_TOML_UNPARSEABLE" in payload["observations"]
    assert payload["current_default_profile"] is None


# ---------------------------------------------------------------------------
# Offline/socket-free execution and protected bytes
# ---------------------------------------------------------------------------


def test_status_socket_free_and_protected_bytes(tmp_path, capsys, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("the status inspection constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    code, out = _env_status(capsys, env, receipt=receipt_path)
    assert code == 0, out
    assert _sha(BASE_PROFILE_PATH) == STRICT_V1_SHA256
    assert _sha(TARGET_PROFILE_PATH) == STRICT_V2_SHA256
    assert _sha(MANIFEST_PATH) == MANIFEST_FILE_SHA256
    assert _sha(ROOT / "config" / "project.example.toml") == CONFIG_TEMPLATE_SHA256


# ---------------------------------------------------------------------------
# Schema drift parity and determinism
# ---------------------------------------------------------------------------


def test_status_checked_in_schema_has_drift_parity():
    schema = json.loads(
        (ROOT / "schemas" / "profile-activation-status.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    assert schema == ProfileActivationStatusV1.model_json_schema()


def test_status_values_are_the_goal_classes():
    assert set(ACTIVATION_STATUS_VALUES) == {
        "NO_HISTORY",
        "ACTIVATED_VERIFIED",
        "ROLLED_BACK_VERIFIED",
        "RECEIPT_FINALIZATION_PENDING",
        "APPLY_RESUMABLE",
        "ROLLBACK_FINALIZATION_PENDING",
        "CONFIG_DIVERGED",
        "AMBIGUOUS_HISTORY",
        "CORRUPT_OR_UNVERIFIABLE",
    }


def test_status_deterministic_repeat_byte_identical(tmp_path, capsys):
    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    first = inspect_activation_status(
        activation_root=env.activation_root,
        project_config_path=env.config_path,
        receipt_path=receipt_path,
    )
    second = inspect_activation_status(
        activation_root=env.activation_root,
        project_config_path=env.config_path,
        receipt_path=receipt_path,
    )
    assert first == second
    assert first.serialized_bytes() == second.serialized_bytes()


def test_status_exit_code_conventions(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, _out = _env_status(capsys, env)
    assert code == 0  # NO_HISTORY is informational

    env_b, _receipt, _original, _activated, _preview = _applied(
        tmp_path / "b", capsys
    )
    code, _out = _env_status(capsys, env_b)
    assert code == 0  # ACTIVATED_VERIFIED is informational
    code, out = _cli(
        capsys,
        "evolution",
        "activation-status",
        "--activation-root",
        env_b.activation_root,
        "--project-config",
        tmp_path / "missing.toml",
    )
    assert code == 2, out


# ---------------------------------------------------------------------------
# Operator rehearsal through the real subprocess CLI (goal §4)
# ---------------------------------------------------------------------------


def _run_cli_subprocess(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "turtle_value_engine", *[str(a) for a in argv]],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )


def test_operator_rehearsal_subprocess_end_to_end(tmp_path, capsys):
    """Preview -> Apply -> Status -> Rollback -> Status over the literal CLI.

    The whole private tree carries a space in its path, and every step's
    disk effect is compared against the snapshot taken before it.
    """

    env = _Env(tmp_path / "private tree with spaces").setup(capsys)
    original_bytes = env.config_path.read_bytes()
    original_sha = _sha(env.config_path)
    argv_base = [
        "evolution",
        "activate-profile",
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        env.exception_path,
        "--decision-record",
        env.record_path,
        "--project-config",
        env.config_path,
        "--trust-root",
        env.trust_root,
        "--authority-evidence",
        env.bundle_path,
        "--activation-root",
        env.activation_root,
    ]
    status_argv = [
        "evolution",
        "activation-status",
        "--activation-root",
        env.activation_root,
        "--project-config",
        env.config_path,
    ]

    def _status(extra: list[str] | None = None) -> tuple[int, dict]:
        completed = _run_cli_subprocess(*status_argv, *(extra or []))
        assert completed.stdout, completed.stderr
        return completed.returncode, json.loads(completed.stdout)

    # 1. Preview: zero tree changes (the activation root does not even exist).
    before = _tree_snapshot(env.activation_root, env.config_path.parent)
    completed = _run_cli_subprocess(*argv_base)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    preview = json.loads(completed.stdout)
    assert preview["preview_state"] == "READY_FOR_APPLY"
    _assert_zero_writes(
        before, _tree_snapshot(env.activation_root, env.config_path.parent)
    )
    assert not env.activation_root.exists()

    # 2. Explicit expected-identity apply.
    completed = _run_cli_subprocess(
        *argv_base,
        "--apply",
        "--expected-plan-id",
        preview["plan_id"],
        "--expected-config-sha256",
        preview["original_config_sha256"],
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    applied = json.loads(completed.stdout)
    assert applied["status"] == "ACTIVATED"
    activated_sha = _sha(env.config_path)
    assert activated_sha == preview["proposed_config_sha256"]
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    receipt_payload = json.loads(receipt_path.read_text("utf-8"))
    assert receipt_payload["activated_config_sha256"] == activated_sha
    image = (
        env.activation_root / "before-images" / receipt_payload["before_image_name"]
    )
    assert _sha(image) == receipt_payload["before_image_sha256"] == original_sha
    assert image.read_bytes() == original_bytes

    # 3. Status -> ACTIVATED_VERIFIED; repeat is byte-identical, zero writes.
    before = _tree_snapshot(*_observed_paths(env))
    code, payload = _status()
    assert code == 0, payload
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert payload["problems"] == []
    first_stdout = _run_cli_subprocess(*status_argv).stdout
    second_stdout = _run_cli_subprocess(*status_argv).stdout
    assert first_stdout == second_stdout
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))

    # 4. Receipt-bound rollback -> byte-exact restoration.
    completed = _run_cli_subprocess(
        "evolution",
        "rollback-activation",
        "--receipt",
        receipt_path,
        "--activation-root",
        env.activation_root,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert json.loads(completed.stdout)["status"] == "ROLLED_BACK"
    assert env.config_path.read_bytes() == original_bytes

    # 5. Status -> ROLLED_BACK_VERIFIED; repeat stable, zero writes.
    before = _tree_snapshot(*_observed_paths(env))
    code, payload = _status()
    assert code == 0, payload
    assert payload["status"] == "ROLLED_BACK_VERIFIED"
    assert _run_cli_subprocess(*status_argv).stdout == (
        _run_cli_subprocess(*status_argv).stdout
    )
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))

    # 6. Receipt inspection through the real CLI.
    code, payload = _status(["--receipt", receipt_path])
    assert code == 0, payload
    inspection = payload["receipt_inspection"]
    assert inspection["store_copy_matches"] is True
    assert inspection["current_config_matches_activated"] is False


def test_operator_rehearsal_interrupted_states_and_recovery(tmp_path, capsys):
    """The three injected faults, classified without recovery by status."""

    # (a) crash after the journal was persisted, before the replace.
    env_a = _Env(tmp_path / "a").setup(capsys)
    _apply_with_fault(env_a, capsys, "journal_persisted")
    assert (
        inspect_activation_status(
            activation_root=env_a.activation_root,
            project_config_path=env_a.config_path,
        ).status
        == "APPLY_RESUMABLE"
    )

    # (b) crash after the replace, before the receipt publication.
    env_b = _Env(tmp_path / "b").setup(capsys)
    preview = env_b.ready_preview(capsys)
    _apply_with_fault(env_b, capsys, "config_replaced")
    status_b = inspect_activation_status(
        activation_root=env_b.activation_root,
        project_config_path=env_b.config_path,
    )
    assert status_b.status == "RECEIPT_FINALIZATION_PENDING"

    # (c) crash after the restore, before the rollback outcome publication.
    env_c, receipt_path, *_rest = _applied(tmp_path / "c", capsys)
    _rollback_with_fault(receipt_path, env_c, "config_restored")
    status_c = inspect_activation_status(
        activation_root=env_c.activation_root,
        project_config_path=env_c.config_path,
    )
    assert status_c.status == "ROLLBACK_FINALIZATION_PENDING"

    # The real CLI apply finalizes (b) without a second config mutation, and
    # the status flips to the verified state only afterwards.
    before_config = env_b.config_path.read_bytes()
    completed = _run_cli_subprocess(
        "evolution",
        "activate-profile",
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        env_b.exception_path,
        "--decision-record",
        env_b.record_path,
        "--project-config",
        env_b.config_path,
        "--trust-root",
        env_b.trust_root,
        "--authority-evidence",
        env_b.bundle_path,
        "--activation-root",
        env_b.activation_root,
        "--apply",
        "--expected-plan-id",
        preview["plan_id"],
        "--expected-config-sha256",
        preview["original_config_sha256"],
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert json.loads(completed.stdout)["status"] == (
        "FINALIZED_AFTER_INTERRUPTED_REPLACE"
    )
    assert env_b.config_path.read_bytes() == before_config
    assert (
        inspect_activation_status(
            activation_root=env_b.activation_root,
            project_config_path=env_b.config_path,
        ).status
        == "ACTIVATED_VERIFIED"
    )
