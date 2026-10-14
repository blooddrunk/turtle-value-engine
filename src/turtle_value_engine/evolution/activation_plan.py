"""Read-only versioned-profile activation planning (Phase 7-C2 + C2-R1).

This module derives a deterministic, machine-readable activation/rollback
plan for one audited base -> target profile pair from a resolved owner policy
decision and a freshly re-run C1 semantic audit.  It is a *plan* in the
strictest sense: every contract here fixes ``execution_performed=False`` and
``automatic_activation_allowed=False`` — a verified decision is necessary
input, never an execution request — and nothing in this module writes a rule
profile, mutates runtime configuration, replays monitoring effects or sends
notifications.

Since Phase 7-C2-R1 the plan additionally separates record integrity from
authenticated authority: a persisted ``OWNER_AUTHORITY_VERIFIED`` claim on a
decision record is re-attested at plan time through an injected, library-only
:class:`OwnerDecisionVerifier` over the exact canonical record bytes and the
record's bound provenance.  Without such a trusted source the plan fails
closed with ``OWNER_AUTHORITY_REVERIFICATION_REQUIRED`` and can never be
READY, so a self-consistent forged VERIFIED record is inert here.  The
active decision record is also bound against the exact plan context (base,
target, manifest, fresh audit, exact exception set by id AND full content
hash) with granular stable blockers.

The plan additionally inventories every explicitly supplied affected
configuration/artifact (project default profile, watchlist references,
normalized-input profile ids, backtest dataset manifests with frozen
decision artifacts, Dashboard surface projections, monitoring runner
configs).  Historical artifacts are always preserved: their profile ids are
labelled, never rewritten, and foreign/missing/unreadable references become
specific blockers instead of silent migrations.  A plan without a project
configuration is explicitly blocked, and a monitoring runner config's
referenced watchlist must be inventoried explicitly (resolved against the
runner config's directory) or the plan blocks.

The Chinese decision dossier generated here is the required automation
output *before* any real owner acceptance is requested: exact hashes, the
threshold relationship, the 13% behavioural contrast, the observed divergence
interval and the accept/reject effects, with the explicit statement that
this is synthetic boundary evidence rather than performance proof.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .materialization_pair import _regular_file_bytes
from .owner_decision import (
    OwnerAuthorityAssessmentV1,
    OwnerDecisionVerifier,
    OwnerPolicyDecisionRecordV1,
    OwnerPolicyDecisionRevocationV1,
    resolve_owner_decision_authority,
)
from .profile_semantic_audit import (
    ProfileSemanticAuditV1,
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)

HASH_PATTERN = r"^[0-9a-f]{64}$"

#: Fixed rollback exclusions: committed monitoring effects, delivered
#: notifications and frozen historical artifacts are never automatically
#: replayed or rewritten by a configuration rollback.
ROLLBACK_EXCLUSIONS: tuple[str, ...] = (
    "NO_AUTOMATIC_MONITORING_REPLAY",
    "NO_AUTOMATIC_NOTIFICATION_REPLAY",
    "NO_HISTORICAL_ARTIFACT_REWRITE",
)


class ActivationPlanError(ValueError):
    """Raised when an activation plan cannot be derived from the inputs."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Config inventory contracts
# ---------------------------------------------------------------------------


class ConfigReferenceV1(BaseModel):
    """One explicitly supplied affected configuration/artifact reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "PROJECT_DEFAULT_PROFILE",
        "WATCHLIST",
        "NORMALIZED_INPUT",
        "BACKTEST_DATASET_MANIFEST",
        "SURFACE_SNAPSHOT",
        "MONITORING_RUNNER_CONFIG",
    ]
    path: StrictStr = Field(min_length=1, max_length=2_048)
    profile_references: list[StrictStr] = Field(max_length=256)
    compatibility: Literal[
        "PROPOSED_MUTATION",
        "ALREADY_TARGET",
        "BASE_PINNED_PRESERVED",
        "FOREIGN",
        "NOT_PROFILE_SCOPED",
        "MISSING",
        "UNREADABLE",
    ]
    blocker_code: StrictStr | None = Field(default=None, max_length=128)
    detail: StrictStr = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        blocker_by_compatibility = {
            "ALREADY_TARGET": "DEFAULT_ALREADY_TARGET",
            "FOREIGN": "FOREIGN_PROFILE_REFERENCE",
            "MISSING": "MISSING_REFERENCE",
            "UNREADABLE": "UNREADABLE_REFERENCE",
        }
        if self.kind != "PROJECT_DEFAULT_PROFILE":
            # A historical/watchlist reference already using the target is
            # compatible; only the mutable project default is a no-op blocker.
            blocker_by_compatibility["ALREADY_TARGET"] = None
        if self.kind == "PROJECT_DEFAULT_PROFILE":
            blocker_by_compatibility["FOREIGN"] = "DEFAULT_NOT_BASE"
            blocker_by_compatibility["MISSING"] = "PROJECT_CONFIG_MISSING"
            blocker_by_compatibility["UNREADABLE"] = "PROJECT_CONFIG_UNREADABLE"
        if self.compatibility == "NOT_PROFILE_SCOPED":
            # A runner configuration is the only not-profile-scoped artifact,
            # and its single live reference (the watchlist) either is
            # inventoried explicitly (no blocker) or blocks the plan with the
            # specific incomplete-inventory code.
            if self.blocker_code not in (None, "RUNNER_WATCHLIST_NOT_INVENTORIED"):
                raise ValueError(
                    "blocker_code must be None or 'RUNNER_WATCHLIST_NOT_INVENTORIED' "
                    f"for compatibility 'NOT_PROFILE_SCOPED' "
                    f"(got {self.blocker_code!r})"
                )
            return self
        expected = blocker_by_compatibility.get(self.compatibility)
        if self.blocker_code != expected:
            raise ValueError(
                f"blocker_code must be {expected!r} for compatibility "
                f"{self.compatibility!r} (got {self.blocker_code!r})"
            )
        return self


def _classify_references(
    references: set[str], *, base_profile_id: str, target_profile_id: str
) -> tuple[str, str, str]:
    """Classify one artifact's profile references against base/target."""

    foreign = sorted(references - {base_profile_id, target_profile_id})
    if foreign:
        return (
            "FOREIGN",
            "FOREIGN_PROFILE_REFERENCE",
            f"references profiles {foreign} that are neither the current default "
            f"{base_profile_id!r} nor the proposed {target_profile_id!r}; the "
            "artifact is preserved byte-for-byte and never rewritten",
        )
    if references == {target_profile_id}:
        return (
            "ALREADY_TARGET",
            "",
            f"already references the proposed profile {target_profile_id!r}",
        )
    if target_profile_id in references:
        return (
            "ALREADY_TARGET",
            "",
            f"references the proposed profile {target_profile_id!r} (among "
            f"{sorted(references)})",
        )
    return (
        "BASE_PINNED_PRESERVED",
        "",
        f"pinned to the prior profile {base_profile_id!r}; preserved "
        "byte-for-byte under the still-published prior profile and never "
        "rewritten — new analyses under the proposed default would use "
        f"{target_profile_id!r}",
    )


