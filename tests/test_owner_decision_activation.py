"""Phase 7-C2 focused regressions: owner decision records and activation plans.

Covers the accept/reject/unverified validation ladder, authority separation
(allowlist is not authentication; fake verifiers are test fixtures injected
through the library only), full-content-hash exception binding (altered
rationale with unchanged C1 exception id), stale audit/profile/manifest
bindings, duplicate/idempotent records, conflict/revocation/supersession
resolution, read-only activation plans with config inventory and rollback,
output guards, schema drift parity, socket-guarded offline execution,
published-byte/default-profile preservation and the absence of any
production fake-verifier escape hatch.
"""

import contextlib
import hashlib
import io
import json
import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine import load_normalized_input
from turtle_value_engine.cli import main
from turtle_value_engine.evolution.activation_plan import (
    ROLLBACK_EXCLUSIONS,
    ProfileActivationPlanV1,
    plan_profile_activation,
)
from turtle_value_engine.evolution.owner_decision import (
    REQUIRED_DECISION_VALIDATION_CHECKS,
    DecisionAuthorityResolutionV1,
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerDecisionError,
    OwnerDecisionVerifier,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
    OwnerPolicyDecisionRevocationV1,
    OwnerPolicyDecisionValidationV1,
    load_decision_record,
    load_decision_revocation,
    record_owner_decision_file,
    resolve_owner_decision_authority,
    validate_owner_decision,
)
from turtle_value_engine.evolution.profile_release import (
    VersionedProfileReleaseCandidateV1,
    _digest,
    _rules,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
    PolicyApprovalClaimV1,
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)

ROOT = Path(__file__).resolve().parents[1]
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
TARGET_PROFILE_PATH = ROOT / "rules" / "strict-v2.yaml"
MANIFEST_PATH = ROOT / "docs" / "releases" / "strict-v2" / "release-candidate.json"
BOUNDARY_PATH = ROOT / "fixtures" / "healthy_cash_cow.json"

STRICT_V1_SHA256 = "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"
STRICT_V2_SHA256 = "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
MANIFEST_CONTENT_SHA256 = (
    "c0d6cb5b60595c8eb67d45735fc8ef05a9a13b6db0f90bf3468f635ec99c61e8"
)
OWNER_IDENTITY = "Ryder Xie"

_boundary_input = None


def _boundary():
    global _boundary_input
    if _boundary_input is None:
        _boundary_input = load_normalized_input(BOUNDARY_PATH)
    return _boundary_input


class ScriptedOwnerVerifier(OwnerDecisionVerifier):
    """Test-fixture verifier: injected through the library boundary only."""

    kind = "scripted-test-verifier"

    def __init__(self, status: str = "OWNER_AUTHORITY_VERIFIED") -> None:
        self.status = status

    def verify_decision_authority(
        self,
        *,
        declared_owner_identity: str,
        provenance: DecisionProvenanceV1,
        decision_source_bytes: bytes,
    ) -> OwnerAuthorityAssessmentV1:
        return OwnerAuthorityAssessmentV1(
            authority_status=self.status,  # type: ignore[arg-type]
            verification_method="INJECTED_VERIFIER",
            verifier_kind=self.kind,
            allowlist_matched=True,
            reason_code="SCRIPTED_EVIDENCE_CONFIRMED",
            detail="Scripted test evidence; never selectable by the production CLI.",
            evidence_content_sha256=hashlib.sha256(decision_source_bytes).hexdigest(),
        )


def _manifest_payload() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


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


def _accept_input(
    *,
    exception: VersionedPolicyExceptionV1 | None = None,
    audit=None,
    owner: str = OWNER_IDENTITY,
    decided_at: str = "2026-10-13",
    rationale: str | None = None,
) -> tuple[OwnerPolicyDecisionInputV1, bytes]:
    if exception is None:
        exception = _policy_exception()
    if audit is None:
        audit = audit_profile_semantics(
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            boundary_input=_boundary(),
            policy_exceptions=[exception],
        )
    manifest = _manifest_payload()
    decision_input = OwnerPolicyDecisionInputV1(
        decision="ACCEPT_WITH_EXCEPTION",
        base_profile_id="strict-v1",
        base_profile_sha256=STRICT_V1_SHA256,
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        release_manifest_id=manifest["release_candidate_id"],
        release_manifest_content_sha256=MANIFEST_CONTENT_SHA256,
        audit_id=audit.audit_id,
        audit_content_sha256=audit.content_sha256,
        exception_id=exception.exception_id,
        exception_content_sha256=exception.content_sha256,
        rationale=rationale
        or "Accept the stricter 14% CDC gate as intended owner policy.",
        declared_owner_identity=owner,
        decided_at=decided_at,
        source_revision="test-note-1",
    )
    raw = json.dumps(
        decision_input.model_dump(mode="json"), indent=2, sort_keys=True
    ).encode("utf-8")
    return decision_input, raw


def _reject_input(**overrides) -> tuple[OwnerPolicyDecisionInputV1, bytes]:
    manifest = _manifest_payload()
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
    )
    payload = {
        "decision": "REJECT",
        "base_profile_id": "strict-v1",
        "base_profile_sha256": STRICT_V1_SHA256,
        "target_profile_id": "strict-v2",
        "target_profile_sha256": STRICT_V2_SHA256,
        "release_manifest_id": manifest["release_candidate_id"],
        "release_manifest_content_sha256": MANIFEST_CONTENT_SHA256,
        "audit_id": audit.audit_id,
        "audit_content_sha256": audit.content_sha256,
        "exception_id": None,
        "exception_content_sha256": None,
        "rationale": "Reject: keep strict-v1 default; strict-v3 must fix the bands.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-13",
        "source_revision": "test-note-1",
    }
    payload.update(overrides)
    decision_input = OwnerPolicyDecisionInputV1.model_validate(payload)
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return decision_input, raw


def _validate(decision_input, raw, **kwargs):
    parameters = {
        "decision_input": decision_input,
        "decision_source_bytes": raw,
        "base_profile_path": BASE_PROFILE_PATH,
        "target_profile_path": TARGET_PROFILE_PATH,
        "release_manifest_path": MANIFEST_PATH,
        "boundary_input": _boundary(),
    }
    if "policy_exceptions" not in kwargs:
        parameters["policy_exceptions"] = (
            [_policy_exception()]
            if decision_input.decision == "ACCEPT_WITH_EXCEPTION"
            else []
        )
    parameters.update(kwargs)
    return validate_owner_decision(**parameters)


