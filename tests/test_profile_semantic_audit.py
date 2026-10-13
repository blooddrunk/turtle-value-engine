"""Phase 7-C1 focused regressions: profile semantic audit and labels.

Covers the published ``strict-v1 -> strict-v2`` audit (structural PASS,
CDC coherence findings for strict-v2 only, ``POLICY_DECISION_REQUIRED``),
exact CDC boundary/epsilon evidence through the real gate, end-to-end
decision divergence through the real pipeline, tamper/lineage/identity
blockers, valid monotonic configurations, policy-exception coverage,
approval-claim detection, deterministic reproducibility, schema drift
parity, socket-guarded offline execution, published-byte preservation and
the profile-aware decision labels.
"""

import contextlib
import hashlib
import io
import json
import socket
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine import load_normalized_input
from turtle_value_engine.calculations.business_quality import (
    calculate_business_quality_from_normalized_input,
)
from turtle_value_engine.cli import main
from turtle_value_engine.config import load_profile
from turtle_value_engine.evolution.profile_release import (
    VersionedProfileReleaseCandidateV1,
    _digest,
    _rules,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
    REQUIRED_SEMANTIC_AUDIT_CHECKS,
    PolicyApprovalClaimV1,
    ProfileSemanticAuditV1,
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)
from turtle_value_engine.pipeline import run_analyze

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


def _published_audit():
    return audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
    )


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


def _audit_argv(tmp_path: Path, output: Path | None = None) -> list[str]:
    argv = [
        "evolution",
        "audit-profile",
        "--base-profile",
        str(BASE_PROFILE_PATH),
        "--target-profile",
        str(TARGET_PROFILE_PATH),
        "--release-manifest",
        str(MANIFEST_PATH),
        "--boundary-input",
        str(BOUNDARY_PATH),
    ]
    if output is not None:
        argv.extend(["--output", str(output)])
    return argv


# --------------------------------------------------------------------------
# 1. Published strict-v2 audit classification
# --------------------------------------------------------------------------


def test_published_strict_v2_audit_requires_policy_decision():
    audit = _published_audit()

    assert audit.activation_readiness == "POLICY_DECISION_REQUIRED"
    assert audit.policy_approval_status == "ABSENT"
    assert audit.blocking_checks == []
    assert audit.policy_decision_reasons == [
        "CDC_BAND_ORDER_VIOLATION:strict-v2",
        "CDC_GATE_TIER_COHERENCE_VIOLATION:strict-v2",
    ]
    assert audit.requires_human_policy_approval is True
    assert audit.automatic_activation_allowed is False
    assert audit.publication_is_not_activation_approval is True
    assert audit.base_profile_id == "strict-v1"
    assert audit.base_profile_sha256 == STRICT_V1_SHA256
    assert audit.target_profile_id == "strict-v2"
    assert audit.target_profile_sha256 == STRICT_V2_SHA256
    assert audit.release_manifest_content_sha256 == MANIFEST_CONTENT_SHA256


def test_published_audit_structural_checks_pass_and_findings_target_only():
    audit = _published_audit()
    by_key = {(check.name, check.scope): check for check in audit.checks}

    assert [(check.name, check.scope) for check in audit.checks] == [
        tuple(item) for item in REQUIRED_SEMANTIC_AUDIT_CHECKS
    ]
    for key, check in by_key.items():
        if key in {
            ("CDC_BAND_ORDER", "target"),
            ("CDC_GATE_TIER_COHERENCE", "target"),
        }:
            assert check.status == "FINDING"
        else:
            assert check.status == "PASS", f"{key}: {check.detail}"
    assert by_key[("CDC_BAND_ORDER", "target")].code == "CDC_BAND_ORDER_VIOLATION"
    assert (
        by_key[("CDC_GATE_TIER_COHERENCE", "target")].code
        == "CDC_GATE_TIER_COHERENCE_VIOLATION"
    )
    assert {finding.code for finding in audit.semantic_findings} == {
        "CDC_BAND_ORDER_VIOLATION",
        "CDC_GATE_TIER_COHERENCE_VIOLATION",
    }
    assert {finding.profile_id for finding in audit.semantic_findings} == {
        "strict-v2"
    }
    assert all(
        not finding.covered_by_policy_exception for finding in audit.semantic_findings
    )


