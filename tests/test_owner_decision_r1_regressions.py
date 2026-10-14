"""Phase 7-C2-R1 regressions: activation-plan trust-boundary hardening.

Every test here encodes one defect found by the 2026-10-14 post-closure
review (``docs/status/phase-7-c2-post-closure-review-2026-10-14.md``):

* R1-A — a persisted ``OWNER_AUTHORITY_VERIFIED`` claim is record integrity,
  never authenticated authority; plan-time authority must be independently
  re-attested by an injected verifier (library-only), and the production CLI
  without a real verifier must fail closed on a forged VERIFIED record.
* R1-B — the plan must bind the active decision record to the exact base
  profile, target profile, release manifest, fresh audit and exception set
  (id AND full content hash), with granular stable blockers.
* R1-C — create-only CLI outputs must be truly atomic (no check-then-replace
  overwrite race), byte-identical reruns stay idempotent, and racing
  conflicting writers are never overwritten.
* R1-D — a library plan without project config is explicitly BLOCKED, and a
  monitoring runner config's referenced watchlist must be inventoried
  explicitly or the plan blocks.
"""

import contextlib
import hashlib
import io
import json
from pathlib import Path

import pytest

from turtle_value_engine import load_normalized_input
from turtle_value_engine.cli import main
from turtle_value_engine.evolution.activation_plan import plan_profile_activation
from turtle_value_engine.evolution.owner_decision import (
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerDecisionError,
    OwnerDecisionVerifier,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
    record_owner_decision_file,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
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


def _accept_payload(**overrides) -> dict:
    """Decision-input payload bound to the real published strict-v2 chain."""

    exception = _policy_exception()
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[exception],
    )
    manifest = _manifest_payload()
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
        "exception_id": exception.exception_id,
        "exception_content_sha256": exception.content_sha256,
        "rationale": "Accept the stricter 14% CDC gate as intended owner policy.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-14",
        "source_revision": "r1-regression-note",
    }
    payload.update(overrides)
    return payload


def _accept_input(**overrides) -> OwnerPolicyDecisionInputV1:
    return OwnerPolicyDecisionInputV1.model_validate(_accept_payload(**overrides))


_UNSET_SOURCE_HASH = object()


def _forged_verified_record(
    decision_input: OwnerPolicyDecisionInputV1 | None = None,
    *,
    authority_status: str = "OWNER_AUTHORITY_VERIFIED",
    verification_method: str = "INJECTED_VERIFIER",
    verifier_kind: str | None = "forged-verifier",
    allowlist_matched: bool | None = True,
    reason_code: str = "FORGED_CLAIM",
    source_content_sha256: object = _UNSET_SOURCE_HASH,
) -> OwnerPolicyDecisionRecordV1:
    """An internally hash-consistent record with an *asserted* authority claim.

    This is exactly what an attacker can produce offline: correct deterministic
    id and content hash, no authenticated source behind the claim.  Nothing
    here authenticates a real owner.
    """

    if decision_input is None:
        decision_input = _accept_input()
    if source_content_sha256 is _UNSET_SOURCE_HASH:
        source_hash: str | None = "a" * 64
    else:
        source_hash = source_content_sha256  # type: ignore[assignment]
    provenance = DecisionProvenanceV1(
        source_kind="LOCAL_UNSIGNED_JSON",
        source_revision="forged-revision",
        source_content_sha256=source_hash,
    )
    authority = OwnerAuthorityAssessmentV1(
        authority_status=authority_status,  # type: ignore[arg-type]
        verification_method=verification_method,  # type: ignore[arg-type]
        verifier_kind=verifier_kind,
        allowlist_matched=allowlist_matched,
        reason_code=reason_code,
        detail="Self-asserted claim with recomputed hashes; proves nothing.",
    )
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=decision_input,
        provenance=provenance,
        authority=authority,
    )