def _record(**kwargs) -> OwnerPolicyDecisionRecordV1:
    verifier = kwargs.pop("verifier", ScriptedOwnerVerifier())
    allowlist = kwargs.pop("allowlist", [OWNER_IDENTITY])
    decision_input, raw = _accept_input()
    validation = _validate(
        decision_input, raw, verifier=verifier, owner_allowlist=allowlist, **kwargs
    )
    assert validation.state == "VALID", validation.blockers
    assert validation.record is not None
    return validation.record


def _run_cli(argv: list[str]) -> tuple[int, object, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    payload = None
    if stdout.getvalue().strip():
        try:
            payload = json.loads(stdout.getvalue())
        except json.JSONDecodeError:
            payload = None
    return code, payload, (stdout.getvalue().strip() or stderr.getvalue().strip())


def _rebuild_manifest_for_bytes(
    tmp_path: Path,
    target_bytes: bytes,
    rule_changes: list[dict],
) -> Path:
    """Self-consistent manifest binding the supplied target bytes (C1 helper)."""

    import yaml as yaml_module

    from turtle_value_engine.config.models import RuleProfile

    target_profile = RuleProfile.model_validate(yaml_module.safe_load(target_bytes))
    manifest = VersionedProfileReleaseCandidateV1.build(
        source_materialization_id="candidate-profile-materialization-test",
        source_materialization_content_sha256="a" * 64,
        evaluation_id="controlled-evolution-evaluation-test",
        evaluation_content_sha256="b" * 64,
        freeze_anchor_id="calibration-freeze-record-test",
        freeze_anchor_sha256="c" * 64,
        evidence_binding_id="calibration-evidence-binding-test",
        evidence_binding_sha256="d" * 64,
        experiment_id="calibration-experiment-test",
        experiment_content_sha256="e" * 64,
        proposal_id="candidate-profile-proposal-test",
        proposal_payload_sha256="f" * 64,
        base_profile_id="strict-v1",
        base_profile_sha256=STRICT_V1_SHA256,
        candidate_profile_id="candidate-profile-test",
        candidate_content_sha256="1" * 64,
        target_profile_id=target_profile.profile.id,
        intended_target_path=f"rules/{target_profile.profile.id}.yaml",
        release_profile_sha256=hashlib.sha256(target_bytes).hexdigest(),
        candidate_rule_payload_sha256=_digest(_rules(target_profile)),
        release_rule_payload_sha256=_digest(_rules(target_profile)),
        metadata_changes=[
            {
                "contract": "candidate_metadata_change_v1",
                "field": "id",
                "before": "candidate-profile-test",
                "after": target_profile.profile.id,
            }
        ],
        rule_changes=rule_changes,
    )
    path = tmp_path / f"{target_profile.profile.id}-manifest.json"
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# 1. Decision validation: accept / reject / authority separation
# --------------------------------------------------------------------------


def test_accept_fixture_is_valid_but_visibly_unverified_without_verifier():
    decision_input, raw = _accept_input()
    validation = _validate(decision_input, raw)

    assert validation.state == "VALID"
    assert validation.authority_status == "OWNER_AUTHORITY_UNVERIFIED"
    assert validation.fresh_audit_activation_readiness == "READY_FOR_POLICY_DECISION"
    assert validation.blockers == []
    assert validation.record is not None
    record = validation.record
    assert record.decision == "ACCEPT_WITH_EXCEPTION"
    assert record.authority.authority_status == "OWNER_AUTHORITY_UNVERIFIED"
    assert record.authority.verification_method == "NO_AUTHENTICATED_SOURCE"
    assert record.automatic_application_allowed is False
    assert record.decision_is_not_execution_request is True
    assert record.exception_id is not None
    assert record.exception_content_sha256 is not None


def test_verified_authority_requires_injected_verifier_and_allowlist():
    decision_input, raw = _accept_input()

    allowlisted_only = _validate(
        decision_input, raw, owner_allowlist=[OWNER_IDENTITY], verifier=None
    )
    assert allowlisted_only.state == "VALID"
    assert allowlisted_only.authority_status == "OWNER_AUTHORITY_UNVERIFIED"
    assert allowlisted_only.record.authority.allowlist_matched is True

    verified = _validate(
        decision_input,
        raw,
        owner_allowlist=[OWNER_IDENTITY],
        verifier=ScriptedOwnerVerifier(),
    )
    assert verified.state == "VALID"
    assert verified.authority_status == "OWNER_AUTHORITY_VERIFIED"
    assert verified.record.authority.verifier_kind == "scripted-test-verifier"


def test_reject_is_valid_and_terminal_without_exception():
    decision_input, raw = _reject_input()
    validation = _validate(decision_input, raw)

    assert validation.state == "VALID"
    assert validation.record.decision == "REJECT"
    assert validation.record.exception_id is None
    assert validation.fresh_audit_activation_readiness == "POLICY_DECISION_REQUIRED"


def test_reject_with_exception_binding_is_invalid_shape():
    exception = _policy_exception()
    with pytest.raises(Exception, match="terminal non-activation"):
        _reject_input(exception_id=exception.exception_id,
                      exception_content_sha256=exception.content_sha256)


def test_accept_without_exception_binding_is_invalid_shape():
    with pytest.raises(Exception, match="bind exactly one policy exception"):
        OwnerPolicyDecisionInputV1.model_validate(
            _reject_input()[0].model_dump(mode="json")
            | {"decision": "ACCEPT_WITH_EXCEPTION"}
        )


def test_wrong_owner_identity_is_blocked_by_allowlist():
    decision_input, raw = _accept_input(owner="someone-else")
    validation = _validate(decision_input, raw, owner_allowlist=[OWNER_IDENTITY])

    assert validation.state == "INVALID"
    assert "AUTHORITY:OWNER_IDENTITY_NOT_ALLOWLISTED" in validation.blockers
    assert validation.record is None


def test_forged_c1_approval_claim_is_not_a_decision_input():
    claim = PolicyApprovalClaimV1(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        decision="ACCEPTED",
        decided_by=OWNER_IDENTITY,
        decided_at="2026-10-13",
        rationale="forged claim reuse",
    )
    with pytest.raises(Exception):
        OwnerPolicyDecisionInputV1.model_validate(
            claim.model_dump(mode="json") | {"decision": "ACCEPT_WITH_EXCEPTION"}
        )


def test_stale_declared_audit_is_blocked_by_fresh_rerun():
    decision_input, raw = _accept_input(
        audit=audit_profile_semantics(
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            boundary_input=_boundary(),
        )
    )
    validation = _validate(decision_input, raw, policy_exceptions=[_policy_exception()])

    assert validation.state == "INVALID"
    assert "AUDIT_FRESH_AND_MATCHING:DECLARED_AUDIT_STALE" in validation.blockers


def test_stale_profile_binding_is_blocked():
    decision_input, raw = _accept_input()
    payload = json.loads(raw)
    payload["target_profile_sha256"] = "9" * 64
    tampered_input = OwnerPolicyDecisionInputV1.model_validate(payload)
    tampered_raw = json.dumps(payload, indent=2, sort_keys=True).encode()

    validation = _validate(
        tampered_input, tampered_raw, policy_exceptions=[_policy_exception()]
    )
    assert validation.state == "INVALID"
    assert "INPUT_BINDINGS_MATCH_BYTES:DECLARED_BINDINGS_STALE" in validation.blockers


def test_stale_manifest_binding_is_blocked(tmp_path):
    # A different but internally valid manifest: same target bytes, different
    # provenance identity, so the decision's declared manifest binding is
    # stale rather than unreadable.
    real_payload = _manifest_payload()
    different_manifest = _rebuild_manifest_for_bytes(
        tmp_path,
        TARGET_PROFILE_PATH.read_bytes(),
        rule_changes=[
            {
                "contract": "candidate_rule_leaf_change_v1",
                "target_key": change["target_key"],
                "profile_path": change["profile_path"],
                "before": change["before"],
                "after": change["after"],
            }
            for change in real_payload["rule_changes"]
        ],
    )
    different_payload = json.loads(different_manifest.read_text(encoding="utf-8"))
    assert different_payload["release_candidate_id"] != real_payload[
        "release_candidate_id"
    ]

    decision_input, raw = _accept_input()
    validation = validate_owner_decision(
        decision_input=decision_input,
        decision_source_bytes=raw,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=different_manifest,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation.state == "INVALID"
    assert "INPUT_BINDINGS_MATCH_BYTES:DECLARED_BINDINGS_STALE" in validation.blockers


def test_altered_exception_rationale_with_unchanged_id_is_blocked():
    bound_exception = _policy_exception()
    altered_exception = _policy_exception(
        rationale="Altered rationale keeping the identical C1 exception id."
    )
    assert altered_exception.exception_id == bound_exception.exception_id
    assert altered_exception.content_sha256 != bound_exception.content_sha256

    decision_input, raw = _accept_input(exception=bound_exception)
    validation = _validate(decision_input, raw, policy_exceptions=[altered_exception])

    assert validation.state == "INVALID"
    assert "EXCEPTION_BINDING_EXACT:EXCEPTION_BINDING_MISMATCH" in validation.blockers


def test_exception_binding_wrong_target_bytes_is_blocked():
    foreign_exception = VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256="9" * 64,
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale="Foreign exception binding different bytes must not cover.",
        declared_by=OWNER_IDENTITY,
    )
    decision_input, raw = _accept_input()
    validation = _validate(decision_input, raw, policy_exceptions=[foreign_exception])

    assert validation.state == "INVALID"
    assert "EXCEPTION_BINDING_EXACT:EXCEPTION_BINDING_MISMATCH" in validation.blockers


def test_unrelated_band_disorder_stays_uncovered_even_with_exact_binding(tmp_path):
    """C1-R1 regression inside the C2 decision boundary."""

    import yaml as yaml_module

    payload = yaml_module.safe_load(TARGET_PROFILE_PATH.read_bytes())
    payload["cdc"]["yield_bands"]["a"] = 0.20
    target_path = tmp_path / "strict-v2.yaml"
    target_path.write_text(
        yaml_module.safe_dump(payload, sort_keys=True), encoding="utf-8"
    )
    target_bytes = target_path.read_bytes()
    manifest_path = _rebuild_manifest_for_bytes(
        tmp_path,
        target_bytes,
        rule_changes=[
            {
                "contract": "candidate_rule_leaf_change_v1",
                "target_key": "cdc-yield-bands-pass",
                "profile_path": "cdc.yield_bands.pass",
                "before": 0.08,
                "after": 0.14,
            },
            {
                "contract": "candidate_rule_leaf_change_v1",
                "target_key": "cdc-yield-bands-a",
                "profile_path": "cdc.yield_bands.a",
                "before": 0.10,
                "after": 0.20,
            },
        ],
    )
    disorder_exception = VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256=hashlib.sha256(target_bytes).hexdigest(),
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale="Even a binding exception cannot cover arbitrary a/s disorder.",
        declared_by=OWNER_IDENTITY,
    )
    disorder_audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=_boundary(),
        policy_exceptions=[disorder_exception],
    )
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        {
            "decision": "ACCEPT_WITH_EXCEPTION",
            "base_profile_id": "strict-v1",
            "base_profile_sha256": STRICT_V1_SHA256,
            "target_profile_id": "strict-v2",
            "target_profile_sha256": hashlib.sha256(target_bytes).hexdigest(),
            "release_manifest_id": manifest_payload["release_candidate_id"],
            "release_manifest_content_sha256": manifest_payload["content_sha256"],
            "audit_id": disorder_audit.audit_id,
            "audit_content_sha256": disorder_audit.content_sha256,
            "exception_id": disorder_exception.exception_id,
            "exception_content_sha256": disorder_exception.content_sha256,
            "rationale": "Accept with exception over a disordered synthetic target.",
            "declared_owner_identity": OWNER_IDENTITY,
            "decided_at": "2026-10-13",
            "source_revision": "test-note-1",
        }
    )
    validation = validate_owner_decision(
        decision_input=decision_input,
        decision_source_bytes=b"disorder",
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=_boundary(),
        policy_exceptions=[disorder_exception],
    )
    assert validation.state == "INVALID"
    assert (
        "EXCEPTION_COVERS_ALL_FINDINGS:UNCOVERED_FINDINGS_REMAIN" in validation.blockers
    )
    assert validation.fresh_audit_activation_readiness == "POLICY_DECISION_REQUIRED"


