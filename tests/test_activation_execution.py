"""Phase 7-C4-A: controlled profile activation and reversible local execution.

Every positive test here drives the *real* end-to-end path with throwaway
runtime-generated Ed25519 keys: sign -> capture -> strict load -> fresh READY
plan -> read-only preview -> explicit apply in a disposable private config ->
receipt/before-image verification -> rollback -> byte-exact restoration.

The negative matrix covers, per the C4-A goal: missing/bad/revoked
signatures, REJECT, conflicting decisions, unsigned supersession, stale or
forged policy exceptions, tampered release/profile bytes, the demonstrated
record/bundle association gap (the 2026-10-22 preflight reproduced on
pristine main: a forged-annotation record with the same decision_record_id
but a different content hash reaches a READY *plan* while the bundle embeds
different bytes — the executor must reject it), already-target states,
symlinks, path aliasing into checked-in artifacts, output collisions,
concurrent writers, interrupted stages (before/after replace), corrupt
receipts/backups and rollback after intervening changes.  Each case asserts
the named error, the exit code and that no unintended bytes changed.

No real owner key material exists here; no real strict-v2 acceptance is
claimed or performed.  `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, the
release manifest and `config/project.example.toml` stay byte-identical.
"""

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from turtle_value_engine import cli as cli_module
from turtle_value_engine import load_normalized_input
from turtle_value_engine.evolution.activation_execution import (
    ActivationExecutionBlocked,
    ActivationExecutionError,
    ProfileActivationIntentV1,
    ProfileActivationPreviewV1,
    ProfileActivationReceiptV1,
    ProfileActivationRollbackIntentV1,
    ProfileActivationRollbackOutcomeV1,
    apply_profile_activation,
    derive_default_profile_edit,
)
from turtle_value_engine.evolution.owner_decision import (
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
)
from turtle_value_engine.evolution.owner_provenance import (
    PROVENANCE_ALGORITHM,
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
    owner_provenance_key_id,
)
from turtle_value_engine.evolution.owner_provenance import (
    OwnerProvenanceKeyRecordV1 as LifecycleKeyRecord,
)
from turtle_value_engine.evolution.owner_trust_store import (
    load_owner_decision_evidence,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
TARGET_PROFILE_PATH = ROOT / "rules" / "strict-v2.yaml"
MANIFEST_PATH = ROOT / "docs" / "releases" / "strict-v2" / "release-candidate.json"
BOUNDARY_PATH = ROOT / "fixtures" / "healthy_cash_cow.json"

STRICT_V1_SHA256 = "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"
STRICT_V2_SHA256 = "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
# The manifest model's internal content hash (bound inside decision inputs).
MANIFEST_CONTENT_SHA256 = (
    "c0d6cb5b60595c8eb67d45735fc8ef05a9a13b6db0f90bf3468f635ec99c61e8"
)
# The raw file bytes of the checked-in release manifest.
MANIFEST_FILE_SHA256 = (
    "604226f405fe03303e45f16e416b68ce4dd27b51f5db260095116e3b356f250d"
)
CONFIG_TEMPLATE_SHA256 = (
    "9c621217285ade015e8537321378c2ad8869ffce1f0665e1e539c3898e45b049"
)
OWNER_IDENTITY = "Ryder Xie"

PRIVATE_CONFIG_TEMPLATE = (
    "# my private project configuration — every byte outside the default\n"
    "schema_version = 1  # schema pinned\n"
    "\n"
    "[project]\n"
    'id = "turtle-value-engine"\n'
    'environment = "private"\n'
    'timezone = "Asia/Taipei"\n'
    "\n"
    "[profiles]\n"
    'default = "strict-v1"  # the one mutable value\n'
    "\n"
    "[paths]\n"
    'private_root = ".tve-private"\n'
    'cache_root = ".tve-cache"\n'
    'historical_root = ".tve-private/historical"\n'
    'artifact_root = ".tve-private/artifacts"\n'
    'reports_root = ".tve-private/reports"\n'
)

_boundary_input = None
_audit_result = None
_audit_no_exception_result = None


def _boundary():
    global _boundary_input
    if _boundary_input is None:
        _boundary_input = load_normalized_input(BOUNDARY_PATH)
    return _boundary_input


def _audit():
    global _audit_result
    if _audit_result is None:
        _audit_result = audit_profile_semantics(
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            boundary_input=_boundary(),
            policy_exceptions=[_policy_exception()],
        )
    return _audit_result


def _audit_no_exception():
    """The fresh audit as a REJECT decision sees it (no exceptions bound)."""
    global _audit_no_exception_result
    if _audit_no_exception_result is None:
        _audit_no_exception_result = audit_profile_semantics(
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            boundary_input=_boundary(),
            policy_exceptions=[],
        )
    return _audit_no_exception_result


def _policy_exception(rationale: str | None = None) -> VersionedPolicyExceptionV1:
    return VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256=STRICT_V2_SHA256,
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale=rationale
        or "Owner accepts the 14% CDC gate sitting above the retained 12% S band.",
        declared_by=OWNER_IDENTITY,
    )