class RecordingVerifier(OwnerDecisionVerifier):
    """Library-injected test verifier with configurable verification truth."""

    kind = "recording-test-verifier"

    def __init__(
        self,
        *,
        status: str = "OWNER_AUTHORITY_VERIFIED",
        method: str = "INJECTED_VERIFIER",
        verifier_kind: str | None = "recording-test-verifier",
        allowlist_matched: bool | None = True,
        evidence_of: bytes | None = None,
        reason_code: str = "SCRIPTED_EVIDENCE_CONFIRMED",
    ) -> None:
        self.status = status
        self.method = method
        self.verifier_kind = verifier_kind
        self.allowlist_matched = allowlist_matched
        self.evidence_of = evidence_of
        self.reason_code = reason_code
        self.seen_bytes: list[bytes] = []

    def verify_decision_authority(
        self,
        *,
        declared_owner_identity: str,
        provenance: DecisionProvenanceV1,
        decision_source_bytes: bytes,
    ) -> OwnerAuthorityAssessmentV1:
        self.seen_bytes.append(decision_source_bytes)
        bound = (
            decision_source_bytes
            if self.evidence_of is None
            else self.evidence_of
        )
        return OwnerAuthorityAssessmentV1(
            authority_status=self.status,  # type: ignore[arg-type]
            verification_method=self.method,  # type: ignore[arg-type]
            verifier_kind=self.verifier_kind,
            allowlist_matched=self.allowlist_matched,
            reason_code=self.reason_code,
            detail="Scripted test verification; never selectable by the CLI.",
            evidence_content_sha256=hashlib.sha256(bound).hexdigest(),
        )


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