def inventory_activation_config_references(
    *,
    base_profile_id: str,
    target_profile_id: str,
    project_config_path: str | Path | None = None,
    watchlist_paths: Sequence[str | Path] = (),
    normalized_input_paths: Sequence[str | Path] = (),
    backtest_manifest_paths: Sequence[str | Path] = (),
    surface_snapshot_paths: Sequence[str | Path] = (),
    runner_config_paths: Sequence[str | Path] = (),
) -> list[ConfigReferenceV1]:
    """Inventory explicitly supplied affected configurations, read-only."""

    references: list[ConfigReferenceV1] = []

    if project_config_path is not None:
        path = Path(project_config_path)
        if not path.is_file():
            references.append(
                ConfigReferenceV1(
                    kind="PROJECT_DEFAULT_PROFILE",
                    path=str(path),
                    profile_references=[],
                    compatibility="MISSING",
                    blocker_code="PROJECT_CONFIG_MISSING",
                    detail="the project runtime configuration file does not exist",
                )
            )
        else:
            try:
                from turtle_value_engine.config import load_project_config

                default_profile = load_project_config(path).profiles.default
            except Exception as exc:
                references.append(
                    ConfigReferenceV1(
                        kind="PROJECT_DEFAULT_PROFILE",
                        path=str(path),
                        profile_references=[],
                        compatibility="UNREADABLE",
                        blocker_code="PROJECT_CONFIG_UNREADABLE",
                        detail=f"project configuration cannot be parsed: {str(exc)[:300]}",
                    )
                )
            else:
                if default_profile == base_profile_id:
                    compatibility, blocker, detail = (
                        "PROPOSED_MUTATION",
                        "",
                        f"[profiles] default is {base_profile_id!r}; the plan "
                        f"proposes exactly one mutation, default -> "
                        f"{target_profile_id!r}",
                    )
                elif default_profile == target_profile_id:
                    compatibility, blocker, detail = (
                        "ALREADY_TARGET",
                        "DEFAULT_ALREADY_TARGET",
                        f"[profiles] default is already {target_profile_id!r}; the "
                        "proposed mutation would be a no-op",
                    )
                else:
                    compatibility, blocker, detail = (
                        "FOREIGN",
                        "DEFAULT_NOT_BASE",
                        f"[profiles] default is {default_profile!r}, neither the "
                        f"expected current {base_profile_id!r} nor the proposed "
                        f"{target_profile_id!r}; the plan cannot be coherent",
                    )
                references.append(
                    ConfigReferenceV1(
                        kind="PROJECT_DEFAULT_PROFILE",
                        path=str(path),
                        profile_references=[default_profile],
                        compatibility=compatibility,  # type: ignore[arg-type]
                        blocker_code=blocker or None,
                        detail=detail,
                    )
                )

    def _append_inventory_entry(
        kind: str,
        path: Path,
        extract,
    ) -> None:
        if not path.is_file():
            references.append(
                ConfigReferenceV1(
                    kind=kind,  # type: ignore[arg-type]
                    path=str(path),
                    profile_references=[],
                    compatibility="MISSING",
                    blocker_code="MISSING_REFERENCE",
                    detail="the referenced artifact does not exist",
                )
            )
            return
        try:
            found = extract(_regular_file_bytes(path))
        except Exception as exc:
            references.append(
                ConfigReferenceV1(
                    kind=kind,  # type: ignore[arg-type]
                    path=str(path),
                    profile_references=[],
                    compatibility="UNREADABLE",
                    blocker_code="UNREADABLE_REFERENCE",
                    detail=f"artifact cannot be validated: {str(exc)[:300]}",
                )
            )
            return
        compatibility, blocker, detail = _classify_references(
            found, base_profile_id=base_profile_id, target_profile_id=target_profile_id
        )
        references.append(
            ConfigReferenceV1(
                kind=kind,  # type: ignore[arg-type]
                path=str(path),
                profile_references=sorted(found),
                compatibility=compatibility,  # type: ignore[arg-type]
                blocker_code=blocker or None,
                detail=detail,
            )
        )

    for raw_path in watchlist_paths:
        path = Path(raw_path)

        def _extract_watchlist(raw: bytes) -> set[str]:
            from turtle_value_engine.monitoring import WatchlistSpecV1

            return {WatchlistSpecV1.model_validate(json.loads(raw)).profile_id}

        _append_inventory_entry("WATCHLIST", path, _extract_watchlist)

    for raw_path in normalized_input_paths:
        path = Path(raw_path)

        def _extract_normalized_input(raw: bytes) -> set[str]:
            from turtle_value_engine.input_loader import parse_normalized_input

            return {parse_normalized_input(raw).profile_id}

        _append_inventory_entry("NORMALIZED_INPUT", path, _extract_normalized_input)

    for raw_path in backtest_manifest_paths:
        path = Path(raw_path)

        def _extract_backtest_manifest(raw: bytes) -> set[str]:
            from turtle_value_engine.backtest import BacktestDatasetManifest

            manifest = BacktestDatasetManifest.model_validate(json.loads(raw))
            found: set[str] = set()
            for artifact in manifest.decision_artifacts:
                if artifact.normalized_input is not None:
                    found.add(artifact.normalized_input.profile_id)
                if artifact.analysis is not None:
                    found.add(artifact.analysis.profile_id)
            return found

        _append_inventory_entry(
            "BACKTEST_DATASET_MANIFEST", path, _extract_backtest_manifest
        )

    for raw_path in surface_snapshot_paths:
        path = Path(raw_path)

        def _extract_surface_snapshot(raw: bytes) -> set[str]:
            from turtle_value_engine.surface.contracts import (
                ResearchSurfaceSnapshotV1,
            )

            return {ResearchSurfaceSnapshotV1.model_validate(json.loads(raw)).profile_id}

        _append_inventory_entry("SURFACE_SNAPSHOT", path, _extract_surface_snapshot)

    # Runner configurations are not profile-scoped, but each one binds exactly
    # one live watchlist path.  A claimed-complete inventory must have that
    # reference inventoried explicitly: relative runner watchlist paths are
    # resolved against the runner configuration's own directory (absolute
    # references are used as-is), and the comparison is on resolved paths.
    supplied_watchlists = {
        Path(raw_path).resolve() for raw_path in watchlist_paths
    }

    for raw_path in runner_config_paths:
        path = Path(raw_path)

        def _extract_runner_config(raw: bytes) -> dict:
            from turtle_value_engine.monitoring_runner import RunnerConfigV1

            runner = RunnerConfigV1.model_validate(json.loads(raw))
            return runner.model_dump(mode="json")

        if not path.is_file():
            references.append(
                ConfigReferenceV1(
                    kind="MONITORING_RUNNER_CONFIG",
                    path=str(path),
                    profile_references=[],
                    compatibility="MISSING",
                    blocker_code="MISSING_REFERENCE",
                    detail="the referenced runner configuration does not exist",
                )
            )
            continue
        try:
            runner_payload = _extract_runner_config(_regular_file_bytes(path))
            watchlist_path = runner_payload["watchlist_path"]
            resolved_watchlist = (path.parent / watchlist_path).resolve()
        except Exception as exc:
            references.append(
                ConfigReferenceV1(
                    kind="MONITORING_RUNNER_CONFIG",
                    path=str(path),
                    profile_references=[],
                    compatibility="UNREADABLE",
                    blocker_code="UNREADABLE_REFERENCE",
                    detail=f"runner configuration cannot be validated: {str(exc)[:300]}",
                )
            )
            continue
        if resolved_watchlist in supplied_watchlists:
            references.append(
                ConfigReferenceV1(
                    kind="MONITORING_RUNNER_CONFIG",
                    path=str(path),
                    profile_references=[],
                    compatibility="NOT_PROFILE_SCOPED",
                    blocker_code=None,
                    detail=(
                        "runner configuration is not profile-scoped; it binds "
                        f"watchlist_path {watchlist_path!r} (resolved "
                        f"{resolved_watchlist}), which is inventoried explicitly "
                        "as a WATCHLIST reference in this plan"
                    ),
                )
            )
        else:
            references.append(
                ConfigReferenceV1(
                    kind="MONITORING_RUNNER_CONFIG",
                    path=str(path),
                    profile_references=[],
                    compatibility="NOT_PROFILE_SCOPED",
                    blocker_code="RUNNER_WATCHLIST_NOT_INVENTORIED",
                    detail=(
                        "runner configuration is not profile-scoped; it binds "
                        f"watchlist_path {watchlist_path!r} (resolved "
                        f"{resolved_watchlist}), which was NOT supplied as a "
                        "watchlist reference — the live runtime inventory is "
                        "incomplete, so no READY can be claimed"
                    ),
                )
            )

    return references