# --------------------------------------------------------------------------
# 2. Exact CDC boundary/epsilon evidence through the real gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("yield_value", "base_status", "target_status"),
    [
        (0.06 - 1e-9, "FAIL", "FAIL"),
        (0.06, "WATCH", "WATCH"),
        (0.06 + 1e-9, "WATCH", "WATCH"),
        (0.08 - 1e-9, "WATCH", "WATCH"),
        (0.08, "PASS", "WATCH"),
        (0.08 + 1e-9, "PASS", "WATCH"),
        (0.10, "PASS", "WATCH"),
        (0.12, "PASS", "WATCH"),
        (0.13, "PASS", "WATCH"),
        (0.14 - 1e-9, "PASS", "WATCH"),
        (0.14, "PASS", "PASS"),
        (0.14 + 1e-9, "PASS", "PASS"),
    ],
)
def test_gate_boundary_rows_match_real_gate_at_exact_yields(
    yield_value, base_status, target_status
):
    audit = _published_audit()
    row = next(
        row for row in audit.gate_boundary_rows if row.cdc_yield == yield_value
    )
    assert row.base_gate_status == base_status
    assert row.target_gate_status == target_status
    assert row.diverges == (base_status != target_status)


def test_gate_divergence_window_is_exactly_half_open_interval():
    audit = _published_audit()
    diverging = [row.cdc_yield for row in audit.gate_boundary_rows if row.diverges]
    assert diverging
    assert all(0.08 <= value < 0.14 for value in diverging)
    non_diverging_inside = [
        row.cdc_yield
        for row in audit.gate_boundary_rows
        if not row.diverges and 0.08 <= row.cdc_yield < 0.14
    ]
    assert non_diverging_inside == []
    assert audit.gate_divergence_count == len(diverging)


# --------------------------------------------------------------------------
# 3. End-to-end decision divergence through the real pipeline
# --------------------------------------------------------------------------


def test_pipeline_rows_prove_decision_divergence_with_reasons():
    audit = _published_audit()
    changed = [row for row in audit.pipeline_boundary_rows if row.decision_changed]

    assert audit.decision_divergence_count == len(changed) >= 2
    for row in changed:
        assert 0.12 < row.target_cdc_yield < 0.14
        assert row.base_gate_status == "PASS"
        assert row.target_gate_status == "WATCH"
        assert row.base_valuation_state == "EXTREME_SAFETY"
        assert row.base_decision_state == "EXTREME_SAFETY"
        assert row.base_auto_decision_allowed is True
        assert row.target_valuation_state == "SPECIAL_REVIEW"
        assert row.target_decision_state == "WATCH"
        assert row.target_auto_decision_allowed is False
        assert row.gate_divergences == ["CDC.YIELD:PASS->WATCH"]
        assert row.withheld_valuation_reasons == ["NON_PRICE_GATES_UNRESOLVED"]
    agreed = [
        row
        for row in audit.pipeline_boundary_rows
        if not row.decision_changed
        and row.target_cdc_yield >= 0.14
    ]
    assert agreed
    for row in agreed:
        assert row.base_decision_state == row.target_decision_state


# --------------------------------------------------------------------------
# 4. Deterministic reproducibility and identity stability
# --------------------------------------------------------------------------


def test_audit_is_deterministic_and_byte_reproducible():
    first = _published_audit()
    second = _published_audit()

    assert first == second
    assert first.audit_id == second.audit_id
    assert first.content_sha256 == second.content_sha256
    assert first.audit_id.startswith("profile-semantic-audit-")


def test_audit_id_binds_declared_inputs():
    base = _published_audit()
    accepted = PolicyApprovalClaimV1(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        decision="ACCEPTED",
        decided_by="owner-test",
        decided_at="2026-10-13",
        rationale="test claim only",
    )
    with_claim = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
        approval_claim=accepted,
    )
    assert with_claim.policy_approval_status == "UNVERIFIED_ACCEPTANCE_CLAIM"
    assert with_claim.audit_id != base.audit_id
    assert with_claim.activation_readiness == "POLICY_DECISION_REQUIRED"
    assert with_claim.automatic_activation_allowed is False