def _write_exception_file(
    tmp_path: Path, exception: VersionedPolicyExceptionV1
) -> Path:
    path = tmp_path / "exception.json"
    path.write_text(
        json.dumps(exception.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_record_file(
    tmp_path: Path, record: OwnerPolicyDecisionRecordV1, name: str = "record.json"
) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_watchlist(tmp_path: Path, profile_id: str, name: str) -> Path:
    from turtle_value_engine.monitoring import WatchlistSpecV1

    watchlist = WatchlistSpecV1.build(
        watchlist_id="r1-watchlist",
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


def _runner_config_bytes(watchlist_path: str) -> bytes:
    return json.dumps(
        {
            "contract": "monitoring_runner_config_v1",
            "schema_version": "1.0.0",
            "runner_id": "r1-test-runner",
            "watchlist_path": watchlist_path,
            "monitoring_workspace_root": "ws",
            "reanalysis_job_root": "jobs",
            "cycle_store_root": "cycles",
            "runner_root": "runner",
            "cache_dir": "cache",
            "network_allowed": False,
            "offline_replay": True,
            "window_days": 7,
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def _plan(tmp_path: Path, *, records, **kwargs):
    parameters = {
        "base_profile_path": BASE_PROFILE_PATH,
        "target_profile_path": TARGET_PROFILE_PATH,
        "release_manifest_path": MANIFEST_PATH,
        "boundary_input": _boundary(),
        "decision_records": records,
        "policy_exceptions": kwargs.pop(
            "policy_exceptions", [_policy_exception()]
        ),
        "project_config_path": kwargs.pop(
            "project_config_path", _write_project_config(tmp_path)
        ),
    }
    parameters.update(kwargs)
    return plan_profile_activation(**parameters)


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
        str(config if config is not None else _write_project_config(tmp_path)),
        "--output",
        str(output),
    ]
    if exception is not None:
        argv.extend(["--policy-exception", str(exception)])
    return argv


# ---------------------------------------------------------------------------
# R1-A — persisted VERIFIED claims are not authority
# ---------------------------------------------------------------------------


def test_cli_forged_verified_record_cannot_reach_ready(tmp_path):
    """R1-A headline: production CLI + self-consistent forged VERIFIED record
    must never output READY (baseline produced exit 0 / READY)."""

    record = _forged_verified_record()
    record_path = _write_record_file(tmp_path, record)
    exception_path = _write_exception_file(tmp_path, _policy_exception())
    output = tmp_path / "plan.json"

    code, payload, _text = _run_cli(
        _plan_argv(
            tmp_path, record_path, output, exception=exception_path
        )
    )

    assert code == 1, payload
    assert payload["plan_state"] == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REQUIRED" in payload["blockers"]
    assert payload["execution_performed"] is False
    assert payload["automatic_activation_allowed"] is False
    # The persisted output stays immutable evidence of the refused plan.
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["plan_state"] == "BLOCKED"


def test_plan_forged_verified_record_without_verifier_blocks(tmp_path):
    record = _forged_verified_record()
    plan = _plan(tmp_path, records=[record])

    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REQUIRED" in plan.blockers
    assert plan.authority_reverification_status == "REVERIFICATION_REQUIRED"
    assert plan.decision_authority_state == "ACCEPT_VERIFIED"
    assert plan.execution_performed is False


def test_plan_forged_verified_with_unbound_provenance_blocks(tmp_path):
    """A VERIFIED claim whose provenance never bound source bytes has no
    original source to re-attest against."""

    record = _forged_verified_record(source_content_sha256=None)
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(),
    )

    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_PROVENANCE_INCOMPLETE" in plan.blockers


def test_injected_verifier_reverification_reaches_ready(tmp_path):
    """The preserved fixture path: explicit library-only injected trusted
    verification evidence over the exact record bytes can reach a read-only
    READY."""

    record = _forged_verified_record()
    verifier = RecordingVerifier()
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=verifier,
    )

    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan.blockers == []
    assert plan.authority_reverification_status == "REVERIFIED"
    assert plan.execution_performed is False
    assert plan.automatic_activation_allowed is False
    # The verifier was consulted over the exact canonical record bytes.
    assert len(verifier.seen_bytes) == 1
    from turtle_value_engine.providers.models import canonical_json_bytes

    canonical = canonical_json_bytes(record.model_dump(mode="json"))
    assert verifier.seen_bytes[0] == canonical


def test_verifier_negative_rejection_blocks(tmp_path):
    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(status="OWNER_AUTHORITY_REJECTED"),
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers


def test_verifier_cannot_confirm_blocks(tmp_path):
    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(status="OWNER_AUTHORITY_UNVERIFIED"),
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_UNVERIFIED" in plan.blockers


def test_verifier_method_claiming_no_source_is_invalid(tmp_path):
    """An edited assessment claiming VERIFIED while its own method says there
    is no authenticated source is self-contradictory."""

    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(method="NO_AUTHENTICATED_SOURCE"),
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_METHOD_INVALID" in plan.blockers


def test_verifier_evidence_for_other_bytes_is_mismatch(tmp_path):
    """Verification evidence bound to different bytes does not attest this
    record."""

    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(evidence_of=b"other bytes entirely"),
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_EVIDENCE_MISMATCH" in plan.blockers


def test_verifier_allowlist_mismatch_blocks(tmp_path):
    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(allowlist_matched=False),
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_ALLOWLIST_MISMATCH" in plan.blockers


def test_record_cannot_self_certify_the_fresh_verification(tmp_path):
    """The fresh re-attestation must come from the verifier call, not from the
    record's serialized authority text: a record claiming VERIFIED stays
    blocked when the injected verifier disagrees, even though the record's own
    authority block says VERIFIED with matching evidence."""

    record = _forged_verified_record()
    assert record.authority.authority_status == "OWNER_AUTHORITY_VERIFIED"
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(status="OWNER_AUTHORITY_UNVERIFIED"),
    )
    assert plan.plan_state == "BLOCKED"
    assert plan.authority_reverification_status == "REVERIFICATION_FAILED"


# ---------------------------------------------------------------------------
# R1-B — exact decision-to-plan-context bindings
# ---------------------------------------------------------------------------


def test_plan_base_binding_stale_blocks(tmp_path):
    """A record bound to a different base profile is stale for this plan."""

    payload = _accept_payload(
        base_profile_id="strict-v0",
        base_profile_sha256="0" * 64,
    )
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    plan = _plan(tmp_path, records=[record])
    assert "DECISION_BASE_BINDING_STALE" in plan.blockers
    assert plan.plan_state == "BLOCKED"


def test_plan_manifest_binding_stale_blocks(tmp_path):
    payload = _accept_payload(
        release_manifest_id="versioned-profile-release-candidate-other",
        release_manifest_content_sha256="b" * 64,
    )
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    plan = _plan(tmp_path, records=[record])
    assert "DECISION_MANIFEST_BINDING_STALE" in plan.blockers
    assert plan.plan_state == "BLOCKED"


def test_plan_audit_binding_stale_blocks_old_audit(tmp_path):
    """A decision authored against an older audit (here: the audit without the
    exception applied) must not authorize a plan built on the fresh audit."""

    audit_without_exception = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
    )
    payload = _accept_payload(
        audit_id=audit_without_exception.audit_id,
        audit_content_sha256=audit_without_exception.content_sha256,
    )
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    plan = _plan(
        tmp_path,
        records=[record],
    )
    assert "DECISION_AUDIT_BINDING_STALE" in plan.blockers
    assert plan.plan_state == "BLOCKED"


