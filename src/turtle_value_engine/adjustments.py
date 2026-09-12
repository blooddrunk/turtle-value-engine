"""Deterministic, evidence-backed adjustment proposal workflow.

The workflow persists the existing :class:`~turtle_value_engine.models.Adjustment`
contract rather than introducing another adjustment representation.  A small
on-disk envelope adds the evidence digests, optional normalized-input scope,
transition history and record hash needed for auditable offline replay.

This module accepts caller-supplied proposal values and reasons only.  It does
not infer accounting treatments, calculate adjusted values, mutate normalized
inputs or invoke a provider/model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    model_validator,
)

from turtle_value_engine.models import (
    Adjustment,
    Evidence,
    NormalizedCompanyInput,
)
from turtle_value_engine.models.common import AdjustmentStatus, ApprovedBy, ProposedBy
from turtle_value_engine.providers.errors import (
    AdjustmentWorkflowConflictError,
    AdjustmentWorkflowCorruptionError,
    AdjustmentWorkflowError,
    AdjustmentWorkflowMissError,
    AdjustmentWorkflowRequestError,
    AdjustmentWorkflowTransitionError,
    AdjustmentWorkflowWriteError,
    EvidenceStoreError,
    EvidenceStoreRequestError,
)
from turtle_value_engine.providers.evidence_store import FilingEvidenceStore
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

ADJUSTMENT_WORKFLOW_VERSION = "adjustment-workflow-v1"
ADJUSTMENT_WORKFLOW_CONTRACT = "adjustment_workflow_v1"
ADJUSTMENT_WORKFLOW_CACHE_FORMAT_VERSION = 1

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_ADJUSTMENT_ID_PATTERN = r"^adjustment-proposal-[0-9a-f]{24}$"
_APPROVAL_ACTORS = frozenset(actor.value for actor in ApprovedBy)

AdjustmentInput: TypeAlias = Adjustment | Mapping[str, object]
EvidenceInput: TypeAlias = Evidence | Mapping[str, object]
NormalizedInput: TypeAlias = NormalizedCompanyInput | Mapping[str, object]


class AdjustmentWorkflowEvidenceBinding(BaseModel):
    """Immutable evidence snapshot identity retained by one proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: StrictStr = Field(min_length=1)
    evidence_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    evidence_store_record_sha256: StrictStr | None = Field(
        default=None,
        pattern=_HASH_PATTERN,
    )


class AdjustmentWorkflowTransition(BaseModel):
    """One auditable lifecycle event for an existing Adjustment contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["PROPOSE", "ACCEPT", "REJECT"]
    status: AdjustmentStatus
    actor: Literal["RULE_ENGINE", "LLM", "HUMAN"]

    @model_validator(mode="after")
    def validate_action_status(self) -> AdjustmentWorkflowTransition:
        expected_status = {
            "PROPOSE": AdjustmentStatus.PROPOSED,
            "ACCEPT": AdjustmentStatus.ACCEPTED,
            "REJECT": AdjustmentStatus.REJECTED,
        }[self.action]
        if self.status is not expected_status:
            raise ValueError(f"{self.action} transition must use status {expected_status.value}")
        return self


class AdjustmentWorkflowScope(BaseModel):
    """Optional normalized-input context bound to a proposal identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    primary_listing: StrictStr = Field(min_length=1)