def test_provenance_binds_submitted_bytes():
    decision_input, raw = _accept_input()
    validation = _validate(decision_input, raw)
    record = validation.record

    assert record.provenance.source_kind == "LOCAL_UNSIGNED_JSON"
    assert record.provenance.source_revision == "test-note-1"
    assert record.provenance.source_content_sha256 == hashlib.sha256(raw).hexdigest()


# --------------------------------------------------------------------------
# 2. Record-set resolution: duplicates, conflicts, revocation, supersession
# --------------------------------------------------------------------------


def test_record_write_is_create_only_and_idempotent(tmp_path):
    record = _record()
    output = tmp_path / "decision.json"

    assert record_owner_decision_file(record, output) == "CREATED"
    first_bytes = output.read_bytes()
    assert record_owner_decision_file(record, output) == "IDEMPOTENT"
    assert output.read_bytes() == first_bytes

    other_input, other_raw = _accept_input(rationale="A second distinct acceptance.")
    other = _validate(other_input, other_raw).record
    with pytest.raises(OwnerDecisionError, match="immutable"):
        record_owner_decision_file(other, output)


def test_tampered_record_file_fails_to_load(tmp_path):
    record = _record()
    output = tmp_path / "decision.json"
    record_owner_decision_file(record, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["rationale"] = "silently rewritten rationale"
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OwnerDecisionError, match="not a valid"):
        load_decision_record(output)


