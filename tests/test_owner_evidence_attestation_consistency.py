"""Phase 7-C3-B-R2 regressions: capture-attestation consistency and safe
owner-key provisioning.

Every test here drives the *real* capture / persistence / offline-replay,
strict-loader and CLI paths with throwaway runtime-generated Ed25519 keys.
The red cases reproduce the R1 post-closure review findings against pristine
main ``c40dc7a``:

* F1-1 — a fully self-consistent forged bundle whose record carries forged
  **unsigned authority metadata** (``attested_key_id``,
  ``attested_registry_id``, ``attested_registry_content_sha256``,
  ``evidence_content_sha256``) while every owner-signed field, the signed
  bytes and the source revision stay genuine replayed
  ``REPLAYS_BYTE_IDENTICAL`` and loaded strictly;
* F1-2 — a model-valid ``VALID`` bundle whose record claims
  ``OWNER_AUTHORITY_VERIFIED`` over a signature whose honest cryptographic
  verification is ``REJECTED`` replayed byte-identically and loaded
  strictly (the activation plan itself still re-attests freshly, which the
  test also observes);
* F1-3 — a ``VALID`` bundle with nonempty ``validation_blockers`` replayed
  clean, although record-time ``validate_owner_decision`` derives ``INVALID``
  whenever blockers exist;
* F2 — the walkthrough §1 key-creation snippet created the encrypted PEM
  ``write_bytes``-permissive (mode ``0666`` under ``umask 000``), silently
  overwrote an existing key on re-invocation and followed a symlinked
  destination.

The green cases pin the preserved invariants: a genuine verified capture,
an honestly rejected (INVALID, no record) capture and an honest
INVALID-with-verified-crypto capture all still replay byte-identically,
and the documented owner-key provisioning procedure is exclusive, 0600-at-
creation, symlink-refusing and reloadable across processes with a throwaway
passphrase.

All Ed25519 keys and passphrases here are throwaway runtime fixtures; no
real owner key material exists in this repository and no real owner
acceptance of strict-v2 is claimed or synthesized.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from turtle_value_engine import cli as cli_module
from turtle_value_engine import load_normalized_input
from turtle_value_engine.evolution.owner_decision import (
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
)
from turtle_value_engine.evolution.owner_provenance import (
    PROVENANCE_ALGORITHM,
    build_owner_provenance_key_registry,
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
    owner_provenance_key_id,
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
WALKTHROUGH_PATH = (
    ROOT / "docs" / "operations" / "owner-provenance-walkthrough.md"
)

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
        "source_revision": "c3b-r2-test",
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
    return evidence_root / bundle.bundle_id, (
        decision_bytes,
        statement,
        snapshot,
        validation,
        bundle,
    )


def _persisted_rejected(tmp_path: Path):
    """An honestly rejected capture: the statement names the trusted key id
    but carries an attacker signature (INVALID bundle, no record)."""

    trusted, attacker = _FixtureKey(), _FixtureKey()
    decision_bytes = _accept_bytes()
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
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
    assert bundle.verification.verification_status == "REJECTED"
    assert bundle.record is None
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    return (
        evidence_root / bundle.bundle_id,
        (decision_bytes, statement, snapshot, trusted),
    )


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


def _forged_bundle_from_record(
    evidence_root: Path, original_dir: Path, forged_record: OwnerPolicyDecisionRecordV1
) -> Path:
    """A fully self-consistent forged bundle: recomputed record content hash,
    bundle id and bundle content hash, matching directory name, all six
    physical components, original signed bytes preserved."""

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


def _record_with_forged_authority(
    decision_bytes: bytes,
    provenance: DecisionProvenanceV1,
    original_authority: OwnerAuthorityAssessmentV1,
    **authority_updates,
) -> OwnerPolicyDecisionRecordV1:
    """Rebuild the record byte-consistently with one forged authority field.

    Every owner-signed decision field and the source revision stay verbatim
    (they come from the genuine signed bytes); only the unsigned authority
    metadata changes, and the record id / content hash are recomputed."""

    forged_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=forged_input,
        provenance=provenance,
        authority=original_authority.model_copy(update=authority_updates),
    )


def _cli(capsys, *argv):
    code = cli_module.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# ---------------------------------------------------------------------------
# F1-1 (red) — forged unsigned authority metadata in a genuine VALID bundle
# ---------------------------------------------------------------------------

_FORGED_AUTHORITY_FIELDS = {
    "attested_key_id": "forged-key-id-never-attested-0000000000000",
    "attested_registry_id": "forged-registry-id-00000000000000000000000",
    "attested_registry_content_sha256": "ab" * 32,
    "evidence_content_sha256": "cd" * 32,
}


@pytest.mark.parametrize("field", sorted(_FORGED_AUTHORITY_FIELDS))
def test_forged_unsigned_authority_metadata_is_a_named_mismatch(
    tmp_path, capsys, field
):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    assert bundle.record is not None
    assert bundle.record.authority.attested_key_id == key.key_id
    forged_record = _record_with_forged_authority(
        decision_bytes,
        bundle.record.provenance,
        bundle.record.authority,
        **{field: _FORGED_AUTHORITY_FIELDS[field]},
    )
    # The forgery is fully self-consistent: every id and hash recomputes.
    OwnerPolicyDecisionRecordV1.model_validate(
        json.loads(json.dumps(forged_record.model_dump(mode="json")))
    )
    assert forged_record.content_sha256 != bundle.record.content_sha256

    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    forged_path = forged_dir / "bundle.json"

    result = reverify_owner_decision_evidence(forged_path)
    assert result.replay_status == "MISMATCH", result.mismatches

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", forged_path)
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        load_owner_decision_evidence(forged_path)
    assert "attestation" in str(excinfo.value) or "authority" in str(excinfo.value)


def test_forged_attested_key_id_names_its_divergence(tmp_path):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_forged_authority(
        decision_bytes,
        bundle.record.provenance,
        bundle.record.authority,
        attested_key_id="forged-key-id-never-attested-0000000000000",
    )
    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    result = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "ATTESTED_KEY_DIVERGED" in result.mismatches


def test_forged_attested_registry_identity_names_its_divergences(tmp_path):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    for updates, expected in (
        (
            {"attested_registry_id": "forged-registry-id-00000000000000000000000"},
            "ATTESTED_REGISTRY_DIVERGED",
        ),
        (
            {"attested_registry_content_sha256": "ab" * 32},
            "ATTESTED_REGISTRY_DIVERGED",
        ),
        (
            {"evidence_content_sha256": "cd" * 32},
            "EVIDENCE_HASH_DIVERGED",
        ),
    ):
        forged_record = _record_with_forged_authority(
            decision_bytes, bundle.record.provenance, bundle.record.authority, **updates
        )
        forged_dir = _forged_bundle_from_record(
            tmp_path / "evidence", bundle_dir, forged_record
        )
        result = reverify_owner_decision_evidence(forged_dir / "bundle.json")
        assert result.replay_status == "MISMATCH", updates
        assert expected in result.mismatches, (updates, result.mismatches)


# ---------------------------------------------------------------------------
# F1-2 (red) — a VALID bundle claiming VERIFIED authority over an honestly
# REJECTED signature must never replay clean
# ---------------------------------------------------------------------------


def _forged_verified_record_over_rejected_bytes(
    decision_bytes: bytes,
    snapshot,
    trusted_key_id: str,
) -> OwnerPolicyDecisionRecordV1:
    """A record exactly shaped like an honest VERIFIED capture (same
    provenance, same attested identities) but over the rejected submission."""

    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    forged_authority = OwnerAuthorityAssessmentV1(
        authority_status="OWNER_AUTHORITY_VERIFIED",
        verification_method="INJECTED_VERIFIER",
        verifier_kind="signed_owner_provenance",
        allowlist_matched=True,
        reason_code="ED25519_OWNER_PROVENANCE_VERIFIED",
        detail=(
            "Forged verified-authority claim over a signature whose honest "
            "cryptographic verification is REJECTED."
        ),
        evidence_content_sha256=hashlib.sha256(decision_bytes).hexdigest(),
        attested_key_id=trusted_key_id,
        attested_registry_id=snapshot.registry.registry_id,
        attested_registry_content_sha256=snapshot.registry.content_sha256,
    )
    provenance = DecisionProvenanceV1(
        source_kind="LOCAL_UNSIGNED_JSON",
        source_revision=decision_input.source_revision,
        source_content_sha256=hashlib.sha256(decision_bytes).hexdigest(),
    )
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=decision_input,
        provenance=provenance,
        authority=forged_authority,
    )


def test_rejected_signature_never_becomes_historic_verified_authority(
    tmp_path, capsys
):
    bundle_dir, (decision_bytes, _, snapshot, trusted) = _persisted_rejected(tmp_path)
    forged_record = _forged_verified_record_over_rejected_bytes(
        decision_bytes, snapshot, trusted.key_id
    )

    # Rebuild a maximally consistent VALID bundle over the rejected capture:
    # honest REJECTED dossier preserved, six-file shape, matching directory.
    payload = json.loads((bundle_dir / "bundle.json").read_text("utf-8"))
    payload["validation_state"] = "VALID"
    payload["validation_blockers"] = []
    payload["record"] = forged_record.model_dump(mode="json")
    payload["record_content_sha256"] = forged_record.content_sha256
    payload["bundle_id"] = _bundle_id_for(payload)
    payload["content_sha256"] = _bundle_content_sha256(payload)
    forged_dir = tmp_path / "evidence" / payload["bundle_id"]
    forged_dir.mkdir(parents=True)
    for name in (
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
    ):
        (forged_dir / name).write_bytes((bundle_dir / name).read_bytes())
    _dump_json(forged_dir / "record.json", forged_record.model_dump(mode="json"))
    _dump_json(forged_dir / "bundle.json", payload)
    forged_path = forged_dir / "bundle.json"

    result = reverify_owner_decision_evidence(forged_path)
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "AUTHORITY_STATUS_INCONSISTENT" in result.mismatches

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", forged_path)
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(forged_path)


def test_forged_verified_claim_does_not_reach_a_ready_plan(tmp_path, capsys):
    """Even where historical replay overstated authority, the plan re-attests
    freshly against the current trust root: the honestly rejected signature
    keeps the plan BLOCKED (and post-fix the forged bundle fails the strict
    evidence load outright)."""

    bundle_dir, (decision_bytes, _, snapshot, trusted) = _persisted_rejected(tmp_path)
    forged_record = _forged_verified_record_over_rejected_bytes(
        decision_bytes, snapshot, trusted.key_id
    )
    payload = json.loads((bundle_dir / "bundle.json").read_text("utf-8"))
    payload["validation_state"] = "VALID"
    payload["validation_blockers"] = []
    payload["record"] = forged_record.model_dump(mode="json")
    payload["record_content_sha256"] = forged_record.content_sha256
    payload["bundle_id"] = _bundle_id_for(payload)
    payload["content_sha256"] = _bundle_content_sha256(payload)
    forged_dir = tmp_path / "evidence" / payload["bundle_id"]
    forged_dir.mkdir(parents=True)
    for name in (
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
    ):
        (forged_dir / name).write_bytes((bundle_dir / name).read_bytes())
    _dump_json(forged_dir / "record.json", forged_record.model_dump(mode="json"))
    _dump_json(forged_dir / "bundle.json", payload)
    forged_path = forged_dir / "bundle.json"

    trust_root = tmp_path / "trust-root"
    public_key = tmp_path / "owner.pub"
    public_key.write_text(trusted.public_base64 + "\n", "utf-8")
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

    submission = tmp_path / "submission"
    submission.mkdir()
    exception_path = submission / "exception.json"
    exception_path.write_text(_policy_exception().model_dump_json(indent=2), "utf-8")
    record_path = submission / "record.json"
    _dump_json(record_path, forged_record.model_dump(mode="json"))

    project_config = submission / "project.toml"
    project_config.write_text(
        "\n".join(
            [
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
        ),
        "utf-8",
    )
    plan_path = submission / "plan.json"
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
        exception_path,
        "--decision-record",
        record_path,
        "--project-config",
        project_config,
        "--trust-root",
        trust_root,
        "--authority-evidence",
        forged_path,
        "--output",
        plan_path,
    )
    assert code != 0, out
    if plan_path.exists():
        plan = json.loads(plan_path.read_text("utf-8"))
        assert plan["plan_state"] != "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert not any(
        item.startswith("OWNER_AUTHORITY_REVERIFICATION_REVERIFIED")
        for item in (json.loads(plan_path.read_text("utf-8"))["blockers"]
                     if plan_path.exists() else [])
    )


# ---------------------------------------------------------------------------
# F1-3 (red) — VALID with nonempty validation blockers
# ---------------------------------------------------------------------------


def test_valid_state_with_nonempty_blockers_is_incoherent(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, (_, _, _, validation, bundle) = _persisted(tmp_path, key)
    # Record-time truth: a VALID capture carries no blockers.
    assert validation.state == "VALID"
    assert validation.blockers == []
    assert bundle.validation_blockers == []

    payload = json.loads((bundle_dir / "bundle.json").read_text("utf-8"))
    payload["validation_blockers"] = ["FORGED_BLOCKER_NEVER_POSSIBLE_AT_CAPTURE"]
    payload["content_sha256"] = _bundle_content_sha256(payload)
    # bundle_id does not bind the blocker list, so the same directory is the
    # maximally consistent forgery; only bundle.json is rewritten.
    _dump_json(bundle_dir / "bundle.json", payload)

    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "VALID_STATE_WITH_BLOCKERS" in result.mismatches

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(bundle_dir / "bundle.json")


# ---------------------------------------------------------------------------
# Green preservation — honest evidence replays byte-identically
# ---------------------------------------------------------------------------


def test_genuine_verified_capture_still_replays_clean_and_loads(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, (_, _, _, _, bundle) = _persisted(tmp_path, key)
    assert bundle.validation_state == "VALID"
    assert bundle.verification.verification_status == "VERIFIED"
    assert bundle.record is not None
    assert bundle.record.authority.authority_status == "OWNER_AUTHORITY_VERIFIED"

    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL", result.mismatches
    loaded = load_owner_decision_evidence(bundle_dir / "bundle.json")
    assert loaded.bundle.bundle_id == bundle.bundle_id

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 0, out


def test_honest_rejected_capture_still_replays_byte_identically(tmp_path, capsys):
    bundle_dir, _ = _persisted_rejected(tmp_path)
    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL", result.mismatches
    assert result.replayed_verification.verification_status == "REJECTED"

    loaded = load_owner_decision_evidence(bundle_dir / "bundle.json")
    assert loaded.bundle.validation_state == "INVALID"

    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 0, out


def test_honest_invalid_capture_with_verified_crypto_still_replays(tmp_path, capsys):
    """A signature that verifies while a decision check fails is a legitimate
    INVALID capture (verified crypto, nonempty blockers, no record): the
    attestation contract must not overreach into re-deriving the economic
    audit — this bundle still replays byte-identically."""

    key = _FixtureKey()
    # A stale audit binding blocks the decision while the signature itself is
    # genuine, so verification stays VERIFIED with an INVALID validation.
    decision_bytes = _accept_bytes(audit_content_sha256="00" * 32)
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    statement = build_owner_signed_decision_statement(
        signature=key.private.sign(
            owner_decision_input_signature_message(decision_input)
        ),
        key_id=key.key_id,
        decision_input=decision_input,
    )
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
    assert validation.state == "INVALID"
    assert validation.blockers
    assert bundle.verification.verification_status == "VERIFIED"
    assert bundle.record is None
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    bundle_path = evidence_root / bundle.bundle_id / "bundle.json"

    result = reverify_owner_decision_evidence(bundle_path)
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL", result.mismatches

    loaded = load_owner_decision_evidence(bundle_path)
    assert loaded.bundle.validation_state == "INVALID"

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", bundle_path)
    assert code == 0, out


# ---------------------------------------------------------------------------
# F2 — safe owner-key provisioning, executed from the walkthrough document
# ---------------------------------------------------------------------------

THROWAWAY_PASSPHRASE = "throwaway-test-passphrase-only"


def _keygen_snippet_from_walkthrough() -> str:
    """Extract the §1 key-creation python heredoc verbatim from the
    operations walkthrough, so the tested procedure is the documented one."""

    text = WALKTHROUGH_PATH.read_text(encoding="utf-8")
    marker = "python - <<'EOF'"
    start = text.index(marker) + len(marker)
    end = text.index("\nEOF", start)
    return text[start:end].lstrip("\n")


def _prepare_owner_home(home: Path) -> None:
    """The walkthrough §0 directory skeleton (outside the repository)."""

    for name in ("trust-root", "bundle", "decisions", "evidence", "private"):
        (home / "tve-trust" / name).mkdir(parents=True, exist_ok=True)


def _run_keygen_snippet(
    home: Path, *, umask: int = 0o000
) -> subprocess.CompletedProcess:
    """Run the documented §1 heredoc in a fresh process against a throwaway
    HOME, forcing a deliberately permissive umask, with the throwaway
    passphrase piped to the interactive prompt (never argv)."""

    script_path = home / f"keygen-{uuid.uuid4().hex}.py"
    script_path.write_text(
        "import os\n"
        f"os.umask({umask!r})\n"
        + _keygen_snippet_from_walkthrough(),
        "utf-8",
    )
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        input=THROWAWAY_PASSPHRASE + "\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    script_path.unlink(missing_ok=True)
    return completed


def test_walkthrough_keygen_creates_private_key_mode_0600_under_permissive_umask(
    tmp_path,
):
    home = tmp_path / "home"
    _prepare_owner_home(home)
    completed = _run_keygen_snippet(home, umask=0o000)
    assert completed.returncode == 0, completed.stderr

    private_pem = home / "tve-trust/private/owner.pem"
    assert private_pem.is_file()
    assert not private_pem.is_symlink()
    # The file is owner-only from the first open, regardless of umask.
    assert (private_pem.stat().st_mode & 0o777) == 0o600, oct(
        private_pem.stat().st_mode & 0o777
    )
    # The private directory is owner-only.
    assert (private_pem.parent.stat().st_mode & 0o777) == 0o700, oct(
        private_pem.parent.stat().st_mode & 0o777
    )
    assert private_pem.read_bytes().startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
    public_key = home / "tve-trust/bundle/owner.pub"
    assert public_key.is_file() and public_key.read_text("utf-8").strip()
    # No secret ever reaches stdout/stderr.
    assert THROWAWAY_PASSPHRASE not in completed.stdout + completed.stderr


def test_walkthrough_keygen_refuses_existing_destination(tmp_path):
    home = tmp_path / "home"
    _prepare_owner_home(home)
    first = _run_keygen_snippet(home)
    assert first.returncode == 0, first.stderr
    private_pem = home / "tve-trust/private/owner.pem"
    original_bytes = private_pem.read_bytes()

    second = _run_keygen_snippet(home)
    assert second.returncode != 0, second.stdout
    assert "refus" in (second.stdout + second.stderr).lower()
    # The existing key is byte-identical: no overwrite, no partial write.
    assert private_pem.read_bytes() == original_bytes


def test_walkthrough_keygen_refuses_symlink_destination(tmp_path):
    home = tmp_path / "home"
    _prepare_owner_home(home)
    outside = tmp_path / "outside-target.pem"
    outside.write_bytes(b"pre-existing outside bytes that must not be touched\n")
    private_pem = home / "tve-trust/private/owner.pem"
    private_pem.symlink_to(outside)

    completed = _run_keygen_snippet(home)
    assert completed.returncode != 0, completed.stdout
    assert "refus" in (completed.stdout + completed.stderr).lower()
    # The symlink was neither replaced nor followed.
    assert private_pem.is_symlink()
    assert outside.read_bytes() == b"pre-existing outside bytes that must not be touched\n"


_SIGN_SCRIPT = """
import json, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from turtle_value_engine.evolution.owner_decision import OwnerPolicyDecisionInputV1
from turtle_value_engine.evolution.owner_provenance import (
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
)
from turtle_value_engine.providers.models import canonical_json_bytes