def test_plan_exception_content_hash_change_blocks(tmp_path):
    """Unchanged C1 exception id with altered rationale (different content
    hash) is a stale exception binding, exactly as at record time."""

    bound = _policy_exception()
    altered = _policy_exception(
        rationale="Altered rationale keeping the identical exception id."
    )
    assert altered.exception_id == bound.exception_id
    assert altered.content_sha256 != bound.content_sha256

    payload = _accept_payload(
        exception_id=bound.exception_id,
        exception_content_sha256=bound.content_sha256,
    )
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    plan = _plan(
        tmp_path,
        records=[record],
        policy_exceptions=[altered],
    )
    assert "DECISION_EXCEPTION_BINDING_STALE" in plan.blockers
    assert plan.plan_state == "BLOCKED"


def test_plan_exception_set_mismatch_blocks(tmp_path):
    """The supplied exception set must be exactly the bound set (no extras)."""

    bound = _policy_exception()
    payload = _accept_payload(
        exception_id=bound.exception_id,
        exception_content_sha256=bound.content_sha256,
    )
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    extra = _policy_exception(rationale="An extra unrelated exception file.")
    plan = _plan(
        tmp_path,
        records=[record],
        policy_exceptions=[bound, extra],
    )
    assert "DECISION_EXCEPTION_SET_MISMATCH" in plan.blockers
    assert plan.plan_state == "BLOCKED"


def test_reject_record_with_supplied_exception_is_set_mismatch(tmp_path):
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
    )
    manifest = _manifest_payload()
    payload = {
        "contract": "owner_policy_decision_input_v1",
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
        "decided_at": "2026-10-14",
        "source_revision": "r1-regression-note",
    }
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    plan = _plan(
        tmp_path,
        records=[record],
        policy_exceptions=[_policy_exception()],
    )
    assert "DECISION_EXCEPTION_SET_MISMATCH" in plan.blockers
    assert "DECISION_IS_REJECT" in plan.blockers


def test_stale_bindings_block_even_with_trusted_reverification(tmp_path):
    """Independent authority re-attestation alone cannot rescue a record that
    binds a different plan context (the full R1-B + R1-A composition)."""

    payload = _accept_payload(base_profile_sha256="0" * 64)
    record = _forged_verified_record(OwnerPolicyDecisionInputV1.model_validate(payload))
    plan = _plan(
        tmp_path,
        records=[record],
        authority_verifier=RecordingVerifier(),
    )
    assert plan.plan_state == "BLOCKED"
    assert "DECISION_BASE_BINDING_STALE" in plan.blockers
    assert "OWNER_AUTHORITY_REVERIFICATION_REQUIRED" not in plan.blockers


# ---------------------------------------------------------------------------
# R1-C — true atomic create-only outputs
# ---------------------------------------------------------------------------


def _install_racing_writer(monkeypatch, output: Path, racing: bytes) -> None:
    """Orchestrate a competing writer that lands inside the publication window.

    Two seams cover both the pre-fix and post-fix publication flows exactly
    once: a ``Path.exists`` hook fires inside the old check-then-replace
    window (before the temp-file replace), and an ``os.open`` hook fires just
    before the new exclusive create.  In both cases the racing writer
    publishes conflicting content before this process's publication; the
    assertion is that it is never overwritten.
    """

    import os

    fired: list[str] = []
    real_open = os.open
    real_exists = Path.exists

    def hooked_exists(self: Path) -> bool:
        result = real_exists(self)
        if self == output and not result and not fired:
            fired.append("exists")
            output.write_bytes(racing)
        return result

    def hooked_open(path, flags, *args, **kwargs):
        if (
            not fired
            and Path(str(path)) == output
            and (flags & os.O_CREAT)
            and (flags & os.O_EXCL)
        ):
            fired.append("open")
            descriptor = real_open(
                output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
            )
            os.write(descriptor, racing)
            os.close(descriptor)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", hooked_exists)
    monkeypatch.setattr(os, "open", hooked_open)


