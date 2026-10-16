"""Phase 7-C3-B focused tests: trusted owner provenance operations.

Covers the trust-root registry snapshot store (append-only chain, enrollment,
rotation, revocation, fail-closed corruption handling, create-only
publication), the immutable decision-evidence bundle (deterministic capture
through the real ``SignedOwnerProvenanceVerifier``, offline byte-identical
re-verification, tamper detection), the fail-closed CLI integration
(``tve provenance registry …``, ``tve provenance verify-evidence``, the
``record-decision``/``plan-activation`` provenance extensions, trust-root
co-location guards) and the narrowly versioned signed revocation and
supersession protocols (verified scoped effect only; unsigned metadata can
never increase authorization).

All Ed25519 keys here are throwaway fixtures generated at runtime; no real
owner key material exists in this repository, and no real owner acceptance
of strict-v2 is claimed or synthesized.
"""

import base64
import hashlib
import json
import socket
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from turtle_value_engine import cli as cli_module
from turtle_value_engine import load_normalized_input
from turtle_value_engine.evolution.activation_plan import ProfileActivationPlanV1
from turtle_value_engine.evolution.owner_decision import (
    AuthenticatedRevocationBindingV1,
    AuthenticatedSupersessionBindingV1,
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
    resolve_owner_decision_authority,
)
from turtle_value_engine.evolution.owner_lifecycle import (
    LIFECYCLE_REVOCATION_PURPOSE,
    LIFECYCLE_SUPERSESSION_PURPOSE,
    REQUIRED_REVOCATION_CHECK_NAMES,
    REQUIRED_SUPERSESSION_CHECK_NAMES,
    OwnerRevocationPayloadV1,
    OwnerSignedRevocationEvidenceV1,
    OwnerSignedSupersessionEvidenceV1,
    OwnerSupersessionPayloadV1,
    build_owner_signed_revocation_statement,
    build_owner_signed_supersession_statement,
    owner_revocation_signature_message,
    owner_supersession_signature_message,
    verify_owner_revocation,
    verify_owner_supersession,
)
from turtle_value_engine.evolution.owner_provenance import (
    PROVENANCE_ALGORITHM,
    SignedOwnerProvenanceVerifier,
    build_owner_provenance_key_registry,
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
    owner_provenance_key_id,
)
from turtle_value_engine.evolution.owner_provenance import (
    OwnerProvenanceKeyRecordV1 as LifecycleKeyRecord,
)
from turtle_value_engine.evolution.owner_trust_store import (
    OwnerProvenanceEvidenceBundleV1,
    OwnerProvenanceRegistrySnapshotV1,
    OwnerProvenanceTrustStore,
    OwnerTrustStoreError,
    build_initial_registry_snapshot,
    capture_owner_decision_evidence,
    enroll_registry_key,
    load_owner_decision_evidence,
    persist_owner_decision_evidence,
    reverify_owner_decision_evidence,
    revoke_registry_key,
    rotate_registry_key,
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
SCHEMAS = ROOT / "schemas"

STRICT_V2_SHA256 = "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
OWNER_IDENTITY = "Ryder Xie"

_boundary_input = None


def _boundary():
    global _boundary_input
    if _boundary_input is None:
        _boundary_input = load_normalized_input(BOUNDARY_PATH)
    return _boundary_input


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
    exception = _policy_exception()
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[exception],
    )
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
        "exception_id": exception.exception_id,
        "exception_content_sha256": exception.content_sha256,
        "rationale": "Accept the stricter 14% CDC gate as intended owner policy.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-15",
        "source_revision": "c3b-test",
    }
    payload.update(overrides)
    return payload


def _accept_bytes(**overrides) -> bytes:
    return canonical_json_bytes(_accept_payload(**overrides))


def _reject_bytes() -> bytes:
    return canonical_json_bytes(
        _accept_payload(
            decision="REJECT",
            exception_id=None,
            exception_content_sha256=None,
            rationale=(
                "Owner rejects the stricter gate until band ordering is "
                "corrected in a strict-v3 candidate."
            ),
        )
    )


class _FixtureKey:
    """A throwaway Ed25519 keypair with its registry record."""

    def __init__(
        self,
        *,
        owner_identity: str = OWNER_IDENTITY,
        authorized_decisions: list[str] | None = None,
        valid_from: str = "2026-01-01",
        valid_until: str = "2026-12-31",
        revoked: bool = False,
    ) -> None:
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
            owner_identity=owner_identity,
            authorized_decisions=authorized_decisions
            or ["ACCEPT_WITH_EXCEPTION", "REJECT"],
            valid_from=valid_from,
            valid_until=valid_until,
            revoked=revoked,
            **({"revocation_reference": "test-revocation"} if revoked else {}),
        )

    def sign_bytes(self, message: bytes) -> bytes:
        return self.private.sign(message)


def _initialized_store(tmp_path: Path, *keys: _FixtureKey) -> OwnerProvenanceTrustStore:
    registry = build_owner_provenance_key_registry([key.record for key in keys])
    store = OwnerProvenanceTrustStore(tmp_path / "trust-root")
    store.init_store(registry)
    return store


def _write_project_config(tmp_path: Path, default: str = "strict-v1") -> Path:
    content = [
        "schema_version = 1",
        "",
        "[project]",
        'id = "turtle-value-engine"',
        'environment = "private"',
        'timezone = "Asia/Taipei"',
        "",
        "[profiles]",
        f'default = "{default}"',
        "",
    ]
    path = tmp_path / "project.toml"
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def _signed_submission(key: _FixtureKey, **overrides) -> tuple[bytes, dict]:
    """Canonical decision-input bytes plus a valid statement payload."""
    decision_bytes = _accept_bytes(**overrides)
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    statement = build_owner_signed_decision_statement(
        signature=key.private.sign(owner_decision_input_signature_message(decision_input)),
        key_id=key.key_id,
        decision_input=decision_input,
    )
    return decision_bytes, json.loads(statement.model_dump_json())


def _unverified_reject_record() -> OwnerPolicyDecisionRecordV1:
    reject_bytes = _reject_bytes()
    reject_input = OwnerPolicyDecisionInputV1.model_validate(json.loads(reject_bytes))
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=reject_input,
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision=reject_input.source_revision,
            source_content_sha256=hashlib.sha256(reject_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            allowlist_matched=None,
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="captured",
        ),
    )