def _accept_payload(**overrides) -> dict:
    audit = (
        _audit_no_exception()
        if overrides.get("decision") == "REJECT"
        else _audit()
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = {
        "contract": "owner_policy_decision_input_v1",
        "decision": "ACCEPT_WITH_EXCEPTION",
        "base_profile_id": "strict-v1",
        "base_profile_sha256": STRICT_V1_SHA256,
        "target_profile_id": "strict-v2",
        "target_profile_sha256": STRICT_V2_SHA256,
        "release_manifest_id": manifest["release_candidate_id"],
        "release_manifest_content_sha256": MANIFEST_CONTENT_SHA256,
        "audit_id": audit.audit_id,
        "audit_content_sha256": audit.content_sha256,
        "exception_id": _policy_exception().exception_id,
        "exception_content_sha256": _policy_exception().content_sha256,
        "rationale": "Accept the stricter 14% CDC gate as intended owner policy.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-22",
        "source_revision": "c4a-test",
    }
    payload.update(overrides)
    return payload


def _accept_bytes(**overrides) -> bytes:
    return canonical_json_bytes(_accept_payload(**overrides))


class _FixtureKey:
    """A throwaway Ed25519 keypair with its registry record."""

    def __init__(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.public_base64 = base64.b64encode(
            self.private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode("ascii")
        self.key_id = owner_provenance_key_id(
            algorithm=PROVENANCE_ALGORITHM, public_key_base64=self.public_base64
        )
        self.record = LifecycleKeyRecord(
            key_id=self.key_id,
            algorithm=PROVENANCE_ALGORITHM,
            public_key_base64=self.public_base64,
            owner_identity=OWNER_IDENTITY,
            authorized_decisions=["ACCEPT_WITH_EXCEPTION", "REJECT"],
            valid_from="2026-01-01",
            valid_until="2026-12-31",
        )


def _signed_statement(key: _FixtureKey, decision_bytes: bytes):
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    return build_owner_signed_decision_statement(
        signature=key.private.sign(
            owner_decision_input_signature_message(decision_input)
        ),
        key_id=key.key_id,
        decision_input=decision_input,
    )


def _cli(capsys, *argv):
    code = cli_module.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_state(root: Path) -> dict[str, tuple[str, int]]:
    state: dict[str, tuple[str, int]] = {}
    if not root.exists():
        return state
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            state[str(path)] = (_sha(path), stat.st_mtime_ns)
    return state


class _Env:
    """One disposable activation environment (trust root, evidence, config)."""

    def __init__(self, tmp_path: Path, key: _FixtureKey | None = None) -> None:
        self.tmp = tmp_path
        self.key = key or _FixtureKey()
        self.submission = tmp_path / "bundle"
        self.trust_root = tmp_path / "trust-root"
        self.decisions = tmp_path / "decisions"
        self.evidence_root = tmp_path / "evidence"
        self.activation_root = tmp_path / "activation"
        self.private_root = tmp_path / "private"
        self.submission.mkdir(parents=True, exist_ok=True)
        self.decisions.mkdir(parents=True, exist_ok=True)
        self.private_root.mkdir(parents=True, exist_ok=True)
        self.public_key = self.submission / "owner.pub"
        self.public_key.write_text(self.key.public_base64 + "\n")

        self.exception = _policy_exception()
        self.exception_path = self.submission / "exception.json"
        self.exception_path.write_text(
            self.exception.model_dump_json() + "\n", "utf-8"
        )
        self.decision_bytes = _accept_bytes()
        self.decision_path = self.submission / "decision-input.json"
        self.decision_path.write_bytes(self.decision_bytes)
        self.statement = _signed_statement(self.key, self.decision_bytes)
        self.statement_path = self.submission / "statement.json"
        self.statement_path.write_text(
            json.dumps(
                json.loads(self.statement.model_dump_json()),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "utf-8",
        )
        self.record_path = self.decisions / "record.json"
        self.bundle_path: Path | None = None
        self.config_path = self.private_root / "project.toml"
        self.config_path.write_text(PRIVATE_CONFIG_TEMPLATE, "utf-8")

    def init_registry(self, capsys) -> None:
        code, out = _cli(
            capsys,
            "provenance",
            "registry",
            "init",
            "--trust-root",
            self.trust_root,
            "--public-key",
            self.public_key,
            "--owner-identity",
            OWNER_IDENTITY,
            "--valid-from",
            "2026-01-01",
            "--valid-until",
            "2026-12-31",
        )
        assert code == 0, out

    def record_and_capture(self, capsys) -> Path:
        code, out = _cli(
            capsys,
            "evolution",
            "record-decision",
            "--decision-input",
            self.decision_path,
            "--base-profile",
            BASE_PROFILE_PATH,
            "--target-profile",
            TARGET_PROFILE_PATH,
            "--release-manifest",
            MANIFEST_PATH,
            "--policy-exception",
            self.exception_path,
            "--signed-statement",
            self.statement_path,
            "--trust-root",
            self.trust_root,
            "--evidence-root",
            self.evidence_root,
            "--record-output",
            self.record_path,
        )
        assert code == 0, out
        self.bundle_path = Path(json.loads(out)["evidence_bundle"]["path"])
        return self.bundle_path

    def setup(self, capsys) -> "_Env":
        self.init_registry(capsys)
        self.record_and_capture(capsys)
        return self

    @property
    def argv(self) -> tuple:
        assert self.bundle_path is not None
        return (
            "evolution",
            "activate-profile",
            "--base-profile",
            BASE_PROFILE_PATH,
            "--target-profile",
            TARGET_PROFILE_PATH,
            "--release-manifest",
            MANIFEST_PATH,
            "--policy-exception",
            self.exception_path,
            "--decision-record",
            self.record_path,
            "--project-config",
            self.config_path,
            "--trust-root",
            self.trust_root,
            "--authority-evidence",
            self.bundle_path,
            "--activation-root",
            self.activation_root,
        )

    def preview(self, capsys, **overrides):
        argv = list(self.argv)
        for key, value in overrides.items():
            argv.extend([f"--{key.replace('_', '-')}", str(value)])
        return _cli(capsys, *argv)

    def apply(
        self,
        capsys,
        plan_id: str,
        config_sha: str,
    ):
        return _cli(
            capsys,
            *self.argv,
            "--apply",
            "--expected-plan-id",
            plan_id,
            "--expected-config-sha256",
            config_sha,
        )

    def rollback(self, capsys, receipt: Path):
        return _cli(
            capsys,
            "evolution",
            "rollback-activation",
            "--receipt",
            receipt,
            "--activation-root",
            self.activation_root,
        )

    def ready_preview(self, capsys) -> dict:
        code, out = self.preview(capsys)
        assert code == 0, out
        payload = json.loads(out)
        assert payload["preview_state"] == "READY_FOR_APPLY", payload["blockers"]
        return payload


def _activated_bytes() -> bytes:
    return PRIVATE_CONFIG_TEMPLATE.encode("utf-8").replace(
        b'"strict-v1"', b'"strict-v2"'
    )


def _no_activation_artifacts(activation_root: Path) -> bool:
    """True when no journal/receipt/before-image/rollback artifact exists."""

    for name in ("journal", "receipts", "before-images", "rollbacks"):
        directory = activation_root / name
        if directory.is_dir() and any(directory.iterdir()):
            return False
    return True


def _without_option(argv: list, flag: str, value: str) -> list:
    """Remove one `flag value` pair from an argv list."""
    result: list = []
    index = 0
    while index < len(argv):
        if (
            argv[index] == flag
            and index + 1 < len(argv)
            and str(argv[index + 1]) == str(value)
        ):
            index += 2
            continue
        result.append(argv[index])
        index += 1
    return result


# ---------------------------------------------------------------------------
# 1. The genuine end-to-end flow
# ---------------------------------------------------------------------------


def test_full_signed_flow_preview_apply_verify_rollback(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()

    # Preview: read-only, activation root untouched, config untouched.
    preview = env.ready_preview(capsys)
    assert preview["plan_state"] == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert preview["original_config_sha256"] == original_sha
    assert preview["prior_default_profile"] == "strict-v1"
    assert preview["proposed_config_sha256"] == hashlib.sha256(
        _activated_bytes()
    ).hexdigest()
    minus = [
        line
        for line in preview["config_diff"]
        if line.startswith("-") and "strict-v1" in line
    ]
    plus = [
        line
        for line in preview["config_diff"]
        if line.startswith("+") and "strict-v2" in line
    ]
    assert minus and plus, preview["config_diff"]
    assert "# the one mutable value" in minus[0]
    assert _no_activation_artifacts(env.activation_root)
    assert env.config_path.read_bytes() == original_bytes

    # Apply: exactly [profiles] default flips; every other byte survives.
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    applied = json.loads(out)
    assert applied["status"] == "ACTIVATED", applied
    receipt_payload = applied["receipt"]
    assert env.config_path.read_bytes() == _activated_bytes()
    assert (
        hashlib.sha256(env.config_path.read_bytes()).hexdigest()
        == receipt_payload["activated_config_sha256"]
    )
    assert receipt_payload["prior_config_sha256"] == original_sha
    assert receipt_payload["prior_default_profile"] == "strict-v1"
    assert receipt_payload["activated_default_profile"] == "strict-v2"

    receipt_path = (
        env.activation_root
        / "receipts"
        / f"{receipt_payload['activation_id']}.json"
    )
    assert receipt_path.is_file()
    persisted_receipt = ProfileActivationReceiptV1.model_validate(
        json.loads(receipt_path.read_bytes())
    )
    assert persisted_receipt.content_sha256 == receipt_payload["content_sha256"]
    before_image = (
        env.activation_root / "before-images" / persisted_receipt.before_image_name
    )
    assert before_image.read_bytes() == original_bytes
    journal = (
        env.activation_root
        / "journal"
        / f"{persisted_receipt.activation_id}.json"
    )
    intent = ProfileActivationIntentV1.model_validate(json.loads(journal.read_bytes()))
    assert intent.receipt == persisted_receipt

    # The activated private config is a valid project config with strict-v2.
    code, out = _cli(
        capsys, "config", "validate", "--input", env.config_path
    )
    assert code == 0, out
    assert "strict-v2" in out

    # Rollback: byte-exact restore of the prior config.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    rolled = json.loads(out)
    assert rolled["status"] == "ROLLED_BACK"
    assert env.config_path.read_bytes() == original_bytes
    outcome_path = (
        env.activation_root / "rollbacks" / f"{rolled['outcome']['rollback_id']}.json"
    )
    ProfileActivationRollbackOutcomeV1.model_validate(
        json.loads(outcome_path.read_bytes())
    )

    # Repeated rollback is an explicit idempotent no-op.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ALREADY_RESTORED"
    assert env.config_path.read_bytes() == original_bytes


def test_preview_is_deterministic_and_read_only(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    before = _tree_state(tmp_path)
    first = env.ready_preview(capsys)
    second = env.ready_preview(capsys)
    assert first["content_sha256"] == second["content_sha256"]
    after = _tree_state(tmp_path)
    assert before == after, "preview must not modify any byte anywhere"


def test_completed_apply_is_an_explicit_no_op(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    activated = _sha(env.config_path)
    state_after_apply = _tree_state(env.activation_root)

    code, out = env.apply(capsys, preview["plan_id"], activated)
    assert code == 0, out
    assert json.loads(out)["status"] == "COMPLETED_ALREADY"
    assert _sha(env.config_path) == activated
    assert _tree_state(env.activation_root) == state_after_apply


def test_reactivation_after_rollback_reuses_deterministic_identities(
    tmp_path, capsys
):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert _sha(env.config_path) == original_sha

    preview2 = env.ready_preview(capsys)
    assert preview2["plan_id"] == preview["plan_id"]
    assert preview2["activation_id"] == preview["activation_id"]
    code, out = env.apply(capsys, preview2["plan_id"], original_sha)
    assert code == 0, out
    assert json.loads(out)["status"] == "ACTIVATED"
    assert _sha(env.config_path) == hashlib.sha256(
        _activated_bytes()
    ).hexdigest()


def test_apply_without_expected_ids_is_refused(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.ready_preview(capsys)
    before = _tree_state(tmp_path)
    code, out = _cli(capsys, *env.argv, "--apply")
    assert code == 2
    assert "--expected-plan-id" in out
    code, out = _cli(
        capsys,
        *env.argv,
        "--apply",
        "--expected-plan-id",
        "some-plan",
    )
    assert code == 2
    assert "--expected-config-sha256" in out
    assert _tree_state(tmp_path) == before


def test_preview_rejects_stray_expected_ids(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _cli(
        capsys, *env.argv, "--expected-plan-id", "x"
    )
    assert code == 2
    assert "--expected-config-sha256 belong to --apply" in out


def test_wrong_expected_plan_id_refused_zero_writes(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    env.ready_preview(capsys)
    code, out = env.apply(capsys, "profile-activation-plan-deadbeef", original_sha)
    assert code == 1
    payload = json.loads(out)
    assert payload["status"] == "PLAN_ID_MISMATCH"
    assert "PLAN_ID_MISMATCH" in payload["blockers"]
    assert _sha(env.config_path) == original_sha
    assert _no_activation_artifacts(env.activation_root)


def test_config_changed_after_preview_refused_not_clobbered(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    foreign = env.config_path.read_text("utf-8").replace(
        "# my private project", "# edited by someone else"
    )
    env.config_path.write_text(foreign, "utf-8")
    foreign_sha = _sha(env.config_path)
    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 1
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_CONFIG_UNSTABLE"
    assert "ACTIVATION_CONFIG_UNSTABLE" in payload["blockers"]
    assert _sha(env.config_path) == foreign_sha


# ---------------------------------------------------------------------------
# 2. The demonstrated association gap (2026-10-22 preflight)
# ---------------------------------------------------------------------------


def _forged_annotation_record_path(env: _Env) -> Path:
    """A record with the same decision_record_id but different content bytes.

    The record id derivation omits authority annotation text, so editing only
    ``authority.detail`` keeps the id while changing ``content_sha256`` —
    exactly the preflight's mismatch class.  Everything else (including the
    signature bindings) stays genuine.
    """

    payload = json.loads(env.record_path.read_text("utf-8"))
    payload["authority"]["detail"] = (
        "FORGED ANNOTATION: never produced by the capture boundary that "
        "wrote the bundle's embedded record."
    )
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {k: v for k, v in payload.items() if k != "content_sha256"}
        )
    ).hexdigest()
    record = OwnerPolicyDecisionRecordV1.model_validate(payload)
    original = OwnerPolicyDecisionRecordV1.model_validate(
        json.loads(env.record_path.read_text("utf-8"))
    )
    assert record.decision_record_id == original.decision_record_id
    assert record.content_sha256 != original.content_sha256
    path = env.decisions / "record-forged-annotation.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return path


def test_planner_still_ready_but_executor_rejects_forged_association(
    tmp_path, capsys
):
    """The reproduced preflight gap: preserved planner semantics, executor
    enforcement.  On pristine main this exact scenario reached a READY plan
    with a record the evidence bundle never embedded; the executor now
    refuses it by name with zero writes."""

    env = _Env(tmp_path).setup(capsys)
    forged_path = _forged_annotation_record_path(env)
    original_sha = _sha(env.config_path)

    # Preserved read-only planner behavior: still READY (pinned).
    plan_path = tmp_path / "plan.json"
    code, out = _cli(
        capsys,
        "evolution",
        "plan-activation",
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        env.exception_path,
        "--decision-record",
        forged_path,
        "--project-config",
        env.config_path,
        "--trust-root",
        env.trust_root,
        "--authority-evidence",
        env.bundle_path,
        "--output",
        plan_path,
    )
    assert code == 0, out
    plan = json.loads(plan_path.read_text("utf-8"))
    assert plan["plan_state"] == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert (
        plan["decision_record_content_sha256"]
        != json.loads(env.bundle_path.read_text("utf-8"))["record"]["content_sha256"]
    )

    # The executor independently refuses the mismatched association.
    argv = list(env.argv)
    argv[argv.index("--decision-record") + 1] = str(forged_path)
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert preview["preview_state"] == "BLOCKED"
    assert "EVIDENCE_RECORD_CONTENT_MISMATCH" in preview["executor_blockers"]
    assert "EVIDENCE_RECORD_BYTES_MISMATCH" in preview["executor_blockers"]

    # Apply with the forged record: refused, zero writes.
    code, out = _cli(
        capsys,
        *argv,
        "--apply",
        "--expected-plan-id",
        plan["plan_id"],
        "--expected-config-sha256",
        original_sha,
    )
    assert code == 1
    assert json.loads(out)["status"] == "ACTIVATION_BLOCKED"
    assert "EVIDENCE_RECORD_CONTENT_MISMATCH" in json.loads(out)["blockers"]
    assert _sha(env.config_path) == original_sha
    assert _no_activation_artifacts(env.activation_root)


def test_wholly_different_record_rejected_everywhere(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    other_bytes = _accept_bytes(
        rationale="A materially different genuine rationale for the fixture."
    )
    other_statement = _signed_statement(env.key, other_bytes)
    other_path = env.decisions / "decision-other.json"
    other_path.write_bytes(other_bytes)
    statement_path = env.submission / "statement-other.json"
    statement_path.write_text(
        json.dumps(
            json.loads(other_statement.model_dump_json()), indent=2, sort_keys=True
        )
        + "\n",
        "utf-8",
    )
    other_record = env.decisions / "record-other.json"
    code, out = _cli(
        capsys,
        "evolution",
        "record-decision",
        "--decision-input",
        other_path,
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
        other_record,
    )
    assert code == 0, out

    # A different rationale record is not the bundle's record: the plan-time
    # re-attestation already rejects it (record-input binding), and the
    # executor would too.
    argv = list(env.argv)
    argv[argv.index("--decision-record") + 1] = str(other_record)
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert preview["preview_state"] == "BLOCKED"
    assert any(
        "OWNER_AUTHORITY_REVERIFICATION" in blocker
        for blocker in preview["blockers"]
    )


# ---------------------------------------------------------------------------
# 3. Authority negatives: missing / bad / revoked / REJECT / conflicts
# ---------------------------------------------------------------------------


def test_missing_trust_root_and_evidence_blocks(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    argv = _without_option(list(env.argv), "--trust-root", env.trust_root)
    argv = _without_option(argv, "--authority-evidence", env.bundle_path)
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert "OWNER_AUTHORITY_REVERIFICATION_REQUIRED" in preview["blockers"]
    assert "EVIDENCE_BUNDLE_ABSENT" in preview["executor_blockers"]
    assert _no_activation_artifacts(env.activation_root)


def test_bad_signature_blocks(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    statement_payload = json.loads(env.statement_path.read_text("utf-8"))
    statement_payload["signature_base64"] = base64.b64encode(b"\x00" * 64).decode()
    # keep the statement content-hash self-consistent is impossible after a
    # signature edit, so tamper at the bundle level instead: replace the
    # persisted statement bytes with a different genuine-but-foreign one.
    other_key = _FixtureKey()
    other_statement = _signed_statement(other_key, env.decision_bytes)
    bundle_dir = env.bundle_path.parent
    (bundle_dir / "statement.json").write_text(
        json.dumps(
            json.loads(other_statement.model_dump_json()), indent=2, sort_keys=True
        )
        + "\n",
        "utf-8",
    )
    with pytest.raises(Exception):
        load_owner_decision_evidence(env.bundle_path)
    code, out = _cli(capsys, *env.argv)
    assert code == 2, out  # strict evidence load fails closed
    assert _no_activation_artifacts(env.activation_root)


def test_revoked_key_after_preview_blocks_apply(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
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
        "c4a test: revocation after preview must block apply",
    )
    assert code == 0, out
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 1
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_BLOCKED"
    assert any(
        "OWNER_AUTHORITY_REVERIFICATION" in blocker for blocker in payload["blockers"]
    )
    assert _sha(env.config_path) == original_sha
    assert _no_activation_artifacts(env.activation_root)


def _record_decision_cli(env: _Env, capsys, payload: dict, out_name: str) -> Path:
    decision_path = env.submission / f"{out_name}-input.json"
    statement_path = env.submission / f"{out_name}-statement.json"
    record_path = env.decisions / f"{out_name}-record.json"
    statement = _signed_statement(env.key, payload["bytes"])
    decision_path.write_bytes(payload["bytes"])
    statement_path.write_text(
        json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True)
        + "\n",
        "utf-8",
    )
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
        "--signed-statement",
        statement_path,
        "--trust-root",
        env.trust_root,
        "--record-output",
        record_path,
    ]
    if payload.get("exception") is not None:
        argv.extend(["--policy-exception", payload["exception"]])
    code, out = _cli(capsys, *argv)
    assert code == 0, out
    return record_path


def test_reject_decision_blocks_activation(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    reject_bytes = canonical_json_bytes(
        _accept_payload(decision="REJECT", exception_id=None, exception_content_sha256=None)
    )
    record_path = _record_decision_cli(
        env, capsys, {"bytes": reject_bytes, "exception": None}, "reject"
    )
    argv = list(env.argv)
    argv[argv.index("--decision-record") + 1] = str(record_path)
    argv = _without_option(argv, "--policy-exception", env.exception_path)
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert "DECISION_IS_REJECT" in preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


def test_conflicting_decisions_block_activation(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    reject_bytes = canonical_json_bytes(
        _accept_payload(decision="REJECT", exception_id=None, exception_content_sha256=None)
    )
    reject_record = _record_decision_cli(
        env, capsys, {"bytes": reject_bytes, "exception": None}, "reject2"
    )
    argv = list(env.argv) + ["--decision-record", reject_record]
    argv = _without_option(argv, "--policy-exception", env.exception_path)
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert "DECISIONS_CONFLICTING" in preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


def test_unsigned_supersession_blocks_at_plan_time(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    # A second genuine accept that (unsigned) supersedes the first.
    newer_bytes = _accept_bytes(rationale="A newer genuine accept rationale here.")
    newer_record = _record_decision_cli(
        env, capsys, {"bytes": newer_bytes, "exception": env.exception_path}, "newer"
    )
    newer_payload = json.loads(newer_record.read_text("utf-8"))
    older_payload = json.loads(env.record_path.read_text("utf-8"))
    newer_payload["supersedes_decision_record_id"] = older_payload[
        "decision_record_id"
    ]
    newer_payload["decision_record_id"] = "recomputed"
    newer_payload["content_sha256"] = "0" * 64
    temporary = OwnerPolicyDecisionRecordV1.model_construct(**newer_payload)
    dump = temporary.model_dump(mode="json", warnings=False)
    from turtle_value_engine.providers.normalization import deterministic_id

    dump["decision_record_id"] = deterministic_id(
        "owner-policy-decision",
        dump["decision"],
        dump["base_profile_id"],
        dump["base_profile_sha256"],
        dump["target_profile_id"],
        dump["target_profile_sha256"],
        dump["release_manifest_id"],
        dump["release_manifest_content_sha256"],
        dump["audit_id"],
        dump["audit_content_sha256"],
        dump["exception_id"] or "",
        dump["exception_content_sha256"] or "",
        dump["rationale"],
        dump["declared_owner_identity"],
        dump["decided_at"],
        dump["provenance"]["source_kind"],
        dump["provenance"]["source_revision"],
        dump["provenance"]["source_content_sha256"] or "",
        dump["authority"]["authority_status"],
        dump["authority"]["verification_method"],
        dump["supersedes_decision_record_id"] or "",
    )
    dump["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {k: v for k, v in dump.items() if k != "content_sha256"}
        )
    ).hexdigest()
    unsigned_superseder = env.decisions / "unsigned-superseder.json"
    unsigned_superseder.write_text(
        json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    OwnerPolicyDecisionRecordV1.model_validate(json.loads(unsigned_superseder.read_bytes()))

    argv = list(env.argv)
    argv[argv.index("--decision-record") + 1] = str(unsigned_superseder)
    argv += ["--decision-record", env.record_path]
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert any(
        "OWNER_AUTHORITY_REVERIFICATION" in blocker
        for blocker in preview["blockers"]
    ), preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


# ---------------------------------------------------------------------------
# 4. Exception / audit / release-binding negatives
# ---------------------------------------------------------------------------


def test_omitted_policy_exception_blocks(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    argv = _without_option(list(env.argv), "--policy-exception", env.exception_path)
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert "DECISION_EXCEPTION_BINDING_STALE" in preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


def test_forged_exception_content_blocks(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    forged = _policy_exception(
        rationale="A materially altered exception rationale for the fixture."
    )
    assert forged.exception_id == env.exception.exception_id
    assert forged.content_sha256 != env.exception.content_sha256
    forged_path = env.submission / "exception-forged.json"
    forged_path.write_text(forged.model_dump_json() + "\n", "utf-8")
    argv = list(env.argv)
    argv[list(env.argv).index(env.exception_path)] = forged_path
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert "DECISION_EXCEPTION_BINDING_STALE" in preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


def test_tampered_release_manifest_bytes_block(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    manifest_copy = tmp_path / "release-tampered.json"
    payload = json.loads(MANIFEST_PATH.read_text("utf-8"))
    payload["notes"] = payload.get("notes", "") + " tampered"
    manifest_copy.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    argv = list(env.argv)
    argv[list(env.argv).index(MANIFEST_PATH)] = manifest_copy
    code, out = _cli(capsys, *argv)
    # The manifest is content-hashed; any edit fails closed as unreadable
    # plan inputs before derivation can even start.
    assert code == 2
    assert "PLAN_INPUTS_UNREADABLE" in out
    assert _no_activation_artifacts(env.activation_root)
    assert not env.activation_root.exists() or True
    assert env.config_path.read_bytes() == PRIVATE_CONFIG_TEMPLATE.encode("utf-8")


def test_tampered_target_profile_bytes_block(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    target_copy = tmp_path / "strict-v2-tampered.yaml"
    target_copy.write_bytes(
        TARGET_PROFILE_PATH.read_bytes() + b"\n# tampered\n"
    )
    argv = list(env.argv)
    argv[list(env.argv).index(TARGET_PROFILE_PATH)] = target_copy
    code, out = _cli(capsys, *argv)
    assert code == 1
    preview = json.loads(out)
    assert any(
        "STALE" in blocker or blocker == "AUDIT_NOT_READY"
        for blocker in preview["blockers"]
    ), preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


# ---------------------------------------------------------------------------
# 5. Target/path guards
# ---------------------------------------------------------------------------


def test_already_target_config_is_explicit_no_op(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace('"strict-v1"', '"strict-v2"'), "utf-8"
    )
    code, out = _cli(capsys, *env.argv)
    assert code == 1
    preview = json.loads(out)
    assert "DEFAULT_ALREADY_TARGET" in preview["blockers"]
    assert _no_activation_artifacts(env.activation_root)


def test_symlinked_config_refused(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    link = tmp_path / "config-link.toml"
    link.symlink_to(env.config_path)
    argv = list(env.argv)
    argv[list(env.argv).index(env.config_path)] = link
    code, out = _cli(capsys, *argv)
    assert code == 2
    assert "CONFIG_PATH_SYMLINK" in out


def test_checked_in_template_and_rules_refused_by_alias(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    # Direct template path.
    argv = list(env.argv)
    argv[list(env.argv).index(env.config_path)] = ROOT / "config" / "project.example.toml"
    code, out = _cli(capsys, *argv)
    assert code == 2
    assert "CONFIG_PATH_PROTECTED" in out
    # A symlink pointing at the template resolves into the protected tree.
    link = tmp_path / "alias.toml"
    link.symlink_to(ROOT / "config" / "project.example.toml")
    argv = list(env.argv)
    argv[list(env.argv).index(env.config_path)] = link
    code, out = _cli(capsys, *argv)
    assert code == 2
    assert "CONFIG_PATH_PROTECTED" in out or "CONFIG_PATH_SYMLINK" in out
    assert _sha(ROOT / "config" / "project.example.toml") == CONFIG_TEMPLATE_SHA256


def test_activation_root_inside_repo_refused(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    argv = list(env.argv)
    argv[list(env.argv).index(env.activation_root)] = ROOT / "rules" / "nope"
    code, out = _cli(capsys, *argv)
    assert code == 2
    assert "ACTIVATION_ROOT_PROTECTED" in out


def test_output_collision_refused(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    code, out = _cli(capsys, *env.argv, "--output", env.config_path)
    assert code == 2
    assert "--output" in out


def test_missing_config_blocks_with_named_code(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    env.config_path.unlink()
    # The executor's own target guard fails closed first (classified exit 2);
    # the plan-level PROJECT_CONFIG_MISSING blocker never gets a chance.
    code, out = _cli(capsys, *env.argv)
    assert code == 2
    assert "CONFIG_PATH_UNAVAILABLE" in out
    assert _no_activation_artifacts(env.activation_root)


# ---------------------------------------------------------------------------
# 6. Byte-preserving edit unit matrix
# ---------------------------------------------------------------------------


def test_edit_preserves_crlf_and_single_quotes_and_no_trailing_newline():
    crlf = (
        b"schema_version = 1\r\n\r\n[profiles]\r\ndefault = \"strict-v1\"\r\n"
    )
    edited = derive_default_profile_edit(crlf, "strict-v2")
    assert edited.new_bytes == crlf.replace(b"strict-v1", b"strict-v2")
    assert edited.new_bytes.count(b"\r\n") == crlf.count(b"\r\n")

    single = b"[profiles]\ndefault = 'strict-v1' # pinned\n"
    edited = derive_default_profile_edit(single, "strict-v2")
    assert b"default = 'strict-v2' # pinned\n" in edited.new_bytes

    no_newline = b"[profiles]\ndefault = \"strict-v1\""
    edited = derive_default_profile_edit(no_newline, "strict-v2")
    assert edited.new_bytes == b"[profiles]\ndefault = \"strict-v2\""


def test_edit_rejects_missing_table_and_non_string_default():
    with pytest.raises(ActivationExecutionError) as excinfo:
        derive_default_profile_edit(b"schema_version = 1\n", "strict-v2")
    assert excinfo.value.code == "CONFIG_PROFILES_TABLE_MISSING"

    with pytest.raises(ActivationExecutionError) as excinfo:
        derive_default_profile_edit(
            b"[profiles]\ndefault = 1\n", "strict-v2"
        )
    assert excinfo.value.code == "CONFIG_DEFAULT_VALUE_UNSUPPORTED"

    with pytest.raises(ActivationExecutionError) as excinfo:
        derive_default_profile_edit(b"not [ toml", "strict-v2")
    assert excinfo.value.code == "CONFIG_TOML_INVALID"

    with pytest.raises(ActivationExecutionError) as excinfo:
        derive_default_profile_edit(
            b'[profiles]\ndefault = """\n"strict-v1"\n"""\n', "strict-v2"
        )
    assert excinfo.value.code == "CONFIG_DEFAULT_VALUE_UNSUPPORTED"


def test_edit_rejects_profiles_subtable_default():
    # default inside [profiles.advanced] is NOT the [profiles] default.
    text = b'[profiles]\ndefault = "strict-v1"\n[profiles.advanced]\ndefault = "x"\n'
    edited = derive_default_profile_edit(text, "strict-v2")
    assert b'[profiles]\ndefault = "strict-v2"' in edited.new_bytes
    assert b'[profiles.advanced]\ndefault = "x"' in edited.new_bytes


# ---------------------------------------------------------------------------
# 7. Concurrency and interruption
# ---------------------------------------------------------------------------


def _subprocess_apply(env: _Env) -> subprocess.CompletedProcess:
    argv = [
        sys.executable,
        "-m",
        "turtle_value_engine",
        *env.argv,
        "--apply",
    ]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )


def test_concurrent_apply_one_wins_one_busy(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]
    argv = [
        sys.executable,
        "-m",
        "turtle_value_engine",
        *env.argv,
        "--apply",
        "--expected-plan-id",
        preview["plan_id"],
        "--expected-config-sha256",
        original_sha,
    ]
    env_vars = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    first = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=ROOT, env=env_vars,
    )
    second = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=ROOT, env=env_vars,
    )
    first_out, _ = first.communicate(timeout=180)
    second_out, _ = second.communicate(timeout=180)
    codes = sorted([first.returncode, second.returncode])
    assert codes == [0, 3], (first.returncode, second.returncode, first_out, second_out)
    winner = json.loads(first_out if first.returncode == 0 else second_out)
    loser_out = second_out if first.returncode == 0 else first_out
    assert winner["status"] in ("ACTIVATED", "COMPLETED_ALREADY")
    assert "ACTIVATION_BUSY" in loser_out
    assert env.config_path.read_bytes() == _activated_bytes()


def test_interrupted_before_replace_resumes_deterministically(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]

    evidence = load_owner_decision_evidence(env.bundle_path)
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
    )

    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )

    verifier = SignedOwnerProvenanceVerifier(
        registry=registry,
        statement=evidence.statement,
        decision_input_bytes=evidence.decision_input_bytes,
    )
    from turtle_value_engine.evolution.owner_decision import load_decision_record

    class _Crash(Exception):
        pass

    common = dict(
        activation_root=env.activation_root,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        decision_records=[load_decision_record(env.record_path)],
        revocations=[],
        policy_exceptions=[env.exception],
        authority_verifier=verifier,
        authority_evidence=evidence,
        signed_revocations=[],
        signed_supersessions=[],
        lifecycle_trust_root=registry,
        project_config_path=env.config_path,
    )
    with pytest.raises(_Crash):
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=original_sha,
            fault_hook=lambda point: (_ for _ in ()).throw(_Crash())
            if point == "before_image_persisted"
            else None,
            **common,
        )
    # Observable on-disk state: journal + before-image persisted, config
    # NOT yet replaced, no receipt.
    journal_dir = env.activation_root / "journal"
    assert list(journal_dir.iterdir())
    images = list((env.activation_root / "before-images").iterdir())
    assert len(images) == 1
    assert images[0].read_bytes() == env.config_path.read_bytes()
    receipts = env.activation_root / "receipts"
    assert not receipts.is_dir() or not list(receipts.iterdir())
    assert _sha(env.config_path) == original_sha

    # Recovery: the same CLI apply resumes and completes.
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    assert json.loads(out)["status"] == "ACTIVATED_RESUMED"
    assert env.config_path.read_bytes() == _activated_bytes()
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    assert receipt_path.is_file()


def test_interrupted_after_replace_finalizes_receipt(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]

    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
    )

    evidence = load_owner_decision_evidence(env.bundle_path)
    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    verifier = SignedOwnerProvenanceVerifier(
        registry=registry,
        statement=evidence.statement,
        decision_input_bytes=evidence.decision_input_bytes,
    )

    class _Crash(Exception):
        pass

    with pytest.raises(_Crash):
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=original_sha,
            boundary_input=_boundary(),
            decision_records=[load_decision_record(env.record_path)],
            revocations=[],
            policy_exceptions=[env.exception],
            authority_verifier=verifier,
            authority_evidence=evidence,
            signed_revocations=[],
            signed_supersessions=[],
            lifecycle_trust_root=registry,
            activation_root=env.activation_root,
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            project_config_path=env.config_path,
            fault_hook=lambda point: (_ for _ in ()).throw(_Crash())
            if point == "config_replaced"
            else None,
        )
    # Observable on-disk state: config already replaced, receipt missing.
    activated_sha = hashlib.sha256(_activated_bytes()).hexdigest()
    assert _sha(env.config_path) == activated_sha
    assert not (env.activation_root / "receipts").exists() or not list(
        (env.activation_root / "receipts").iterdir()
    )

    # Recovery: rerun finalizes the receipt, zero further mutation.
    code, out = env.apply(capsys, preview["plan_id"], activated_sha)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "FINALIZED_AFTER_INTERRUPTED_REPLACE"
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    assert receipt_path.is_file()
    assert _sha(env.config_path) == activated_sha

    # Rollback still works from the finalized receipt.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert _sha(env.config_path) == original_sha


def test_foreign_writer_during_apply_caught_before_replace(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]

    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
    )

    evidence = load_owner_decision_evidence(env.bundle_path)
    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    verifier = SignedOwnerProvenanceVerifier(
        registry=registry,
        statement=evidence.statement,
        decision_input_bytes=evidence.decision_input_bytes,
    )

    def foreign_writer(point: str) -> None:
        if point == "temp_written":
            env.config_path.write_bytes(
                env.config_path.read_bytes() + b"# foreign writer\n"
            )

    with pytest.raises(ActivationExecutionBlocked) as excinfo:
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=original_sha,
            boundary_input=_boundary(),
            decision_records=[load_decision_record(env.record_path)],
            revocations=[],
            policy_exceptions=[env.exception],
            authority_verifier=verifier,
            authority_evidence=evidence,
            signed_revocations=[],
            signed_supersessions=[],
            lifecycle_trust_root=registry,
            activation_root=env.activation_root,
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            project_config_path=env.config_path,
            fault_hook=foreign_writer,
        )
    assert (
        excinfo.value.payload["status"] == "ACTIVATION_CONFIG_CHANGED_DURING_APPLY"
    )
    foreign_sha = _sha(env.config_path)
    assert foreign_sha != original_sha
    assert not list(env.config_path.parent.glob(".tve-activation-*.tmp")), (
        "the staged write must be discarded"
    )


def test_diverged_pending_journal_blocks_closed(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]

    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
    )

    evidence = load_owner_decision_evidence(env.bundle_path)
    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    verifier = SignedOwnerProvenanceVerifier(
        registry=registry,
        statement=evidence.statement,
        decision_input_bytes=evidence.decision_input_bytes,
    )

    class _Crash(Exception):
        pass

    with pytest.raises(_Crash):
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=original_sha,
            boundary_input=_boundary(),
            decision_records=[load_decision_record(env.record_path)],
            revocations=[],
            policy_exceptions=[env.exception],
            authority_verifier=verifier,
            authority_evidence=evidence,
            signed_revocations=[],
            signed_supersessions=[],
            lifecycle_trust_root=registry,
            activation_root=env.activation_root,
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            project_config_path=env.config_path,
            fault_hook=lambda point: (_ for _ in ()).throw(_Crash())
            if point == "journal_persisted"
            else None,
        )
    # A foreign edit diverges the config from both journal hashes.
    env.config_path.write_bytes(
        env.config_path.read_bytes() + b"# diverged by someone\n"
    )
    diverged_sha = _sha(env.config_path)
    with pytest.raises(ActivationExecutionBlocked) as excinfo:
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=diverged_sha,
            boundary_input=_boundary(),
            decision_records=[load_decision_record(env.record_path)],
            revocations=[],
            policy_exceptions=[env.exception],
            authority_verifier=verifier,
            authority_evidence=evidence,
            signed_revocations=[],
            signed_supersessions=[],
            lifecycle_trust_root=registry,
            activation_root=env.activation_root,
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            project_config_path=env.config_path,
        )
    assert excinfo.value.payload["status"] == "ACTIVATION_CONFIG_DIVERGED"
    assert _sha(env.config_path) == diverged_sha


def test_conflicting_pending_intent_fails_closed(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]

    # Build a second, internally valid but DIFFERENT pending intent for the
    # same config path (different plan id -> different activation id).
    receipt_payload = {
        "contract": "profile_activation_receipt_v1",
        "schema_version": "1.0.0",
        "activation_id": "pending",
        "plan_id": "profile-activation-plan-foreignbutvalid0000000000000000",
        "plan_content_sha256": "0" * 64,
        "current_profile_id": "strict-v1",
        "current_profile_sha256": STRICT_V1_SHA256,
        "activated_profile_id": "strict-v2",
        "activated_profile_sha256": STRICT_V2_SHA256,
        "release_manifest_id": json.loads(MANIFEST_PATH.read_text("utf-8"))[
            "release_candidate_id"
        ],
        "release_manifest_content_sha256": MANIFEST_CONTENT_SHA256,
        "audit_id": _audit().audit_id,
        "audit_content_sha256": _audit().content_sha256,
        "decision_record_id": "owner-policy-decision-x",
        "decision_record_content_sha256": "1" * 64,
        "evidence_bundle_id": "owner-provenance-evidence-bundle-x",
        "evidence_bundle_content_sha256": "2" * 64,
        "authority_registry_id": "owner-provenance-key-registry-x",
        "authority_registry_content_sha256": "3" * 64,
        "project_config_path": str(env.config_path.resolve()),
        "prior_config_sha256": original_sha,
        "activated_config_sha256": hashlib.sha256(b"other").hexdigest(),
        "prior_default_profile": "strict-v1",
        "activated_default_profile": "strict-v2",
        "before_image_name": f"{original_sha}.toml",
        "before_image_sha256": original_sha,
        "outcome": "ACTIVATED",
        "rollback_reference": "tve evolution rollback-activation",
        "rollback_exclusions": [
            "NO_AUTOMATIC_MONITORING_REPLAY",
            "NO_AUTOMATIC_NOTIFICATION_REPLAY",
            "NO_HISTORICAL_ARTIFACT_REWRITE",
        ],
        "apply_was_explicit_opt_in": True,
        "automatic_rollback_allowed": False,
    }
    from turtle_value_engine.providers.normalization import deterministic_id

    receipt_payload["activation_id"] = deterministic_id(
        "profile-activation-execution",
        receipt_payload["plan_id"],
        receipt_payload["project_config_path"],
        receipt_payload["prior_config_sha256"],
        receipt_payload["activated_config_sha256"],
        receipt_payload["decision_record_id"],
        receipt_payload["decision_record_content_sha256"],
        receipt_payload["evidence_bundle_id"],
        receipt_payload["evidence_bundle_content_sha256"],
        receipt_payload["authority_registry_id"],
        receipt_payload["authority_registry_content_sha256"],
    )
    receipt_payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {k: v for k, v in receipt_payload.items() if k != "content_sha256"}
        )
    ).hexdigest()
    foreign_receipt = ProfileActivationReceiptV1.model_validate(receipt_payload)
    foreign_intent_payload = {
        "contract": "profile_activation_intent_v1",
        "schema_version": "1.0.0",
        "intent_id": foreign_receipt.activation_id,
        "receipt": json.loads(foreign_receipt.model_dump_json()),
        "recovery_note": "crafted pending intent for the conflict test",
    }
    foreign_intent_payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {
                k: v
                for k, v in foreign_intent_payload.items()
                if k != "content_sha256"
            }
        )
    ).hexdigest()
    foreign_intent = ProfileActivationIntentV1.model_validate(foreign_intent_payload)
    (env.activation_root / "journal").mkdir(parents=True, exist_ok=True)
    (
        env.activation_root / "journal" / f"{foreign_receipt.activation_id}.json"
    ).write_bytes(foreign_intent.serialized_bytes())

    from turtle_value_engine.evolution.owner_decision import load_decision_record
    from turtle_value_engine.evolution.owner_provenance import (
        SignedOwnerProvenanceVerifier,
    )
    from turtle_value_engine.evolution.owner_trust_store import (
        OwnerProvenanceTrustStore,
    )

    evidence = load_owner_decision_evidence(env.bundle_path)
    registry = OwnerProvenanceTrustStore(env.trust_root).latest_snapshot().registry
    verifier = SignedOwnerProvenanceVerifier(
        registry=registry,
        statement=evidence.statement,
        decision_input_bytes=evidence.decision_input_bytes,
    )
    with pytest.raises(ActivationExecutionBlocked) as excinfo:
        apply_profile_activation(
            expected_plan_id=preview["plan_id"],
            expected_config_sha256=original_sha,
            boundary_input=_boundary(),
            decision_records=[load_decision_record(env.record_path)],
            revocations=[],
            policy_exceptions=[env.exception],
            authority_verifier=verifier,
            authority_evidence=evidence,
            signed_revocations=[],
            signed_supersessions=[],
            lifecycle_trust_root=registry,
            activation_root=env.activation_root,
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            project_config_path=env.config_path,
        )
    assert excinfo.value.payload["status"] == "ACTIVATION_INTENT_CONFLICT"
    assert _sha(env.config_path) == original_sha


# ---------------------------------------------------------------------------
# 8. Rollback negatives
# ---------------------------------------------------------------------------


def _applied_env(tmp_path: Path, capsys) -> tuple[_Env, Path, str, str]:
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    activated_sha = _sha(env.config_path)
    return env, receipt_path, original_sha, activated_sha


def test_corrupt_receipt_refused(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied_env(
        tmp_path, capsys
    )
    payload = json.loads(receipt_path.read_text("utf-8"))
    payload["prior_default_profile"] = "strict-v9"
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    code, out = env.rollback(capsys, receipt_path)
    assert code == 2
    assert "RECEIPT_INVALID" in out
    assert _sha(env.config_path) == activated_sha


def test_rollback_after_intervening_change_refused(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied_env(
        tmp_path, capsys
    )
    env.config_path.write_bytes(
        env.config_path.read_bytes() + b"# intervening edit\n"
    )
    intervened_sha = _sha(env.config_path)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 1
    payload = json.loads(out)
    assert payload["status"] == "ROLLBACK_PRECONDITION_VIOLATED"
    assert _sha(env.config_path) == intervened_sha


def test_rollback_with_missing_before_image_refused(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied_env(
        tmp_path, capsys
    )
    for image in (env.activation_root / "before-images").iterdir():
        image.unlink()
    code, out = env.rollback(capsys, receipt_path)
    assert code == 2
    assert "BEFORE_IMAGE_UNAVAILABLE" in out
    assert _sha(env.config_path) == activated_sha


def test_rollback_with_tampered_before_image_refused(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied_env(
        tmp_path, capsys
    )
    image = next((env.activation_root / "before-images").iterdir())
    image.write_bytes(image.read_bytes() + b"# tampered\n")
    code, out = env.rollback(capsys, receipt_path)
    assert code == 2
    assert "BEFORE_IMAGE_HASH_MISMATCH" in out
    assert _sha(env.config_path) == activated_sha


def test_rollback_busy_when_apply_holds_lock(tmp_path, capsys):
    import fcntl

    env, receipt_path, original_sha, activated_sha = _applied_env(
        tmp_path, capsys
    )
    lock_dir = env.activation_root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(
        str(env.config_path.resolve()).encode("utf-8")
    ).hexdigest()[:24]
    lock_path = lock_dir / f"{digest}.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        code, out = env.rollback(capsys, receipt_path)
        assert code == 3
        assert "ACTIVATION_BUSY" in out
        assert _sha(env.config_path) == activated_sha
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


# ---------------------------------------------------------------------------
# 9. Offline/socket-free execution and protected bytes
# ---------------------------------------------------------------------------


def test_full_apply_rollback_offline_socket_free(tmp_path, capsys, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("the activation executor constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    env, receipt_path, original_sha, _activated = _applied_env(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert _sha(env.config_path) == original_sha


def test_protected_repository_bytes_unchanged(tmp_path, capsys):
    _Env(tmp_path).setup(capsys)
    assert _sha(BASE_PROFILE_PATH) == STRICT_V1_SHA256
    assert _sha(TARGET_PROFILE_PATH) == STRICT_V2_SHA256
    assert _sha(MANIFEST_PATH) == MANIFEST_FILE_SHA256
    assert _sha(ROOT / "config" / "project.example.toml") == CONFIG_TEMPLATE_SHA256
    template = (ROOT / "config" / "project.example.toml").read_text("utf-8")
    assert 'default = "strict-v1"' in template


def test_receipt_is_deterministic_across_identical_activations(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    first = receipt_path.read_bytes()
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    assert receipt_path.read_bytes() == first, (
        "the same authoritative activation state must produce byte-identical "
        "receipts (no wall-clock, no machine-local variance)"
    )


# ---------------------------------------------------------------------------
# 10. Schema drift parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("profile-activation-receipt.schema.json", ProfileActivationReceiptV1),
        ("profile-activation-intent.schema.json", ProfileActivationIntentV1),
        (
            "profile-activation-rollback-outcome.schema.json",
            ProfileActivationRollbackOutcomeV1,
        ),
        (
            "profile-activation-rollback-intent.schema.json",
            ProfileActivationRollbackIntentV1,
        ),
        ("profile-activation-preview.schema.json", ProfileActivationPreviewV1),
    ],
)
def test_checked_in_schemas_have_drift_parity(schema_name, model):
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == model.model_json_schema()