# --------------------------------------------------------------------------
# 5. Schema drift parity and schema validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("profile-semantic-audit.schema.json", ProfileSemanticAuditV1),
        ("versioned-policy-exception.schema.json", VersionedPolicyExceptionV1),
        ("policy-approval-claim.schema.json", PolicyApprovalClaimV1),
    ],
)
def test_checked_in_schemas_have_drift_parity(schema_name, model):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == model.model_json_schema()


def test_audit_schema_pins_exact_check_sequence():
    schema = json.loads(
        (ROOT / "schemas" / "profile-semantic-audit.schema.json").read_text(
            encoding="utf-8"
        )
    )
    prefix_items = schema["properties"]["checks"]["prefixItems"]
    assert len(prefix_items) == len(REQUIRED_SEMANTIC_AUDIT_CHECKS)
    for entry, (name, scope) in zip(prefix_items, REQUIRED_SEMANTIC_AUDIT_CHECKS):
        assert entry["properties"]["name"]["const"] == name
        assert entry["properties"]["scope"]["const"] == scope
    assert schema["properties"]["checks"]["items"] is False
    validator = Draft202012Validator(schema)
    validator.validate(_published_audit().model_dump(mode="json"))
    reordered = _published_audit().model_dump(mode="json")
    reordered["checks"][0], reordered["checks"][1] = (
        reordered["checks"][1],
        reordered["checks"][0],
    )
    with pytest.raises(Exception):
        validator.validate(reordered)


def test_audit_validates_against_checked_in_schema():
    schema = Draft202012Validator(
        json.loads(
            (ROOT / "schemas" / "profile-semantic-audit.schema.json").read_text(
                encoding="utf-8"
            )
        )
    )
    schema.validate(_published_audit().model_dump(mode="json"))


# --------------------------------------------------------------------------
# 6. Tamper, identity and unregistered-change blockers
# --------------------------------------------------------------------------


def _rebuild_manifest_for_bytes(
    tmp_path: Path,
    target_bytes: bytes,
    rule_changes: list[dict],
) -> Path:
    """Build a self-consistent manifest binding the supplied target bytes."""

    target_profile = load_profile_module_validate(target_bytes)
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
        base_profile_sha256=hashlib.sha256(BASE_PROFILE_PATH.read_bytes()).hexdigest(),
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


def load_profile_module_validate(raw_bytes: bytes):
    import yaml as yaml_module

    from turtle_value_engine.config.models import RuleProfile

    return RuleProfile.model_validate(yaml_module.safe_load(raw_bytes))


def test_tampered_manifest_blocks_activation(tmp_path):
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["release_profile_sha256"] = "0" * 64
    tampered = tmp_path / "c1-tampered-manifest.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=tampered,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
    )
    assert audit.activation_readiness == "BLOCKED_FOR_ACTIVATION"
    assert "RELEASE_MANIFEST_VALID:pair" in audit.blocking_checks
    assert "RELEASE_MANIFEST_INVALID" in {
        check.code for check in audit.checks if check.status == "BLOCKED"
    }


def test_wrong_target_bytes_block_activation(tmp_path):
    import yaml as yaml_module

    payload = yaml_module.safe_load(TARGET_PROFILE_PATH.read_bytes())
    payload["cdc"]["yield_bands"]["watch"] = 0.05
    tampered_target = tmp_path / "strict-v2.yaml"
    tampered_target.write_text(
        yaml_module.safe_dump(payload, sort_keys=True), encoding="utf-8"
    )

    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=tampered_target,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
    )
    assert audit.activation_readiness == "BLOCKED_FOR_ACTIVATION"
    assert "TARGET_PROFILE_BYTES_HASH:pair" in audit.blocking_checks
    assert "TARGET_PROFILE_IDENTITY:pair" in audit.blocking_checks