def test_duplicate_records_collapse_in_resolution():
    first = _record()
    second = _record()
    assert first == second

    resolution = resolve_owner_decision_authority(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        records=[first, second],
    )
    assert resolution.resolved_state == "ACCEPT_VERIFIED"
    assert resolution.active_decision_record_id == first.decision_record_id


def test_conflicting_accept_and_reject_is_terminal_conflict():
    accept = _record()
    reject_input, reject_raw = _reject_input()
    reject = _validate(reject_input, reject_raw).record

    resolution = resolve_owner_decision_authority(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        records=[accept, reject],
    )
    assert resolution.resolved_state == "CONFLICTING"
    assert "CONFLICTING_DECISIONS" in resolution.blockers
    assert resolution.active_decision_record_id is None


def test_two_distinct_acceptances_are_ambiguous_not_newest_wins():
    first_input, first_raw = _accept_input(decided_at="2026-10-12")
    first = _validate(first_input, first_raw).record
    second_input, second_raw = _accept_input(decided_at="2026-10-13")
    second = _validate(second_input, second_raw).record

    resolution = resolve_owner_decision_authority(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        records=[first, second],
    )
    assert resolution.resolved_state == "AMBIGUOUS"
    assert "AMBIGUOUS_MULTIPLE_ACTIVE_RECORDS" in resolution.blockers


def _build_revocation(record: OwnerPolicyDecisionRecordV1) -> OwnerPolicyDecisionRevocationV1:
    return OwnerPolicyDecisionRevocationV1.build(
        revoked_decision_record_id=record.decision_record_id,
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-14",
        rationale="Withdrawing the earlier acceptance pending a strict-v3 fix.",
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="test-note-2",
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="offline revocation stays unverified",
        ),
    )