private = serialization.load_pem_private_key(
    Path(sys.argv[1]).read_bytes(), sys.argv[2].encode("utf-8")
)
model = OwnerPolicyDecisionInputV1.model_validate(
    json.loads(Path(sys.argv[3]).read_text("utf-8"))
)
Path(sys.argv[3]).write_bytes(canonical_json_bytes(model.model_dump(mode="json")))
statement = build_owner_signed_decision_statement(
    signature=private.sign(owner_decision_input_signature_message(model)),
    key_id=sys.argv[4],
    decision_input=model,
)
Path(sys.argv[5]).write_text(
    json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True)
    + "\\n",
    "utf-8",
)
"""


def test_walkthrough_provisioned_key_reloads_and_signs_in_a_fresh_process(tmp_path):
    """The throwaway key provisioned by the documented snippet reloads in a
    second process and signs verifiable canonical bytes (test-only secret)."""

    home = tmp_path / "home"
    _prepare_owner_home(home)
    completed = _run_keygen_snippet(home)
    assert completed.returncode == 0, completed.stderr
    private_pem = home / "tve-trust/private/owner.pem"
    public_b64 = (
        (home / "tve-trust/bundle/owner.pub").read_text("utf-8").strip()
    )

    submission = tmp_path / "submission"
    submission.mkdir()
    decision_path = submission / "decision-input.json"
    decision_path.write_text(json.dumps(_accept_payload()), "utf-8")
    statement_path = submission / "statement.json"

    key_id = owner_provenance_key_id(
        algorithm=PROVENANCE_ALGORITHM, public_key_base64=public_b64
    )
    sign_env = dict(os.environ)
    sign_env["PYTHONPATH"] = str(ROOT / "src")
    signed = subprocess.run(
        [
            sys.executable,
            "-c",
            _SIGN_SCRIPT,
            str(private_pem),
            THROWAWAY_PASSPHRASE,
            str(decision_path),
            key_id,
            str(statement_path),
        ],
        capture_output=True,
        text=True,
        env=sign_env,
        check=False,
    )
    assert signed.returncode == 0, signed.stderr

    statement = json.loads(statement_path.read_text("utf-8"))
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_path.read_text("utf-8"))
    )
    reloaded = serialization.load_pem_private_key(
        private_pem.read_bytes(), THROWAWAY_PASSPHRASE.encode("utf-8")
    )
    assert isinstance(reloaded, Ed25519PrivateKey)
    reloaded.public_key().verify(
        base64.b64decode(statement["signature_base64"]),
        owner_decision_input_signature_message(decision_input),
    )