def test_unregistered_extra_rule_change_blocks_even_with_matching_hashes(tmp_path):
    import yaml as yaml_module

    payload = yaml_module.safe_load(TARGET_PROFILE_PATH.read_bytes())
    payload["cdc"]["yield_bands"]["watch"] = 0.05
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
            }
        ],
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
    )
    blocked_codes = {
        check.code for check in audit.checks if check.status == "BLOCKED"
    }
    assert audit.activation_readiness == "BLOCKED_FOR_ACTIVATION"
    assert "RULE_CHANGES_MISMATCH" in blocked_codes


def test_wrong_filename_blocks_target_identity(tmp_path):
    copied = tmp_path / "not-strict-v2.yaml"
    copied.write_bytes(TARGET_PROFILE_PATH.read_bytes())
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=copied,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
    )
    assert audit.activation_readiness == "BLOCKED_FOR_ACTIVATION"
    assert "TARGET_PROFILE_IDENTITY:pair" in audit.blocking_checks


# --------------------------------------------------------------------------
# 7. Valid monotonic configuration reaches READY_FOR_POLICY_DECISION
# --------------------------------------------------------------------------


def _write_monotonic_target(tmp_path: Path) -> tuple[Path, Path]:
    """strict-v2 with a 14% gate that stays inside its own band and tiers."""

    import yaml as yaml_module

    payload = yaml_module.safe_load(TARGET_PROFILE_PATH.read_bytes())
    payload["cdc"]["yield_bands"]["s"] = 0.16
    payload["cdc"]["yield_bands"]["a"] = 0.15
    payload["valuation"]["tiers"]["extreme_safety"]["cdc_yield"] = 0.14
    target_path = tmp_path / "strict-v2.yaml"
    target_path.write_text(
        yaml_module.safe_dump(payload, sort_keys=True), encoding="utf-8"
    )
    manifest_path = _rebuild_manifest_for_bytes(
        tmp_path,
        target_path.read_bytes(),
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
                "target_key": "cdc-yield-bands-s",
                "profile_path": "cdc.yield_bands.s",
                "before": 0.12,
                "after": 0.16,
            },
            {
                "contract": "candidate_rule_leaf_change_v1",
                "target_key": "cdc-yield-bands-a",
                "profile_path": "cdc.yield_bands.a",
                "before": 0.10,
                "after": 0.15,
            },
            {
                "contract": "candidate_rule_leaf_change_v1",
                "target_key": "valuation-tiers-extreme-safety-cdc-yield",
                "profile_path": "valuation.tiers.extreme_safety.cdc_yield",
                "before": 0.12,
                "after": 0.14,
            },
        ],
    )
    return target_path, manifest_path


def test_monotonic_compliant_profile_is_ready_for_policy_decision(tmp_path):
    target_path, manifest_path = _write_monotonic_target(tmp_path)
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
    )
    assert audit.semantic_findings == []
    assert audit.blocking_checks == []
    assert audit.policy_decision_reasons == []
    assert audit.activation_readiness == "READY_FOR_POLICY_DECISION"
    assert audit.requires_human_policy_approval is True
    assert audit.automatic_activation_allowed is False


# --------------------------------------------------------------------------
# 8. Policy exceptions
# --------------------------------------------------------------------------


def _policy_exception_for_strict_v2() -> VersionedPolicyExceptionV1:
    return VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256=STRICT_V2_SHA256,
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale=(
            "Owner-declared stricter eligibility gate: the 14% CDC pass "
            "threshold intentionally sits above the retained S band."
        ),
        declared_by="owner",
    )


def test_binding_policy_exception_covers_the_published_findings():
    exception = _policy_exception_for_strict_v2()
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
        policy_exceptions=[exception],
    )
    assert audit.policy_exception_ids == [exception.exception_id]
    assert all(
        finding.covered_by_policy_exception for finding in audit.semantic_findings
    )
    assert all(
        finding.covering_exception_id == exception.exception_id
        for finding in audit.semantic_findings
    )
    assert audit.activation_readiness == "READY_FOR_POLICY_DECISION"
    assert audit.requires_human_policy_approval is True