def test_revocation_removes_record_and_is_reported(tmp_path):
    record = _record()
    revocation = _build_revocation(record)

    # The revocation file round-trips through the fail-closed loader.
    revocation_path = tmp_path / "revocation.json"
    revocation_path.write_text(
        json.dumps(revocation.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    reloaded = load_decision_revocation(revocation_path)
    assert reloaded == revocation

    resolution = resolve_owner_decision_authority(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        records=[record],
        revocations=[revocation],
    )
    assert resolution.resolved_state == "NO_DECISION"
    assert "ALL_CURRENT_RECORDS_REVOKED" in resolution.blockers
    assert resolution.revoked_record_ids == [record.decision_record_id]

    tampered = json.loads(revocation_path.read_text(encoding="utf-8"))
    tampered["rationale"] = "silently rewritten revocation rationale"
    revocation_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(OwnerDecisionError, match="not a valid"):
        load_decision_revocation(revocation_path)


def test_revocation_of_unknown_record_fails_closed():
    record = _record()
    revocation = OwnerPolicyDecisionRevocationV1.build(
        revoked_decision_record_id="owner-policy-decision-nonexistent",
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-14",
        rationale="Revocation pointing at a record that was never supplied.",
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="test-note-2",
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="offline revocation stays unverified",
        ),
    )
    with pytest.raises(OwnerDecisionError, match="unknown decision record"):
        resolve_owner_decision_authority(
            target_profile_id="strict-v2",
            target_profile_sha256=STRICT_V2_SHA256,
            records=[record],
            revocations=[revocation],
        )


def test_supersession_resolves_to_the_correcting_record():
    reject_input, reject_raw = _reject_input()
    reject = _validate(reject_input, reject_raw).record
    accept_input, accept_raw = _accept_input()
    accept = validate_owner_decision(
        decision_input=accept_input,
        decision_source_bytes=accept_raw,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
        supersedes_decision_record_id=reject.decision_record_id,
    ).record

    resolution = resolve_owner_decision_authority(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        records=[reject, accept],
    )
    assert resolution.resolved_state == "ACCEPT_UNVERIFIED"
    assert resolution.superseded_record_ids == [reject.decision_record_id]
    assert resolution.active_decision_record_id == accept.decision_record_id


def test_double_supersession_fails_closed():
    reject_input, reject_raw = _reject_input()
    reject = _validate(reject_input, reject_raw).record
    accepts = []
    for decided_at in ("2026-10-14", "2026-10-15"):
        accept_input, accept_raw = _accept_input(decided_at=decided_at)
        accepts.append(
            validate_owner_decision(
                decision_input=accept_input,
                decision_source_bytes=accept_raw,
                base_profile_path=BASE_PROFILE_PATH,
                target_profile_path=TARGET_PROFILE_PATH,
                release_manifest_path=MANIFEST_PATH,
                boundary_input=_boundary(),
                policy_exceptions=[_policy_exception()],
                supersedes_decision_record_id=reject.decision_record_id,
            ).record
        )
    with pytest.raises(OwnerDecisionError, match="supersede the same"):
        resolve_owner_decision_authority(
            target_profile_id="strict-v2",
            target_profile_sha256=STRICT_V2_SHA256,
            records=[reject, *accepts],
        )


def test_stale_records_are_reported_not_silently_discarded():
    record = _record()
    resolution = resolve_owner_decision_authority(
        target_profile_id="strict-v2",
        target_profile_sha256="9" * 64,
        records=[record],
    )
    assert resolution.resolved_state == "NO_DECISION"
    assert resolution.stale_record_ids == [record.decision_record_id]
    assert "ALL_RECORDS_STALE" in resolution.blockers


# --------------------------------------------------------------------------
# 3. Activation planning: readiness ladder, config inventory, rollback
# --------------------------------------------------------------------------


def _write_project_config(tmp_path: Path, default: str) -> Path:
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


def _write_watchlist(tmp_path: Path, profile_id: str, name: str) -> Path:
    from turtle_value_engine.monitoring import WatchlistSpecV1

    watchlist = WatchlistSpecV1.build(
        watchlist_id="test-watchlist",
        profile_id=profile_id,
        entries=[
            {
                "listing_id": "SH600519",
                "company_display_name": "Fixture",
                "enabled": True,
            }
        ],
    )
    path = tmp_path / name
    path.write_text(
        json.dumps(watchlist.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_backtest_manifest(tmp_path: Path, name: str) -> Path:
    from turtle_value_engine.backtest import (
        HistoricalDecisionArtifact,
        ListingLifecycle,
        Market,
        UniverseCoverage,
        build_dataset_manifest,
    )

    normalized = _boundary()
    listing = normalized.company.primary_listing
    lifecycle = ListingLifecycle(
        listing_id=listing,
        company_id="economic-company-1",
        economic_company_id="economic-company-1",
        market=Market.A,
        currency="CNY",
        listing_date=date(2020, 1, 1),
        terminal_status="ACTIVE",
        trading_calendar="cal",
        timezone="Asia/Shanghai",
        sector="consumer",
    )
    artifact = HistoricalDecisionArtifact(
        artifact_id="artifact-1",
        listing_id=listing,
        decision_time=datetime(2026, 9, 9, tzinfo=UTC),
        as_of=normalized.as_of,
        available_at=datetime(2026, 9, 9, tzinfo=UTC),
        normalized_input=normalized,
        source_hash="a" * 64,
    )
    manifest = build_dataset_manifest(
        dataset_id="dataset-c2",
        dataset_version="1",
        start_date=date(2025, 1, 1),
        end_date=date(2026, 9, 10),
        calendar_id="cal",
        universe_id="u1",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[lifecycle],
        decision_artifacts=[artifact],
    )
    path = tmp_path / name
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_surface_snapshot(tmp_path: Path, name: str) -> Path:
    from turtle_value_engine.pipeline import run_analyze
    from turtle_value_engine.surface import build_research_surface_snapshot

    snapshot = build_research_surface_snapshot(run_analyze(_boundary()))
    path = tmp_path / name
    path.write_text(
        json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _plan(tmp_path: Path, *, records, exceptions=None, default="strict-v1", **kwargs):
    parameters = {
        "base_profile_path": BASE_PROFILE_PATH,
        "target_profile_path": TARGET_PROFILE_PATH,
        "release_manifest_path": MANIFEST_PATH,
        "boundary_input": _boundary(),
        "decision_records": records,
        "policy_exceptions": (
            exceptions if exceptions is not None else [_policy_exception()]
        ),
        "project_config_path": _write_project_config(tmp_path, default),
    }
    parameters.update(kwargs)
    return plan_profile_activation(**parameters)


def test_plan_without_decision_is_blocked_and_policy_gated(tmp_path):
    plan = _plan(tmp_path, records=[])
    assert plan.plan_state == "BLOCKED"
    assert "NO_OWNER_DECISION_RECORD" in plan.blockers
    assert plan.execution_performed is False
    assert plan.automatic_activation_allowed is False
    assert plan.decision is None
    # The default profile stays strict-v1 even after planning.
    from turtle_value_engine.config import load_profile

    assert load_profile().profile.id == "strict-v1"


def test_plan_with_unverified_accept_is_blocked(tmp_path):
    record = _record(verifier=None, allowlist=None)
    plan = _plan(tmp_path, records=[record])
    assert plan.plan_state == "BLOCKED"
    assert plan.blockers == ["OWNER_AUTHORITY_UNVERIFIED"]
    assert plan.decision_authority_state == "ACCEPT_UNVERIFIED"


def test_plan_with_reject_is_terminal_blocked(tmp_path):
    reject_input, reject_raw = _reject_input()
    reject = _validate(reject_input, reject_raw).record
    plan = _plan(tmp_path, records=[reject], exceptions=[])
    assert plan.plan_state == "BLOCKED"
    assert "DECISION_IS_REJECT" in plan.blockers
    assert "AUDIT_NOT_READY" in plan.blockers


def test_verified_accept_with_compatible_config_is_ready(tmp_path):
    record = _record()
    watchlist = _write_watchlist(tmp_path, "strict-v1", "watchlist.json")
    plan = _plan(
        tmp_path,
        records=[record],
        watchlist_paths=[watchlist],
        authority_verifier=ScriptedOwnerVerifier(),
    )

    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan.blockers == []
    assert plan.execution_performed is False
    assert plan.automatic_activation_allowed is False
    assert plan.verified_decision_is_not_execution_request is True
    assert plan.audit_activation_readiness == "READY_FOR_POLICY_DECISION"
    assert plan.decision_record_id == record.decision_record_id
    compatibility = {
        item.kind: item.compatibility for item in plan.config_inventory
    }
    assert compatibility["PROJECT_DEFAULT_PROFILE"] == "PROPOSED_MUTATION"
    assert compatibility["WATCHLIST"] == "BASE_PINNED_PRESERVED"


def test_ready_plan_requires_the_bound_exception_file(tmp_path):
    record = _record()
    plan = _plan(
        tmp_path,
        records=[record],
        exceptions=[],
        authority_verifier=ScriptedOwnerVerifier(),
    )
    assert plan.plan_state == "BLOCKED"
    assert "DECISION_EXCEPTION_BINDING_STALE" in plan.blockers
    assert "AUDIT_NOT_READY" in plan.blockers


def test_incompatible_and_missing_project_config_block(tmp_path):
    record = _record()
    foreign = _plan(tmp_path, records=[record], default="strict-v3")
    assert "DEFAULT_NOT_BASE" in foreign.blockers

    already = _plan(tmp_path, records=[record], default="strict-v2")
    assert "DEFAULT_ALREADY_TARGET" in already.blockers

    missing = _plan(
        tmp_path,
        records=[record],
        project_config_path=tmp_path / "absent.toml",
    )
    assert "PROJECT_CONFIG_MISSING" in missing.blockers

    unreadable = tmp_path / "broken.toml"
    unreadable.write_text("not [ valid toml", encoding="utf-8")
    broken = _plan(tmp_path, records=[record], project_config_path=unreadable)
    assert "PROJECT_CONFIG_UNREADABLE" in broken.blockers


def test_watchlist_foreign_and_missing_references_block(tmp_path):
    record = _record()
    foreign_watchlist = _write_watchlist(
        tmp_path, "strict-v9", "watchlist-foreign.json"
    )
    plan = _plan(tmp_path, records=[record], watchlist_paths=[foreign_watchlist])
    assert "FOREIGN_PROFILE_REFERENCE" in plan.blockers
    foreign_entry = next(
        item
        for item in plan.config_inventory
        if item.kind == "WATCHLIST" and item.compatibility == "FOREIGN"
    )
    assert "never rewritten" in foreign_entry.detail

    missing_watchlist = tmp_path / "absent-watchlist.json"
    plan = _plan(tmp_path, records=[record], watchlist_paths=[missing_watchlist])
    assert "MISSING_REFERENCE" in plan.blockers


def test_historical_artifact_inventory_preserves_and_labels(tmp_path):
    record = _record()
    manifest = _write_backtest_manifest(tmp_path, "backtest.json")
    surface = _write_surface_snapshot(tmp_path, "surface.json")
    watchlist = _write_watchlist(tmp_path, "strict-v1", "watchlist.json")
    runner = tmp_path / "runner.json"
    runner.write_text(
        json.dumps(
            {
                "contract": "monitoring_runner_config_v1",
                "schema_version": "1.0.0",
                "runner_id": "test-runner",
                "watchlist_path": "watchlist.json",
                "monitoring_workspace_root": "ws",
                "reanalysis_job_root": "jobs",
                "cycle_store_root": "cycles",
                "runner_root": "runner",
                "cache_dir": "cache",
                "network_allowed": False,
                "offline_replay": True,
                "window_days": 7,
            }
        ),
        encoding="utf-8",
    )

    plan = _plan(
        tmp_path,
        records=[record],
        backtest_manifest_paths=[manifest],
        surface_snapshot_paths=[surface],
        runner_config_paths=[runner],
        watchlist_paths=[watchlist],
        normalized_input_paths=[BOUNDARY_PATH],
        authority_verifier=ScriptedOwnerVerifier(),
    )
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    by_kind = {item.kind: item for item in plan.config_inventory}
    assert by_kind["BACKTEST_DATASET_MANIFEST"].compatibility == "BASE_PINNED_PRESERVED"
    assert by_kind["BACKTEST_DATASET_MANIFEST"].profile_references == ["strict-v1"]
    assert by_kind["SURFACE_SNAPSHOT"].compatibility == "BASE_PINNED_PRESERVED"
    assert by_kind["SURFACE_SNAPSHOT"].profile_references == ["strict-v1"]
    assert by_kind["NORMALIZED_INPUT"].compatibility == "BASE_PINNED_PRESERVED"
    assert by_kind["MONITORING_RUNNER_CONFIG"].compatibility == "NOT_PROFILE_SCOPED"
    assert by_kind["MONITORING_RUNNER_CONFIG"].blocker_code is None


def test_inventory_unreadable_references_block(tmp_path):
    record = _record()
    broken = tmp_path / "broken-watchlist.json"
    broken.write_text("{ not json", encoding="utf-8")
    plan = _plan(tmp_path, records=[record], watchlist_paths=[broken])
    assert "UNREADABLE_REFERENCE" in plan.blockers


def test_rollback_plan_binds_prior_bytes_and_excludes_replay(tmp_path):
    record = _record()
    config = _write_project_config(tmp_path, "strict-v1")
    plan = _plan(tmp_path, records=[record])

    assert plan.rollback.prior_project_config_path == str(config)
    assert (
        plan.rollback.prior_project_config_sha256
        == hashlib.sha256(config.read_bytes()).hexdigest()
    )
    assert plan.rollback.prior_default_profile == "strict-v1"
    assert plan.rollback.exclusions == list(ROLLBACK_EXCLUSIONS)
    assert any("restore" in step for step in plan.rollback.restoration_steps)
    assert "strict-v1" in plan.rollback.expected_current_state


def test_plan_is_deterministic_and_repeat_runs_are_identical(tmp_path):
    record = _record()
    first = _plan(tmp_path, records=[record])
    second = _plan(tmp_path, records=[record])
    assert first == second
    assert first.plan_id == second.plan_id
    assert first.content_sha256 == second.content_sha256


# --------------------------------------------------------------------------
# 4. CLI boundary: exit codes, guards, no verifier escape hatch, offline
# --------------------------------------------------------------------------


def _record_decision_argv(
    tmp_path: Path,
    decision_input: Path,
    *,
    exception: Path | None,
    record_output: Path,
    output: Path | None = None,
    allowlist: Path | None = None,
) -> list[str]:
    argv = [
        "evolution",
        "record-decision",
        "--decision-input",
        str(decision_input),
        "--base-profile",
        str(BASE_PROFILE_PATH),
        "--target-profile",
        str(TARGET_PROFILE_PATH),
        "--release-manifest",
        str(MANIFEST_PATH),
        "--boundary-input",
        str(BOUNDARY_PATH),
        "--record-output",
        str(record_output),
    ]
    if exception is not None:
        argv.extend(["--policy-exception", str(exception)])
    if allowlist is not None:
        argv.extend(["--owner-allowlist", str(allowlist)])
    if output is not None:
        argv.extend(["--output", str(output)])
    return argv


def _write_decision_input_file(
    tmp_path: Path,
    decision_input: OwnerPolicyDecisionInputV1,
    name: str = "decision-input.json",
) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(decision_input.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_exception_file(
    tmp_path: Path, exception: VersionedPolicyExceptionV1
) -> Path:
    path = tmp_path / "exception.json"
    path.write_text(
        json.dumps(exception.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_cli_records_valid_unverified_decision_and_is_idempotent(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_output = tmp_path / "decision-record.json"
    validation_output = tmp_path / "validation.json"

    code, payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path,
            decision_path,
            exception=exception_path,
            record_output=record_output,
            output=validation_output,
        )
    )
    assert code == 0
    assert payload["state"] == "VALID"
    assert payload["authority_status"] == "OWNER_AUTHORITY_UNVERIFIED"
    persisted_record = json.loads(record_output.read_text(encoding="utf-8"))
    assert persisted_record["decision"] == "ACCEPT_WITH_EXCEPTION"
    assert persisted_record["authority"]["authority_status"] == (
        "OWNER_AUTHORITY_UNVERIFIED"
    )
    assert json.loads(validation_output.read_text(encoding="utf-8"))["state"] == "VALID"

    first_bytes = record_output.read_bytes()
    code, payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path,
            decision_path,
            exception=exception_path,
            record_output=record_output,
        )
    )
    assert code == 0
    assert record_output.read_bytes() == first_bytes


def test_cli_invalid_decision_exits_one_and_writes_no_record(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps(["someone-else"]), encoding="utf-8")
    record_output = tmp_path / "decision-record.json"

    code, payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path,
            decision_path,
            exception=_write_exception_file(tmp_path, exception),
            record_output=record_output,
            allowlist=allowlist,
        )
    )
    assert code == 1
    assert payload["state"] == "INVALID"
    assert "AUTHORITY:OWNER_IDENTITY_NOT_ALLOWLISTED" in payload["blockers"]
    assert not record_output.exists()


def test_cli_stale_audit_exits_one(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(
        exception=exception,
        audit=audit_profile_semantics(
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            boundary_input=_boundary(),
        ),
    )
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    record_output = tmp_path / "decision-record.json"
    code, payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path,
            decision_path,
            exception=_write_exception_file(tmp_path, exception),
            record_output=record_output,
        )
    )
    assert code == 1
    assert "AUDIT_FRESH_AND_MATCHING:DECLARED_AUDIT_STALE" in payload["blockers"]
    assert not record_output.exists()


def test_cli_output_guards(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)

    # overwrite a supplied input
    code, _payload, text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=decision_path
        )
    )
    assert code == 2
    assert "decision-input" in text

    # symlink output
    symlink = tmp_path / "record-symlink.json"
    symlink.symlink_to(tmp_path / "target.json")
    code, _payload, text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=symlink
        )
    )
    assert code == 2
    assert "symlink" in text

    # published directory
    published = ROOT / "rules" / "c2-record.json"
    code, _payload, text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=published
        )
    )
    assert code == 2
    assert "published artifact directories" in text
    assert not published.exists()