# ---------------------------------------------------------------------------
# Rollback and plan contracts
# ---------------------------------------------------------------------------


class RollbackPlanV1(BaseModel):
    """Deterministic rollback reference for the proposed activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prior_project_config_path: StrictStr | None = Field(
        default=None, max_length=2_048
    )
    prior_project_config_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    prior_default_profile: StrictStr | None = Field(default=None, max_length=128)
    expected_current_state: StrictStr = Field(min_length=1, max_length=2_000)
    restoration_steps: list[StrictStr] = Field(min_length=1, max_length=32)
    exclusions: list[StrictStr] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_rollback(self) -> Self:
        if self.exclusions != list(ROLLBACK_EXCLUSIONS):
            raise ValueError(
                "rollback exclusions are fixed: no monitoring/notification replay "
                "and no historical-artifact rewrite"
            )
        return self


class ProfileActivationPlanV1(BaseModel):
    """Immutable read-only activation plan; execution never happens here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_plan_v1"] = "profile_activation_plan_v1"
    plan_id: StrictStr = Field(min_length=1)
    current_profile_id: StrictStr = Field(min_length=1)
    current_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    proposed_profile_id: StrictStr = Field(min_length=1)
    proposed_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    release_manifest_id: StrictStr = Field(min_length=1)
    release_manifest_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    audit_id: StrictStr = Field(min_length=1)
    audit_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    audit_activation_readiness: StrictStr = Field(min_length=1, max_length=64)
    audit_policy_decision_reasons: list[StrictStr] = Field(max_length=64)
    decision_authority_state: StrictStr = Field(min_length=1, max_length=64)
    authority_reverification_status: Literal[
        "NOT_APPLICABLE",
        "REVERIFIED",
        "REVERIFICATION_REQUIRED",
        "REVERIFICATION_FAILED",
    ]
    decision_record_id: StrictStr | None = Field(default=None, min_length=1)
    decision_record_content_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    decision: Literal["ACCEPT_WITH_EXCEPTION", "REJECT"] | None = None
    config_inventory: list[ConfigReferenceV1] = Field(max_length=2_048)
    rollback: RollbackPlanV1
    blockers: list[StrictStr] = Field(max_length=128)
    plan_state: Literal["READY_FOR_EXPLICIT_OWNER_EXECUTION", "BLOCKED"]
    automatic_activation_allowed: Literal[False] = False
    execution_performed: Literal[False] = False
    verified_decision_is_not_execution_request: Literal[True] = True
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION":
            if self.blockers:
                raise ValueError("a ready plan carries no blockers")
            if self.decision != "ACCEPT_WITH_EXCEPTION":
                raise ValueError("a ready plan requires an accepted decision")
            if self.decision_authority_state != "ACCEPT_VERIFIED":
                raise ValueError("a ready plan requires verified owner authority")
            if self.authority_reverification_status != "REVERIFIED":
                raise ValueError(
                    "a ready plan requires authority that was independently "
                    "re-attested at plan time from a trusted verifier, never a "
                    "persisted record claim"
                )
            if self.audit_activation_readiness != "READY_FOR_POLICY_DECISION":
                raise ValueError("a ready plan requires a machine-clean fresh audit")
        else:
            if not self.blockers:
                raise ValueError("a blocked plan requires blockers")
        expected_id = deterministic_id(
            "profile-activation-plan",
            self.current_profile_id,
            self.current_profile_sha256,
            self.proposed_profile_id,
            self.proposed_profile_sha256,
            self.release_manifest_id,
            self.release_manifest_content_sha256,
            self.audit_id,
            self.audit_content_sha256,
            self.decision_authority_state,
            self.authority_reverification_status,
            self.decision_record_id or "",
            self.decision_record_content_sha256 or "",
            sorted(self.blockers),
            sorted(
                f"{item.kind}:{item.path}:{item.compatibility}"
                for item in self.config_inventory
            ),
        )
        if self.plan_id != expected_id:
            raise ValueError("plan id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected_content:
            raise ValueError("plan content_sha256 does not match content")
        return self


# ---------------------------------------------------------------------------
# Plan derivation
# ---------------------------------------------------------------------------


def _reverify_decision_authority(
    *,
    record: OwnerPolicyDecisionRecordV1,
    authority_verifier: OwnerDecisionVerifier | None,
) -> tuple[str, list[str]]:
    """Independently re-attest a persisted ``OWNER_AUTHORITY_VERIFIED`` claim.

    A record's serialized ``authority`` text and its self-recomputed content
    hash prove record integrity, never authenticated authority (C2-R1 R1-A).
    Authority for a plan is therefore re-assessed here against a trusted
    injected verifier over the exact canonical record bytes and the record's
    bound provenance; without such a source the plan fails closed — a forged
    VERIFIED record can never reach READY through this path.  The verifier
    interface stays library-only: the production CLI constructs none.
    """

    if authority_verifier is None:
        return (
            "REVERIFICATION_REQUIRED",
            ["OWNER_AUTHORITY_REVERIFICATION_REQUIRED"],
        )

    blockers: list[str] = []
    if (
        record.provenance.source_content_sha256 is None
        or not record.provenance.source_revision
    ):
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_PROVENANCE_INCOMPLETE")

    assessment: OwnerAuthorityAssessmentV1 | None = None
    try:
        record_bytes = canonical_json_bytes(record.model_dump(mode="json"))
        assessment = authority_verifier.verify_decision_authority(
            declared_owner_identity=record.declared_owner_identity,
            provenance=record.provenance,
            decision_source_bytes=record_bytes,
        )
    except Exception as exc:
        return (
            "REVERIFICATION_FAILED",
            [f"OWNER_AUTHORITY_REVERIFICATION_ERRORED:{str(exc)[:120]}"],
        )

    if assessment.authority_status == "OWNER_AUTHORITY_REJECTED":
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_REJECTED")
    elif assessment.authority_status != "OWNER_AUTHORITY_VERIFIED":
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_UNVERIFIED")
    if assessment.verification_method != "INJECTED_VERIFIER" or (
        not assessment.verifier_kind
    ):
        # A VERIFIED claim whose own method says there is no authenticated
        # source is self-contradictory, whatever text it carries.
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_METHOD_INVALID")
    if assessment.evidence_content_sha256 != _sha256_hex(record_bytes):
        # Evidence absent from, or not bound to, these exact record bytes
        # attests something else.
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_EVIDENCE_MISMATCH")
    if assessment.allowlist_matched is False:
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_ALLOWLIST_MISMATCH")
    elif assessment.allowlist_matched is None:
        # Absence of a positive identity authorization result is not proof.
        blockers.append("OWNER_AUTHORITY_REVERIFICATION_ALLOWLIST_UNCONFIRMED")

    if blockers:
        return ("REVERIFICATION_FAILED", blockers)
    return ("REVERIFIED", [])


def plan_profile_activation(
    *,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    boundary_input=None,
    decision_records: Sequence[OwnerPolicyDecisionRecordV1] = (),
    revocations: Sequence[OwnerPolicyDecisionRevocationV1] = (),
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
    authority_verifier: OwnerDecisionVerifier | None = None,
    project_config_path: str | Path | None = None,
    watchlist_paths: Sequence[str | Path] = (),
    normalized_input_paths: Sequence[str | Path] = (),
    backtest_manifest_paths: Sequence[str | Path] = (),
    surface_snapshot_paths: Sequence[str | Path] = (),
    runner_config_paths: Sequence[str | Path] = (),
) -> ProfileActivationPlanV1:
    """Derive one read-only activation plan from fresh evidence, never trust
    a previous dossier's self-reported readiness or a persisted authority
    claim.

    The active decision record is bound against the exact plan context
    (base/target profile ids and byte hashes, release manifest id and content
    hash, fresh audit id and content hash, and the exact exception set by id
    AND full content hash).  A ``OWNER_AUTHORITY_VERIFIED`` claim on the
    record is additionally re-attested through ``authority_verifier`` — an
    injected, library-only trusted source; without one the plan fails closed
    with ``OWNER_AUTHORITY_REVERIFICATION_REQUIRED`` and can never be READY.
    Revocations are unauthenticated bookkeeping: any revocation that
    withdraws a record of this plan's exact target blocks the plan with
    ``OWNER_REVOCATION_AUTHORITY_UNVERIFIED`` until a versioned signed
    revocation protocol exists.
    """

    from turtle_value_engine.evolution.profile_release import (
        VersionedProfileReleaseCandidateV1,
    )

    base_bytes = _regular_file_bytes(Path(base_profile_path))
    target_bytes = _regular_file_bytes(Path(target_profile_path))
    manifest_bytes = _regular_file_bytes(Path(release_manifest_path))
    base_sha = _sha256_hex(base_bytes)
    target_sha = _sha256_hex(target_bytes)
    try:
        base_profile = yaml.safe_load(base_bytes)
        target_profile = yaml.safe_load(target_bytes)
        base_id = base_profile["profile"]["id"]
        target_id = target_profile["profile"]["id"]
        manifest = VersionedProfileReleaseCandidateV1.model_validate(
            json.loads(manifest_bytes)
        )
    except Exception as exc:
        raise ActivationPlanError(f"PLAN_INPUTS_UNREADABLE: {str(exc)[:300]}") from exc

    records_by_id = {record.decision_record_id: record for record in decision_records}
    resolution = resolve_owner_decision_authority(
        target_profile_id=target_id,
        target_profile_sha256=target_sha,
        records=list(decision_records),
        revocations=list(revocations),
    )

    blockers: list[str] = []
    # A revocation is unauthenticated bookkeeping: until a versioned signed
    # revocation protocol exists, no revocation may shape what this plan
    # authorizes.  The resolver applies every structurally valid revocation
    # at face value, so a forged revocation of a dissenting REJECT would
    # otherwise collapse a CONFLICTING set onto a single signed ACCEPT and
    # reach READY.  Any revocation that withdraws a record of THIS plan's
    # exact target therefore blocks the plan; withdrawing a decision can
    # never increase what the remaining set authorizes.
    revoked_current_ids = [
        record_id
        for record_id in resolution.revoked_record_ids
        if (withdrawn := records_by_id.get(record_id)) is not None
        and withdrawn.target_profile_id == target_id
        and withdrawn.target_profile_sha256 == target_sha
    ]
    if revoked_current_ids:
        blockers.append("OWNER_REVOCATION_AUTHORITY_UNVERIFIED")
    audit_exceptions = list(policy_exceptions)
    fresh_audit = audit_profile_semantics(
        base_profile_path=base_profile_path,
        target_profile_path=target_profile_path,
        release_manifest_path=release_manifest_path,
        boundary_input=boundary_input,
        policy_exceptions=audit_exceptions,
    )

    # R1-B: bind the active decision record to THIS plan's exact context.
    active_record = (
        records_by_id.get(resolution.active_decision_record_id or "")
        if resolution.active_decision_record_id is not None
        else None
    )
    if active_record is not None:
        if (
            active_record.base_profile_id != base_id
            or active_record.base_profile_sha256 != base_sha
        ):
            blockers.append("DECISION_BASE_BINDING_STALE")
        if (
            active_record.release_manifest_id != manifest.release_candidate_id
            or active_record.release_manifest_content_sha256 != manifest.content_sha256
        ):
            blockers.append("DECISION_MANIFEST_BINDING_STALE")
        if (
            active_record.audit_id != fresh_audit.audit_id
            or active_record.audit_content_sha256 != fresh_audit.content_sha256
        ):
            blockers.append("DECISION_AUDIT_BINDING_STALE")
        supplied_exception_pairs = sorted(
            (exception.exception_id, exception.content_sha256)
            for exception in audit_exceptions
        )
        if active_record.decision == "ACCEPT_WITH_EXCEPTION":
            bound_pair = (
                active_record.exception_id or "",
                active_record.exception_content_sha256 or "",
            )
            if bound_pair not in supplied_exception_pairs:
                blockers.append("DECISION_EXCEPTION_BINDING_STALE")
            if supplied_exception_pairs != [bound_pair]:
                blockers.append("DECISION_EXCEPTION_SET_MISMATCH")
        elif supplied_exception_pairs:
            blockers.append("DECISION_EXCEPTION_SET_MISMATCH")

    # R1-A: a persisted VERIFIED claim must be independently re-attested.
    reverification_status = "NOT_APPLICABLE"
    if resolution.resolved_state == "ACCEPT_VERIFIED" and active_record is not None:
        reverification_status, reverification_blockers = (
            _reverify_decision_authority(
                record=active_record,
                authority_verifier=authority_verifier,
            )
        )
        blockers.extend(reverification_blockers)

    state_blockers = {
        "NO_DECISION": {
            "NO_OWNER_DECISION_RECORD": "NO_OWNER_DECISION_RECORD",
            "ALL_RECORDS_STALE": "ALL_DECISION_RECORDS_STALE",
            "ALL_CURRENT_RECORDS_REVOKED": "ALL_CURRENT_DECISIONS_REVOKED",
            "ALL_CURRENT_RECORDS_SUPERSEDED_OR_REVOKED": (
                "ALL_CURRENT_DECISIONS_REVOKED"
            ),
        },
        "AMBIGUOUS": {"AMBIGUOUS_MULTIPLE_ACTIVE_RECORDS": "DECISIONS_AMBIGUOUS"},
        "CONFLICTING": {"CONFLICTING_DECISIONS": "DECISIONS_CONFLICTING"},
    }
    if resolution.resolved_state in state_blockers:
        mapping = state_blockers[resolution.resolved_state]
        blockers.extend(
            sorted({mapping[item] for item in resolution.blockers if item in mapping})
        )
    elif resolution.resolved_state == "REJECTED":
        blockers.append("DECISION_IS_REJECT")
    elif resolution.resolved_state == "ACCEPT_UNVERIFIED":
        blockers.append("OWNER_AUTHORITY_UNVERIFIED")
    elif resolution.resolved_state == "ACCEPT_AUTHORITY_REJECTED":
        blockers.append("OWNER_AUTHORITY_REJECTED")

    if fresh_audit.activation_readiness != "READY_FOR_POLICY_DECISION":
        blockers.append("AUDIT_NOT_READY")
        blockers.extend(fresh_audit.policy_decision_reasons)

    inventory = inventory_activation_config_references(
        base_profile_id=base_id,
        target_profile_id=target_id,
        project_config_path=project_config_path,
        watchlist_paths=watchlist_paths,
        normalized_input_paths=normalized_input_paths,
        backtest_manifest_paths=backtest_manifest_paths,
        surface_snapshot_paths=surface_snapshot_paths,
        runner_config_paths=runner_config_paths,
    )
    blockers.extend(
        item.blocker_code for item in inventory if item.blocker_code is not None
    )
    if project_config_path is None:
        # R1-D: a claimed-complete inventory cannot be derived without the
        # project runtime configuration whose default would change; the CLI
        # already requires it, and the library boundary must agree.
        blockers.append("PROJECT_CONFIG_REQUIRED")

    prior_config_sha: str | None = None
    prior_default: str | None = None
    if project_config_path is not None and Path(project_config_path).is_file():
        prior_config_sha = _sha256_hex(_regular_file_bytes(Path(project_config_path)))
        prior_default = next(
            (
                item.profile_references[0]
                for item in inventory
                if item.kind == "PROJECT_DEFAULT_PROFILE" and item.profile_references
            ),
            None,
        )

    config_location = (
        str(project_config_path)
        if project_config_path is not None
        else "the project configuration"
    )
    rollback = RollbackPlanV1(
        prior_project_config_path=(
            str(project_config_path) if project_config_path is not None else None
        ),
        prior_project_config_sha256=prior_config_sha,
        prior_default_profile=prior_default,
        expected_current_state=(
            f"[profiles] default is {prior_default or base_id!r}; "
            f"rules/{base_id}.yaml and rules/{target_id}.yaml bytes are "
            "unchanged (both profiles remain published); monitoring state, "
            "delivery ledgers, historical artifacts and surface projections "
            "are untouched by the activation step"
        ),
        restoration_steps=[
            f"restore [profiles] default from {target_id!r} back to "
            f"{prior_default or base_id!r} in {config_location} "
            f"(prior bytes sha256: {prior_config_sha or 'not supplied'})",
            f"re-run `tve evolution audit-profile` over rules/{base_id}.yaml "
            f"vs rules/{target_id}.yaml to re-confirm the prior readiness",
            "rebuild any Dashboard surface projection explicitly from new "
            "analyses if desired; committed monitoring runs and delivered "
            "notifications are immutable history and are never replayed",
        ],
        exclusions=list(ROLLBACK_EXCLUSIONS),
    )

    deduped_blockers = sorted(set(blockers))
    plan_state: Literal["READY_FOR_EXPLICIT_OWNER_EXECUTION", "BLOCKED"] = (
        "BLOCKED" if deduped_blockers else "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    )
    plan = ProfileActivationPlanV1.model_construct(
        contract="profile_activation_plan_v1",
        plan_id="pending",
        current_profile_id=base_id,
        current_profile_sha256=base_sha,
        proposed_profile_id=target_id,
        proposed_profile_sha256=target_sha,
        release_manifest_id=manifest.release_candidate_id,
        release_manifest_content_sha256=manifest.content_sha256,
        audit_id=fresh_audit.audit_id,
        audit_content_sha256=fresh_audit.content_sha256,
        audit_activation_readiness=fresh_audit.activation_readiness,
        audit_policy_decision_reasons=fresh_audit.policy_decision_reasons,
        decision_authority_state=resolution.resolved_state,
        authority_reverification_status=reverification_status,
        decision_record_id=resolution.active_decision_record_id,
        decision_record_content_sha256=(
            resolution.active_decision_record_content_sha256
        ),
        decision=resolution.active_decision,
        config_inventory=inventory,
        rollback=rollback,
        blockers=deduped_blockers,
        plan_state=plan_state,
        automatic_activation_allowed=False,
        execution_performed=False,
        verified_decision_is_not_execution_request=True,
        content_sha256="0" * 64,
    )
    payload = plan.model_dump(mode="json", warnings=False)
    payload["plan_id"] = deterministic_id(
        "profile-activation-plan",
        payload["current_profile_id"],
        payload["current_profile_sha256"],
        payload["proposed_profile_id"],
        payload["proposed_profile_sha256"],
        payload["release_manifest_id"],
        payload["release_manifest_content_sha256"],
        payload["audit_id"],
        payload["audit_content_sha256"],
        payload["decision_authority_state"],
        payload["authority_reverification_status"],
        payload["decision_record_id"] or "",
        payload["decision_record_content_sha256"] or "",
        sorted(payload["blockers"]),
        sorted(
            f"{item['kind']}:{item['path']}:{item['compatibility']}"
            for item in payload["config_inventory"]
        ),
    )
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return ProfileActivationPlanV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Chinese decision dossier (required before any real owner acceptance)
# ---------------------------------------------------------------------------


def build_owner_decision_dossier_markdown(
    *,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    audit: ProfileSemanticAuditV1,
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
) -> bytes:
    """Deterministic Chinese owner decision dossier from fresh audit evidence.

    Everything stated here is derived from the supplied bytes and the fresh
    audit — never from a previous dossier's self-reported state — and the
    document explicitly says the boundary evidence is synthetic and is not
    proof that the new thresholds improve investment performance.
    """

    target_payload = yaml.safe_load(_regular_file_bytes(Path(target_profile_path)))
    base_payload = yaml.safe_load(_regular_file_bytes(Path(base_profile_path)))
    target_bands = target_payload["cdc"]["yield_bands"]
    base_bands = base_payload["cdc"]["yield_bands"]
    target_tier = target_payload["valuation"]["tiers"]["extreme_safety"]["cdc_yield"]
    base_tier = base_payload["valuation"]["tiers"]["extreme_safety"]["cdc_yield"]

    diverging = [row for row in audit.gate_boundary_rows if row.diverges]
    if not diverging:
        raise ActivationPlanError(
            "DOSSIER_DIVERGENCE_UNAVAILABLE: the fresh audit observes no CDC gate "
            "divergence between the audited profiles"
        )
    window_low = diverging[0].cdc_yield
    window_high = next(
        row.cdc_yield
        for row in audit.gate_boundary_rows
        if not row.diverges and row.cdc_yield > window_low
    )
    changed_rows = [
        row for row in audit.pipeline_boundary_rows if row.decision_changed
    ]
    if not changed_rows:
        raise ActivationPlanError(
            "DOSSIER_DIVERGENCE_UNAVAILABLE: the fresh audit observes no "
            "end-to-end decision divergence between the audited profiles"
        )
    contrast = min(changed_rows, key=lambda row: abs(row.target_cdc_yield - 0.13))
    exception_section = ""
    for exception in policy_exceptions:
        exception_section += (
            f"- 策略例外：`{exception.exception_code}`，绑定 "
            f"`{exception.exception_id}` / 内容 SHA-256 "
            f"`{exception.content_sha256}`\n"
        )

    lines = [
        "# Turtle Value Engine — strict-v2 所有者政策决策材料",
        "",
        "本材料由确定性自动化在重新运行的 C1 语义审计之上生成，供所有者就已发布的",
        "strict-v2 做出唯一的人类决策。它是合成边界证据，不构成对投资表现改善的",
        "证明；发布、CI 成功与审计通过都不等于批准。",
        "",
        "## 1. 精确身份与哈希",
        "",
        f"- 基线档案：`{audit.base_profile_id}`，字节 SHA-256 "
        f"`{audit.base_profile_sha256}`",
        f"- 候选档案：`{audit.target_profile_id}`，字节 SHA-256 "
        f"`{audit.target_profile_sha256}`",
        f"- 发布清单：`{audit.release_manifest_id}`，内容 SHA-256 "
        f"`{audit.release_manifest_content_sha256}`",
        f"- 本次新审计：`{audit.audit_id}`，内容 SHA-256 "
        f"`{audit.content_sha256}`，就绪状态 "
        f"`{audit.activation_readiness}`",
    ]
    if exception_section:
        lines.append(exception_section.rstrip())
    lines.extend(
        [
            "",
            "## 2. 门槛关系（14% 门槛与 12% S 档/估值档）",
            "",
            f"- strict-v1：CDC 通过门槛 {base_bands['pass']}，S 档 "
            f"{base_bands['s']}，extreme_safety 估值档 CDC 门槛 {base_tier}。",
            f"- strict-v2：CDC 通过门槛提高到 {target_bands['pass']}，但 S 档仍为 "
            f"{target_bands['s']}，extreme_safety 估值档 CDC 门槛仍为 "
            f"{target_tier}。",
            f"- 未覆盖发现：{', '.join(audit.policy_decision_reasons) or '（无）'}。",
            "  即：通过门槛高于自家 S 档（CDC_BAND_ORDER_VIOLATION），且高于",
            "  extreme_safety 估值档门槛（CDC_GATE_TIER_COHERENCE_VIOLATION）——",
            "  满足最高估值档的收益率仍可能被资格门槛压到 WATCH。",
            "",
            "## 3. 13% 收益率行为对照（真实引擎回放）",
            "",
            f"- 合成边界收益率 {contrast.target_cdc_yield:.2%} 下：",
            f"  - strict-v1：门槛 {contrast.base_gate_status}，估值 "
            f"{contrast.base_valuation_state}，决策 {contrast.base_decision_state}"
            f"（自动允许={contrast.base_auto_decision_allowed}）。",
            f"  - strict-v2：门槛 {contrast.target_gate_status}，估值 "
            f"{contrast.target_valuation_state}，决策 {contrast.target_decision_state}"
            f"（自动允许={contrast.target_auto_decision_allowed}）。",
            f"  - 门槛分歧：{', '.join(contrast.gate_divergences) or '（无）'}；"
            f"估值扣留原因：{', '.join(contrast.withheld_valuation_reasons) or '（无）'}。",
            "",
            "## 4. 观察到的分歧区间",
            "",
            f"- CDC 门槛分歧区间为 [{window_low:.2%}, {window_high:.2%})：区间内 "
            "strict-v1 判 PASS 而 strict-v2 判 WATCH；区间外两者一致。",
            f"- 决策分歧行数 {audit.decision_divergence_count}，门槛分歧行数 "
            f"{audit.gate_divergence_count}（边界含 epsilon 探针，全部来自真实"
            "引擎回放）。",
            "",
            "## 5. 接受 / 拒绝的影响",
            "",
            "- 接受（ACCEPT_WITH_EXCEPTION）：声明 "
            "`CDC_GATE_ABOVE_S_BAND_PERMITTED` 策略例外，承认 14% 门槛有意高于 "
            "12% S 档；strict-v2 保持已发布字节，后续可进入单独评审的启用/回滚"
            "计划（本包只生成只读计划，不执行切换）。",
            "- 拒绝（REJECT）：strict-v2 作为已发布研究工件保留但不启用，默认档案 "
            "保持 strict-v1；修正后的门槛需要通过既有的 7-A→B1→B2 演化/发布链"
            "构建新的 strict-v3 发布，不允许原地修改 strict-v2 字节。",
            "",
            "## 6. 提交方式（唯一人类步骤）",
            "",
            "1. 通过既定的认证来源提交决策（本地无符号 JSON 只会被记录为"
            "未验证状态；EnvironmentFile 用户名、Git 作者、CI 成功与发布清单都"
            "不构成授权证明）。",
            "2. 决策输入 JSON 必须包含字段：decision、base_profile_id、"
            "base_profile_sha256、target_profile_id、target_profile_sha256、"
            "release_manifest_id、release_manifest_content_sha256、audit_id、"
            "audit_content_sha256、exception_id/exception_content_sha256（仅接受"
            "时）、rationale、declared_owner_identity、decided_at、"
            "source_revision。",
            "3. 用 `tve evolution record-decision` 验证并记录：所有哈希绑定、"
            "新鲜审计一致性与例外覆盖都会被重新检查。",
            "4. 预期结果：接受 + 精确例外 → 记录 VALID（授权状态单独显示）；"
            "拒绝 → 记录 VALID 且为终局非启用结果。",
            "5. 失败处理：DECLARED_BINDINGS_STALE 表示字节与声明不符（检查是否"
            "档案/清单已变化）；DECLARED_AUDIT_STALE 表示审计身份不匹配（用当前"
            "字节重新取得审计哈希）；EXCEPTION_BINDING_MISMATCH 表示例外 id 未变"
            "但内容哈希不符（内容被改动）；OWNER_IDENTITY_NOT_ALLOWLISTED 表示"
            "声明身份不在允许清单。缺少真实授权时，自动化只报告具体阻塞项和"
            "完成的只读计划，绝不声称已启用。",
            "",
            "## 7. 固定边界声明",
            "",
            "- 本材料是合成边界证据，不是 14% 门槛改善投资表现的证明。",
            "- 记录有效性与真实授权分离：无认证来源时记录保持可见的未验证状态。",
            "- 所有计划保持 execution_performed=false 与 "
            "automatic_activation_allowed=false；实际切换默认档案属于后续单独"
            "选择的包。",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


__all__ = [
    "ActivationPlanError",
    "ConfigReferenceV1",
    "ProfileActivationPlanV1",
    "ROLLBACK_EXCLUSIONS",
    "RollbackPlanV1",
    "build_owner_decision_dossier_markdown",
    "inventory_activation_config_references",
    "plan_profile_activation",
]