def test_mismatched_policy_exception_does_not_cover():
    exception = VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256="9" * 64,
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale="Foreign exception binding different bytes; must not cover.",
        declared_by="someone",
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
        policy_exceptions=[exception],
    )
    exceptions_check = next(
        check
        for check in audit.checks
        if check.name == "POLICY_EXCEPTIONS_VALID"
    )
    assert exceptions_check.status == "FINDING"
    assert exceptions_check.code == "POLICY_EXCEPTION_NOT_APPLICABLE"
    assert audit.policy_exception_ids == []
    assert all(
        not finding.covered_by_policy_exception
        for finding in audit.semantic_findings
    )
    assert audit.activation_readiness == "POLICY_DECISION_REQUIRED"


def test_exception_never_covers_arbitrary_band_disorder(tmp_path):
    import yaml as yaml_module

    payload = yaml_module.safe_load(TARGET_PROFILE_PATH.read_bytes())
    # a > s is not the registered gate-above-band anomaly pattern.
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
    exception = VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256=hashlib.sha256(target_bytes).hexdigest(),
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale="Even a binding exception cannot cover arbitrary disorder.",
        declared_by="owner",
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
        policy_exceptions=[exception],
    )
    band_finding = next(
        finding
        for finding in audit.semantic_findings
        if finding.code == "CDC_BAND_ORDER_VIOLATION"
    )
    coherence_finding = next(
        finding
        for finding in audit.semantic_findings
        if finding.code == "CDC_GATE_TIER_COHERENCE_VIOLATION"
    )
    assert band_finding.covered_by_policy_exception is False
    assert coherence_finding.covered_by_policy_exception is True
    assert audit.activation_readiness == "POLICY_DECISION_REQUIRED"
    assert audit.policy_decision_reasons == ["CDC_BAND_ORDER_VIOLATION:strict-v2"]


def test_exception_contract_rejects_wrong_content_hash_and_ids():
    exception = _policy_exception_for_strict_v2()
    tampered_payload = exception.model_dump(mode="json")
    tampered_payload["rationale"] = "different rationale, unchanged id/hash"
    with pytest.raises(Exception):
        VersionedPolicyExceptionV1.model_validate(tampered_payload)


# --------------------------------------------------------------------------
# 9. Approval-claim detection
# --------------------------------------------------------------------------


def test_missing_approval_is_reported_absent_by_default():
    assert _published_audit().policy_approval_status == "ABSENT"


def test_stale_approval_claim_is_mismatched():
    stale = PolicyApprovalClaimV1(
        target_profile_id="strict-v2",
        target_profile_sha256="5" * 64,
        decision="ACCEPTED",
        decided_by="owner",
        decided_at="2026-10-12",
        rationale="Claim binds different bytes.",
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
        approval_claim=stale,
    )
    assert audit.policy_approval_status == "MISMATCHED_CLAIM"
    assert audit.activation_readiness == "POLICY_DECISION_REQUIRED"
    assert audit.automatic_activation_allowed is False


def test_rejection_claim_is_detected_but_never_enables_activation():
    rejection = PolicyApprovalClaimV1(
        target_profile_id="strict-v2",
        target_profile_sha256=STRICT_V2_SHA256,
        decision="REJECTED",
        decided_by="owner",
        decided_at="2026-10-13",
        rationale="Explicitly rejected pending a strict-v3 fix.",
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=load_normalized_input(BOUNDARY_PATH),
        approval_claim=rejection,
    )
    assert audit.policy_approval_status == "UNVERIFIED_REJECTION_CLAIM"
    assert audit.activation_readiness == "POLICY_DECISION_REQUIRED"


# --------------------------------------------------------------------------
# 10. Boundary-template blockers
# --------------------------------------------------------------------------


def test_boundary_template_profile_mismatch_blocks_replay():
    wrong_profile_template = load_normalized_input(BOUNDARY_PATH).model_copy(
        update={"profile_id": "strict-v2"}
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=wrong_profile_template,
    )
    replay_check = next(
        check
        for check in audit.checks
        if check.name == "BOUNDARY_REPLAY_REPRODUCIBLE"
    )
    assert replay_check.status == "BLOCKED"
    assert replay_check.code == "BOUNDARY_TEMPLATE_PROFILE_MISMATCH"
    assert audit.activation_readiness == "BLOCKED_FOR_ACTIVATION"