def test_cli_record_refuses_overwriting_different_record(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_output = tmp_path / "decision-record.json"

    code, _payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=record_output
        )
    )
    assert code == 0

    other_input, _other_raw = _accept_input(
        exception=exception, rationale="A second distinct acceptance rationale."
    )
    other_path = _write_decision_input_file(tmp_path, other_input, "decision-2.json")
    code, _payload, text = _run_cli(
        _record_decision_argv(
            tmp_path, other_path, exception=exception_path, record_output=record_output
        )
    )
    assert code == 2
    assert "different decision record already exists" in text


def _plan_argv(
    tmp_path: Path,
    record_path: Path,
    output: Path,
    *,
    exception: Path | None = None,
    config: Path | None = None,
) -> list[str]:
    argv = [
        "evolution",
        "plan-activation",
        "--base-profile",
        str(BASE_PROFILE_PATH),
        "--target-profile",
        str(TARGET_PROFILE_PATH),
        "--release-manifest",
        str(MANIFEST_PATH),
        "--boundary-input",
        str(BOUNDARY_PATH),
        "--decision-record",
        str(record_path),
        "--project-config",
        str(config if config is not None else _write_project_config(tmp_path, "strict-v1")),
        "--output",
        str(output),
    ]
    if exception is not None:
        argv.extend(["--policy-exception", str(exception)])
    return argv