class AdjustmentWorkflowRecord(BaseModel):
    """Integrity-checked on-disk envelope around the existing Adjustment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cache_format_version: Literal[ADJUSTMENT_WORKFLOW_CACHE_FORMAT_VERSION] = (
        ADJUSTMENT_WORKFLOW_CACHE_FORMAT_VERSION
    )
    contract: Literal[ADJUSTMENT_WORKFLOW_CONTRACT] = ADJUSTMENT_WORKFLOW_CONTRACT
    adjustment: Adjustment
    evidence_bindings: list[AdjustmentWorkflowEvidenceBinding] = Field(min_length=1)
    scope: AdjustmentWorkflowScope | None = None
    transition_history: list[AdjustmentWorkflowTransition] = Field(min_length=1)
    record_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_consistency(self) -> AdjustmentWorkflowRecord:
        """Keep IDs, evidence references and lifecycle history internally closed."""

        expected_id = _expected_adjustment_id(self.adjustment, self.scope)
        if self.adjustment.id != expected_id:
            raise ValueError("adjustment ID does not match deterministic workflow identity")

        binding_ids = [binding.evidence_id for binding in self.evidence_bindings]
        if binding_ids != self.adjustment.source_evidence_ids:
            raise ValueError("evidence bindings must preserve adjustment evidence references")
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("evidence bindings must not contain duplicate IDs")

        first = self.transition_history[0]
        if (
            first.action != "PROPOSE"
            or first.status is not AdjustmentStatus.PROPOSED
            or first.actor != self.adjustment.proposed_by.value
        ):
            raise ValueError("workflow history must begin with the matching proposal actor")

        if self.adjustment.status is AdjustmentStatus.PROPOSED:
            if self.adjustment.approved_by is not None:
                raise ValueError("proposed adjustments must not contain approved_by")
            if len(self.transition_history) != 1:
                raise ValueError("proposed adjustment history cannot contain terminal transitions")
            return self

        if len(self.transition_history) != 2:
            raise ValueError("terminal adjustment history must contain exactly two transitions")
        terminal = self.transition_history[1]
        if self.adjustment.status is AdjustmentStatus.ACCEPTED:
            if terminal.action != "ACCEPT" or terminal.status is not AdjustmentStatus.ACCEPTED:
                raise ValueError("accepted adjustment history must end with ACCEPT")
            if terminal.actor not in _APPROVAL_ACTORS:
                raise ValueError("accepted adjustment history requires an approval actor")
            if self.adjustment.approved_by is None:
                raise ValueError("accepted adjustments require approved_by")
            if terminal.actor != self.adjustment.approved_by.value:
                raise ValueError("accepted adjustment approver must match terminal actor")
        elif self.adjustment.status is AdjustmentStatus.REJECTED:
            if terminal.action != "REJECT" or terminal.status is not AdjustmentStatus.REJECTED:
                raise ValueError("rejected adjustment history must end with REJECT")
            if terminal.actor not in _APPROVAL_ACTORS:
                raise ValueError("rejected adjustment history requires a review actor")
            if self.adjustment.approved_by is not None:
                raise ValueError("rejected adjustments must not contain approved_by")
        return self


def _coerce_adjustment(adjustment: AdjustmentInput) -> tuple[Adjustment, bool]:
    if isinstance(adjustment, Adjustment):
        payload = adjustment.model_dump(mode="python", warnings=False)
        supplied_id = True
    elif isinstance(adjustment, Mapping):
        payload = dict(adjustment)
        supplied_id = "id" in payload
        if not supplied_id:
            payload["id"] = "pending"
    else:
        raise TypeError("adjustment must be an Adjustment model or JSON object")

    try:
        return Adjustment.model_validate(payload), supplied_id
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid adjustment: {exc}") from exc


def _validated_normalized_input(value: NormalizedInput) -> NormalizedCompanyInput:
    try:
        if isinstance(value, NormalizedCompanyInput):
            payload = value.model_dump(mode="python", warnings=False)
        elif isinstance(value, Mapping):
            payload = value
        else:
            raise TypeError("normalized_input must be a NormalizedCompanyInput or JSON object")
        return NormalizedCompanyInput.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid normalized input: {exc}") from exc


def _scope_for(normalized_input: NormalizedCompanyInput | None) -> AdjustmentWorkflowScope | None:
    if normalized_input is None:
        return None
    return AdjustmentWorkflowScope(
        analysis_id=normalized_input.analysis_id,
        as_of=normalized_input.as_of,
        profile_id=normalized_input.profile_id,
        primary_listing=normalized_input.company.primary_listing,
    )


def _immutable_adjustment_payload(adjustment: Adjustment) -> dict[str, object]:
    payload = adjustment.model_dump(mode="json")
    return {
        "target_field": payload["target_field"],
        "adjustment_type": payload["adjustment_type"],
        "input_value": payload["input_value"],
        "proposed_adjusted_value": payload["proposed_adjusted_value"],
        "reason": payload["reason"],
        "source_evidence_ids": payload["source_evidence_ids"],
        "proposed_by": payload["proposed_by"],
        "confidence": payload["confidence"],
    }


def _identity_payload(
    adjustment: Adjustment,
    scope: AdjustmentWorkflowScope | None,
) -> dict[str, object]:
    return {
        "adjustment": _immutable_adjustment_payload(adjustment),
        "scope": scope.model_dump(mode="json") if scope is not None else None,
    }


def _expected_adjustment_id(
    adjustment: Adjustment,
    scope: AdjustmentWorkflowScope | None,
) -> str:
    return deterministic_id("adjustment-proposal", _identity_payload(adjustment, scope))


def adjustment_id_for(
    adjustment: AdjustmentInput,
    *,
    normalized_input: NormalizedInput | None = None,
) -> str:
    """Return the deterministic ID for one explicit PROPOSED adjustment."""

    try:
        candidate, _supplied_id = _coerce_adjustment(adjustment)
        _validate_proposal(candidate)
        normalized = (
            _validated_normalized_input(normalized_input)
            if normalized_input is not None
            else None
        )
        return _expected_adjustment_id(candidate, _scope_for(normalized))
    except AdjustmentWorkflowError:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise AdjustmentWorkflowRequestError(f"cannot derive adjustment ID: {exc}") from exc


def _coerce_evidence(evidence: EvidenceInput) -> Evidence:
    if isinstance(evidence, Evidence):
        payload = evidence.model_dump(mode="python", warnings=False)
    elif isinstance(evidence, Mapping):
        payload = dict(evidence)
    else:
        raise TypeError("evidence must be an Evidence model or JSON object")
    try:
        return Evidence.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid evidence: {exc}") from exc


def _evidence_digest(evidence: Evidence) -> str:
    return hashlib.sha256(canonical_json_bytes(evidence.model_dump(mode="json"))).hexdigest()


def _evidence_candidates(
    evidence_ids: Sequence[str],
    *,
    normalized_input: NormalizedCompanyInput | None,
    evidence_index: Iterable[EvidenceInput] | None,
    evidence_store: FilingEvidenceStore | None,
) -> tuple[tuple[Evidence, str | None], ...]:
    normalized_by_id: dict[str, Evidence] = {}
    explicit_by_id: dict[str, Evidence] = {}

    if normalized_input is not None:
        normalized_by_id = {evidence.id: evidence for evidence in normalized_input.evidence_index}

    if evidence_index is not None:
        for item in evidence_index:
            evidence = _coerce_evidence(item)
            if evidence.id in explicit_by_id:
                raise ValueError(f"evidence_index contains duplicate ID: {evidence.id}")
            explicit_by_id[evidence.id] = evidence

    if normalized_input is None and evidence_index is None and evidence_store is None:
        raise ValueError("one evidence resolver is required")

    resolved: list[tuple[Evidence, str | None]] = []
    for evidence_id in evidence_ids:
        candidates: list[tuple[Evidence, str | None]] = []
        if evidence_id in normalized_by_id:
            candidates.append((normalized_by_id[evidence_id], None))
        if evidence_id in explicit_by_id:
            candidates.append((explicit_by_id[evidence_id], None))
        if evidence_store is not None:
            try:
                record = evidence_store.read_record(evidence_id)
            except EvidenceStoreRequestError:
                record = None
            except EvidenceStoreError as exc:
                raise AdjustmentWorkflowCorruptionError(
                    f"cannot validate referenced evidence {evidence_id}: {exc}"
                ) from exc
            if record is not None:
                candidates.append((record.evidence, record.record_sha256))

        if not candidates:
            raise ValueError(f"unknown evidence ID: {evidence_id}")

        first_evidence, first_record_hash = candidates[0]
        first_payload = canonical_json_bytes(first_evidence.model_dump(mode="json"))
        for candidate, _record_hash in candidates[1:]:
            if canonical_json_bytes(candidate.model_dump(mode="json")) != first_payload:
                raise AdjustmentWorkflowConflictError(
                    f"conflicting evidence records for ID: {evidence_id}"
                )
        store_record_hash = next(
            (record_hash for _candidate, record_hash in candidates if record_hash is not None),
            first_record_hash,
        )
        resolved.append((first_evidence, store_record_hash))
    return tuple(resolved)


def _evidence_bindings_for(
    evidence_ids: Sequence[str],
    *,
    normalized_input: NormalizedCompanyInput | None,
    evidence_index: Iterable[EvidenceInput] | None,
    evidence_store: FilingEvidenceStore | None,
) -> list[AdjustmentWorkflowEvidenceBinding]:
    candidates = _evidence_candidates(
        evidence_ids,
        normalized_input=normalized_input,
        evidence_index=evidence_index,
        evidence_store=evidence_store,
    )
    return [
        AdjustmentWorkflowEvidenceBinding(
            evidence_id=evidence.id,
            evidence_sha256=_evidence_digest(evidence),
            evidence_store_record_sha256=store_record_hash,
        )
        for evidence, store_record_hash in candidates
    ]


def _validate_proposal(adjustment: Adjustment) -> None:
    if adjustment.status is not AdjustmentStatus.PROPOSED:
        raise ValueError("workflow creation accepts only PROPOSED adjustments")
    if adjustment.approved_by is not None:
        raise ValueError("proposed adjustments must not contain approved_by")


def _approval_actor(actor: ApprovedBy | ProposedBy | str) -> ApprovedBy:
    try:
        return ApprovedBy(actor)
    except (TypeError, ValueError) as exc:
        raise ValueError("transition actor must be HUMAN or RULE_ENGINE") from exc


def _proposal_actor(actor: ProposedBy | str | None, adjustment: Adjustment) -> None:
    if actor is None:
        return
    try:
        supplied = ProposedBy(actor)
    except (TypeError, ValueError) as exc:
        raise ValueError("proposer must be RULE_ENGINE, LLM or HUMAN") from exc
    if supplied is not adjustment.proposed_by:
        raise ValueError("proposer does not match adjustment.proposed_by")


def _record_without_hash(record: AdjustmentWorkflowRecord) -> dict[str, object]:
    return record.model_dump(mode="json", exclude={"record_sha256"})


def _record_with_hash(record: AdjustmentWorkflowRecord) -> AdjustmentWorkflowRecord:
    digest = hashlib.sha256(canonical_json_bytes(_record_without_hash(record))).hexdigest()
    return AdjustmentWorkflowRecord.model_validate(
        record.model_copy(update={"record_sha256": digest}).model_dump(
            mode="python", warnings=False
        )
    )


def _record_for(
    adjustment: Adjustment,
    bindings: list[AdjustmentWorkflowEvidenceBinding],
    scope: AdjustmentWorkflowScope | None,
) -> AdjustmentWorkflowRecord:
    record = AdjustmentWorkflowRecord(
        adjustment=adjustment,
        evidence_bindings=bindings,
        scope=scope,
        transition_history=[
            AdjustmentWorkflowTransition(
                action="PROPOSE",
                status=AdjustmentStatus.PROPOSED,
                actor=adjustment.proposed_by.value,
            )
        ],
        record_sha256="0" * 64,
    )
    return _record_with_hash(record)


def _record_from_file(path: Path) -> AdjustmentWorkflowRecord:
    if path.is_symlink() or not path.is_file():
        raise AdjustmentWorkflowCorruptionError(
            f"adjustment workflow entry is not a regular file: {path}"
        )
    try:
        with path.open("rb") as handle:
            payload = json.load(handle, parse_constant=_reject_non_json_number)
        record = AdjustmentWorkflowRecord.model_validate(payload)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise AdjustmentWorkflowCorruptionError(
            f"invalid adjustment workflow entry {path}: {exc}"
        ) from exc
    if path.stem != record.adjustment.id:
        raise AdjustmentWorkflowCorruptionError(
            f"adjustment workflow filename does not match adjustment ID: {path}"
        )
    expected_hash = hashlib.sha256(canonical_json_bytes(_record_without_hash(record))).hexdigest()
    if record.record_sha256 != expected_hash:
        raise AdjustmentWorkflowCorruptionError(
            f"adjustment workflow record hash mismatch: {path}"
        )
    return record


def _same_proposal(
    stored: AdjustmentWorkflowRecord,
    requested: AdjustmentWorkflowRecord,
) -> bool:
    return (
        _immutable_adjustment_payload(stored.adjustment)
        == _immutable_adjustment_payload(requested.adjustment)
        and stored.scope == requested.scope
        and stored.evidence_bindings == requested.evidence_bindings
    )


def _validate_scope(
    record: AdjustmentWorkflowRecord,
    normalized_input: NormalizedCompanyInput | None,
) -> None:
    if normalized_input is None:
        return
    expected_scope = _scope_for(normalized_input)
    if record.scope != expected_scope:
        raise ValueError("workflow scope does not match normalized input")


def _validate_bindings(
    record: AdjustmentWorkflowRecord,
    *,
    normalized_input: NormalizedCompanyInput | None,
    evidence_index: Iterable[EvidenceInput] | None,
    evidence_store: FilingEvidenceStore | None,
) -> None:
    if normalized_input is None and evidence_index is None and evidence_store is None:
        return
    bindings = _evidence_bindings_for(
        record.adjustment.source_evidence_ids,
        normalized_input=normalized_input,
        evidence_index=evidence_index,
        evidence_store=evidence_store,
    )
    if bindings != record.evidence_bindings:
        raise ValueError("referenced evidence does not match persisted workflow provenance")


def _atomic_create(path: Path, serialized: bytes) -> None:
    temporary_path: Path | None = None
    descriptor = -1
    try:
        _ensure_directory(path.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, path)
        temporary_path.unlink()
        temporary_path = None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _atomic_replace(path: Path, serialized: bytes) -> None:
    temporary_path: Path | None = None
    descriptor = -1
    try:
        _ensure_directory(path.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _serialized(record: AdjustmentWorkflowRecord) -> bytes:
    return canonical_json_bytes(record.model_dump(mode="json")) + b"\n"


def _ensure_directory(directory: Path) -> None:
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise OSError(f"adjustment workflow path is not a directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise OSError(f"adjustment workflow path is not a directory: {directory}")


def _reject_non_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


class AdjustmentProposalWorkflow:
    """Filesystem-backed workflow for explicit Adjustment proposals."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, adjustment_id: str) -> Path:
        """Return the exact path for one deterministic proposal ID."""

        if not isinstance(adjustment_id, str) or not re.fullmatch(
            _ADJUSTMENT_ID_PATTERN, adjustment_id
        ):
            raise ValueError("adjustment_id must be a deterministic proposal ID")
        return self.root / "adjustments" / f"{adjustment_id}.json"

    def append(
        self,
        adjustment: AdjustmentInput,
        *,
        proposer: ProposedBy | str | None = None,
        normalized_input: NormalizedInput | None = None,
        evidence_index: Iterable[EvidenceInput] | None = None,
        evidence_store: FilingEvidenceStore | None = None,
    ) -> Adjustment:
        """Persist one explicit PROPOSED adjustment, idempotently."""

        try:
            candidate, supplied_id = _coerce_adjustment(adjustment)
            _validate_proposal(candidate)
            _proposal_actor(proposer, candidate)
            normalized = (
                _validated_normalized_input(normalized_input)
                if normalized_input is not None
                else None
            )
            scope = _scope_for(normalized)
            expected_id = _expected_adjustment_id(candidate, scope)
            if supplied_id and candidate.id != expected_id:
                raise ValueError("supplied adjustment ID is not deterministic")
            canonical_adjustment = Adjustment.model_validate(
                candidate.model_copy(update={"id": expected_id}).model_dump(
                    mode="python", warnings=False
                )
            )
            bindings = _evidence_bindings_for(
                canonical_adjustment.source_evidence_ids,
                normalized_input=normalized,
                evidence_index=evidence_index,
                evidence_store=evidence_store,
            )
            record = _record_for(canonical_adjustment, bindings, scope)
        except AdjustmentWorkflowError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise AdjustmentWorkflowRequestError(
                f"invalid adjustment proposal request: {exc}"
            ) from exc

        path = self.path_for(record.adjustment.id)
        if path.exists() or path.is_symlink():
            existing = _record_from_file(path)
            if _same_proposal(existing, record):
                return existing.adjustment
            raise AdjustmentWorkflowConflictError(
                f"adjustment ID already stores a different proposal: {record.adjustment.id}"
            )

        try:
            _atomic_create(path, _serialized(record))
        except FileExistsError:
            existing = _record_from_file(path)
            if _same_proposal(existing, record):
                return existing.adjustment
            raise AdjustmentWorkflowConflictError(
                f"adjustment ID already stores a different proposal: {record.adjustment.id}"
            )
        except (OSError, TypeError, ValueError) as exc:
            raise AdjustmentWorkflowWriteError(
                f"cannot write adjustment workflow entry {path}: {exc}"
            ) from exc
        return record.adjustment

    def upsert(self, adjustment: AdjustmentInput, **kwargs: object) -> Adjustment:
        """Idempotent append alias; lifecycle changes require ``transition``."""

        return self.append(adjustment, **kwargs)  # type: ignore[arg-type]

    create = append

    def read_record(
        self,
        adjustment_id: str,
        *,
        normalized_input: NormalizedInput | None = None,
        evidence_index: Iterable[EvidenceInput] | None = None,
        evidence_store: FilingEvidenceStore | None = None,
    ) -> AdjustmentWorkflowRecord | None:
        """Read one integrity-checked local record, optionally rebind it."""

        try:
            path = self.path_for(adjustment_id)
        except (TypeError, ValueError) as exc:
            raise AdjustmentWorkflowRequestError(f"invalid adjustment ID: {exc}") from exc
        if not path.exists() and not path.is_symlink():
            return None
        record = _record_from_file(path)
        try:
            normalized = (
                _validated_normalized_input(normalized_input)
                if normalized_input is not None
                else None
            )
            _validate_scope(record, normalized)
            _validate_bindings(
                record,
                normalized_input=normalized,
                evidence_index=evidence_index,
                evidence_store=evidence_store,
            )
        except AdjustmentWorkflowError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise AdjustmentWorkflowRequestError(
                f"stored adjustment does not match requested provenance: {exc}"
            ) from exc
        return record

    def read(
        self,
        adjustment_id: str,
        *,
        normalized_input: NormalizedInput | None = None,
        evidence_index: Iterable[EvidenceInput] | None = None,
        evidence_store: FilingEvidenceStore | None = None,
    ) -> Adjustment | None:
        """Read one existing Adjustment without any network access."""

        record = self.read_record(
            adjustment_id,
            normalized_input=normalized_input,
            evidence_index=evidence_index,
            evidence_store=evidence_store,
        )
        return None if record is None else record.adjustment

    get = read

    def replay(
        self,
        adjustment_id: str,
        *,
        normalized_input: NormalizedInput | None = None,
        evidence_index: Iterable[EvidenceInput] | None = None,
        evidence_store: FilingEvidenceStore | None = None,
    ) -> Adjustment:
        """Require and return one verified offline proposal replay."""

        adjustment = self.read(
            adjustment_id,
            normalized_input=normalized_input,
            evidence_index=evidence_index,
            evidence_store=evidence_store,
        )
        if adjustment is None:
            raise AdjustmentWorkflowMissError(
                f"no replayable adjustment proposal: {adjustment_id}"
            )
        return adjustment

    def transition(
        self,
        adjustment_id: str,
        status: AdjustmentStatus | str,
        *,
        actor: ApprovedBy | ProposedBy | str,
        normalized_input: NormalizedInput | None = None,
        evidence_index: Iterable[EvidenceInput] | None = None,
        evidence_store: FilingEvidenceStore | None = None,
    ) -> Adjustment:
        """Apply one explicit terminal transition to a PROPOSED record."""

        try:
            target_status = AdjustmentStatus(status)
        except (TypeError, ValueError) as exc:
            raise AdjustmentWorkflowRequestError(
                "transition status must be ACCEPTED or REJECTED"
            ) from exc
        if target_status is AdjustmentStatus.PROPOSED:
            raise AdjustmentWorkflowTransitionError(
                "PROPOSED is a creation state, not a terminal transition"
            )
        try:
            approval_actor = _approval_actor(actor)
        except (TypeError, ValueError) as exc:
            raise AdjustmentWorkflowRequestError(str(exc)) from exc

        record = self.read_record(
            adjustment_id,
            normalized_input=normalized_input,
            evidence_index=evidence_index,
            evidence_store=evidence_store,
        )
        if record is None:
            raise AdjustmentWorkflowMissError(
                f"no transitionable adjustment proposal: {adjustment_id}"
            )
        if record.adjustment.status is not AdjustmentStatus.PROPOSED:
            raise AdjustmentWorkflowTransitionError(
                f"cannot transition terminal adjustment {adjustment_id}"
            )

        updated = Adjustment.model_validate(
            record.adjustment.model_copy(
                update={
                    "status": target_status,
                    "approved_by": (
                        approval_actor if target_status is AdjustmentStatus.ACCEPTED else None
                    ),
                }
            ).model_dump(mode="python", warnings=False)
        )
        transition = AdjustmentWorkflowTransition(
            action="ACCEPT" if target_status is AdjustmentStatus.ACCEPTED else "REJECT",
            status=target_status,
            actor=approval_actor.value,
        )
        updated_record = _record_with_hash(
            AdjustmentWorkflowRecord(
                adjustment=updated,
                evidence_bindings=record.evidence_bindings,
                scope=record.scope,
                transition_history=[*record.transition_history, transition],
                record_sha256="0" * 64,
            )
        )
        try:
            _atomic_replace(self.path_for(adjustment_id), _serialized(updated_record))
        except (OSError, TypeError, ValueError) as exc:
            raise AdjustmentWorkflowWriteError(
                f"cannot persist adjustment transition {adjustment_id}: {exc}"
            ) from exc
        return updated_record.adjustment

    def accept(
        self,
        adjustment_id: str,
        *,
        actor: ApprovedBy | ProposedBy | str,
        **kwargs: object,
    ) -> Adjustment:
        """Accept a proposal with an explicit HUMAN or RULE_ENGINE approver."""

        return self.transition(
            adjustment_id,
            AdjustmentStatus.ACCEPTED,
            actor=actor,
            **kwargs,  # type: ignore[arg-type]
        )

    def reject(
        self,
        adjustment_id: str,
        *,
        actor: ApprovedBy | ProposedBy | str,
        **kwargs: object,
    ) -> Adjustment:
        """Reject a proposal with an explicit HUMAN or RULE_ENGINE reviewer."""

        return self.transition(
            adjustment_id,
            AdjustmentStatus.REJECTED,
            actor=actor,
            **kwargs,  # type: ignore[arg-type]
        )

    def lookup(
        self,
        *,
        status: AdjustmentStatus | str | None = None,
        target_field: str | None = None,
        normalized_input: NormalizedInput | None = None,
        evidence_index: Iterable[EvidenceInput] | None = None,
        evidence_store: FilingEvidenceStore | None = None,
    ) -> tuple[Adjustment, ...]:
        """Return verified local adjustments in deterministic ID order."""

        try:
            target_status = AdjustmentStatus(status) if status is not None else None
            if target_field is not None and (
                not isinstance(target_field, str) or not target_field
            ):
                raise ValueError("target_field must be a non-empty string")
            normalized = (
                _validated_normalized_input(normalized_input)
                if normalized_input is not None
                else None
            )
            evidence_values = tuple(evidence_index) if evidence_index is not None else None
        except (TypeError, ValueError, ValidationError) as exc:
            raise AdjustmentWorkflowRequestError(f"invalid adjustment lookup: {exc}") from exc

        directory = self.root / "adjustments"
        if not directory.exists():
            return ()
        if directory.is_symlink() or not directory.is_dir():
            raise AdjustmentWorkflowCorruptionError(
                f"adjustment workflow directory is not a directory: {directory}"
            )

        matches: list[Adjustment] = []
        for path in sorted(directory.glob("*.json")):
            record = _record_from_file(path)
            if target_status is not None and record.adjustment.status is not target_status:
                continue
            if target_field is not None and record.adjustment.target_field != target_field:
                continue
            try:
                _validate_scope(record, normalized)
                _validate_bindings(
                    record,
                    normalized_input=normalized,
                    evidence_index=evidence_values,
                    evidence_store=evidence_store,
                )
            except AdjustmentWorkflowError:
                raise
            except (TypeError, ValueError, ValidationError) as exc:
                raise AdjustmentWorkflowRequestError(
                    f"stored adjustment does not match requested provenance: {exc}"
                ) from exc
            matches.append(record.adjustment)
        return tuple(matches)


AdjustmentProposalStore = AdjustmentProposalWorkflow


__all__ = [
    "ADJUSTMENT_WORKFLOW_CACHE_FORMAT_VERSION",
    "ADJUSTMENT_WORKFLOW_CONTRACT",
    "ADJUSTMENT_WORKFLOW_VERSION",
    "AdjustmentProposalStore",
    "AdjustmentProposalWorkflow",
    "AdjustmentWorkflowEvidenceBinding",
    "AdjustmentWorkflowRecord",
    "AdjustmentWorkflowScope",
    "AdjustmentWorkflowTransition",
    "adjustment_id_for",
]