# ---------------------------------------------------------------------------
# 1. Trust-root registry snapshot store (package A)
# ---------------------------------------------------------------------------


def test_snapshot_chain_lifecycle_init_enroll_revoke_rotate(tmp_path):
    key1, key2, key3 = _FixtureKey(), _FixtureKey(), _FixtureKey()
    store = _initialized_store(tmp_path, key1)

    first = store.latest_snapshot()
    assert first.sequence == 1
    assert first.parent_snapshot_content_sha256 is None
    assert first.registry.content_sha256 == build_owner_provenance_key_registry(
        [key1.record]
    ).content_sha256

    store.append_snapshot(enroll_registry_key(first, key2.record))
    second = store.latest_snapshot()
    assert second.sequence == 2
    assert second.parent_snapshot_content_sha256 == first.snapshot_content_sha256
    assert {item.key_id for item in second.registry.keys} == {
        key1.key_id,
        key2.key_id,
    }

    store.append_snapshot(
        rotate_registry_key(second, key1.key_id, key3.record, "compromise-suspected")
    )
    third = store.latest_snapshot()
    old = next(item for item in third.registry.keys if item.key_id == key1.key_id)
    new = next(item for item in third.registry.keys if item.key_id == key3.key_id)
    assert old.revoked and old.revocation_reference == "compromise-suspected"
    assert not new.revoked

    store.append_snapshot(revoke_registry_key(third, key2.key_id, "retired"))
    fourth = store.latest_snapshot()
    retired = next(item for item in fourth.registry.keys if item.key_id == key2.key_id)
    assert retired.revoked

    # The chain is reloadable end to end and old snapshots stay valid models.
    reloaded = OwnerProvenanceTrustStore(tmp_path / "trust-root").latest_snapshot()
    assert reloaded == fourth
    for sequence in range(1, 5):
        raw = tmp_path / "trust-root" / "snapshots" / f"snapshot-{sequence:06d}.json"
        assert OwnerProvenanceRegistrySnapshotV1.model_validate(
            json.loads(raw.read_text(encoding="utf-8"))
        )


def test_same_key_set_under_different_trust_content_is_a_distinct_snapshot():
    key = _FixtureKey()
    narrow = build_owner_provenance_key_registry(
        [
            LifecycleKeyRecord(
                key_id=key.key_id,
                public_key_base64=key.public_base64,
                owner_identity=OWNER_IDENTITY,
                authorized_decisions=["REJECT"],
                valid_from="2026-01-01",
                valid_until="2026-02-02",
            )
        ]
    )
    wide = build_owner_provenance_key_registry(
        [
            LifecycleKeyRecord(
                key_id=key.key_id,
                public_key_base64=key.public_base64,
                owner_identity=OWNER_IDENTITY,
                authorized_decisions=["ACCEPT_WITH_EXCEPTION", "REJECT"],
                valid_from="2026-01-01",
                valid_until="2026-12-31",
            )
        ]
    )
    snapshot_narrow = build_initial_registry_snapshot(narrow)
    snapshot_wide = build_initial_registry_snapshot(wide)
    assert narrow.registry_id == wide.registry_id  # key-set derived by design
    assert (
        snapshot_narrow.snapshot_content_sha256 != snapshot_wide.snapshot_content_sha256
    )
    assert snapshot_narrow.snapshot_id != snapshot_wide.snapshot_id


def test_store_corruptions_fail_closed(tmp_path):
    store = _initialized_store(tmp_path, _FixtureKey())
    first = store.latest_snapshot()
    store.append_snapshot(enroll_registry_key(first, _FixtureKey().record))
    snapshots = tmp_path / "trust-root" / "snapshots"
    second = store.snapshot_by_sequence(2)

    # Tampered snapshot body (re-serialized with an edited identity).
    tampered = json.loads((snapshots / "snapshot-000002.json").read_text("utf-8"))
    tampered["registry"]["keys"][0]["owner_identity"] = "attacker"
    (snapshots / "snapshot-000002.json").write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    with pytest.raises(OwnerTrustStoreError):
        store.latest_snapshot()
    (snapshots / "snapshot-000002.json").write_text(
        json.dumps(
            json.loads(second.model_dump_json()), indent=2, sort_keys=True
        )
        + "\n",
        "utf-8",
    )
    assert store.latest_snapshot().sequence == 2

    # Gap in the chain.
    (snapshots / "snapshot-000001.json").unlink()
    with pytest.raises(OwnerTrustStoreError):
        store.latest_snapshot()

    # Foreign file inside the snapshots directory.
    other_key = _FixtureKey()
    fresh = OwnerProvenanceTrustStore(tmp_path / "other")
    fresh.init_store(
        build_owner_provenance_key_registry([other_key.record])
    )
    assert fresh.latest_snapshot().sequence == 1
    (tmp_path / "other" / "snapshots" / "not-a-snapshot.json").write_text("{}", "utf-8")
    with pytest.raises(OwnerTrustStoreError):
        fresh.latest_snapshot()


def test_store_init_and_append_are_create_only(tmp_path):
    key_a, key_b = _FixtureKey(), _FixtureKey()
    store = _initialized_store(tmp_path, key_a)
    first = store.latest_snapshot()

    # Byte-identical init is idempotent; a different first snapshot never
    # overwrites the committed one.
    assert (
        store.init_store(build_owner_provenance_key_registry([key_a.record]))
        == "IDEMPOTENT"
    )
    with pytest.raises(OwnerTrustStoreError, match="immutable"):
        store.init_store(build_owner_provenance_key_registry([key_b.record]))
    assert store.latest_snapshot() == first

    # A foreign file at the next sequence path is never clobbered: the
    # append fails closed (as a chain tamper here) and overwrites nothing.
    next_path = tmp_path / "trust-root" / "snapshots" / "snapshot-000002.json"
    next_path.write_text("foreign", "utf-8")
    with pytest.raises(OwnerTrustStoreError):
        store.append_snapshot(enroll_registry_key(first, key_b.record))
    assert next_path.read_text("utf-8") == "foreign"
    next_path.unlink()
    store.append_snapshot(enroll_registry_key(first, key_b.record))
    assert store.latest_snapshot().sequence == 2

    # A symlinked snapshot path is refused outright.
    next_path.unlink()
    next_path.symlink_to(tmp_path / "elsewhere.json")
    with pytest.raises(OwnerTrustStoreError, match="symlink"):
        store.append_snapshot(enroll_registry_key(first, key_b.record))