def test_cli_plan_blocked_exit_one_persists_plan(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_path = tmp_path / "decision-record.json"
    code, _payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=record_path
        )
    )
    assert code == 0

    plan_output = tmp_path / "plan.json"
    code, payload, _text = _run_cli(
        _plan_argv(tmp_path, record_path, plan_output, exception=exception_path)
    )
    assert code == 1
    assert payload["plan_state"] == "BLOCKED"
    assert payload["blockers"] == ["OWNER_AUTHORITY_UNVERIFIED"]
    assert payload["execution_performed"] is False
    persisted = json.loads(plan_output.read_text(encoding="utf-8"))
    assert persisted["plan_id"] == payload["plan_id"]

    # identical rerun is idempotent
    code, payload_again, _text = _run_cli(
        _plan_argv(tmp_path, record_path, plan_output, exception=exception_path)
    )
    assert code == 1
    assert payload_again["plan_id"] == payload["plan_id"]
    assert plan_output.read_bytes() == (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def test_cli_plan_tampered_record_exits_two(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_path = tmp_path / "decision-record.json"
    code, _payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=record_path
        )
    )
    assert code == 0

    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["rationale"] = "silently rewritten"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    code, _payload, text = _run_cli(
        _plan_argv(
            tmp_path, record_path, tmp_path / "plan.json", exception=exception_path
        )
    )
    assert code == 2
    assert "not a valid owner_policy_decision_record_v1" in text


