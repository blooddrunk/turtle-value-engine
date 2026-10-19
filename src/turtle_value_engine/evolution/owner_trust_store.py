"""Trusted owner-provenance operations: registry snapshots and evidence (Phase 7-C3-B).

This module turns the C3-A verification core into a persistently auditable
personal-research workflow:

* a **trust-root store** — an explicitly supplied directory holding an
  append-only chain of :class:`OwnerProvenanceRegistrySnapshotV1` files,
  each wrapping one :class:`OwnerProvenanceKeyRegistryV1` with a sequence
  number and a content-hash link to its parent.  Loading validates the
  whole chain fail-closed (gaps, duplicates, tampered parents, foreign
  files); nothing ever rewrites a committed snapshot.  Enrollment,
  rotation and revocation of *trust itself* are pure snapshot transitions
  persisted create-only;
* an **evidence store** — one immutable, create-only bundle directory per
  deterministic ``bundle_id`` holding the exact canonical decision-input
  bytes, the signed statement, the registry snapshot that was trusted at
  capture time, the verification dossier and the resulting decision record
  (or ``null`` when validation failed), bound by one manifest;
* deterministic **capture** through the real
  :class:`SignedOwnerProvenanceVerifier` at record time, and offline
  **re-verification** from persisted evidence that must replay the dossier
  byte-identically and re-prove the record bindings.

Trust-root ownership is explicit: the store root is an operator-supplied
path; no decision artifact can designate it (no such field exists in any
decision contract), and the CLI additionally refuses a trust root nested
inside a submitted decision bundle (and decision artifacts stored inside
the trust root) so a bundle can never smuggle its own trust root.  The
module constructs no provider, model, transport or network client, reads
no environment, never signs, and never holds private key material.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, NamedTuple, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .owner_decision import (
    OwnerPolicyDecisionRecordV1,
    OwnerPolicyDecisionValidationV1,
    validate_owner_decision,
)
from .owner_provenance import (
    _DECISION_CONTENT_FIELDS,
    HASH_PATTERN,
    OwnerProvenanceKeyRecordV1,
    OwnerProvenanceKeyRegistryV1,
    OwnerProvenanceVerificationV1,
    OwnerSignedDecisionStatementV1,
    SignedOwnerProvenanceVerifier,
    _parse_canonical_decision_input,
    build_owner_provenance_key_registry,
    verify_owner_provenance,
)

_SNAPSHOT_NAME_PATTERN = re.compile(r"^snapshot-(\d{6})\.json$")


class OwnerTrustStoreError(ValueError):
    """Raised when trust-root snapshots or evidence bundles fail closed."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular_file_bytes(path: Path) -> bytes:
    """Read one regular file, refusing symlinks and special files."""

    if path.is_symlink():
        raise OwnerTrustStoreError(f"trust-store artifact is a symlink: {path}")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise OwnerTrustStoreError(
            f"trust-store artifact is unavailable: {path}"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OwnerTrustStoreError(
                f"trust-store artifact is not a regular file: {path}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _serialize_json(model: BaseModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    ).encode("utf-8")


def _write_create_only(path: Path, content: bytes, *, label: str) -> str:
    """Create-only publication with inode-guarded failure cleanup.

    A single exclusive ``O_CREAT | O_EXCL`` open: a competing writer's
    different content is never overwritten, byte-identical racing writes
    collapse to idempotence, and a symlinked target is refused.  Mirrors the
    repository-standard publication discipline (C2-R1-C).
    """

    if path.is_symlink():
        raise OwnerTrustStoreError(f"{label} must not be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        if path.is_symlink():
            raise OwnerTrustStoreError(f"{label} must not be a symlink: {path}") from None
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise OwnerTrustStoreError(
                f"{label} already exists at this path and cannot be read; "
                f"outputs are immutable — choose a new path: {path}"
            ) from exc
        if existing == content:
            return "IDEMPOTENT"
        raise OwnerTrustStoreError(
            f"{label} already exists with different content; outputs are "
            f"immutable — choose a new path: {path}"
        ) from None
    created_ino = os.fstat(descriptor).st_ino
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            if os.stat(path).st_ino == created_ino:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return "CREATED"


# ---------------------------------------------------------------------------
# Versioned registry snapshots
# ---------------------------------------------------------------------------


class OwnerProvenanceRegistrySnapshotV1(BaseModel):
    """One append-only trust-root snapshot wrapping a full key registry.

    ``snapshot_id`` derives from the sequence, the parent snapshot content
    hash and the wrapped registry identity (id + full content hash), so the
    same key set under different trust content is a distinct snapshot
    identity (the C3-A-R2 content-snapshot rule applied to the store).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_provenance_registry_snapshot_v1"] = (
        "owner_provenance_registry_snapshot_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    snapshot_id: StrictStr = Field(min_length=1, max_length=128)
    sequence: StrictInt = Field(ge=1)
    parent_snapshot_content_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    registry: OwnerProvenanceKeyRegistryV1
    snapshot_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if (self.sequence == 1) != (self.parent_snapshot_content_sha256 is None):
            raise ValueError(
                "exactly the first snapshot has no parent content hash"
            )
        expected_id = deterministic_id(
            "owner-provenance-registry-snapshot",
            str(self.sequence),
            self.parent_snapshot_content_sha256 or "",
            self.registry.registry_id,
            self.registry.content_sha256,
        )
        if self.snapshot_id != expected_id:
            raise ValueError("snapshot id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"snapshot_content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.snapshot_content_sha256 != expected_content:
            raise ValueError("snapshot content_sha256 does not match content")
        return self


def _next_snapshot(
    previous: OwnerProvenanceRegistrySnapshotV1,
    registry: OwnerProvenanceKeyRegistryV1,
) -> OwnerProvenanceRegistrySnapshotV1:
    sequence = previous.sequence + 1
    snapshot_id = deterministic_id(
        "owner-provenance-registry-snapshot",
        str(sequence),
        previous.snapshot_content_sha256,
        registry.registry_id,
        registry.content_sha256,
    )
    fields = {
        "contract": "owner_provenance_registry_snapshot_v1",
        "schema_version": "1.0.0",
        "snapshot_id": snapshot_id,
        "sequence": sequence,
        "parent_snapshot_content_sha256": previous.snapshot_content_sha256,
        "registry": registry.model_dump(mode="json"),
    }
    return OwnerProvenanceRegistrySnapshotV1(
        **fields,
        snapshot_content_sha256=_sha256_hex(
            canonical_json_bytes(
                {key: value for key, value in fields.items()}
            )
        ),
    )


def build_initial_registry_snapshot(
    registry: OwnerProvenanceKeyRegistryV1,
) -> OwnerProvenanceRegistrySnapshotV1:
    """Sequence-1 snapshot (no parent) for a brand-new trust root."""

    snapshot_id = deterministic_id(
        "owner-provenance-registry-snapshot",
        "1",
        "",
        registry.registry_id,
        registry.content_sha256,
    )
    fields = {
        "contract": "owner_provenance_registry_snapshot_v1",
        "schema_version": "1.0.0",
        "snapshot_id": snapshot_id,
        "sequence": 1,
        "parent_snapshot_content_sha256": None,
        "registry": registry.model_dump(mode="json"),
    }
    return OwnerProvenanceRegistrySnapshotV1(
        **fields,
        snapshot_content_sha256=_sha256_hex(
            canonical_json_bytes({key: value for key, value in fields.items()})
        ),
    )


def enroll_registry_key(
    snapshot: OwnerProvenanceRegistrySnapshotV1,
    record: OwnerProvenanceKeyRecordV1,
) -> OwnerProvenanceRegistrySnapshotV1:
    """Enroll one additional trusted public key (new snapshot, old intact)."""

    for item in snapshot.registry.keys:
        if item.key_id == record.key_id:
            raise ValueError(
                f"key {record.key_id} is already registered in this trust root"
            )
        if item.public_key_base64 == record.public_key_base64:
            raise ValueError("this key material is already registered")
    keys = [*snapshot.registry.keys, record]
    return _next_snapshot(
        snapshot, build_owner_provenance_key_registry(list(keys))
    )


def revoke_registry_key(
    snapshot: OwnerProvenanceRegistrySnapshotV1,
    key_id: str,
    revocation_reference: str,
) -> OwnerProvenanceRegistrySnapshotV1:
    """Revoke one registered key with a mandatory reference (new snapshot)."""

    keys: list[OwnerProvenanceKeyRecordV1] = []
    found = False
    for item in snapshot.registry.keys:
        if item.key_id != key_id:
            keys.append(item)
            continue
        if item.revoked:
            raise ValueError(f"key {key_id} is already revoked in this trust root")
        found = True
        keys.append(
            item.model_copy(
                update={"revoked": True, "revocation_reference": revocation_reference}
            )
        )
    if not found:
        raise ValueError(f"unknown key id in this trust root: {key_id}")
    return _next_snapshot(
        snapshot, build_owner_provenance_key_registry(list(keys))
    )


def rotate_registry_key(
    snapshot: OwnerProvenanceRegistrySnapshotV1,
    old_key_id: str,
    new_record: OwnerProvenanceKeyRecordV1,
    revocation_reference: str,
) -> OwnerProvenanceRegistrySnapshotV1:
    """Rotate trust: revoke the old key and enroll the new one atomically.

    Both changes land in ONE snapshot (a single sequence increment from
    the previous snapshot) so no intermediate trust state ever exists where
    the old key is revoked but the new one is absent (or vice versa).
    """

    keys: list[OwnerProvenanceKeyRecordV1] = []
    found = False
    for item in snapshot.registry.keys:
        if item.key_id == old_key_id:
            if item.revoked:
                raise ValueError(
                    f"key {old_key_id} is already revoked in this trust root"
                )
            found = True
            keys.append(
                item.model_copy(
                    update={
                        "revoked": True,
                        "revocation_reference": revocation_reference,
                    }
                )
            )
        else:
            keys.append(item)
    if not found:
        raise ValueError(f"unknown key id in this trust root: {old_key_id}")
    for item in keys:
        if item.key_id == new_record.key_id:
            raise ValueError(
                f"key {new_record.key_id} is already registered in this trust root"
            )
        if item.public_key_base64 == new_record.public_key_base64:
            raise ValueError("this key material is already registered")
    return _next_snapshot(
        snapshot,
        build_owner_provenance_key_registry([*keys, new_record]),
    )


# ---------------------------------------------------------------------------
# The trust-root store
# ---------------------------------------------------------------------------


class OwnerProvenanceTrustStore:
    """An explicitly supplied trust-root directory of versioned snapshots.

    Layout: ``<root>/snapshots/snapshot-<sequence:06d>.json``.  Every load
    validates the complete chain from sequence 1 (contiguity, parent-hash
    links, model-level tamper detection); foreign files, gaps and duplicate
    sequences fail closed.  Publication is create-only — committed
    snapshots are immutable.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._snapshots_dir = self._root / "snapshots"

    @property
    def root(self) -> Path:
        return self._root

    def _snapshot_path(self, sequence: int) -> Path:
        return self._snapshots_dir / f"snapshot-{sequence:06d}.json"

    def _load_chain(self) -> list[OwnerProvenanceRegistrySnapshotV1]:
        if not self._snapshots_dir.is_dir():
            raise OwnerTrustStoreError(
                f"trust root has no snapshots directory: {self._root}"
            )
        found: dict[int, Path] = {}
        for entry in sorted(self._snapshots_dir.iterdir()):
            match = _SNAPSHOT_NAME_PATTERN.fullmatch(entry.name)
            if match is None:
                raise OwnerTrustStoreError(
                    f"foreign file in the trust-root snapshots directory: {entry}"
                )
            found[int(match.group(1))] = entry
        if not found:
            raise OwnerTrustStoreError(
                f"trust root contains no registry snapshots: {self._root}"
            )
        sequences = sorted(found)
        if sequences != list(range(1, len(sequences) + 1)):
            raise OwnerTrustStoreError(
                "trust-root snapshot chain is not contiguous from sequence 1: "
                f"{sequences}"
            )
        snapshots: list[OwnerProvenanceRegistrySnapshotV1] = []
        for sequence in sequences:
            try:
                snapshot = OwnerProvenanceRegistrySnapshotV1.model_validate(
                    json.loads(_regular_file_bytes(found[sequence]))
                )
            except OwnerTrustStoreError:
                raise
            except Exception as exc:
                raise OwnerTrustStoreError(
                    f"trust-root snapshot {sequence} is tampered or unreadable: "
                    f"{str(exc)[:300]}"
                ) from exc
            if snapshot.sequence != sequence:
                raise OwnerTrustStoreError(
                    f"trust-root snapshot filename sequence {sequence} does not "
                    f"match its content sequence {snapshot.sequence}"
                )
            if snapshots:
                parent = snapshots[-1]
                if snapshot.parent_snapshot_content_sha256 != (
                    parent.snapshot_content_sha256
                ):
                    raise OwnerTrustStoreError(
                        f"trust-root snapshot {sequence} does not chain to its "
                        "parent content hash"
                    )
            snapshots.append(snapshot)
        return snapshots

    def latest_snapshot(self) -> OwnerProvenanceRegistrySnapshotV1:
        """The highest-sequence snapshot of a fully validated chain."""

        return self._load_chain()[-1]

    def snapshot_by_sequence(self, sequence: int) -> OwnerProvenanceRegistrySnapshotV1:
        for snapshot in self._load_chain():
            if snapshot.sequence == sequence:
                return snapshot
        raise OwnerTrustStoreError(
            f"trust root has no snapshot at sequence {sequence}"
        )

    def init_store(
        self, registry: OwnerProvenanceKeyRegistryV1
    ) -> Literal["CREATED", "IDEMPOTENT"]:
        """Persist sequence 1 (refuses a different existing first snapshot)."""

        return _write_create_only(
            self._snapshot_path(1),
            _serialize_json(build_initial_registry_snapshot(registry)),
            label="initial trust-root snapshot",
        )

    def append_snapshot(
        self, snapshot: OwnerProvenanceRegistrySnapshotV1
    ) -> Literal["CREATED", "IDEMPOTENT"]:
        """Append one snapshot as the next sequence of the current chain."""

        chain = self._load_chain()
        latest = chain[-1]
        if snapshot.sequence != latest.sequence + 1:
            raise OwnerTrustStoreError(
                f"appended snapshot sequence must be exactly "
                f"{latest.sequence + 1} (got {snapshot.sequence})"
            )
        if snapshot.parent_snapshot_content_sha256 != latest.snapshot_content_sha256:
            raise OwnerTrustStoreError(
                "appended snapshot does not chain to the latest committed "
                "snapshot content hash"
            )
        return _write_create_only(
            self._snapshot_path(snapshot.sequence),
            _serialize_json(snapshot),
            label=f"trust-root snapshot {snapshot.sequence}",
        )

    def apply_snapshot_operation(
        self,
        operation,
    ) -> tuple[OwnerProvenanceRegistrySnapshotV1, Literal["CREATED", "IDEMPOTENT"]]:
        """Derive and append the next snapshot from a pure transition.

        ``operation`` maps the latest validated snapshot to the next one
        (``enroll_registry_key`` / ``revoke_registry_key`` /
        ``rotate_registry_key`` results).  Derivation is pure; only the
        append touches the filesystem, create-only.
        """

        next_snapshot = operation(self.latest_snapshot())
        result = self.append_snapshot(next_snapshot)
        return next_snapshot, result


# ---------------------------------------------------------------------------
# Evidence bundles
# ---------------------------------------------------------------------------


class OwnerProvenanceEvidenceBundleV1(BaseModel):
    """One immutable captured evidence unit for a signed decision submission.

    Binds the exact canonical decision-input bytes, the signed statement,
    the trust-root snapshot that was trusted at capture time (id + content
    hash, plus the wrapped registry identity), the deterministic
    verification dossier, the validation outcome and the resulting decision
    record (``null`` when validation failed).  The bundle is captured
    evidence, never authority: plan-time authority always comes from fresh
    verification against the operator's *current* trust root.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_provenance_evidence_bundle_v1"] = (
        "owner_provenance_evidence_bundle_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    bundle_id: StrictStr = Field(min_length=1, max_length=128)
    decision_input_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    statement_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    registry_snapshot_id: StrictStr = Field(min_length=1, max_length=128)
    registry_snapshot_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    registry_id: StrictStr = Field(min_length=1, max_length=128)
    registry_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    verification: OwnerProvenanceVerificationV1
    validation_state: Literal["VALID", "INVALID"]
    validation_blockers: list[StrictStr] = Field(max_length=64)
    record: OwnerPolicyDecisionRecordV1 | None = None
    record_content_sha256: StrictStr | None = Field(default=None, pattern=HASH_PATTERN)
    capture_is_evidence_not_authority: Literal[True] = True
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if (self.record is None) != (self.record_content_sha256 is None):
            raise ValueError(
                "the record and its content hash are supplied together or "
                "not at all"
            )
        if self.record is not None:
            if self.record.content_sha256 != self.record_content_sha256:
                raise ValueError(
                    "record_content_sha256 does not match the embedded record"
                )
        if (self.validation_state == "VALID") != (self.record is not None):
            raise ValueError(
                "a VALID capture embeds its record; an INVALID capture embeds none"
            )
        expected_id = deterministic_id(
            "owner-provenance-evidence-bundle",
            self.decision_input_content_sha256,
            self.statement_content_sha256,
            self.registry_snapshot_id,
            self.registry_snapshot_content_sha256,
            self.verification.verification_id,
            self.record.decision_record_id if self.record is not None else "",
            self.record_content_sha256 or "",
            self.validation_state,
        )
        if self.bundle_id != expected_id:
            raise ValueError("bundle id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("bundle content_sha256 does not match content")
        return self


class LoadedOwnerDecisionEvidence(NamedTuple):
    """A fully hash-validated view of one persisted evidence bundle."""

    bundle: OwnerProvenanceEvidenceBundleV1
    decision_input_bytes: bytes
    statement: OwnerSignedDecisionStatementV1
    snapshot: OwnerProvenanceRegistrySnapshotV1


_BUNDLE_BASE_COMPONENTS: tuple[str, ...] = (
    "bundle.json",
    "decision-input.json",
    "statement.json",
    "registry-snapshot.json",
    "verification.json",
)


def _check_bundle_directory_shape(
    bundle_dir: Path, bundle: OwnerProvenanceEvidenceBundleV1
) -> None:
    """Fail closed unless the bundle directory holds exactly its components.

    A complete VALID bundle is the six-file shape (the base components plus
    ``record.json``); an INVALID no-record capture is the five-file shape.
    Missing, extra, symlinked and non-file entries are classified store
    errors, so an unexpected ``record.json`` can never masquerade as a
    no-record bundle and no foreign file hides inside a bundle.  The check
    is read-only: nothing is deleted or rewritten.
    """

    expected = set(_BUNDLE_BASE_COMPONENTS)
    if bundle.record is not None:
        expected.add("record.json")
    try:
        entries = sorted(bundle_dir.iterdir())
    except OSError as exc:
        raise OwnerTrustStoreError(
            f"evidence bundle directory is unavailable: {bundle_dir}"
        ) from exc
    actual: set[str] = set()
    for entry in entries:
        if entry.is_symlink():
            raise OwnerTrustStoreError(
                f"evidence bundle component is a symlink: {entry}"
            )
        if not entry.is_file():
            raise OwnerTrustStoreError(
                f"evidence bundle directory holds a non-file entry: {entry}"
            )
        actual.add(entry.name)
    missing = sorted(expected - actual)
    if missing:
        raise OwnerTrustStoreError(
            f"evidence bundle is missing components: {', '.join(missing)} "
            f"({bundle_dir})"
        )
    extra = sorted(actual - expected)
    if extra:
        raise OwnerTrustStoreError(
            "evidence bundle directory holds unexpected entries: "
            f"{', '.join(extra)} ({bundle_dir})"
        )


def _record_signed_payload_divergences(
    record: OwnerPolicyDecisionRecordV1, decision_input_bytes: bytes
) -> list[str]:
    """Named divergences between the record and the bytes it claims to embed.

    Mirrors the plan-time re-attestation binding: every owner-signed
    decision-input field and the provenance ``source_revision`` must appear
    verbatim in the persisted record.  A self-consistent SHA-256 or a
    recomputed deterministic id is integrity, not authentication — this
    field-level comparison is what makes a fully self-consistent forged
    record visible offline.
    """

    parsed = _parse_canonical_decision_input(decision_input_bytes)
    if parsed is None:
        return ["SIGNED_INPUT_UNUSABLE"]
    input_dump = parsed.model_dump(mode="json")
    record_dump = record.model_dump(mode="json")
    divergences: list[str] = []
    if any(
        input_dump.get(field) != record_dump.get(field)
        for field in _DECISION_CONTENT_FIELDS
    ):
        divergences.append("RECORD_SIGNED_CONTENT_DIVERGED")
    if record.provenance.source_revision != parsed.source_revision:
        divergences.append("RECORD_SOURCE_REVISION_DIVERGED")
    return divergences


def build_owner_decision_evidence_bundle(
    *,
    validation: OwnerPolicyDecisionValidationV1,
    decision_input_bytes: bytes,
    statement: OwnerSignedDecisionStatementV1,
    registry_snapshot: OwnerProvenanceRegistrySnapshotV1,
) -> OwnerProvenanceEvidenceBundleV1:
    """Assemble the evidence bundle from an already-produced validation.

    The validation must be the record-time result over exactly these bytes
    and this statement/snapshot (the capture boundary below guarantees
    that); the pure dossier is recomputed deterministically here.
    """

    verification = verify_owner_provenance(
        decision_input_bytes=decision_input_bytes,
        statement=statement,
        registry=registry_snapshot.registry,
    )
    record = validation.record
    fields = {
        "contract": "owner_provenance_evidence_bundle_v1",
        "schema_version": "1.0.0",
        "decision_input_content_sha256": _sha256_hex(decision_input_bytes),
        "statement_content_sha256": statement.content_sha256,
        "registry_snapshot_id": registry_snapshot.snapshot_id,
        "registry_snapshot_content_sha256": registry_snapshot.snapshot_content_sha256,
        "registry_id": registry_snapshot.registry.registry_id,
        "registry_content_sha256": registry_snapshot.registry.content_sha256,
        "verification": verification.model_dump(mode="json"),
        "validation_state": validation.state,
        "validation_blockers": list(validation.blockers),
        "record": record.model_dump(mode="json") if record is not None else None,
        "record_content_sha256": (
            record.content_sha256 if record is not None else None
        ),
        "capture_is_evidence_not_authority": True,
    }
    fields["bundle_id"] = deterministic_id(
        "owner-provenance-evidence-bundle",
        fields["decision_input_content_sha256"],
        fields["statement_content_sha256"],
        fields["registry_snapshot_id"],
        fields["registry_snapshot_content_sha256"],
        verification.verification_id,
        record.decision_record_id if record is not None else "",
        fields["record_content_sha256"] or "",
        validation.state,
    )
    return OwnerProvenanceEvidenceBundleV1(
        **fields,
        content_sha256=_sha256_hex(
            canonical_json_bytes({key: value for key, value in fields.items()})
        ),
    )


def capture_owner_decision_evidence(
    *,
    decision_input_bytes: bytes,
    statement: OwnerSignedDecisionStatementV1,
    registry_snapshot: OwnerProvenanceRegistrySnapshotV1,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    boundary_input=None,
    policy_exceptions: Sequence = (),
    owner_allowlist=None,
) -> tuple[OwnerPolicyDecisionValidationV1, OwnerProvenanceEvidenceBundleV1]:
    """Capture one signed submission: validate + verify + bundle, deterministically.

    Runs the real record-time boundary — ``validate_owner_decision`` with
    the real :class:`SignedOwnerProvenanceVerifier` injected over the exact
    submitted bytes — then assembles the evidence bundle from that
    validation plus the pure ``verify_owner_provenance`` dossier over the
    same bytes/statement/snapshot.  A signature that does not verify yields
    an honest ``INVALID`` validation (no record) and a ``REJECTED`` dossier
    in the bundle, never a fabricated ``VERIFIED`` capture.
    """

    from turtle_value_engine.evolution.owner_decision import (
        OwnerPolicyDecisionInputV1,
    )

    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_input_bytes)
    )
    verifier = SignedOwnerProvenanceVerifier(
        registry=registry_snapshot.registry,
        statement=statement,
        decision_input_bytes=decision_input_bytes,
    )
    validation = validate_owner_decision(
        decision_input=decision_input,
        decision_source_bytes=decision_input_bytes,
        base_profile_path=base_profile_path,
        target_profile_path=target_profile_path,
        release_manifest_path=release_manifest_path,
        boundary_input=boundary_input,
        policy_exceptions=policy_exceptions,
        owner_allowlist=owner_allowlist,
        verifier=verifier,
    )
    bundle = build_owner_decision_evidence_bundle(
        validation=validation,
        decision_input_bytes=decision_input_bytes,
        statement=statement,
        registry_snapshot=registry_snapshot,
    )
    return validation, bundle


def persist_owner_decision_evidence(
    evidence_root: str | Path,
    bundle: OwnerProvenanceEvidenceBundleV1,
    *,
    decision_input_bytes: bytes,
    statement: OwnerSignedDecisionStatementV1,
    registry_snapshot: OwnerProvenanceRegistrySnapshotV1,
) -> Literal["CREATED", "IDEMPOTENT"]:
    """Persist one evidence bundle create-only under its deterministic id.

    Every component file is published through the exclusive create-only
    writer, so a byte-identical recapture is idempotent everywhere and any
    foreign content at any component path is a classified failure that
    overwrites nothing.
    """

    if _sha256_hex(decision_input_bytes) != bundle.decision_input_content_sha256:
        raise OwnerTrustStoreError(
            "persisted decision-input bytes do not match the bundle binding"
        )
    if statement.content_sha256 != bundle.statement_content_sha256:
        raise OwnerTrustStoreError(
            "persisted statement does not match the bundle binding"
        )
    if (
        registry_snapshot.snapshot_id != bundle.registry_snapshot_id
        or registry_snapshot.snapshot_content_sha256
        != bundle.registry_snapshot_content_sha256
    ):
        raise OwnerTrustStoreError(
            "persisted registry snapshot does not match the bundle binding"
        )
    bundle_dir = Path(evidence_root) / bundle.bundle_id
    outcomes = [
        _write_create_only(
            bundle_dir / "decision-input.json",
            decision_input_bytes,
            label="evidence decision-input",
        ),
        _write_create_only(
            bundle_dir / "statement.json",
            _serialize_json(statement),
            label="evidence statement",
        ),
        _write_create_only(
            bundle_dir / "registry-snapshot.json",
            _serialize_json(registry_snapshot),
            label="evidence registry snapshot",
        ),
        _write_create_only(
            bundle_dir / "verification.json",
            _serialize_json(bundle.verification),
            label="evidence verification dossier",
        ),
    ]
    if bundle.record is not None:
        outcomes.append(
            _write_create_only(
                bundle_dir / "record.json",
                _serialize_json(bundle.record),
                label="evidence decision record",
            )
        )
    outcomes.append(
        _write_create_only(
            bundle_dir / "bundle.json", _serialize_json(bundle), label="evidence bundle"
        )
    )
    # The manifest is the authority-last marker: a complete bundle is only
    # observable once bundle.json exists (candidate-first, record-last).
    return "CREATED" if any(item == "CREATED" for item in outcomes) else "IDEMPOTENT"


def load_owner_decision_evidence(
    bundle_path: str | Path,
) -> LoadedOwnerDecisionEvidence:
    """Load one persisted bundle, validating every component hash."""

    bundle_file = Path(bundle_path)
    if bundle_file.name != "bundle.json":
        raise OwnerTrustStoreError(
            f"evidence bundle path must point at bundle.json: {bundle_file}"
        )
    bundle_dir = bundle_file.parent
    try:
        bundle = OwnerProvenanceEvidenceBundleV1.model_validate(
            json.loads(_regular_file_bytes(bundle_file))
        )
    except OwnerTrustStoreError:
        raise
    except Exception as exc:
        raise OwnerTrustStoreError(
            f"evidence bundle is tampered or unreadable: {str(exc)[:300]}"
        ) from exc
    _check_bundle_directory_shape(bundle_dir, bundle)

    decision_input_bytes = _regular_file_bytes(bundle_dir / "decision-input.json")
    if _sha256_hex(decision_input_bytes) != bundle.decision_input_content_sha256:
        raise OwnerTrustStoreError(
            "persisted decision-input bytes do not match the bundle binding"
        )

    def _load_model(name: str, model_cls):
        try:
            return model_cls.model_validate(
                json.loads(_regular_file_bytes(bundle_dir / name))
            )
        except OwnerTrustStoreError:
            raise
        except Exception as exc:
            raise OwnerTrustStoreError(
                f"evidence component {name} is tampered or unreadable: "
                f"{str(exc)[:300]}"
            ) from exc

    statement = _load_model("statement.json", OwnerSignedDecisionStatementV1)
    if statement.content_sha256 != bundle.statement_content_sha256:
        raise OwnerTrustStoreError(
            "persisted statement does not match the bundle binding"
        )
    snapshot = _load_model(
        "registry-snapshot.json", OwnerProvenanceRegistrySnapshotV1
    )
    if (
        snapshot.snapshot_id != bundle.registry_snapshot_id
        or snapshot.snapshot_content_sha256 != bundle.registry_snapshot_content_sha256
    ):
        raise OwnerTrustStoreError(
            "persisted registry snapshot does not match the bundle binding"
        )
    if (
        snapshot.registry.registry_id != bundle.registry_id
        or snapshot.registry.content_sha256 != bundle.registry_content_sha256
    ):
        raise OwnerTrustStoreError(
            "persisted registry snapshot's registry identity does not match "
            "the bundle binding"
        )
    verification = _load_model(
        "verification.json", OwnerProvenanceVerificationV1
    )
    if verification != bundle.verification:
        raise OwnerTrustStoreError(
            "persisted verification dossier does not match the bundle embedding"
        )
    if bundle.record is not None:
        record = _load_model("record.json", OwnerPolicyDecisionRecordV1)
        if record != bundle.record:
            raise OwnerTrustStoreError(
                "persisted decision record does not match the bundle embedding"
            )
        divergences = _record_signed_payload_divergences(
            bundle.record, decision_input_bytes
        )
        if divergences:
            raise OwnerTrustStoreError(
                "persisted decision record diverges from the signed "
                f"decision-input bytes ({', '.join(divergences)})"
            )
    return LoadedOwnerDecisionEvidence(
        bundle=bundle,
        decision_input_bytes=decision_input_bytes,
        statement=statement,
        snapshot=snapshot,
    )


# ---------------------------------------------------------------------------
# Offline re-verification
# ---------------------------------------------------------------------------


class EvidenceReverificationV1(BaseModel):
    """Deterministic offline replay result for one persisted evidence bundle.

    ``REPLAYS_BYTE_IDENTICAL`` requires every persisted component file to
    match its manifest binding (decision-input bytes, statement, registry
    snapshot and its internal registry identity, the physical
    ``verification.json``, and — for a record-bearing bundle — the physical
    ``record.json``), the freshly recomputed dossier to equal the embedded
    one byte-for-byte, and the embedded record to bind the owner-signed
    decision-input fields verbatim; anything else is a named ``MISMATCH``.
    This is audit replay of captured evidence, never a fresh authority
    claim for a plan.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_provenance_evidence_reverification_v1"] = (
        "owner_provenance_evidence_reverification_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    reverification_id: StrictStr = Field(min_length=1, max_length=128)
    bundle_id: StrictStr = Field(min_length=1, max_length=128)
    replay_status: Literal["REPLAYS_BYTE_IDENTICAL", "MISMATCH"]
    mismatches: list[StrictStr] = Field(max_length=64)
    replayed_verification: OwnerProvenanceVerificationV1
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_reverification(self) -> Self:
        expected_id = deterministic_id(
            "owner-provenance-evidence-reverification",
            self.bundle_id,
            self.replay_status,
            self.replayed_verification.verification_id,
            sorted(self.mismatches),
        )
        if self.reverification_id != expected_id:
            raise ValueError(
                "reverification id disagrees with the bound content"
            )
        if (self.replay_status == "REPLAYS_BYTE_IDENTICAL") != (not self.mismatches):
            raise ValueError(
                "a byte-identical replay names no mismatch; a mismatch replay "
                "is not byte-identical"
            )
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError(
                "reverification content_sha256 does not match content"
            )
        return self


def reverify_owner_decision_evidence(
    bundle_path: str | Path,
) -> EvidenceReverificationV1:
    """Replay one persisted evidence bundle offline: same bytes, same dossier.

    Unlike the strict :func:`load_owner_decision_evidence` (which fail-closes
    for consumers), this audit boundary *compares*: every persisted
    component file that parses is compared against the manifest binding —
    including the physical ``verification.json`` and, for a record-bearing
    bundle, the physical ``record.json`` — and the dossier is recomputed
    from the actual persisted bytes, so tampering surfaces as a named
    ``MISMATCH``.  The persisted record must also embed the owner-signed
    decision-input fields verbatim, so a fully self-consistent forged
    record/manifest whose signed fields diverge cannot replay clean.  The
    bundle directory must hold exactly its complete component shape; a
    missing, unexpected, symlinked or unparseable component fails closed as
    a classified store error instead of being reinterpreted as success.
    """

    bundle_file = Path(bundle_path)
    if bundle_file.name != "bundle.json":
        raise OwnerTrustStoreError(
            f"evidence bundle path must point at bundle.json: {bundle_file}"
        )
    bundle_dir = bundle_file.parent
    try:
        bundle = OwnerProvenanceEvidenceBundleV1.model_validate(
            json.loads(_regular_file_bytes(bundle_file))
        )
    except OwnerTrustStoreError:
        raise
    except Exception as exc:
        raise OwnerTrustStoreError(
            f"evidence bundle is tampered or unreadable: {str(exc)[:300]}"
        ) from exc
    _check_bundle_directory_shape(bundle_dir, bundle)

    def _load_component(name: str, model_cls):
        try:
            return model_cls.model_validate(
                json.loads(_regular_file_bytes(bundle_dir / name))
            )
        except OwnerTrustStoreError:
            raise
        except Exception as exc:
            raise OwnerTrustStoreError(
                f"evidence component {name} is tampered or unreadable: "
                f"{str(exc)[:300]}"
            ) from exc

    statement = _load_component("statement.json", OwnerSignedDecisionStatementV1)
    snapshot = _load_component(
        "registry-snapshot.json", OwnerProvenanceRegistrySnapshotV1
    )
    verification_file = _load_component(
        "verification.json", OwnerProvenanceVerificationV1
    )

    decision_input_bytes = _regular_file_bytes(bundle_dir / "decision-input.json")
    mismatches: list[str] = []
    if _sha256_hex(decision_input_bytes) != bundle.decision_input_content_sha256:
        mismatches.append("DECISION_INPUT_BYTES_DIVERGED")
    if statement.content_sha256 != bundle.statement_content_sha256:
        mismatches.append("STATEMENT_DIVERGED")
    if (
        snapshot.snapshot_id != bundle.registry_snapshot_id
        or snapshot.snapshot_content_sha256 != bundle.registry_snapshot_content_sha256
    ):
        mismatches.append("REGISTRY_SNAPSHOT_DIVERGED")
    if (
        snapshot.registry.registry_id != bundle.registry_id
        or snapshot.registry.content_sha256 != bundle.registry_content_sha256
    ):
        mismatches.append("REGISTRY_IDENTITY_DIVERGED")
    if verification_file != bundle.verification:
        mismatches.append("VERIFICATION_FILE_DIVERGED")

    fresh = verify_owner_provenance(
        decision_input_bytes=decision_input_bytes,
        statement=statement,
        registry=snapshot.registry,
    )
    if fresh != bundle.verification:
        mismatches.append("VERIFICATION_REPLAY_DIVERGED")

    record = bundle.record
    if record is not None:
        record_file = _load_component("record.json", OwnerPolicyDecisionRecordV1)
        if record_file != bundle.record:
            mismatches.append("RECORD_FILE_DIVERGED")
        if (
            record.provenance.source_content_sha256
            != bundle.decision_input_content_sha256
        ):
            mismatches.append("RECORD_PROVENANCE_NOT_BOUND_TO_INPUT_BYTES")
        if record.content_sha256 != bundle.record_content_sha256:
            mismatches.append("RECORD_CONTENT_HASH_MISMATCH")
        mismatches.extend(
            _record_signed_payload_divergences(record, decision_input_bytes)
        )

    status: Literal["REPLAYS_BYTE_IDENTICAL", "MISMATCH"] = (
        "REPLAYS_BYTE_IDENTICAL" if not mismatches else "MISMATCH"
    )
    fields = {
        "contract": "owner_provenance_evidence_reverification_v1",
        "schema_version": "1.0.0",
        "bundle_id": bundle.bundle_id,
        "replay_status": status,
        "mismatches": sorted(mismatches),
        "replayed_verification": fresh.model_dump(mode="json"),
    }
    fields["reverification_id"] = deterministic_id(
        "owner-provenance-evidence-reverification",
        fields["bundle_id"],
        status,
        fresh.verification_id,
        sorted(mismatches),
    )
    return EvidenceReverificationV1(
        **fields,
        content_sha256=_sha256_hex(
            canonical_json_bytes({key: value for key, value in fields.items()})
        ),
    )


__all__ = [
    "EvidenceReverificationV1",
    "LoadedOwnerDecisionEvidence",
    "OwnerProvenanceEvidenceBundleV1",
    "OwnerProvenanceRegistrySnapshotV1",
    "OwnerProvenanceTrustStore",
    "OwnerTrustStoreError",
    "build_initial_registry_snapshot",
    "build_owner_decision_evidence_bundle",
    "capture_owner_decision_evidence",
    "enroll_registry_key",
    "load_owner_decision_evidence",
    "persist_owner_decision_evidence",
    "reverify_owner_decision_evidence",
    "revoke_registry_key",
    "rotate_registry_key",
]