def test_lifecycle_operation_invariants_fail_closed():
    key1, key2 = _FixtureKey(), _FixtureKey()
    first = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([key1.record])
    )

    with pytest.raises(ValueError, match="already registered"):
        enroll_registry_key(first, key1.record)
    with pytest.raises(ValueError, match="unknown"):
        revoke_registry_key(first, "owner-provenance-key-nonexistent", "ref")
    revoked_snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry(
            [
                LifecycleKeyRecord(
                    key_id=key1.key_id,
                    public_key_base64=key1.public_base64,
                    owner_identity=OWNER_IDENTITY,
                    authorized_decisions=["REJECT"],
                    valid_from="2026-01-01",
                    valid_until="2026-12-31",
                    revoked=True,
                    revocation_reference="pre-revoked",
                )
            ]
        )
    )
    with pytest.raises(ValueError, match="already revoked"):
        revoke_registry_key(revoked_snapshot, key1.key_id, "again")
    with pytest.raises(ValueError, match="unknown"):
        rotate_registry_key(first, "owner-provenance-key-nonexistent", key2.record, "r")
    with pytest.raises(ValueError, match="already revoked"):
        rotate_registry_key(revoked_snapshot, key1.key_id, key2.record, "r")


# ---------------------------------------------------------------------------
# 2. Evidence capture and offline re-verification (package A)
# ---------------------------------------------------------------------------


def _capture(tmp_path: Path, key: _FixtureKey, *, decision_bytes: bytes | None = None):
    decision_bytes = decision_bytes or _accept_bytes()
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
    return decision_bytes, statement, snapshot, validation, bundle


def test_capture_creates_a_verified_record_and_complete_bundle(tmp_path):
    key = _FixtureKey()
    decision_bytes, statement, snapshot, validation, bundle = _capture(tmp_path, key)

    assert validation.state == "VALID"
    assert validation.record is not None
    assert validation.record.authority.authority_status == "OWNER_AUTHORITY_VERIFIED"
    assert (
        validation.record.authority.attested_registry_id
        == snapshot.registry.registry_id
    )
    assert bundle.verification.verification_status == "VERIFIED"
    assert bundle.record is not None
    assert bundle.validation_state == "VALID"
    assert bundle.decision_input_content_sha256 == hashlib.sha256(
        decision_bytes
    ).hexdigest()

    evidence_root = tmp_path / "evidence"
    result = persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    assert result == "CREATED"
    bundle_dir = evidence_root / bundle.bundle_id
    assert {
        "bundle.json",
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
        "record.json",
    } == {item.name for item in bundle_dir.iterdir()}
    assert (bundle_dir / "decision-input.json").read_bytes() == decision_bytes

    # Byte-identical recapture is idempotent with identical identities.
    *_, bundle_again = _capture(tmp_path, key)
    assert bundle_again == bundle
    assert (
        persist_owner_decision_evidence(
            evidence_root,
            bundle_again,
            decision_input_bytes=decision_bytes,
            statement=statement,
            registry_snapshot=snapshot,
        )
        == "IDEMPOTENT"
    )