def test_cli_plan_consumes_revocation_file(tmp_path):
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_path = tmp_path / "decision-record.json"
    code, _payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=record_path
        )
    )
    assert code == 0
    record = load_decision_record(record_path)

    revocation_path = tmp_path / "revocation.json"
    revocation_path.write_text(
        json.dumps(
            _build_revocation(record).model_dump(mode="json"), indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    plan_output = tmp_path / "plan.json"
    argv = _plan_argv(tmp_path, record_path, plan_output, exception=exception_path)
    argv.extend(["--revocation", str(revocation_path)])
    code, payload, _text = _run_cli(argv)
    assert code == 1
    assert "ALL_CURRENT_DECISIONS_REVOKED" in payload["blockers"]
    assert payload["decision_authority_state"] == "NO_DECISION"


def test_cli_dossier_generates_chinese_material(tmp_path):
    exception = _policy_exception()
    exception_path = _write_exception_file(tmp_path, exception)
    output = tmp_path / "dossier.md"
    code, payload, _text = _run_cli(
        [
            "evolution",
            "decision-dossier",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(TARGET_PROFILE_PATH),
            "--release-manifest",
            str(MANIFEST_PATH),
            "--boundary-input",
            str(BOUNDARY_PATH),
            "--policy-exception",
            str(exception_path),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert payload["status"] == "generated"
    text = output.read_text(encoding="utf-8")
    assert "所有者政策决策材料" in text
    assert STRICT_V1_SHA256 in text
    assert STRICT_V2_SHA256 in text
    assert MANIFEST_CONTENT_SHA256 in text
    assert "13.00%" in text
    assert "[8.00%, 14.00%)" in text
    assert "EXTREME_SAFETY" in text and "WATCH" in text
    assert "合成边界证据" in text

    # deterministic regeneration is idempotent
    code, second_payload, _text = _run_cli(
        [
            "evolution",
            "decision-dossier",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(TARGET_PROFILE_PATH),
            "--release-manifest",
            str(MANIFEST_PATH),
            "--boundary-input",
            str(BOUNDARY_PATH),
            "--policy-exception",
            str(exception_path),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert second_payload["dossier_sha256"] == payload["dossier_sha256"]


def test_cli_has_no_verifier_escape_hatch():
    from turtle_value_engine import cli as cli_module

    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    # Since Phase 7-C3-B the CLI may construct exactly the REAL
    # SignedOwnerProvenanceVerifier from explicit operator inputs
    # (--signed-statement + --trust-root); the default flow still passes no
    # verifier, no selector exists, and no fake verifier is reachable.
    assert "verifier = None" in source  # default flow passes no verifier
    assert source.count("SignedOwnerProvenanceVerifier(") == 2
    for forbidden in ("--verifier", "--fake-verifier", "--scripted-verifier"):
        assert forbidden not in source
    assert not hasattr(cli_module, "ScriptedOwnerVerifier")


def test_cli_commands_construct_no_socket(tmp_path, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("Phase 7-C2 CLI constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_path = tmp_path / "decision-record.json"
    code, payload, _text = _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=record_path
        )
    )
    assert code == 0
    assert payload["contract"] == "owner_policy_decision_validation_v1"

    plan_path = tmp_path / "plan.json"
    code, payload, _text = _run_cli(
        _plan_argv(tmp_path, record_path, plan_path, exception=exception_path)
    )
    assert code == 1
    assert payload["contract"] == "profile_activation_plan_v1"

    dossier_path = tmp_path / "dossier.md"
    code, payload, _text = _run_cli(
        [
            "evolution",
            "decision-dossier",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(TARGET_PROFILE_PATH),
            "--release-manifest",
            str(MANIFEST_PATH),
            "--boundary-input",
            str(BOUNDARY_PATH),
            "--output",
            str(dossier_path),
        ]
    )
    assert code == 0
    assert payload["status"] == "generated"


def test_published_bytes_and_default_unchanged_after_cli(tmp_path):
    before = (
        BASE_PROFILE_PATH.read_bytes(),
        TARGET_PROFILE_PATH.read_bytes(),
        MANIFEST_PATH.read_bytes(),
    )
    exception = _policy_exception()
    decision_input, _raw = _accept_input(exception=exception)
    decision_path = _write_decision_input_file(tmp_path, decision_input)
    exception_path = _write_exception_file(tmp_path, exception)
    record_path = tmp_path / "decision-record.json"
    _run_cli(
        _record_decision_argv(
            tmp_path, decision_path, exception=exception_path, record_output=record_path
        )
    )
    _run_cli(
        _plan_argv(
            tmp_path, record_path, tmp_path / "plan.json", exception=exception_path
        )
    )
    _run_cli(
        [
            "evolution",
            "decision-dossier",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(TARGET_PROFILE_PATH),
            "--release-manifest",
            str(MANIFEST_PATH),
            "--boundary-input",
            str(BOUNDARY_PATH),
            "--output",
            str(tmp_path / "dossier.md"),
        ]
    )
    after = (
        BASE_PROFILE_PATH.read_bytes(),
        TARGET_PROFILE_PATH.read_bytes(),
        MANIFEST_PATH.read_bytes(),
    )
    assert before == after
    from turtle_value_engine.config import load_project_config

    assert (
        load_project_config(ROOT / "config" / "project.example.toml").profiles.default
        == "strict-v1"
    )
    from turtle_value_engine.config import load_profile

    assert load_profile().profile.id == "strict-v1"


def test_config_template_default_profile_unchanged():
    content = (ROOT / "config" / "project.example.toml").read_text(encoding="utf-8")
    assert 'default = "strict-v1"' in content


# --------------------------------------------------------------------------
# 5. Schema drift parity and semantic pinning
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("owner-policy-decision-input.schema.json", OwnerPolicyDecisionInputV1),
        ("owner-policy-decision-record.schema.json", OwnerPolicyDecisionRecordV1),
        (
            "owner-policy-decision-revocation.schema.json",
            OwnerPolicyDecisionRevocationV1,
        ),
        (
            "owner-policy-decision-validation.schema.json",
            OwnerPolicyDecisionValidationV1,
        ),
        (
            "owner-decision-authority-resolution.schema.json",
            DecisionAuthorityResolutionV1,
        ),
        ("profile-activation-plan.schema.json", ProfileActivationPlanV1),
    ],
)
def test_checked_in_schemas_have_drift_parity(schema_name, model):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == model.model_json_schema()


def test_validation_schema_pins_exact_check_sequence():
    schema = json.loads(
        (ROOT / "schemas" / "owner-policy-decision-validation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    prefix_items = schema["properties"]["checks"]["prefixItems"]
    assert len(prefix_items) == len(REQUIRED_DECISION_VALIDATION_CHECKS)
    for entry, (name, scope) in zip(prefix_items, REQUIRED_DECISION_VALIDATION_CHECKS):
        assert entry["properties"]["name"]["const"] == name
        assert entry["properties"]["scope"]["const"] == scope
    assert schema["properties"]["checks"]["items"] is False

    exception = _policy_exception()
    decision_input, raw = _accept_input(exception=exception)
    validation = _validate(decision_input, raw)
    validator = Draft202012Validator(schema)
    validator.validate(validation.model_dump(mode="json"))
    reordered = validation.model_dump(mode="json")
    reordered["checks"][0], reordered["checks"][1] = (
        reordered["checks"][1],
        reordered["checks"][0],
    )
    with pytest.raises(Exception):
        validator.validate(reordered)

    # The frozen C1 audit schema keeps its eighteen-check sequence untouched.
    c1_schema = json.loads(
        (ROOT / "schemas" / "profile-semantic-audit.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(c1_schema)
    assert len(c1_schema["properties"]["checks"]["prefixItems"]) == 18