def test_boundary_template_evidence_collision_blocks_replay():
    from turtle_value_engine.models import Evidence

    template = load_normalized_input(BOUNDARY_PATH)
    collided = template.model_copy(
        update={
            "evidence_index": [
                *template.evidence_index,
                Evidence(
                    id="profile-audit-bq-hard-rule-evidence",
                    direction="SUPPORT",
                    strength="E3",
                    statement="collision",
                    source={"type": "ANNUAL_REPORT", "title": "collision"},
                    confidence=1,
                ),
            ]
        }
    )
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=collided,
    )
    replay_check = next(
        check
        for check in audit.checks
        if check.name == "BOUNDARY_REPLAY_REPRODUCIBLE"
    )
    assert replay_check.status == "BLOCKED"
    assert replay_check.code == "BOUNDARY_TEMPLATE_EVIDENCE_COLLISION"


# --------------------------------------------------------------------------
# 11. CLI boundary: exit codes, output guards, no network, byte preservation
# --------------------------------------------------------------------------


def test_cli_published_audit_exits_one_and_persists_dossier(tmp_path):
    output = tmp_path / "audit.json"
    code, payload, _text = _run_cli(_audit_argv(tmp_path, output))

    assert code == 1
    assert payload["activation_readiness"] == "POLICY_DECISION_REQUIRED"
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == payload
    assert persisted["content_sha256"] == payload["content_sha256"]


def test_cli_compliant_audit_exits_zero(tmp_path):
    target_path, manifest_path = _write_monotonic_target(tmp_path)
    code, payload, _text = _run_cli(
        [
            "evolution",
            "audit-profile",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(target_path),
            "--release-manifest",
            str(manifest_path),
            "--boundary-input",
            str(BOUNDARY_PATH),
        ]
    )
    assert code == 0
    assert payload["activation_readiness"] == "READY_FOR_POLICY_DECISION"


def test_cli_refuses_output_over_inputs_rules_and_symlinks(tmp_path):
    code, _payload, text = _run_cli(_audit_argv(tmp_path, MANIFEST_PATH))
    assert code == 2
    assert "release-manifest" in text

    (tmp_path / "sub").mkdir()
    symlink = tmp_path / "sub" / "audit.json"
    symlink.symlink_to(tmp_path / "real-audit.json")
    code, _payload, text = _run_cli(_audit_argv(tmp_path, symlink))
    assert code == 2
    assert "symlink" in text

    code, _payload, text = _run_cli(
        _audit_argv(tmp_path, ROOT / "rules" / "audit.json")
    )
    assert code == 2
    assert "published artifact directories" in text


def test_cli_invalid_inputs_exit_two(tmp_path):
    code, _payload, _text = _run_cli(
        [
            "evolution",
            "audit-profile",
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--target-profile",
            str(TARGET_PROFILE_PATH),
            "--release-manifest",
            str(tmp_path / "missing.json"),
        ]
    )
    assert code == 2