def test_capture_with_foreign_signature_records_no_record(tmp_path):
    trusted, foreign = _FixtureKey(), _FixtureKey()
    decision_bytes = _accept_bytes()
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([trusted.record])
    )
    bad_statement = build_owner_signed_decision_statement(
        signature=foreign.private.sign(
            owner_decision_input_signature_message(decision_input)
        ),
        key_id=trusted.key_id,
        decision_input=decision_input,
    )
    validation_bad, bundle_bad = capture_owner_decision_evidence(
        decision_input_bytes=decision_bytes,
        statement=bad_statement,
        registry_snapshot=snapshot,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation_bad.state == "INVALID"
    assert validation_bad.record is None
    assert bundle_bad.record is None
    assert bundle_bad.validation_state == "INVALID"
    assert bundle_bad.verification.verification_status == "REJECTED"
    assert "SIGNATURE_VERIFIED" in bundle_bad.verification.reason_code


def test_reverify_replays_byte_identically_and_detects_tampering(tmp_path):
    key = _FixtureKey()
    decision_bytes, statement, snapshot, _, bundle = _capture(tmp_path, key)
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
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL"
    assert result.mismatches == []
    assert result.replayed_verification == bundle.verification

    # Tampered decision-input bytes are a classified mismatch.
    bundle_dir = bundle_path.parent
    original = (bundle_dir / "decision-input.json").read_bytes()
    (bundle_dir / "decision-input.json").write_bytes(
        canonical_json_bytes(_accept_payload(rationale="Tampered rationale text."))
    )
    tampered = reverify_owner_decision_evidence(bundle_path)
    assert tampered.replay_status == "MISMATCH"
    assert tampered.mismatches
    (bundle_dir / "decision-input.json").write_bytes(original)
    assert (
        reverify_owner_decision_evidence(bundle_path).replay_status
        == "REPLAYS_BYTE_IDENTICAL"
    )

    # A tampered embedded dossier (forged VERIFIED) cannot survive replay:
    # the file itself no longer matches its own content hash.
    forged = json.loads((bundle_dir / "verification.json").read_text("utf-8"))
    forged["detail"] = "everything is fine, trust me"
    (bundle_dir / "verification.json").write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    with pytest.raises(Exception):
        reverify_owner_decision_evidence(bundle_path)


def test_reverify_is_offline_and_socket_free(tmp_path, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("evidence re-verification constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    key = _FixtureKey()
    decision_bytes, statement, snapshot, _, bundle = _capture(tmp_path, key)
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    assert (
        reverify_owner_decision_evidence(
            evidence_root / bundle.bundle_id / "bundle.json"
        ).replay_status
        == "REPLAYS_BYTE_IDENTICAL"
    )


def test_load_evidence_validates_every_component_hash(tmp_path):
    key = _FixtureKey()
    decision_bytes, statement, snapshot, _, bundle = _capture(tmp_path, key)
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    loaded = load_owner_decision_evidence(
        evidence_root / bundle.bundle_id / "bundle.json"
    )
    assert loaded.decision_input_bytes == decision_bytes
    assert loaded.statement == statement
    assert loaded.snapshot == snapshot
    assert loaded.bundle == bundle

    snapshot_file = evidence_root / bundle.bundle_id / "registry-snapshot.json"
    payload = json.loads(snapshot_file.read_text("utf-8"))
    payload["registry"]["keys"][0]["owner_identity"] = "attacker"
    snapshot_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    with pytest.raises(Exception):
        load_owner_decision_evidence(evidence_root / bundle.bundle_id / "bundle.json")


def test_evidence_directory_collision_is_a_classified_failure(tmp_path):
    key = _FixtureKey()
    decision_bytes, statement, snapshot, _, bundle = _capture(tmp_path, key)
    evidence_root = tmp_path / "evidence"
    target_dir = evidence_root / bundle.bundle_id
    target_dir.mkdir(parents=True)
    (target_dir / "bundle.json").write_text("foreign", "utf-8")
    with pytest.raises(OwnerTrustStoreError, match="immutable"):
        persist_owner_decision_evidence(
            evidence_root,
            bundle,
            decision_input_bytes=decision_bytes,
            statement=statement,
            registry_snapshot=snapshot,
        )
    assert (target_dir / "bundle.json").read_text("utf-8") == "foreign"


# ---------------------------------------------------------------------------
# 3. Signed revocation and supersession protocols (package B)
# ---------------------------------------------------------------------------


def _revocation_payload(record: OwnerPolicyDecisionRecordV1, **overrides):
    payload = {
        "contract": "owner_signed_revocation_payload_v1",
        "revoked_decision_record_id": record.decision_record_id,
        "revoked_record_content_sha256": record.content_sha256,
        "target_profile_id": record.target_profile_id,
        "target_profile_sha256": record.target_profile_sha256,
        "revoked_by": OWNER_IDENTITY,
        "revoked_at": "2026-10-15",
        "rationale": "The owner withdraws this decision after reconsideration.",
        "source_revision": "c3b-test",
    }
    payload.update(overrides)
    return OwnerRevocationPayloadV1.model_validate(payload)


def _signed_revocation(
    key: _FixtureKey, record: OwnerPolicyDecisionRecordV1, **overrides
):
    payload = _revocation_payload(record, **overrides)
    statement = build_owner_signed_revocation_statement(
        signature=key.private.sign(owner_revocation_signature_message(payload)),
        key_id=key.key_id,
        payload=payload,
    )
    return OwnerSignedRevocationEvidenceV1(payload=payload, statement=statement)


_BINDING_FIELDS = {
    "revoked_decision_record_id",
    "revoked_record_content_sha256",
    "target_profile_id",
    "target_profile_sha256",
    "revoked_by",
    "revoked_at",
}


def _revocation_binding(record: OwnerPolicyDecisionRecordV1, **overrides):
    payload = _revocation_payload(record, **overrides)
    return AuthenticatedRevocationBindingV1.model_validate(
        {
            key: value
            for key, value in payload.model_dump(mode="json").items()
            if key in _BINDING_FIELDS
        }
    )


def test_signed_revocation_happy_path_verifies_every_check(tmp_path):
    key = _FixtureKey()
    _, _, _, _, bundle = _capture(tmp_path, key)
    evidence = _signed_revocation(key, bundle.record)
    registry = build_owner_provenance_key_registry([key.record])

    dossier = verify_owner_revocation(
        payload=evidence.payload, statement=evidence.statement, registry=registry
    )
    assert dossier.verification_status == "VERIFIED"
    assert [check.name for check in dossier.checks] == list(
        REQUIRED_REVOCATION_CHECK_NAMES
    )
    replay = verify_owner_revocation(
        payload=evidence.payload, statement=evidence.statement, registry=registry
    )
    assert replay == dossier


def test_signed_revocation_negative_classes_fail_closed(tmp_path):
    key = _FixtureKey()
    other = _FixtureKey()
    _, _, _, _, bundle = _capture(tmp_path, key)
    record = bundle.record
    registry = build_owner_provenance_key_registry([key.record])

    def failures(payload, statement, reg):
        dossier = verify_owner_revocation(
            payload=payload, statement=statement, registry=reg
        )
        assert dossier.verification_status == "REJECTED"
        return [check.name for check in dossier.checks if not check.passed]

    # Unknown signing key.
    unknown = _signed_revocation(other, record)
    assert "KEY_RESOLUTION" in failures(unknown.payload, unknown.statement, registry)

    # Revoked signing key.
    revoked_key = _FixtureKey(revoked=True)
    revoked_registry = build_owner_provenance_key_registry([revoked_key.record])
    revoked = _signed_revocation(revoked_key, record)
    assert "KEY_NOT_REVOKED" in failures(
        revoked.payload, revoked.statement, revoked_registry
    )

    # Out-of-window key (revoked_at outside the declared window).
    expired = _FixtureKey(valid_until="2026-01-01")
    expired_registry = build_owner_provenance_key_registry([expired.record])
    expired_evidence = _signed_revocation(expired, record)
    assert "KEY_VALIDITY_WINDOW" in failures(
        expired_evidence.payload, expired_evidence.statement, expired_registry
    )

    # Foreign owner identity.
    foreign_identity = _FixtureKey(owner_identity="Someone Else")
    foreign_registry = build_owner_provenance_key_registry([foreign_identity.record])
    foreign_evidence = _signed_revocation(foreign_identity, record)
    assert "KEY_IDENTITY_BINDING" in failures(
        foreign_evidence.payload, foreign_evidence.statement, foreign_registry
    )

    # Cross-purpose replay: a decision signature cannot serve as a
    # revocation signature (domain separation breaks SIGNATURE_VERIFIED).
    _, decision_statement = _signed_submission(key)
    cross = build_owner_signed_revocation_statement(
        signature=base64.b64decode(decision_statement["signature_base64"]),
        key_id=key.key_id,
        payload=_revocation_payload(record),
    )
    assert "SIGNATURE_VERIFIED" in failures(_revocation_payload(record), cross, registry)

    # Tampered payload under an unchanged statement (content binding).
    good = _signed_revocation(key, record)
    tampered_payload = _revocation_payload(
        record, rationale="The owner withdraws this decision, actually."
    )
    assert "PAYLOAD_CONTENT_BINDING" in failures(
        tampered_payload, good.statement, registry
    )


def _supersession_payload(
    old_record: OwnerPolicyDecisionRecordV1,
    new_record: OwnerPolicyDecisionRecordV1,
    **overrides,
):
    payload = {
        "contract": "owner_signed_supersession_payload_v1",
        "superseded_decision_record_id": old_record.decision_record_id,
        "superseded_record_content_sha256": old_record.content_sha256,
        "superseding_decision_record_id": new_record.decision_record_id,
        "superseding_record_content_sha256": new_record.content_sha256,
        "target_profile_id": old_record.target_profile_id,
        "target_profile_sha256": old_record.target_profile_sha256,
        "superseded_by": OWNER_IDENTITY,
        "superseded_at": "2026-10-15",
        "rationale": "The renewed acceptance replaces the earlier record.",
        "source_revision": "c3b-test",
    }
    payload.update(overrides)
    return OwnerSupersessionPayloadV1.model_validate(payload)


def _second_accept_bundle(tmp_path: Path, key: _FixtureKey):
    *_, bundle = _capture(
        tmp_path,
        key,
        decision_bytes=canonical_json_bytes(
            _accept_payload(
                rationale="Renewed acceptance after re-reviewing the divergence window."
            )
        ),
    )
    return bundle


def test_signed_supersession_protocol_and_domain_separation(tmp_path):
    key = _FixtureKey()
    _, _, _, _, first_bundle = _capture(tmp_path, key)
    second_bundle = _second_accept_bundle(tmp_path, key)
    old_record, new_record = first_bundle.record, second_bundle.record
    assert new_record.decision_record_id != old_record.decision_record_id

    payload = _supersession_payload(old_record, new_record)
    statement = build_owner_signed_supersession_statement(
        signature=key.private.sign(owner_supersession_signature_message(payload)),
        key_id=key.key_id,
        payload=payload,
    )
    evidence = OwnerSignedSupersessionEvidenceV1(payload=payload, statement=statement)
    registry = build_owner_provenance_key_registry([key.record])

    dossier = verify_owner_supersession(
        payload=payload, statement=statement, registry=registry
    )
    assert dossier.verification_status == "VERIFIED"
    assert [check.name for check in dossier.checks] == list(
        REQUIRED_SUPERSESSION_CHECK_NAMES
    )

    # A revocation signature cannot serve as a supersession signature.
    cross = build_owner_signed_supersession_statement(
        signature=key.private.sign(
            owner_revocation_signature_message(_revocation_payload(old_record))
        ),
        key_id=key.key_id,
        payload=payload,
    )
    rejected = verify_owner_supersession(payload=payload, statement=cross, registry=registry)
    assert rejected.verification_status == "REJECTED"
    assert "SIGNATURE_VERIFIED" in [
        check.name for check in rejected.checks if not check.passed
    ]
    assert LIFECYCLE_REVOCATION_PURPOSE != LIFECYCLE_SUPERSESSION_PURPOSE
    assert evidence.statement.key_id == key.key_id


def test_authenticated_revocation_bindings_resolve_sets_fail_closed(tmp_path):
    key = _FixtureKey()
    _, _, _, _, accept_bundle = _capture(tmp_path, key)
    accept_record = accept_bundle.record
    reject_record = _unverified_reject_record()

    def resolve(**overrides):
        return resolve_owner_decision_authority(
            target_profile_id="strict-v2",
            target_profile_sha256=STRICT_V2_SHA256,
            records=[accept_record, reject_record],
            **overrides,
        )

    # Baseline: the set is CONFLICTING.
    assert resolve().resolved_state == "CONFLICTING"

    # An authenticated revocation of the dissenting REJECT resolves the set.
    resolved = resolve(
        authenticated_revocations=[_revocation_binding(reject_record)]
    )
    assert resolved.resolved_state == "ACCEPT_VERIFIED"
    assert resolved.authenticated_revoked_record_ids == [
        reject_record.decision_record_id
    ]

    # Wrong content-hash binding fails closed.
    with pytest.raises(Exception):
        resolve(
            authenticated_revocations=[
                _revocation_binding(
                    reject_record, revoked_record_content_sha256="0" * 64
                )
            ]
        )

    # Unknown record reference fails closed.
    with pytest.raises(Exception):
        resolve(
            authenticated_revocations=[
                _revocation_binding(
                    reject_record, revoked_decision_record_id="missing-id"
                )
            ]
        )

    # Cross-target binding fails closed.
    with pytest.raises(Exception):
        resolve(
            authenticated_revocations=[
                _revocation_binding(reject_record, target_profile_id="strict-v3")
            ]
        )


def test_authenticated_supersession_bindings_resolve_ambiguity(tmp_path):
    key = _FixtureKey()
    _, _, _, _, first_bundle = _capture(tmp_path, key)
    second_bundle = _second_accept_bundle(tmp_path, key)
    old_record, new_record = first_bundle.record, second_bundle.record

    def resolve(**overrides):
        return resolve_owner_decision_authority(
            target_profile_id="strict-v2",
            target_profile_sha256=STRICT_V2_SHA256,
            records=[old_record, new_record],
            **overrides,
        )

    assert resolve().resolved_state == "AMBIGUOUS"

    payload = _supersession_payload(old_record, new_record)
    binding = AuthenticatedSupersessionBindingV1.model_validate(
        {
            k: v
            for k, v in payload.model_dump(mode="json").items()
            if k
            not in ("contract", "rationale", "source_revision")
        }
    )
    resolved = resolve(authenticated_supersessions=[binding])
    assert resolved.resolved_state == "ACCEPT_VERIFIED"
    assert resolved.active_decision_record_id == new_record.decision_record_id
    assert resolved.authenticated_superseded_record_ids == [
        old_record.decision_record_id
    ]

    # Wrong content hash on either side fails closed.
    bad = AuthenticatedSupersessionBindingV1.model_validate(
        {
            **{
                k: v
                for k, v in payload.model_dump(mode="json").items()
                if k not in ("contract", "rationale", "source_revision")
            },
            "superseded_record_content_sha256": "0" * 64,
        }
    )
    with pytest.raises(Exception):
        resolve(authenticated_supersessions=[bad])

    # Two DISTINCT authenticated supersessions of the same record fail
    # closed (an exact duplicate binding collapses idempotently).
    *_, third_bundle = _capture(
        tmp_path,
        key,
        decision_bytes=canonical_json_bytes(
            _accept_payload(
                rationale="A third acceptance competing to replace the record."
            )
        ),
    )
    third_record = third_bundle.record
    second_binding = AuthenticatedSupersessionBindingV1.model_validate(
        {
            k: v
            for k, v in _supersession_payload(old_record, third_record)
            .model_dump(mode="json")
            .items()
            if k not in ("contract", "rationale", "source_revision")
        }
    )
    with pytest.raises(Exception):
        resolve(
            authenticated_supersessions=[binding, second_binding],
        )
    # An exact duplicate binding is idempotent, not a conflict.
    assert (
        resolve(authenticated_supersessions=[binding, binding]).resolved_state
        == "ACCEPT_VERIFIED"
    )


# ---------------------------------------------------------------------------
# 4. Plan boundary: fresh lifecycle verification only
# ---------------------------------------------------------------------------


def _plan(
    tmp_path: Path,
    *,
    records,
    signed_revocations=(),
    signed_supersessions=(),
    lifecycle_registry=None,
    authority_verifier=None,
    revocations=(),
):
    from turtle_value_engine.evolution.activation_plan import plan_profile_activation

    return plan_profile_activation(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        decision_records=records,
        revocations=list(revocations),
        policy_exceptions=[_policy_exception()],
        project_config_path=_write_project_config(tmp_path),
        authority_verifier=authority_verifier,
        signed_revocations=list(signed_revocations),
        signed_supersessions=list(signed_supersessions),
        lifecycle_trust_root=lifecycle_registry,
    )


def test_plan_signed_revocation_requires_trust_root_and_fresh_verification(
    tmp_path,
):
    key = _FixtureKey()
    decision_bytes, statement, _, _, accept_bundle = _capture(tmp_path, key)
    accept_record = accept_bundle.record
    reject_record = _unverified_reject_record()
    signed = _signed_revocation(key, reject_record)

    # Without a trust root the plan blocks; the statement is never trusted
    # just because it was supplied.
    plan = _plan(
        tmp_path,
        records=[accept_record, reject_record],
        signed_revocations=[signed],
    )
    assert plan.plan_state == "BLOCKED"
    assert "LIFECYCLE_TRUST_ROOT_REQUIRED" in plan.blockers

    # A forged signature under the real trust root is rejected by name.
    forged = _signed_revocation(_FixtureKey(), reject_record)
    plan_forged = _plan(
        tmp_path,
        records=[accept_record, reject_record],
        signed_revocations=[forged],
        lifecycle_registry=build_owner_provenance_key_registry([key.record]),
    )
    assert plan_forged.plan_state == "BLOCKED"
    assert any(
        item.startswith("SIGNED_REVOCATION_REJECTED:") for item in plan_forged.blockers
    )

    # A genuine signed revocation resolves the conflict; with the authority
    # verifier injected the plan reaches READY (execution still impossible).
    plan_ok = _plan(
        tmp_path,
        records=[accept_record, reject_record],
        signed_revocations=[signed],
        lifecycle_registry=build_owner_provenance_key_registry([key.record]),
        authority_verifier=SignedOwnerProvenanceVerifier(
            registry=build_owner_provenance_key_registry([key.record]),
            statement=statement,
            decision_input_bytes=decision_bytes,
        ),
    )
    assert plan_ok.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan_ok.authenticated_revoked_record_ids == [
        reject_record.decision_record_id
    ]
    assert plan_ok.execution_performed is False
    assert plan_ok.automatic_activation_allowed is False


def test_plan_unsigned_revocation_still_cannot_upgrade_authorization(tmp_path):
    from turtle_value_engine.evolution.owner_decision import (
        OwnerPolicyDecisionRevocationV1,
    )

    key = _FixtureKey()
    decision_bytes, statement, _, _, accept_bundle = _capture(tmp_path, key)
    accept_record = accept_bundle.record
    reject_record = _unverified_reject_record()
    forged_revocation = OwnerPolicyDecisionRevocationV1.build(
        revoked_decision_record_id=reject_record.decision_record_id,
        target_profile_id=reject_record.target_profile_id,
        target_profile_sha256=reject_record.target_profile_sha256,
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-15",
        rationale="An unsigned forged withdrawal of the dissenting reject.",
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3b-test",
            source_content_sha256=hashlib.sha256(b"unsigned").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            allowlist_matched=None,
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="captured",
        ),
    )
    plan = _plan(
        tmp_path,
        records=[accept_record, reject_record],
        revocations=[forged_revocation],
        authority_verifier=SignedOwnerProvenanceVerifier(
            registry=build_owner_provenance_key_registry([key.record]),
            statement=statement,
            decision_input_bytes=decision_bytes,
        ),
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_REVOCATION_AUTHORITY_UNVERIFIED" in plan.blockers


# ---------------------------------------------------------------------------
# 5. CLI end to end (real entrypoints)
# ---------------------------------------------------------------------------


def _cli(tmp_path, capsys, *argv):
    code = cli_module.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _write_public_key(tmp_path: Path, key: _FixtureKey, name: str) -> Path:
    path = tmp_path / name
    path.write_text(key.public_base64 + "\n", "utf-8")
    return path


def _exception_file(directory: Path) -> Path:
    path = directory / "exception.json"
    path.write_text(_policy_exception().model_dump_json(indent=2), "utf-8")
    return path


def test_cli_personal_research_walkthrough_to_ready_and_back(tmp_path, capsys):
    key = _FixtureKey()
    trust_root = tmp_path / "trust-root"
    evidence_root = tmp_path / "evidence"
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    exception_path = _exception_file(bundle_dir)

    # 1. Initialize the trust root with the owner's PUBLIC key only.
    code, out = _cli(
        tmp_path,
        capsys,
        "provenance",
        "registry",
        "init",
        "--trust-root",
        trust_root,
        "--public-key",
        _write_public_key(tmp_path, key, "owner.pub"),
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2026-12-31",
    )
    assert code == 0, out
    assert key.key_id in out

    # 2. Sign the exact canonical decision bytes outside the engine, then
    #    capture through the CLI: record VERIFIED + evidence bundle.
    decision_path = bundle_dir / "decision-input.json"
    statement_path = bundle_dir / "statement.json"
    record_path = bundle_dir / "record.json"
    decision_bytes, statement_payload = _signed_submission(key)
    decision_path.write_bytes(decision_bytes)
    statement_path.write_text(
        json.dumps(statement_payload, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    code, out = _cli(
        tmp_path,
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
    bundle_json = json.loads(out)["evidence_bundle"]
    bundle_path = Path(bundle_json["path"])
    assert bundle_path.name == "bundle.json"
    assert bundle_path.is_relative_to(evidence_root.resolve()) or bundle_path.exists()

    # 3. Offline evidence re-verification through the CLI.
    code, out = _cli(
        tmp_path, capsys, "provenance", "verify-evidence", "--bundle", bundle_path
    )
    assert code == 0, out
    assert "REPLAYS_BYTE_IDENTICAL" in out

    # 4. Plan from the captured evidence under the CURRENT trust root.
    project_config = _write_project_config(tmp_path)
    plan_path = tmp_path / "plan.json"
    code, out = _cli(
        tmp_path,
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
        bundle_path,
        "--output",
        plan_path,
    )
    assert code == 0, out
    plan = json.loads(plan_path.read_text("utf-8"))
    assert plan["plan_state"] == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan["authority_reverification_status"] == "REVERIFIED"
    assert plan["execution_performed"] is False

    # 5. Revoking the key in the trust root flips the plan back to blocked.
    code, out = _cli(
        tmp_path,
        capsys,
        "provenance",
        "registry",
        "revoke",
        "--trust-root",
        trust_root,
        "--key-id",
        key.key_id,
        "--reference",
        "testing revocation effect",
    )
    assert code == 0, out
    plan_path_2 = tmp_path / "plan-2.json"
    code, out = _cli(
        tmp_path,
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
        bundle_path,
        "--output",
        plan_path_2,
    )
    assert code == 1, out
    plan_2 = json.loads(plan_path_2.read_text("utf-8"))
    assert plan_2["plan_state"] == "BLOCKED"
    assert any(
        item.startswith("OWNER_AUTHORITY_REVERIFICATION")
        for item in plan_2["blockers"]
    )


def test_cli_record_decision_without_provenance_stays_unverified(tmp_path, capsys):
    decision_path = tmp_path / "decision-input.json"
    decision_path.write_bytes(_accept_bytes())
    record_path = tmp_path / "record.json"
    code, out = _cli(
        tmp_path,
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
        _exception_file(tmp_path),
        "--record-output",
        record_path,
    )
    assert code == 0, out
    record = json.loads(record_path.read_text("utf-8"))
    assert record["authority"]["authority_status"] == "OWNER_AUTHORITY_UNVERIFIED"


def test_cli_orphan_provenance_flags_fail_closed(tmp_path, capsys):
    decision_path = tmp_path / "decision-input.json"
    decision_path.write_bytes(_accept_bytes())
    statement_path = tmp_path / "statement.json"
    statement_path.write_text("{}", "utf-8")
    base_argv = [
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
        _exception_file(tmp_path),
        "--record-output",
        tmp_path / "record.json",
    ]

    # Statement without a trust root.
    code, out = _cli(
        tmp_path, capsys, *base_argv, "--signed-statement", statement_path
    )
    assert code == 2, out

    # Trust root without a statement.
    code, out = _cli(
        tmp_path, capsys, *base_argv, "--trust-root", tmp_path / "trust-root"
    )
    assert code == 2, out

    # Plan authority evidence without a trust root.
    code, out = _cli(
        tmp_path,
        capsys,
        "evolution",
        "plan-activation",
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--decision-record",
        tmp_path / "missing-record.json",
        "--project-config",
        _write_project_config(tmp_path),
        "--authority-evidence",
        tmp_path / "missing-bundle.json",
        "--output",
        tmp_path / "plan.json",
    )
    assert code == 2, out


def test_cli_trust_root_co_location_guards(tmp_path, capsys):
    key = _FixtureKey()
    # The whole "bundle" including a trust root inside it: the trust root
    # nested inside the submitted decision directory is refused.
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    trust_root = bundle_dir / "trust-root"
    code, out = _cli(
        tmp_path,
        capsys,
        "provenance",
        "registry",
        "init",
        "--trust-root",
        trust_root,
        "--public-key",
        _write_public_key(tmp_path, key, "owner.pub"),
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2026-12-31",
    )
    assert code == 0, out  # init itself is a deliberate trust decision

    decision_path = bundle_dir / "decision-input.json"
    decision_path.write_bytes(_accept_bytes())
    statement_path = bundle_dir / "statement.json"
    statement_path.write_text("{}", "utf-8")
    code, out = _cli(
        tmp_path,
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
        _exception_file(tmp_path),
        "--signed-statement",
        statement_path,
        "--trust-root",
        trust_root,
        "--record-output",
        tmp_path / "record.json",
    )
    assert code == 2, out
    assert "trust root" in out

    # A decision artifact stored inside the trust root is refused too.
    trust_root_isolated = tmp_path / "isolated-trust-root"
    code, out = _cli(
        tmp_path,
        capsys,
        "provenance",
        "registry",
        "init",
        "--trust-root",
        trust_root_isolated,
        "--public-key",
        _write_public_key(tmp_path, key, "owner.pub"),
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2026-12-31",
    )
    assert code == 0, out
    inside_decision = trust_root_isolated / "decision-input.json"
    inside_decision.write_bytes(_accept_bytes())
    code, out = _cli(
        tmp_path,
        capsys,
        "evolution",
        "record-decision",
        "--decision-input",
        inside_decision,
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        _exception_file(tmp_path),
        "--signed-statement",
        statement_path,
        "--trust-root",
        trust_root_isolated,
        "--record-output",
        tmp_path / "record.json",
    )
    assert code == 2, out


def test_cli_verify_evidence_exit_codes(tmp_path, capsys):
    key = _FixtureKey()
    decision_bytes, statement, snapshot, _, bundle = _capture(tmp_path, key)
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    bundle_path = evidence_root / bundle.bundle_id / "bundle.json"

    code, out = _cli(
        tmp_path, capsys, "provenance", "verify-evidence", "--bundle", bundle_path
    )
    assert code == 0, out

    (bundle_path.parent / "decision-input.json").write_bytes(
        canonical_json_bytes(_accept_payload(rationale="Tampered rationale text."))
    )
    code, out = _cli(
        tmp_path, capsys, "provenance", "verify-evidence", "--bundle", bundle_path
    )
    assert code == 1, out


def test_cli_provenance_registry_status_and_rotate(tmp_path, capsys):
    key1, key2 = _FixtureKey(), _FixtureKey()
    trust_root = tmp_path / "trust-root"
    _cli(
        tmp_path,
        capsys,
        "provenance",
        "registry",
        "init",
        "--trust-root",
        trust_root,
        "--public-key",
        _write_public_key(tmp_path, key1, "owner.pub"),
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2026-12-31",
    )
    code, out = _cli(
        tmp_path,
        capsys,
        "provenance",
        "registry",
        "rotate",
        "--trust-root",
        trust_root,
        "--old-key-id",
        key1.key_id,
        "--reference",
        "routine rotation",
        "--public-key",
        _write_public_key(tmp_path, key2, "owner2.pub"),
        "--owner-identity",
        OWNER_IDENTITY,
        "--valid-from",
        "2026-01-01",
        "--valid-until",
        "2027-12-31",
    )
    assert code == 0, out
    code, out = _cli(
        tmp_path, capsys, "provenance", "registry", "status", "--trust-root", trust_root
    )
    assert code == 0, out
    status = json.loads(out)
    assert status["sequence"] == 2
    assert status["key_count"] == 2
    revoked = [item for item in status["keys"] if item["revoked"]]
    assert len(revoked) == 1 and revoked[0]["key_id"] == key1.key_id


# ---------------------------------------------------------------------------
# 6. Schema drift parity, source discipline and published-byte preservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        (
            "owner-provenance-registry-snapshot.schema.json",
            OwnerProvenanceRegistrySnapshotV1,
        ),
        (
            "owner-provenance-evidence-bundle.schema.json",
            OwnerProvenanceEvidenceBundleV1,
        ),
    ],
)
def test_new_schemas_have_drift_parity(schema_name, model):
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == model.model_json_schema()


def test_lifecycle_schemas_have_drift_parity():
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerRevocationPayloadV1 as RevocationPayload,
    )
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerRevocationVerificationV1 as RevocationVerification,
    )
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerSignedRevocationStatementV1 as RevocationStatement,
    )
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerSignedSupersessionStatementV1 as SupersessionStatement,
    )
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerSupersessionPayloadV1 as SupersessionPayload,
    )
    from turtle_value_engine.evolution.owner_lifecycle import (
        OwnerSupersessionVerificationV1 as SupersessionVerification,
    )

    for name, model in (
        ("owner-revocation-payload", RevocationPayload),
        ("owner-signed-revocation-statement", RevocationStatement),
        ("owner-revocation-verification", RevocationVerification),
        ("owner-supersession-payload", SupersessionPayload),
        ("owner-signed-supersession-statement", SupersessionStatement),
        ("owner-supersession-verification", SupersessionVerification),
    ):
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema(), name