def test_write_create_or_identical_racing_writer_not_overwritten(
    tmp_path, monkeypatch
):
    """Orchestrated interleaving: a second writer creates conflicting content
    inside the publication window; the conflicting file must survive."""

    record = _forged_verified_record()
    record_path = _write_record_file(tmp_path, record)
    exception_path = _write_exception_file(tmp_path, _policy_exception())
    output = tmp_path / "plan.json"
    racing = b'{"racing": "conflicting content from a second writer"}'

    _install_racing_writer(monkeypatch, output, racing)
    code, _payload, text = _run_cli(
        _plan_argv(tmp_path, record_path, output, exception=exception_path)
    )
    monkeypatch.undo()

    assert output.read_bytes() == racing, "racing writer content was overwritten"
    assert code == 2
    assert "already exists with different content" in text


def test_write_create_or_identical_idempotent_and_refusing(tmp_path):
    from turtle_value_engine.cli import _write_create_or_identical

    output = tmp_path / "out.json"
    assert _write_create_or_identical(output, b"payload", label="--output") == "CREATED"
    assert (
        _write_create_or_identical(output, b"payload", label="--output") == "IDEMPOTENT"
    )
    with pytest.raises(ValueError, match="different content"):
        _write_create_or_identical(output, b"other", label="--output")
    assert output.read_bytes() == b"payload"
    # No temporary artifacts are left behind.
    assert sorted(item.name for item in tmp_path.iterdir()) == ["out.json"]


def test_cli_record_decision_racing_writer_not_overwritten(tmp_path, monkeypatch):
    """The same interleaving through record-decision's validation output."""

    exception = _policy_exception()
    decision_path = tmp_path / "decision-input.json"
    decision_path.write_text(
        json.dumps(_accept_payload(), indent=2, sort_keys=True), encoding="utf-8"
    )
    exception_path = _write_exception_file(tmp_path, exception)
    output = tmp_path / "validation.json"
    racing = b"racing conflicting validation bytes"

    _install_racing_writer(monkeypatch, output, racing)
    code, _payload, text = _run_cli(
        [
            "evolution",
            "record-decision",
            "--decision-input",
            str(decision_path),
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
            "--record-output",
            str(tmp_path / "record.json"),
            "--output",
            str(output),
        ]
    )
    monkeypatch.undo()

    assert output.read_bytes() == racing
    assert code == 2
    assert "already exists with different content" in text


def test_cli_decision_dossier_racing_writer_not_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "dossier.md"
    racing = b"racing conflicting dossier bytes"

    _install_racing_writer(monkeypatch, output, racing)
    code, _payload, text = _run_cli(
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
            str(output),
        ]
    )
    monkeypatch.undo()

    assert output.read_bytes() == racing
    assert code == 2
    assert "already exists with different content" in text


def test_record_owner_decision_file_race_surfaces_owner_decision_error(
    tmp_path, monkeypatch
):
    """A racing writer that lands between the record-file existence check and
    the exclusive create must surface the classified immutability error, not a
    raw FileExistsError, and must never be overwritten."""

    record = _forged_verified_record()
    output = tmp_path / "decision-record.json"
    racing = b'{"racing": "conflicting record"}'

    real_exists = Path.exists
    fired: list[bool] = []

    def hooked_exists(self: Path) -> bool:
        result = real_exists(self)
        if self == output and not result and not fired:
            fired.append(True)
            output.write_bytes(racing)
        return result

    monkeypatch.setattr(Path, "exists", hooked_exists)
    try:
        with pytest.raises(OwnerDecisionError, match="immutable"):
            record_owner_decision_file(record, output)
    finally:
        monkeypatch.undo()

    assert output.read_bytes() == racing


# ---------------------------------------------------------------------------
# R1-D — inventory completeness before READY
# ---------------------------------------------------------------------------


def test_plan_without_project_config_is_blocked(tmp_path):
    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        project_config_path=None,
    )
    assert plan.plan_state == "BLOCKED"
    assert "PROJECT_CONFIG_REQUIRED" in plan.blockers


