"""Phase 7-C3-B-R1 regressions: evidence replay component integrity.

Every test here drives the *real* capture / persistence / offline-replay and
CLI paths with throwaway runtime-generated Ed25519 keys.  The red cases
reproduce the post-closure review findings against the pre-fix audit
boundary ``reverify_owner_decision_evidence`` (and, where named, the strict
consumer loader):

* the on-disk ``verification.json`` was loaded but never compared with the
  manifest embedding;
* the physical ``record.json`` was never read at all (missing or swapped
  records replayed clean);
* the manifest's ``registry_id`` / ``registry_content_sha256`` were never
  reconciled with the registry inside the persisted snapshot;
* a fully self-consistent forged record+manifest (recomputed deterministic
  ids and content hashes) whose decision fields diverge from the signed
  bytes replayed ``REPLAYS_BYTE_IDENTICAL``;
* an unexpected ``record.json`` inside an INVALID no-record bundle (or any
  foreign extra component) was silently ignored.

The green cases pin the preserved invariants: honest clean and honest
rejected evidence replay byte-identically, repeated replay is
deterministic, symlinked components fail closed, replay constructs no
socket, and plan-time authority is still re-attested freshly against the
operator's *current* trust root (revocation flips READY to BLOCKED).

All Ed25519 keys and passphrases here are throwaway runtime fixtures; no
real owner key material exists in this repository and no real owner
acceptance of strict-v2 is claimed or synthesized.
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
from turtle_value_engine.evolution.owner_decision import (
    DecisionProvenanceV1,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
)
from turtle_value_engine.evolution.owner_provenance import (
    PROVENANCE_ALGORITHM,
    build_owner_provenance_key_registry,
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
    owner_provenance_key_id,
    verify_owner_provenance,
)
from turtle_value_engine.evolution.owner_provenance import (
    OwnerProvenanceKeyRecordV1 as LifecycleKeyRecord,
)
from turtle_value_engine.evolution.owner_trust_store import (
    OwnerTrustStoreError,
    build_initial_registry_snapshot,
    capture_owner_decision_evidence,
    load_owner_decision_evidence,
    persist_owner_decision_evidence,
    reverify_owner_decision_evidence,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

ROOT = Path(__file__).resolve().parents[1]
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
TARGET_PROFILE_PATH = ROOT / "rules" / "strict-v2.yaml"
MANIFEST_PATH = ROOT / "docs" / "releases" / "strict-v2" / "release-candidate.json"
BOUNDARY_PATH = ROOT / "fixtures" / "healthy_cash_cow.json"

STRICT_V2_SHA256 = "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
OWNER_IDENTITY = "Ryder Xie"

_boundary_input = None
_audit_result = None


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
    audit = _audit()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = {
        "contract": "owner_policy_decision_input_v1",
        "decision": "ACCEPT_WITH_EXCEPTION",
        "base_profile_id": "strict-v1",
        "base_profile_sha256": "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333",
        "target_profile_id": "strict-v2",
        "target_profile_sha256": STRICT_V2_SHA256,
        "release_manifest_id": manifest["release_candidate_id"],
        "release_manifest_content_sha256": (
            "c0d6cb5b60595c8eb67d45735fc8ef05a9a13b6db0f90bf3468f635ec99c61e8"
        ),
        "audit_id": audit.audit_id,
        "audit_content_sha256": audit.content_sha256,
        "exception_id": _policy_exception().exception_id,
        "exception_content_sha256": _policy_exception().content_sha256,
        "rationale": "Accept the stricter 14% CDC gate as intended owner policy.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-15",
        "source_revision": "c3b-r1-test",
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
        signature=key.private.sign(owner_decision_input_signature_message(decision_input)),
        key_id=key.key_id,
        decision_input=decision_input,
    )


def _capture(key: _FixtureKey, *, decision_bytes: bytes | None = None, statement=None):
    """A genuine capture through the real record-time boundary."""

    decision_bytes = decision_bytes or _accept_bytes()
    statement = statement or _signed_statement(key, decision_bytes)
    snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([key.record])
    )
    validation, bundle = capture_owner_decision_evidence(
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation.state == "VALID"
    return decision_bytes, statement, snapshot, validation, bundle


def _persisted(tmp_path: Path, key: _FixtureKey):
    decision_bytes, statement, snapshot, validation, bundle = _capture(key)
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    bundle_dir = evidence_root / bundle.bundle_id
    assert {
        "bundle.json",
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
        "record.json",
    } == {item.name for item in bundle_dir.iterdir()}
    return bundle_dir, (decision_bytes, statement, snapshot, validation, bundle)


def _dump_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )


def _bundle_content_sha256(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _bundle_id_for(payload: dict) -> str:
    record = payload.get("record")
    return deterministic_id(
        "owner-provenance-evidence-bundle",
        payload["decision_input_content_sha256"],
        payload["statement_content_sha256"],
        payload["registry_snapshot_id"],
        payload["registry_snapshot_content_sha256"],
        payload["verification"]["verification_id"],
        record["decision_record_id"] if record is not None else "",
        payload.get("record_content_sha256") or "",
        payload["validation_state"],
    )


def _cli(capsys, *argv):
    code = cli_module.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# ---------------------------------------------------------------------------
# Red case 2 — a missing on-disk record.json must not replay clean
# ---------------------------------------------------------------------------


def test_missing_record_component_fails_closed(tmp_path, capsys):
    bundle_dir, _ = _persisted(tmp_path, _FixtureKey())
    bundle_path = bundle_dir / "bundle.json"
    (bundle_dir / "record.json").unlink()

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        reverify_owner_decision_evidence(bundle_path)
    assert "record.json" in str(excinfo.value)

    code, _ = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_path
    )
    assert code != 0

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_path)


# ---------------------------------------------------------------------------
# Red case 3 — a different but fully valid on-disk record.json is a named
# component divergence, not a clean replay
# ---------------------------------------------------------------------------


def test_divergent_valid_record_file_is_a_named_mismatch(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, statement, snapshot, _, bundle) = _persisted(
        tmp_path, key
    )
    other_bytes = _accept_bytes(
        rationale="A materially different genuine rationale for the fixture."
    )
    *_, other_bundle = _capture(key, decision_bytes=other_bytes)
    assert other_bundle.record is not None
    assert other_bundle.record != bundle.record
    _dump_json(bundle_dir / "record.json", other_bundle.record.model_dump(mode="json"))

    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "RECORD_FILE_DIVERGED" in result.mismatches

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_dir / "bundle.json")


# ---------------------------------------------------------------------------
# Red case 4 — a different but internally valid on-disk verification.json
# (recomputed against a foreign registry) is a named divergence
# ---------------------------------------------------------------------------


def test_divergent_valid_verification_file_is_a_named_mismatch(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, statement, snapshot, _, bundle) = _persisted(
        tmp_path, key
    )
    foreign_registry = build_owner_provenance_key_registry([_FixtureKey().record])
    divergent = verify_owner_provenance(
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry=foreign_registry,
    )
    assert divergent.verification_status == "REJECTED"
    assert divergent != bundle.verification
    _dump_json(
        bundle_dir / "verification.json", divergent.model_dump(mode="json")
    )

    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "VERIFICATION_FILE_DIVERGED" in result.mismatches

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_dir / "bundle.json")


# ---------------------------------------------------------------------------
# Red case 5 — a model-valid manifest whose registry identity diverges from
# the persisted snapshot's internal registry
# ---------------------------------------------------------------------------


def test_manifest_registry_identity_divergence_is_classified(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, _ = _persisted(tmp_path, key)
    foreign_registry = build_owner_provenance_key_registry([_FixtureKey().record])
    payload = json.loads((bundle_dir / "bundle.json").read_text("utf-8"))
    payload["registry_id"] = foreign_registry.registry_id
    payload["registry_content_sha256"] = foreign_registry.content_sha256
    payload["content_sha256"] = _bundle_content_sha256(payload)
    _dump_json(bundle_dir / "bundle.json", payload)

    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "REGISTRY_IDENTITY_DIVERGED" in result.mismatches

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_dir / "bundle.json")


# ---------------------------------------------------------------------------
# Red case 6 — a fully self-consistent forged record+manifest that changes
# signed decision fields (the original signature and signed bytes survive)
# ---------------------------------------------------------------------------


def _forged_bundle_dir(
    evidence_root: Path,
    original_dir: Path,
    forged_record: OwnerPolicyDecisionRecordV1,
) -> Path:
    payload = json.loads((original_dir / "bundle.json").read_text("utf-8"))
    payload["record"] = forged_record.model_dump(mode="json")
    payload["record_content_sha256"] = forged_record.content_sha256
    payload["bundle_id"] = _bundle_id_for(payload)
    payload["content_sha256"] = _bundle_content_sha256(payload)
    forged_dir = evidence_root / payload["bundle_id"]
    forged_dir.mkdir(parents=True)
    for name in (
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
    ):
        (forged_dir / name).write_bytes((original_dir / name).read_bytes())
    _dump_json(forged_dir / "record.json", forged_record.model_dump(mode="json"))
    _dump_json(forged_dir / "bundle.json", payload)
    return forged_dir


def test_self_consistent_forged_record_with_changed_decision_is_rejected(tmp_path):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, statement, snapshot, validation, bundle) = _persisted(
        tmp_path, key
    )
    assert bundle.record is not None
    signed_payload = json.loads(decision_bytes)
    forged_input = OwnerPolicyDecisionInputV1.model_validate(
        {
            **signed_payload,
            "decision": "REJECT",
            "exception_id": None,
            "exception_content_sha256": None,
            "rationale": "A forged rejection rationale replacing the signed accept.",
        }
    )
    forged_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=forged_input,
        provenance=bundle.record.provenance,
        authority=bundle.record.authority,
    )
    assert forged_record.decision_record_id != bundle.record.decision_record_id

    forged_dir = _forged_bundle_dir(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    result = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "RECORD_SIGNED_CONTENT_DIVERGED" in result.mismatches

    # The strict consumer loader fails closed on the same divergence.
    with pytest.raises(OwnerTrustStoreError, match="signed"):
        load_owner_decision_evidence(forged_dir / "bundle.json")


def test_self_consistent_forged_record_with_changed_revision_is_rejected(tmp_path):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, statement, snapshot, validation, bundle) = _persisted(
        tmp_path, key
    )
    assert bundle.record is not None
    signed_payload = json.loads(decision_bytes)
    forged_input = OwnerPolicyDecisionInputV1.model_validate(
        {
            **signed_payload,
            "rationale": "A forged rationale edit that the owner never signed here.",
        }
    )
    forged_provenance = DecisionProvenanceV1(
        source_kind=bundle.record.provenance.source_kind,
        source_revision="forged-revision",
        source_content_sha256=bundle.record.provenance.source_content_sha256,
    )
    forged_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=forged_input,
        provenance=forged_provenance,
        authority=bundle.record.authority,
    )

    forged_dir = _forged_bundle_dir(tmp_path / "evidence", bundle_dir, forged_record)
    result = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "RECORD_SIGNED_CONTENT_DIVERGED" in result.mismatches
    assert "RECORD_SOURCE_REVISION_DIVERGED" in result.mismatches


# ---------------------------------------------------------------------------
# Red case 7 — INVALID no-record bundles and unexpected components
# ---------------------------------------------------------------------------


def _persisted_invalid(tmp_path: Path):
    trusted, attacker = _FixtureKey(), _FixtureKey()
    decision_bytes = _accept_bytes()
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    # The statement claims the trusted key id but carries the attacker's
    # signature: an honestly rejected capture (INVALID bundle, no record).
    statement = build_owner_signed_decision_statement(
        signature=attacker.private.sign(
            owner_decision_input_signature_message(decision_input)
        ),
        key_id=trusted.key_id,
        decision_input=decision_input,
    )
    snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([trusted.record])
    )
    validation, bundle = capture_owner_decision_evidence(
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation.state == "INVALID"
    assert bundle.record is None
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    bundle_dir = evidence_root / bundle.bundle_id
    assert "record.json" not in {item.name for item in bundle_dir.iterdir()}
    return bundle_dir, bundle


def test_invalid_bundle_with_unexpected_record_file_fails_closed(tmp_path, capsys):
    bundle_dir, bundle = _persisted_invalid(tmp_path)
    other_key = _FixtureKey()
    *_, other_bundle = _capture(other_key)
    assert other_bundle.record is not None
    _dump_json(bundle_dir / "record.json", other_bundle.record.model_dump(mode="json"))

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert "record.json" in str(excinfo.value)

    code, _ = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code != 0

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_dir / "bundle.json")


def test_extra_foreign_component_fails_closed(tmp_path, capsys):
    bundle_dir, _ = _persisted(tmp_path, _FixtureKey())
    (bundle_dir / "notes.txt").write_text("foreign", "utf-8")

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert "notes.txt" in str(excinfo.value)

    code, _ = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code != 0

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_dir / "bundle.json")


def test_symlinked_record_component_fails_closed(tmp_path, capsys):
    bundle_dir, _ = _persisted(tmp_path, _FixtureKey())
    original = (bundle_dir / "record.json").read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(original)
    (bundle_dir / "record.json").unlink()
    (bundle_dir / "record.json").symlink_to(outside)

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert "symlink" in str(excinfo.value)

    code, _ = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code != 0


# ---------------------------------------------------------------------------
# Green preservation — honest evidence, determinism, offline behavior
# ---------------------------------------------------------------------------


def test_clean_bundle_replays_byte_identically_and_repeats_deterministically(
    tmp_path, capsys
):
    bundle_dir, (_, _, _, _, bundle) = _persisted(tmp_path, _FixtureKey())
    bundle_path = bundle_dir / "bundle.json"

    first = reverify_owner_decision_evidence(bundle_path)
    assert first.replay_status == "REPLAYS_BYTE_IDENTICAL"
    assert first.mismatches == []
    assert first.replayed_verification == bundle.verification
    second = reverify_owner_decision_evidence(bundle_path)
    assert first == second

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", bundle_path)
    assert code == 0, out
    assert "REPLAYS_BYTE_IDENTICAL" in out


def test_honest_invalid_capture_replays_as_rejected_evidence(tmp_path, capsys):
    bundle_dir, bundle = _persisted_invalid(tmp_path)
    bundle_path = bundle_dir / "bundle.json"

    result = reverify_owner_decision_evidence(bundle_path)
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL"
    assert result.replayed_verification.verification_status == "REJECTED"
    assert bundle.validation_state == "INVALID"

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", bundle_path)
    assert code == 0, out


def test_symlinked_verification_component_still_fails_closed(tmp_path):
    bundle_dir, _ = _persisted(tmp_path, _FixtureKey())
    original = (bundle_dir / "verification.json").read_bytes()
    outside = tmp_path / "outside-verification.json"
    outside.write_bytes(original)
    (bundle_dir / "verification.json").unlink()
    (bundle_dir / "verification.json").symlink_to(outside)
    with pytest.raises(OwnerTrustStoreError, match="symlink"):
        reverify_owner_decision_evidence(bundle_dir / "bundle.json")


def test_replay_remains_offline_and_socket_free(tmp_path, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("evidence re-verification constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    bundle_dir, _ = _persisted(tmp_path, _FixtureKey())
    assert (
        reverify_owner_decision_evidence(bundle_dir / "bundle.json").replay_status
        == "REPLAYS_BYTE_IDENTICAL"
    )


def _write_project_config(tmp_path: Path) -> Path:
    content = [
        "schema_version = 1",
        "",
        "[project]",
        'id = "turtle-value-engine"',
        'environment = "private"',
        'timezone = "Asia/Taipei"',
        "",
        "[profiles]",
        'default = "strict-v1"',
        "",
    ]
    path = tmp_path / "project.toml"
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def test_plan_authority_still_re_attests_the_current_trust_root(tmp_path, capsys):
    """Historical evidence never transfers authority: the plan re-verifies
    the signature against the trust root's CURRENT latest snapshot, so
    revoking the key flips READY back to BLOCKED."""

    key = _FixtureKey()
    trust_root = tmp_path / "trust-root"
    evidence_root = tmp_path / "evidence"
    submission = tmp_path / "submission"
    submission.mkdir()
    public_key = tmp_path / "owner.pub"
    public_key.write_text(key.public_base64 + "\n", "utf-8")
    exception_path = submission / "exception.json"
    exception_path.write_text(
        _policy_exception().model_dump_json(indent=2), "utf-8"
    )

    code, out = _cli(
        capsys,
        "provenance",
        "registry",
        "init",
        "--trust-root",
        trust_root,
        "--public-key",
        public_key,
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2026-12-31",
    )
    assert code == 0, out

    decision_bytes = _accept_bytes()
    statement = _signed_statement(key, decision_bytes)
    decision_path = submission / "decision-input.json"
    decision_path.write_bytes(decision_bytes)
    statement_path = submission / "statement.json"
    statement_path.write_text(
        json.dumps(
            json.loads(statement.model_dump_json()), indent=2, sort_keys=True
        )
        + "\n",
        "utf-8",
    )
    record_path = submission / "record.json"
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
        exception_path,
        "--signed-statement",
        statement_path,
        "--trust-root",
        trust_root,
        "--evidence-root",
        evidence_root,
        "--record-output",
        record_path,
    )
    assert code == 0, out
    bundle_path = Path(json.loads(out)["evidence_bundle"]["path"])

    project_config = _write_project_config(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_argv = (
        "evolution",
        "plan-activation",
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        exception_path,
        "--decision-record",
        record_path,
        "--project-config",
        project_config,
        "--trust-root",
        trust_root,
        "--authority-evidence",
        bundle_path,
    )
    code, out = _cli(capsys, *plan_argv, "--output", plan_path)
    assert code == 0, out
    plan = json.loads(plan_path.read_text("utf-8"))
    assert plan["plan_state"] == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan["authority_reverification_status"] == "REVERIFIED"
    assert plan["execution_performed"] is False

    code, out = _cli(
        capsys,
        "provenance",
        "registry",
        "revoke",
        "--trust-root",
        trust_root,
        "--key-id",
        key.key_id,
        "--reference",
        "r1 regression: authority must be fresh",
    )
    assert code == 0, out

    plan_path_2 = tmp_path / "plan-2.json"
    code, out = _cli(capsys, *plan_argv, "--output", plan_path_2)
    assert code == 1, out
    plan_2 = json.loads(plan_path_2.read_text("utf-8"))
    assert plan_2["plan_state"] == "BLOCKED"
    assert any(
        item.startswith("OWNER_AUTHORITY_REVERIFICATION")
        for item in plan_2["blockers"]
    )


# ---------------------------------------------------------------------------
# Walkthrough round-trip smoke — the documented encrypted-key procedure
# (generate -> encrypted PKCS#8 on disk -> FRESH PROCESS reload -> sign)
# executed with throwaway keys and a test passphrase.
# ---------------------------------------------------------------------------

_KEYGEN_SCRIPT = """
import base64, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
passphrase = os.environ["TVE_TEST_PASSPHRASE"].encode("utf-8")
pem = key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.BestAvailableEncryption(passphrase),
)
Path(sys.argv[1]).write_bytes(pem)
Path(sys.argv[2]).write_text(
    base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    + "\\n",
    "utf-8",
)
print(json.dumps({"written": [sys.argv[1], sys.argv[2]]}))
"""

_SIGN_SCRIPT = """
import json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from turtle_value_engine.evolution.owner_decision import OwnerPolicyDecisionInputV1
from turtle_value_engine.evolution.owner_provenance import (
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
)
from turtle_value_engine.providers.models import canonical_json_bytes