def test_cli_audit_constructs_no_socket(tmp_path, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("C1 audit constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    code, payload, _text = _run_cli(_audit_argv(tmp_path, tmp_path / "audit.json"))
    assert code == 1
    assert payload["contract"] == "profile_semantic_audit_v1"


def test_published_bytes_and_default_profile_unchanged_after_audit(tmp_path):
    before = (
        BASE_PROFILE_PATH.read_bytes(),
        TARGET_PROFILE_PATH.read_bytes(),
        MANIFEST_PATH.read_bytes(),
    )
    code, _payload, _text = _run_cli(_audit_argv(tmp_path, tmp_path / "audit.json"))
    assert code == 1
    after = (
        BASE_PROFILE_PATH.read_bytes(),
        TARGET_PROFILE_PATH.read_bytes(),
        MANIFEST_PATH.read_bytes(),
    )
    assert before == after
    assert hashlib.sha256(after[0]).hexdigest() == STRICT_V1_SHA256
    assert hashlib.sha256(after[1]).hexdigest() == STRICT_V2_SHA256
    # Zero implicit activation: the default profile remains strict-v1.
    assert load_profile().profile.id == "strict-v1"


# --------------------------------------------------------------------------
# 12. Profile-aware decision labels (strict-v1 strings preserved)
# --------------------------------------------------------------------------


def _green_path_analysis(profile_id: str, market_cap: float):
    from turtle_value_engine.evolution.profile_semantic_audit import (
        _augment_with_audit_business_quality,
        _boundary_input_at_yield,
    )

    profile = load_profile(
        BASE_PROFILE_PATH if profile_id == "strict-v1" else TARGET_PROFILE_PATH
    )
    template = load_normalized_input(BOUNDARY_PATH).model_copy(
        update={"profile_id": profile_id}
    )
    reference = run_analyze(template, profile=profile)
    cdc = reference.metrics.cdc.normalized_parent_core_cdc
    augmented, dimensions = _augment_with_audit_business_quality(template)
    business_quality = calculate_business_quality_from_normalized_input(
        augmented, dimensions, profile
    )
    probe = _boundary_input_at_yield(augmented, cdc / market_cap)
    probe = probe.model_copy(update={"profile_id": profile_id})
    return run_analyze(probe, profile=profile, business_quality=business_quality)


def test_decision_summary_labels_follow_the_active_profile():
    v1_analysis = _green_path_analysis("strict-v1", 0.13)
    v2_analysis = _green_path_analysis("strict-v2", 0.13)

    assert v1_analysis.decision.state.value == "EXTREME_SAFETY"
    assert v1_analysis.decision.summary == "Deterministic strict-v1 state: EXTREME_SAFETY."
    assert v2_analysis.decision.state.value == "WATCH"
    assert v2_analysis.decision.summary == "Deterministic strict-v2 state: WATCH."


def test_no_normal_valuation_label_follows_the_active_profile():
    from turtle_value_engine.evolution.profile_semantic_audit import (
        _augment_with_audit_business_quality,
        _boundary_input_at_yield,
    )

    def _no_normal(profile_id: str, yield_value: float):
        profile = load_profile(
            BASE_PROFILE_PATH if profile_id == "strict-v1" else TARGET_PROFILE_PATH
        )
        template = load_normalized_input(BOUNDARY_PATH).model_copy(
            update={"profile_id": profile_id}
        )
        reference = run_analyze(template, profile=profile)
        cdc = reference.metrics.cdc.normalized_parent_core_cdc
        augmented, dimensions = _augment_with_audit_business_quality(template)
        business_quality = calculate_business_quality_from_normalized_input(
            augmented, dimensions, profile
        )
        probe = _boundary_input_at_yield(augmented, cdc / yield_value)
        without_shares = probe.model_copy(
            update={
                "profile_id": profile_id,
                "facts": [
                    fact
                    for fact in probe.facts
                    if fact.field != "normalized_diluted_economic_shares"
                ],
            }
        )
        return run_analyze(
            without_shares, profile=profile, business_quality=business_quality
        )

    v1_analysis = _no_normal("strict-v1", 0.13)
    assert v1_analysis.decision.state.value == "NO_NORMAL_VALUATION"
    assert v1_analysis.decision.summary == (
        "No normal strict-v1 valuation is available for this input."
    )
    assert (
        "The strict-v1 inputs do not support a normal valuation."
        in v1_analysis.decision.blocking_reasons
    )
    # strict-v2 needs a yield at or above its 14% gate for the CDC gate to
    # pass, otherwise gate precedence yields WATCH before valuation.
    v2_analysis = _no_normal("strict-v2", 0.145)
    assert v2_analysis.decision.state.value == "NO_NORMAL_VALUATION"
    assert v2_analysis.decision.summary == (
        "No normal strict-v2 valuation is available for this input."
    )
    assert (
        "The strict-v2 inputs do not support a normal valuation."
        in v2_analysis.decision.blocking_reasons
    )


def test_baseline_fixture_summaries_unchanged_for_strict_v1():
    normalized_input = load_normalized_input(BOUNDARY_PATH)
    analysis = run_analyze(normalized_input)
    assert analysis.decision.summary == (
        "Deterministic analysis requires manual review; no automated investment "
        "recommendation is issued."
    )
    failing = run_analyze(load_normalized_input(ROOT / "fixtures" / "leveraged_dividend_trap.json"))
    assert failing.decision.summary == (
        "A hard gate failed; no normal investment recommendation is issued."
    )