def test_lifecycle_verification_schemas_pin_the_check_sequence():
    for name, required in (
        ("owner-revocation-verification", REQUIRED_REVOCATION_CHECK_NAMES),
        ("owner-supersession-verification", REQUIRED_SUPERSESSION_CHECK_NAMES),
    ):
        schema = json.loads(
            (SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8")
        )
        checks = schema["properties"]["checks"]
        assert checks["items"] is False
        assert [
            item["properties"]["name"]["const"] for item in checks["prefixItems"]
        ] == list(required)


def test_resolver_and_plan_schemas_regenerated_with_authenticated_fields():
    from turtle_value_engine.evolution.owner_decision import (
        DecisionAuthorityResolutionV1,
    )

    resolution_schema = json.loads(
        (SCHEMAS / "owner-decision-authority-resolution.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert "authenticated_revoked_record_ids" in resolution_schema["properties"]
    assert "authenticated_superseded_record_ids" in resolution_schema["properties"]
    assert resolution_schema == DecisionAuthorityResolutionV1.model_json_schema()
    plan_schema = json.loads(
        (SCHEMAS / "profile-activation-plan.schema.json").read_text(encoding="utf-8")
    )
    assert "authenticated_revoked_record_ids" in plan_schema["properties"]
    assert plan_schema == ProfileActivationPlanV1.model_json_schema()


def test_no_private_key_material_or_env_trust_in_production_modules():
    for module in (
        "evolution/owner_trust_store.py",
        "evolution/owner_lifecycle.py",
        "evolution/owner_provenance.py",
    ):
        source = (ROOT / "src" / "turtle_value_engine" / module).read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "Ed25519PrivateKey",
            "generate_private_key",
            "os.environ",
            "getenv",
        ):
            assert forbidden not in source, (module, forbidden)


def test_cli_wiring_constructs_only_the_real_verifier():
    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    # The real verifier is wired at exactly the two authorized boundaries;
    # a verifier selector or trust bypass flag must not exist.  (The CLI
    # elsewhere resolves declared monitoring ENV references; nothing
    # environment-derived may influence provenance trust, pinned by the
    # module-level scan in the provenance tests plus the absence of any
    # trust-related environment lookup here.)
    assert source.count("SignedOwnerProvenanceVerifier(") == 2
    for forbidden in (
        "--verifier-kind",
        "--verifier",
        "trust=True",
        "TVE_TRUST",
        "TRUST_ROOT_ENV",
    ):
        assert forbidden not in source


def test_decision_artifacts_cannot_designate_a_trust_root():
    for model in (
        OwnerPolicyDecisionInputV1,
        build_owner_signed_decision_statement.__globals__[
            "OwnerSignedDecisionStatementV1"
        ],
        OwnerProvenanceEvidenceBundleV1,
    ):
        fields = set(model.model_json_schema()["properties"])
        assert not any(
            "path" in name or "trust" in name for name in fields
        ), fields


def test_published_bytes_and_default_profile_are_preserved():
    import tomllib

    assert (
        hashlib.sha256(BASE_PROFILE_PATH.read_bytes()).hexdigest()
        == "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"
    )
    assert hashlib.sha256(TARGET_PROFILE_PATH.read_bytes()).hexdigest() == STRICT_V2_SHA256
    assert (
        hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        == "604226f405fe03303e45f16e416b68ce4dd27b51f5db260095116e3b356f250d"
    )
    config = tomllib.loads(
        (ROOT / "config" / "project.example.toml").read_text(encoding="utf-8")
    )
    assert config["profiles"]["default"] == "strict-v1"