passphrase = os.environ["TVE_TEST_PASSPHRASE"].encode("utf-8")
private = serialization.load_pem_private_key(
    Path(sys.argv[1]).read_bytes(), passphrase
)
model = OwnerPolicyDecisionInputV1.model_validate(
    json.loads(Path(sys.argv[2]).read_text("utf-8"))
)
Path(sys.argv[2]).write_bytes(canonical_json_bytes(model.model_dump(mode="json")))
statement = build_owner_signed_decision_statement(
    signature=private.sign(owner_decision_input_signature_message(model)),
    key_id=sys.argv[3],
    decision_input=model,
)
Path(sys.argv[4]).write_text(
    json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True)
    + "\\n",
    "utf-8",
)
"""


def _run_python(script: str, *args: str, env_passphrase: str) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["TVE_TEST_PASSPHRASE"] = env_passphrase
    completed = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "TVE_TEST_PASSPHRASE" not in completed.stdout


def test_walkthrough_encrypted_key_round_trip_across_processes(tmp_path, capsys):
    trust_root = tmp_path / "trust-root"
    evidence_root = tmp_path / "evidence"
    submission = tmp_path / "submission"
    submission.mkdir()
    private_pem = tmp_path / "owner-private.pem"
    public_key = tmp_path / "owner.pub"
    # Throwaway fixture passphrase delivered by environment, never argv.
    passphrase = "throwaway-test-passphrase-only"

    _run_python(
        _KEYGEN_SCRIPT,
        private_pem,
        public_key,
        env_passphrase=passphrase,
    )
    assert b"BEGIN ENCRYPTED PRIVATE KEY" in private_pem.read_bytes()

    code, out = _cli(
        capsys,
        "provenance",
        "registry",
        "init",
        "--trust-root",
        trust_root,
        "--public-key",
        public_key,
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2026-12-31",
    )
    assert code == 0, out
    key_id = json.loads(out)["key_id"]

    decision_path = submission / "decision-input.json"
    decision_path.write_text(json.dumps(_accept_payload()), "utf-8")
    statement_path = submission / "statement.json"
    _run_python(
        _SIGN_SCRIPT,
        private_pem,
        decision_path,
        key_id,
        statement_path,
        env_passphrase=passphrase,
    )

    exception_path = submission / "exception.json"
    exception_path.write_text(
        _policy_exception().model_dump_json(indent=2), "utf-8"
    )
    record_path = submission / "record.json"
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
        exception_path,
        "--signed-statement",
        statement_path,
        "--trust-root",
        trust_root,
        "--evidence-root",
        evidence_root,
        "--record-output",
        record_path,
    )
    assert code == 0, out
    record = json.loads(record_path.read_text("utf-8"))
    assert record["authority"]["authority_status"] == "OWNER_AUTHORITY_VERIFIED"
    bundle_path = Path(json.loads(out)["evidence_bundle"]["path"])

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_path
    )
    assert code == 0, out
    assert "REPLAYS_BYTE_IDENTICAL" in out