def test_plan_runner_watchlist_reference_must_be_inventoried(tmp_path):
    """A runner config's live watchlist reference that is not explicitly
    inventoried blocks the plan instead of silently assuming completeness."""

    record = _forged_verified_record()
    runner = tmp_path / "runner.json"
    runner.write_bytes(_runner_config_bytes("watchlist.json"))

    plan = _plan(
        tmp_path,
        records=[record],
        runner_config_paths=[runner],
    )
    assert plan.plan_state == "BLOCKED"
    assert "RUNNER_WATCHLIST_NOT_INVENTORIED" in plan.blockers
    runner_entry = next(
        item
        for item in plan.config_inventory
        if item.kind == "MONITORING_RUNNER_CONFIG"
    )
    assert runner_entry.blocker_code == "RUNNER_WATCHLIST_NOT_INVENTORIED"


def test_plan_runner_watchlist_inventoried_by_explicit_supply(tmp_path):
    """Explicitly supplying the referenced watchlist (resolved relative to the
    runner config's directory) completes the inventory."""

    record = _forged_verified_record()
    runner = tmp_path / "runner.json"
    runner.write_bytes(_runner_config_bytes("watchlist.json"))
    watchlist = _write_watchlist(tmp_path, "strict-v1", "watchlist.json")

    plan = _plan(
        tmp_path,
        records=[record],
        runner_config_paths=[runner],
        watchlist_paths=[watchlist],
        authority_verifier=RecordingVerifier(),
    )
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert "RUNNER_WATCHLIST_NOT_INVENTORIED" not in plan.blockers


def test_plan_runner_watchlist_wrong_supply_still_blocks(tmp_path):
    """Supplying a *different* watchlist does not complete the reference."""

    record = _forged_verified_record()
    runner = tmp_path / "runner.json"
    runner.write_bytes(_runner_config_bytes("watchlist.json"))
    other = _write_watchlist(tmp_path, "strict-v1", "other-watchlist.json")

    plan = _plan(
        tmp_path,
        records=[record],
        runner_config_paths=[runner],
        watchlist_paths=[other],
    )
    assert plan.plan_state == "BLOCKED"
    assert "RUNNER_WATCHLIST_NOT_INVENTORIED" in plan.blockers


def test_plan_runner_watchlist_absolute_reference(tmp_path):
    subdir = tmp_path / "runner-dir"
    subdir.mkdir()
    watchlist = _write_watchlist(subdir, "strict-v1", "watchlist.json")
    runner = subdir / "runner.json"
    runner.write_bytes(_runner_config_bytes(str(watchlist)))

    record = _forged_verified_record()
    plan = _plan(
        tmp_path,
        records=[record],
        runner_config_paths=[runner],
        watchlist_paths=[watchlist],
        authority_verifier=RecordingVerifier(),
    )
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"


# ---------------------------------------------------------------------------
# Cross-cutting invariants under the hardened boundary
# ---------------------------------------------------------------------------


def test_hardened_cli_stays_offline_and_preserves_published_bytes(tmp_path):
    before = (
        BASE_PROFILE_PATH.read_bytes(),
        TARGET_PROFILE_PATH.read_bytes(),
        MANIFEST_PATH.read_bytes(),
        (ROOT / "config" / "project.example.toml").read_bytes(),
    )

    def no_sockets(*args, **kwargs):
        raise AssertionError("C2-R1 CLI constructed a socket")

    import socket as socket_module

    original_socket = socket_module.socket
    original_connection = socket_module.create_connection
    socket_module.socket = no_sockets
    socket_module.create_connection = no_sockets
    try:
        record = _forged_verified_record()
        record_path = _write_record_file(tmp_path, record)
        exception_path = _write_exception_file(tmp_path, _policy_exception())
        code, payload, _text = _run_cli(
            _plan_argv(
                tmp_path, record_path, tmp_path / "plan.json", exception=exception_path
            )
        )
        assert code == 1
        assert payload["plan_state"] == "BLOCKED"
    finally:
        socket_module.socket = original_socket
        socket_module.create_connection = original_connection

    after = (
        BASE_PROFILE_PATH.read_bytes(),
        TARGET_PROFILE_PATH.read_bytes(),
        MANIFEST_PATH.read_bytes(),
        (ROOT / "config" / "project.example.toml").read_bytes(),
    )
    assert before == after


def test_no_verifier_escape_hatch_in_hardened_cli():
    from turtle_value_engine import cli as cli_module

    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "--authority-verifier",
        "--verifier",
        "--fake-verifier",
        "--trust-verified",
    ):
        assert forbidden not in source
    assert "OwnerDecisionVerifier" not in source
