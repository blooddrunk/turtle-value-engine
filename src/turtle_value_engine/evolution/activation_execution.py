"""Controlled profile activation and reversible local execution (Phase 7-C4-A).

This module is the repository's first *mutation* boundary for the versioned
profile lifecycle: an opt-in, offline, single-file executor that changes only
``[profiles] default`` in one explicitly supplied private project TOML
configuration, strictly after a freshly derived
``READY_FOR_EXPLICIT_OWNER_EXECUTION`` plan (Phase 7-C2/C3) whose active owner
decision record is proven to be the exact record embedded in the strictly
loaded evidence bundle.

Design boundaries, made explicit:

* **Preview is the default and is byte-for-byte read-only.**  It derives the
  fresh plan, the executor-level provenance-association check, the exact
  before/after config bytes and diff, the intended backup/receipt paths and
  the rollback command — and writes nothing, not even the activation root.
* **Mutation requires ``--apply`` plus the freshly previewed
  ``--expected-plan-id`` and ``--expected-config-sha256``.**  The apply path
  re-reads every authoritative input and re-derives the whole plan inside a
  per-config exclusive lock; it never trusts a saved plan JSON, an earlier
  READY state or any persisted claim.
* **One file changes.**  The edit is a byte-preserving substitution of the
  single ``[profiles] default`` scalar; every other byte, key and comment of
  the private config survives verbatim, and the result must re-validate as
  TOML with exactly that one semantic change.  Checked-in repository
  artifacts (the config template, rule profiles, release manifests, source,
  tests, schemas) are refused as targets through resolved-path aliasing
  guards, and symlinked/non-regular targets fail closed.
* **Recoverability is deterministic, never magical.**  A content-addressed
  private before-image and an immutable intent journal are persisted *before*
  the atomic same-directory ``os.replace``; the deterministic create-only
  receipt is published *after* it.  Every publication fsyncs the file body
  and its parent directory entry before returning.  A crash at any point
  leaves an on-disk state that the next invocation classifies and completes
  (or refuses) by name — multi-file cross-restart atomicity is deliberately
  not claimed.  Rollback symmetrically persists an immutable recovery intent
  before the restore and finalizes the rollback outcome after it, so an
  interrupted rollback's audit artifact is recoverable on retry while a
  prior-byte state without durable proof is never fabricated into one.
* **Store containment is enforced below the activation root.**  The store
  descendant directories (``locks``, ``journal``, ``receipts``,
  ``before-images``, ``rollbacks``) are refused as symlinks or
  non-directories before any mutation — a hostile layout cannot direct a
  lock file, journal, before-image, receipt or rollback artifact outside
  the private root.
* **Rollback is separately invoked and byte-exact.**  It restores the exact
  prior bytes only after receipt validation, before-image hash verification
  and a current-config precondition check, refusing to clobber any
  intervening unrelated change.  Rollback never replays monitoring runs,
  notifications or historical artifacts (the fixed C2 exclusions).

The 2026-10-22 preflight of this phase demonstrated, against pristine main,
that the read-only planner accepts an active ``--decision-record`` whose
content hash/bytes differ from the ``--authority-evidence`` bundle's embedded
record (same ``decision_record_id`` — the id derivation omits authority
annotation text) while fresh signed-input re-attestation still returns READY.
That is preserved planner semantics (the signature still authenticates the
same decision content), but it is insufficient provenance for a *mutation*:
this executor therefore independently requires the active record to be the
bundle's embedded record byte-for-byte (``EVIDENCE_RECORD_ASSOCIATION_*``).

No provider, model, transport, network socket, monitoring replay,
notification replay or historical-artifact rewrite is constructed anywhere in
this module.  Every contract here records that activation required an
explicit apply command and that rollback required an explicit rollback
command.  All keys/signatures used by tests are throwaway runtime fixtures;
no real owner decision or strict-v2 activation is performed by this code.
"""

from __future__ import annotations

import difflib
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, NamedTuple, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .activation_plan import (
    ROLLBACK_EXCLUSIONS,
    ProfileActivationPlanV1,
    plan_profile_activation,
)
from .materialization_pair import _regular_file_bytes
from .owner_decision import (
    OwnerPolicyDecisionRecordV1,
    OwnerPolicyDecisionRevocationV1,
)
from .owner_lifecycle import (
    OwnerSignedRevocationEvidenceV1,
    OwnerSignedSupersessionEvidenceV1,
)
from .owner_provenance import OwnerProvenanceKeyRegistryV1
from .owner_trust_store import LoadedOwnerDecisionEvidence
from .profile_semantic_audit import VersionedPolicyExceptionV1

HASH_PATTERN = r"^[0-9a-f]{64}$"

#: Repository-checked-in trees an activation target/activation root may never
#: alias into (the private config normally lives under an ignored private
#: root such as ``.tve-private/``, which is intentionally absent here).
_PROTECTED_REPO_SUBDIRS: tuple[str, ...] = (
    ".git",
    "rules",
    "config",
    "docs",
    "src",
    "tests",
    "scripts",
    "schemas",
    "apps",
    "fixtures",
    "deploy",
    "build",
    "plans",
)

_PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<lead>\s*)default(?P<gap>\s*)=(?P<gap2>\s*)"
    r"(?P<quote>[\"'])(?P<value>[^\"'\n]*)(?P=quote)"
    r"(?P<trailing>[^#\n]*(?:#.*)?)$"
)
_DEFAULT_KEY_HINT_PATTERN = re.compile(r"^\s*default\s*[=:]")

#: Named fault points available to the deterministic interruption tests
#: (library-only; the production CLI never supplies a hook).
FAULT_POINTS: tuple[str, ...] = (
    "journal_persisted",
    "before_image_persisted",
    "temp_written",
    "config_replaced",
    "rollback_intent_persisted",
    "config_restored",
)

#: Activation-store descendant directories the executor publishes into.  A
#: hostile layout (symlink or non-directory entry) is refused before any
#: mutation, so no lock, journal, before-image, receipt or rollback byte can
#: be directed outside the activation root through a descendant path.
_APPLY_STORE_DIRS: tuple[str, ...] = (
    "locks",
    "journal",
    "receipts",
    "before-images",
)
_ROLLBACK_STORE_DIRS: tuple[str, ...] = ("locks", "before-images", "rollbacks")


class ActivationExecutionError(ValueError):
    """Unusable executor input or environment (classified, fail-closed).

    Carries a stable machine-readable ``code`` so tests and operators can
    assert the exact refusal reason.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ActivationExecutionBlocked(Exception):
    """A refused activation/rollback with a printable payload (exit class 1)."""

    def __init__(self, payload: dict) -> None:
        super().__init__(str(payload.get("status", "BLOCKED")))
        self.payload = payload


class ActivationBusyError(Exception):
    """Another activation holds this config's exclusive lock (exit 3)."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_create_or_identical(
    path: Path, content: bytes, *, label: str, mode: int = 0o600
) -> str:
    """Create-only publication; byte-identical reruns are idempotent no-ops.

    Same repository-standard publication discipline as the C2/C3 record
    boundary: a single exclusive ``O_CREAT | O_EXCL`` open (no
    check-then-replace window), full write + fsync before returning, and
    cleanup of only the exclusively-created inode on failure.  The parent
    directory entry is fsynced after the file body (and its own parent when
    the store directory itself was just created), so a publication that must
    precede the config swap is durable as a directory entry, not only as
    file bytes.
    """

    if path.is_symlink():
        raise ActivationExecutionError(
            "OUTPUT_PATH_SYMLINK", f"{label} must not be a symlink: {path}"
        )
    parent_existed = path.parent.is_dir()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError:
        if path.is_symlink():
            raise ActivationExecutionError(
                "OUTPUT_PATH_SYMLINK", f"{label} must not be a symlink: {path}"
            ) from None
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ActivationExecutionError(
                "OUTPUT_PATH_UNREADABLE",
                f"{label} already exists and cannot be read; outputs are "
                f"immutable — choose a new path: {path}",
            ) from exc
        if existing == content:
            return "IDEMPOTENT"
        raise ActivationExecutionError(
            "OUTPUT_PATH_CONFLICT",
            f"{label} already exists with different content; outputs are "
            f"immutable — choose a new path: {path}",
        ) from None
    created_ino = os.fstat(descriptor).st_ino
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
        if not parent_existed:
            # The store directory entry itself is new; make it durable inside
            # the activation root (store layouts are one level deep).
            _fsync_dir(path.parent.parent)
    except BaseException:
        try:
            if os.stat(path).st_ino == created_ino:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return "CREATED"


def _pretty_json_bytes(model: BaseModel) -> bytes:
    return (
        json.dumps(
            json.loads(model.model_dump_json()),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Immutable contracts
# ---------------------------------------------------------------------------


class ProfileActivationReceiptV1(BaseModel):
    """Immutable, deterministic receipt of one completed activation.

    Binds the exact fresh plan identity and content, the base/target profile
    bytes, the release manifest, the fresh audit, the active owner decision
    record, the strictly loaded evidence bundle, the re-attesting trust-root
    registry, the exact config bytes replaced (prior and activated hashes),
    the content-addressed before-image and the rollback reference.  No
    wall-clock field: a resumed or repeated activation of the same
    authoritative state produces byte-identical bytes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_receipt_v1"] = (
        "profile_activation_receipt_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    activation_id: StrictStr = Field(min_length=1, max_length=168)
    plan_id: StrictStr = Field(min_length=1, max_length=168)
    plan_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    current_profile_id: StrictStr = Field(min_length=1, max_length=128)
    current_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    activated_profile_id: StrictStr = Field(min_length=1, max_length=128)
    activated_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    release_manifest_id: StrictStr = Field(min_length=1, max_length=168)
    release_manifest_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    audit_id: StrictStr = Field(min_length=1, max_length=168)
    audit_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    decision_record_id: StrictStr = Field(min_length=1, max_length=168)
    decision_record_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    evidence_bundle_id: StrictStr = Field(min_length=1, max_length=168)
    evidence_bundle_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    authority_registry_id: StrictStr = Field(min_length=1, max_length=168)
    authority_registry_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    project_config_path: StrictStr = Field(min_length=1, max_length=2_048)
    prior_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    activated_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    prior_default_profile: StrictStr = Field(min_length=1, max_length=128)
    activated_default_profile: StrictStr = Field(min_length=1, max_length=128)
    before_image_name: StrictStr = Field(min_length=1, max_length=256)
    before_image_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    outcome: Literal["ACTIVATED"] = "ACTIVATED"
    rollback_reference: StrictStr = Field(min_length=1, max_length=4_096)
    rollback_exclusions: list[StrictStr] = Field(min_length=1, max_length=16)
    apply_was_explicit_opt_in: Literal[True] = True
    automatic_rollback_allowed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if tuple(self.rollback_exclusions) != ROLLBACK_EXCLUSIONS:
            raise ValueError(
                "receipt rollback exclusions are the fixed C2 exclusions"
            )
        expected_id = deterministic_id(
            "profile-activation-execution",
            self.plan_id,
            self.project_config_path,
            self.prior_config_sha256,
            self.activated_config_sha256,
            self.decision_record_id,
            self.decision_record_content_sha256,
            self.evidence_bundle_id,
            self.evidence_bundle_content_sha256,
            self.authority_registry_id,
            self.authority_registry_content_sha256,
        )
        if self.activation_id != expected_id:
            raise ValueError("activation id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("receipt content_sha256 does not match content")
        return self

    def serialized_bytes(self) -> bytes:
        return _pretty_json_bytes(self)


class ProfileActivationIntentV1(BaseModel):
    """Immutable intent journal persisted before any config byte changes.

    Embeds the complete deterministic receipt so an interrupted apply can be
    finalized byte-identically without re-deriving (or re-trusting) anything.
    The journal is never rewritten; later invocations classify it against the
    observable disk state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_intent_v1"] = (
        "profile_activation_intent_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    intent_id: StrictStr = Field(min_length=1, max_length=168)
    receipt: ProfileActivationReceiptV1
    recovery_note: StrictStr = Field(min_length=1, max_length=2_048)
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_intent(self) -> Self:
        if self.intent_id != self.receipt.activation_id:
            raise ValueError("intent id must equal the embedded activation id")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("intent content_sha256 does not match content")
        return self

    def serialized_bytes(self) -> bytes:
        return _pretty_json_bytes(self)


class ProfileActivationRollbackOutcomeV1(BaseModel):
    """Immutable record of one completed explicit rollback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_rollback_v1"] = (
        "profile_activation_rollback_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    rollback_id: StrictStr = Field(min_length=1, max_length=168)
    activation_id: StrictStr = Field(min_length=1, max_length=168)
    receipt_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    project_config_path: StrictStr = Field(min_length=1, max_length=2_048)
    restored_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    restored_default_profile: StrictStr = Field(min_length=1, max_length=128)
    before_image_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    outcome: Literal["ROLLED_BACK"] = "ROLLED_BACK"
    rollback_was_explicit_opt_in: Literal[True] = True
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        expected_id = deterministic_id(
            "profile-activation-rollback",
            self.activation_id,
            self.receipt_content_sha256,
            self.project_config_path,
            self.restored_config_sha256,
        )
        if self.rollback_id != expected_id:
            raise ValueError("rollback id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError(
                "rollback outcome content_sha256 does not match content"
            )
        return self

    def serialized_bytes(self) -> bytes:
        return _pretty_json_bytes(self)


class ProfileActivationRollbackIntentV1(BaseModel):
    """Immutable recovery intent persisted before the config restoration.

    Written while the config still holds the receipt's activated bytes, this
    record is *not* a claim that the rollback completed: it binds the exact
    receipt, config path and byte hashes an interrupted rollback can be
    verified against, so a retry that already observes the restored bytes
    can finalize the durable rollback outcome deterministically without
    rewriting the config — and without fabricating an outcome for a rollback
    that never provably ran.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_rollback_intent_v1"] = (
        "profile_activation_rollback_intent_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    rollback_id: StrictStr = Field(min_length=1, max_length=168)
    activation_id: StrictStr = Field(min_length=1, max_length=168)
    receipt_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    project_config_path: StrictStr = Field(min_length=1, max_length=2_048)
    activated_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    restored_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    before_image_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    purpose: Literal["ROLLBACK_RECOVERY_INTENT"] = "ROLLBACK_RECOVERY_INTENT"
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_intent(self) -> Self:
        expected_id = deterministic_id(
            "profile-activation-rollback",
            self.activation_id,
            self.receipt_content_sha256,
            self.project_config_path,
            self.restored_config_sha256,
        )
        if self.rollback_id != expected_id:
            raise ValueError(
                "rollback intent id disagrees with the bound content"
            )
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError(
                "rollback intent content_sha256 does not match content"
            )
        return self

    def serialized_bytes(self) -> bytes:
        return _pretty_json_bytes(self)


class ProfileActivationPreviewV1(BaseModel):
    """The deterministic, read-only preview payload of one activation intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_preview_v1"] = (
        "profile_activation_preview_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    preview_state: Literal["READY_FOR_APPLY", "BLOCKED"]
    plan_id: StrictStr = Field(min_length=1, max_length=168)
    plan_state: StrictStr = Field(min_length=1, max_length=64)
    plan_blockers: list[StrictStr] = Field(max_length=128)
    executor_blockers: list[StrictStr] = Field(max_length=128)
    blockers: list[StrictStr] = Field(max_length=256)
    current_profile_id: StrictStr = Field(min_length=1, max_length=128)
    current_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    proposed_profile_id: StrictStr = Field(min_length=1, max_length=128)
    proposed_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    project_config_path: StrictStr = Field(min_length=1, max_length=2_048)
    original_config_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    prior_default_profile: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )
    proposed_config_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    config_diff: list[StrictStr] = Field(max_length=512)
    activation_id: StrictStr | None = Field(
        default=None, min_length=1, max_length=168
    )
    before_image_path: StrictStr | None = Field(
        default=None, min_length=1, max_length=2_048
    )
    receipt_path: StrictStr | None = Field(
        default=None, min_length=1, max_length=2_048
    )
    rollback_command: StrictStr | None = Field(
        default=None, min_length=1, max_length=4_096
    )
    apply_command_hint: StrictStr | None = Field(
        default=None, min_length=1, max_length=4_096
    )
    execution_performed: Literal[False] = False
    automatic_activation_allowed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_preview(self) -> Self:
        if self.preview_state == "READY_FOR_APPLY":
            if self.blockers:
                raise ValueError("a ready preview carries no blockers")
            for required in (
                self.original_config_sha256,
                self.prior_default_profile,
                self.proposed_config_sha256,
                self.activation_id,
                self.before_image_path,
                self.receipt_path,
                self.rollback_command,
                self.apply_command_hint,
            ):
                if required is None:
                    raise ValueError(
                        "a ready preview binds the full intended execution"
                    )
        elif not self.blockers:
            raise ValueError("a blocked preview names its blockers")
        expected_blockers = sorted(
            set(self.plan_blockers) | set(self.executor_blockers)
        )
        if self.blockers != expected_blockers:
            raise ValueError("preview blockers are the union of plan/executor")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("preview content_sha256 does not match content")
        return self

    def serialized_bytes(self) -> bytes:
        return _pretty_json_bytes(self)


class ActivationApplyResult(NamedTuple):
    """Library result of one apply invocation (CLI composes the payload)."""

    status: str
    receipt: ProfileActivationReceiptV1
    detail: str


class ActivationRollbackResult(NamedTuple):
    """Library result of one rollback invocation."""

    status: str
    outcome: ProfileActivationRollbackOutcomeV1 | None
    detail: str


class _EditedConfig(NamedTuple):
    old_default: str
    new_bytes: bytes
    old_bytes: bytes


# ---------------------------------------------------------------------------
# Path guards
# ---------------------------------------------------------------------------


def _protected_roots() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[3]
    roots = [repo_root / name for name in _PROTECTED_REPO_SUBDIRS]
    cwd = Path.cwd()
    roots.extend(cwd / name for name in ("rules", "config"))
    return [root.resolve() for root in roots]


def _guard_target_config(config_path: Path) -> Path:
    """Validate the mutation target: a regular, non-symlink, non-protected file."""

    try:
        metadata = os.lstat(config_path)
    except OSError as exc:
        raise ActivationExecutionError(
            "CONFIG_PATH_UNAVAILABLE",
            f"the project config cannot be inspected: {config_path} "
            f"({str(exc)[:200]})",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ActivationExecutionError(
            "CONFIG_PATH_SYMLINK",
            f"the activation target must not be a symlink: {config_path}",
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise ActivationExecutionError(
            "CONFIG_PATH_NOT_REGULAR",
            f"the activation target must be a regular file: {config_path}",
        )
    resolved = config_path.resolve()
    for root in _protected_roots():
        if resolved == root or resolved.is_relative_to(root):
            raise ActivationExecutionError(
                "CONFIG_PATH_PROTECTED",
                f"the activation target is a checked-in repository artifact "
                f"({resolved} under {root}); activate a private copy such as "
                ".tve-private/project.toml, never the template, rules or "
                "release artifacts",
            )
    return resolved


def _guard_activation_root(activation_root: Path) -> Path:
    try:
        metadata = os.lstat(activation_root)
    except OSError:
        metadata = None
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode):
            raise ActivationExecutionError(
                "ACTIVATION_ROOT_SYMLINK",
                f"the activation root must not be a symlink: {activation_root}",
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise ActivationExecutionError(
                "ACTIVATION_ROOT_NOT_DIRECTORY",
                f"the activation root must be a directory: {activation_root}",
            )
    resolved = activation_root.resolve()
    for root in _protected_roots():
        if resolved == root or resolved.is_relative_to(root):
            raise ActivationExecutionError(
                "ACTIVATION_ROOT_PROTECTED",
                f"the activation root must live outside checked-in repository "
                f"trees ({resolved} under {root})",
            )
    return resolved


def _guard_contained_dir(activation_root: Path, relative: str) -> Path:
    """Refuse a symlinked/non-directory activation-store descendant.

    Every existing path component below the (already verified) activation
    root must be a real directory — a symlink here could direct the lock
    file, journal, before-image, receipt or rollback outcome outside the
    private store.  Missing components are created later by the anchored
    ``mkdir(parents=True)`` inside the verified root and need no check.  The
    resolved descendant is additionally proven to stay under the root.
    """

    target = activation_root / relative
    current = activation_root
    for part in Path(relative).parts:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ActivationExecutionError(
                "ACTIVATION_STORE_UNAVAILABLE",
                f"the activation store directory '{relative}' cannot be "
                f"inspected: {current} ({str(exc)[:200]})",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ActivationExecutionError(
                "ACTIVATION_STORE_SYMLINK",
                f"the activation store directory '{relative}' must be a real "
                f"directory inside the activation root, not a symlink: "
                f"{current}",
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise ActivationExecutionError(
                "ACTIVATION_STORE_NOT_DIRECTORY",
                f"the activation store directory '{relative}' must be a real "
                f"directory inside the activation root: {current}",
            )
    resolved = target.resolve(strict=False)
    if not (resolved == activation_root or resolved.is_relative_to(activation_root)):
        raise ActivationExecutionError(
            "ACTIVATION_STORE_ESCAPE",
            f"the activation store directory '{relative}' resolves outside "
            f"the activation root: {resolved}",
        )
    return target


def _guard_activation_store(activation_root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        _guard_contained_dir(activation_root, name)


def _lock_path(activation_root: Path, resolved_config: Path) -> Path:
    digest = _sha256_hex(str(resolved_config).encode("utf-8"))[:24]
    return activation_root / "locks" / f"{digest}.lock"


class _ConfigLock:
    """Exclusive per-config activation lock, non-blocking, fail-closed."""

    def __init__(self, activation_root: Path, resolved_config: Path) -> None:
        self.path = _lock_path(activation_root, resolved_config)
        self._descriptor: int | None = None

    def __enter__(self) -> _ConfigLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise ActivationExecutionError(
                "ACTIVATION_LOCK_UNAVAILABLE",
                f"the activation lock cannot be acquired: {str(exc)[:200]}",
            ) from exc
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._descriptor)
            self._descriptor = None
            raise ActivationBusyError(str(self.path)) from exc
        except OSError as exc:
            os.close(self._descriptor)
            self._descriptor = None
            raise ActivationExecutionError(
                "ACTIVATION_LOCK_UNAVAILABLE",
                f"the activation lock cannot be acquired: {str(exc)[:200]}",
            ) from exc
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._descriptor is not None:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self._descriptor)
                self._descriptor = None


# ---------------------------------------------------------------------------
# Byte-preserving [profiles].default edit
# ---------------------------------------------------------------------------


def derive_default_profile_edit(
    config_bytes: bytes, target_profile_id: str
) -> _EditedConfig:
    """Substitute exactly the ``[profiles] default`` scalar, byte-preserving.

    Every other byte (comments, ordering, key styles, line endings, trailing
    newline) survives verbatim; the result must re-parse as TOML whose only
    semantic difference is ``profiles.default``.  Ambiguous, missing,
    multi-line or non-string ``default`` values fail closed with classified
    codes.
    """

    if not _PROFILE_ID_PATTERN.fullmatch(target_profile_id):
        raise ActivationExecutionError(
            "TARGET_PROFILE_ID_INVALID",
            "target profile id is not a plain profile identifier: "
            f"{target_profile_id!r}",
        )
    try:
        text = config_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ActivationExecutionError(
            "CONFIG_BYTES_NOT_UTF8",
            f"the project config is not valid UTF-8: {str(exc)[:200]}",
        ) from exc
    try:
        old_parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ActivationExecutionError(
            "CONFIG_TOML_INVALID",
            f"the project config does not parse as TOML: {str(exc)[:200]}",
        ) from exc
    profiles_table = old_parsed.get("profiles")
    if not isinstance(profiles_table, dict) or "default" not in profiles_table:
        raise ActivationExecutionError(
            "CONFIG_PROFILES_TABLE_MISSING",
            "the project config has no [profiles] table with a default key",
        )
    old_default = profiles_table["default"]
    if not isinstance(old_default, str):
        raise ActivationExecutionError(
            "CONFIG_DEFAULT_VALUE_UNSUPPORTED",
            f"[profiles] default must be a quoted string (got "
            f"{type(old_default).__name__})",
        )

    lines = text.splitlines(keepends=True)
    in_profiles = False
    matched_line = -1
    match_span: tuple[int, int] | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            header = stripped[1 : stripped.index("]")] if "]" in stripped else ""
            in_profiles = header.strip() == "profiles"
            continue
        if not in_profiles:
            continue
        if not _DEFAULT_KEY_HINT_PATTERN.match(line):
            continue
        line_body = line.rstrip("\r\n")
        match = _DEFAULT_ASSIGNMENT_PATTERN.match(line_body)
        if match is not None and line_body[match.start("quote") :].startswith(
            ('"""', "'''")
        ):
            match = None  # a triple-quote opener is not a single-line value
        if match is None:
            raise ActivationExecutionError(
                "CONFIG_DEFAULT_VALUE_UNSUPPORTED",
                "the [profiles] default assignment must be a single-line "
                "quoted string value (multi-line, unquoted or non-string "
                "defaults are refused)",
            )
        if matched_line >= 0:
            raise ActivationExecutionError(
                "CONFIG_DEFAULT_KEY_AMBIGUOUS",
                "the [profiles] table holds more than one default assignment",
            )
        matched_line = index
        match_span = (match.start("value"), match.end("value"))
    if matched_line < 0 or match_span is None:
        raise ActivationExecutionError(
            "CONFIG_DEFAULT_KEY_MISSING",
            "no usable [profiles] default string assignment was found in "
            "the [profiles] table",
        )

    line_text = lines[matched_line]
    newline = ""
    for candidate in ("\r\n", "\n"):
        if line_text.endswith(candidate):
            newline = candidate
            break
    body = line_text[: len(line_text) - len(newline)] if newline else line_text
    start, end = match_span
    new_body = body[:start] + target_profile_id + body[end:]
    lines[matched_line] = new_body + newline
    new_text = "".join(lines)

    try:
        new_parsed = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise ActivationExecutionError(
            "CONFIG_EDIT_RESULT_INVALID",
            f"the edited config no longer parses as TOML: {str(exc)[:200]} "
            "(this is an executor defect — no bytes were written)",
        ) from exc
    new_profiles = new_parsed.get("profiles")
    if not isinstance(new_profiles, dict):
        raise ActivationExecutionError(
            "CONFIG_EDIT_RESULT_INVALID",
            "the edited config lost its [profiles] table "
            "(executor defect — no bytes were written)",
        )
    if new_profiles.get("default") != target_profile_id:
        raise ActivationExecutionError(
            "CONFIG_EDIT_RESULT_INVALID",
            "the edited config's [profiles] default is not the target "
            "(executor defect — no bytes were written)",
        )
    if _without_default(old_parsed) != _without_default(new_parsed):
        raise ActivationExecutionError(
            "CONFIG_EDIT_RESULT_INVALID",
            "the edit changed more than [profiles] default "
            "(executor defect — no bytes were written)",
        )
    return _EditedConfig(
        old_default=old_default,
        new_bytes=new_text.encode("utf-8"),
        old_bytes=config_bytes,
    )


def _without_default(parsed: dict) -> dict:
    profiles = dict(parsed.get("profiles") or {})
    profiles.pop("default", None)
    semantic = dict(parsed)
    semantic["profiles"] = profiles
    return semantic


# ---------------------------------------------------------------------------
# Executor provenance association (C4-A preflight outcome)
# ---------------------------------------------------------------------------


def evidence_record_association_blockers(
    *,
    active_record: OwnerPolicyDecisionRecordV1 | None,
    evidence: LoadedOwnerDecisionEvidence | None,
) -> list[str]:
    """Require the active record to be exactly the bundle's embedded record.

    The 2026-10-22 preflight demonstrated that the read-only planner accepts
    a supplied record whose content hash/bytes differ from the evidence
    bundle's embedded record while fresh re-attestation still returns READY.
    A mutation needs a tighter provenance receipt: the record the operator
    selected must be the very record the capture boundary embedded — same
    deterministic id AND byte-identical canonical content.
    """

    blockers: list[str] = []
    if evidence is None:
        blockers.append("EVIDENCE_BUNDLE_ABSENT")
        return blockers
    embedded = evidence.bundle.record
    if embedded is None:
        blockers.append("EVIDENCE_BUNDLE_RECORD_MISSING")
        return blockers
    if active_record is None:
        blockers.append("ACTIVE_RECORD_ABSENT")
        return blockers
    if active_record.decision_record_id != embedded.decision_record_id:
        blockers.append("EVIDENCE_RECORD_ID_MISMATCH")
    if active_record.content_sha256 != embedded.content_sha256:
        blockers.append("EVIDENCE_RECORD_CONTENT_MISMATCH")
    if canonical_json_bytes(
        active_record.model_dump(mode="json")
    ) != canonical_json_bytes(embedded.model_dump(mode="json")):
        blockers.append("EVIDENCE_RECORD_BYTES_MISMATCH")
    return blockers


# ---------------------------------------------------------------------------
# Shared derivation
# ---------------------------------------------------------------------------


class _DerivedExecution(NamedTuple):
    plan: ProfileActivationPlanV1
    evidence: LoadedOwnerDecisionEvidence | None
    executor_blockers: list[str]
    config_bytes: bytes
    edited: _EditedConfig | None


def _derive_execution(
    *,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    boundary_input,
    decision_records: Sequence[OwnerPolicyDecisionRecordV1],
    revocations: Sequence[OwnerPolicyDecisionRevocationV1],
    policy_exceptions: Sequence[VersionedPolicyExceptionV1],
    authority_evidence: LoadedOwnerDecisionEvidence | None,
    signed_revocations: Sequence[OwnerSignedRevocationEvidenceV1],
    signed_supersessions: Sequence[OwnerSignedSupersessionEvidenceV1],
    lifecycle_trust_root: OwnerProvenanceKeyRegistryV1 | None,
    project_config_path: Path,
    authority_verifier,
    watchlist_paths: Sequence[str | Path] = (),
    normalized_input_paths: Sequence[str | Path] = (),
    backtest_manifest_paths: Sequence[str | Path] = (),
    surface_snapshot_paths: Sequence[str | Path] = (),
    runner_config_paths: Sequence[str | Path] = (),
) -> _DerivedExecution:
    config_bytes = _regular_file_bytes(project_config_path)
    plan = plan_profile_activation(
        base_profile_path=base_profile_path,
        target_profile_path=target_profile_path,
        release_manifest_path=release_manifest_path,
        boundary_input=boundary_input,
        decision_records=decision_records,
        revocations=revocations,
        policy_exceptions=policy_exceptions,
        authority_verifier=authority_verifier,
        signed_revocations=signed_revocations,
        signed_supersessions=signed_supersessions,
        lifecycle_trust_root=lifecycle_trust_root,
        project_config_path=project_config_path,
        watchlist_paths=watchlist_paths,
        normalized_input_paths=normalized_input_paths,
        backtest_manifest_paths=backtest_manifest_paths,
        surface_snapshot_paths=surface_snapshot_paths,
        runner_config_paths=runner_config_paths,
    )
    active_record = next(
        (
            record
            for record in decision_records
            if record.decision_record_id == (plan.decision_record_id or "")
        ),
        None,
    )
    executor_blockers = evidence_record_association_blockers(
        active_record=active_record, evidence=authority_evidence
    )
    edited: _EditedConfig | None = None
    if plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION" and not (
        executor_blockers
    ):
        edited = derive_default_profile_edit(
            config_bytes, plan.proposed_profile_id
        )
        if edited.old_default == plan.proposed_profile_id:
            executor_blockers.append("DEFAULT_ALREADY_TARGET")
            edited = None
    return _DerivedExecution(
        plan=plan,
        evidence=authority_evidence,
        executor_blockers=executor_blockers,
        config_bytes=config_bytes,
        edited=edited,
    )


def build_activation_receipt(
    *,
    plan: ProfileActivationPlanV1,
    evidence: LoadedOwnerDecisionEvidence,
    project_config_path: Path,
    edited: _EditedConfig,
) -> ProfileActivationReceiptV1:
    """Assemble the deterministic receipt from freshly derived state."""

    if plan.authority_reverification_registry_id is None:
        raise ActivationExecutionError(
            "RECEIPT_INPUTS_INCOMPLETE",
            "a READY plan must carry the re-attestation registry identity",
        )
    prior_sha = _sha256_hex(edited.old_bytes)
    fields = {
        "plan_id": plan.plan_id,
        "plan_content_sha256": plan.content_sha256,
        "current_profile_id": plan.current_profile_id,
        "current_profile_sha256": plan.current_profile_sha256,
        "activated_profile_id": plan.proposed_profile_id,
        "activated_profile_sha256": plan.proposed_profile_sha256,
        "release_manifest_id": plan.release_manifest_id,
        "release_manifest_content_sha256": plan.release_manifest_content_sha256,
        "audit_id": plan.audit_id,
        "audit_content_sha256": plan.audit_content_sha256,
        "decision_record_id": plan.decision_record_id or "",
        "decision_record_content_sha256": plan.decision_record_content_sha256
        or "",
        "evidence_bundle_id": evidence.bundle.bundle_id,
        "evidence_bundle_content_sha256": evidence.bundle.content_sha256,
        "authority_registry_id": plan.authority_reverification_registry_id,
        "authority_registry_content_sha256": (
            plan.authority_reverification_registry_content_sha256
        ),
        "project_config_path": str(project_config_path),
        "prior_config_sha256": prior_sha,
        "activated_config_sha256": _sha256_hex(edited.new_bytes),
        "prior_default_profile": edited.old_default,
        "activated_default_profile": plan.proposed_profile_id,
        "before_image_name": f"{prior_sha}.toml",
        "before_image_sha256": prior_sha,
        "rollback_reference": (
            "tve evolution rollback-activation --receipt "
            "<activation-root>/receipts/<activation_id>.json "
            "--activation-root <activation-root>"
        ),
        "rollback_exclusions": list(ROLLBACK_EXCLUSIONS),
    }
    activation_id = deterministic_id(
        "profile-activation-execution",
        fields["plan_id"],
        fields["project_config_path"],
        fields["prior_config_sha256"],
        fields["activated_config_sha256"],
        fields["decision_record_id"],
        fields["decision_record_content_sha256"],
        fields["evidence_bundle_id"],
        fields["evidence_bundle_content_sha256"],
        fields["authority_registry_id"],
        fields["authority_registry_content_sha256"],
    )
    payload = {
        "contract": "profile_activation_receipt_v1",
        "schema_version": "1.0.0",
        "activation_id": activation_id,
        **fields,
        "outcome": "ACTIVATED",
        "apply_was_explicit_opt_in": True,
        "automatic_rollback_allowed": False,
    }
    payload["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    )
    return ProfileActivationReceiptV1.model_validate(payload)


def build_rollback_command(receipt_path: Path, activation_root: Path) -> str:
    """The complete, safely shell-quoted operator rollback command."""

    return shlex.join(
        [
            "tve",
            "evolution",
            "rollback-activation",
            "--receipt",
            str(receipt_path),
            "--activation-root",
            str(activation_root),
        ]
    )


def build_apply_command_hint(
    apply_command_argv: Sequence[str],
    *,
    plan_id: str,
    original_config_sha256: str,
) -> str:
    """The complete, safely shell-quoted operator apply command.

    ``apply_command_argv`` is the exact ``activate-profile`` argument vector
    (starting at ``"evolution"``) the operator's invocation used, without
    the trailing apply opt-in flags, which are bound to the freshly derived
    preview identities here.
    """

    return shlex.join(
        [
            "tve",
            *apply_command_argv,
            "--apply",
            "--expected-plan-id",
            plan_id,
            "--expected-config-sha256",
            original_config_sha256,
        ]
    )


def _build_intent(receipt: ProfileActivationReceiptV1) -> (
    ProfileActivationIntentV1
):
    fields = {
        "contract": "profile_activation_intent_v1",
        "schema_version": "1.0.0",
        "intent_id": receipt.activation_id,
        "receipt": json.loads(receipt.model_dump_json()),
        "recovery_note": (
            "interrupted apply: if the config hash equals "
            "activated_config_sha256, rerun the same apply to finalize the "
            "receipt; if it equals prior_config_sha256, rerun to resume; if "
            "neither, inspect manually — the before-image is preserved and "
            "no automatic mutation will proceed"
        ),
    }
    temporary = ProfileActivationIntentV1.model_construct(
        **fields, content_sha256="0" * 64
    )
    payload = temporary.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    )
    return ProfileActivationIntentV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Preview (default, read-only)
# ---------------------------------------------------------------------------


def preview_profile_activation(
    *,
    activation_root: str | Path,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    boundary_input=None,
    decision_records: Sequence[OwnerPolicyDecisionRecordV1] = (),
    revocations: Sequence[OwnerPolicyDecisionRevocationV1] = (),
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
    authority_verifier=None,
    authority_evidence: LoadedOwnerDecisionEvidence | None = None,
    signed_revocations: Sequence[OwnerSignedRevocationEvidenceV1] = (),
    signed_supersessions: Sequence[OwnerSignedSupersessionEvidenceV1] = (),
    lifecycle_trust_root: OwnerProvenanceKeyRegistryV1 | None = None,
    project_config_path: str | Path,
    watchlist_paths: Sequence[str | Path] = (),
    normalized_input_paths: Sequence[str | Path] = (),
    backtest_manifest_paths: Sequence[str | Path] = (),
    surface_snapshot_paths: Sequence[str | Path] = (),
    runner_config_paths: Sequence[str | Path] = (),
    apply_command_argv: Sequence[str] | None = None,
) -> ProfileActivationPreviewV1:
    """Derive the read-only preview; performs no writes of any kind.

    ``apply_command_argv`` carries the exact original ``activate-profile``
    argument vector (starting at ``"evolution"``, without the trailing
    ``--apply`` opt-in flags) so the emitted ``apply_command_hint`` is a
    complete, shell-quoted, directly executable command.  Only the CLI
    boundary sees the original decision/evidence file paths; when it is
    omitted, the hint names only the path arguments this function itself
    received and is not guaranteed runnable for library callers that loaded
    records from files.
    """

    root = _guard_activation_root(Path(activation_root))
    config_path = _guard_target_config(Path(project_config_path))
    derived = _derive_execution(
        base_profile_path=base_profile_path,
        target_profile_path=target_profile_path,
        release_manifest_path=release_manifest_path,
        boundary_input=boundary_input,
        decision_records=decision_records,
        revocations=revocations,
        policy_exceptions=policy_exceptions,
        authority_evidence=authority_evidence,
        signed_revocations=signed_revocations,
        signed_supersessions=signed_supersessions,
        lifecycle_trust_root=lifecycle_trust_root,
        project_config_path=config_path,
        authority_verifier=authority_verifier,
        watchlist_paths=watchlist_paths,
        normalized_input_paths=normalized_input_paths,
        backtest_manifest_paths=backtest_manifest_paths,
        surface_snapshot_paths=surface_snapshot_paths,
        runner_config_paths=runner_config_paths,
    )
    plan = derived.plan
    blockers = sorted(set(plan.blockers) | set(derived.executor_blockers))
    ready = (
        plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
        and not derived.executor_blockers
        and derived.edited is not None
    )

    original_sha: str | None = None
    prior_default: str | None = None
    proposed_sha: str | None = None
    diff_lines: list[str] = []
    activation_id: str | None = None
    before_image_path: str | None = None
    receipt_path: str | None = None
    rollback_command: str | None = None
    apply_hint: str | None = None

    if derived.edited is not None:
        edited = derived.edited
        original_sha = _sha256_hex(edited.old_bytes)
        prior_default = edited.old_default
        proposed_sha = _sha256_hex(edited.new_bytes)
        diff_lines = [
            line.rstrip("\n")
            for line in difflib.unified_diff(
                edited.old_bytes.decode("utf-8").splitlines(keepends=True),
                edited.new_bytes.decode("utf-8").splitlines(keepends=True),
                fromfile=f"project.toml (current, sha256 {original_sha})",
                tofile=f"project.toml (proposed, sha256 {proposed_sha})",
                n=2,
            )
        ]
    if ready and derived.evidence is not None:
        receipt = build_activation_receipt(
            plan=plan,
            evidence=derived.evidence,
            project_config_path=config_path,
            edited=derived.edited,
        )
        activation_id = receipt.activation_id
        before_image_path = str(
            root / "before-images" / receipt.before_image_name
        )
        receipt_path = str(root / "receipts" / f"{receipt.activation_id}.json")
        rollback_command = build_rollback_command(Path(receipt_path), root)
        argv = (
            list(apply_command_argv)
            if apply_command_argv is not None
            else [
                "evolution",
                "activate-profile",
                "--base-profile",
                str(base_profile_path),
                "--target-profile",
                str(target_profile_path),
                "--release-manifest",
                str(release_manifest_path),
                "--project-config",
                str(config_path),
                "--activation-root",
                str(root),
            ]
        )
        apply_hint = build_apply_command_hint(
            argv,
            plan_id=plan.plan_id,
            original_config_sha256=original_sha or "",
        )

    payload = {
        "contract": "profile_activation_preview_v1",
        "schema_version": "1.0.0",
        "preview_state": "READY_FOR_APPLY" if ready else "BLOCKED",
        "plan_id": plan.plan_id,
        "plan_state": plan.plan_state,
        "plan_blockers": sorted(plan.blockers),
        "executor_blockers": sorted(derived.executor_blockers),
        "blockers": blockers,
        "current_profile_id": plan.current_profile_id,
        "current_profile_sha256": plan.current_profile_sha256,
        "proposed_profile_id": plan.proposed_profile_id,
        "proposed_profile_sha256": plan.proposed_profile_sha256,
        "project_config_path": str(config_path),
        "original_config_sha256": original_sha,
        "prior_default_profile": prior_default,
        "proposed_config_sha256": proposed_sha,
        "config_diff": diff_lines,
        "activation_id": activation_id,
        "before_image_path": before_image_path,
        "receipt_path": receipt_path,
        "rollback_command": rollback_command,
        "apply_command_hint": apply_hint,
        "execution_performed": False,
        "automatic_activation_allowed": False,
    }
    payload["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    )
    return ProfileActivationPreviewV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Apply (explicit opt-in mutation)
# ---------------------------------------------------------------------------


def _journals_for_config(
    journal_dir: Path, resolved_config: Path
) -> list[ProfileActivationIntentV1]:
    intents: list[ProfileActivationIntentV1] = []
    if not journal_dir.is_dir():
        return intents
    for entry in sorted(journal_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".json":
            raise ActivationExecutionError(
                "JOURNAL_DIR_FOREIGN_ENTRY",
                "the activation journal directory holds an unexpected entry: "
                f"{entry}",
            )
        try:
            intent = ProfileActivationIntentV1.model_validate(
                json.loads(entry.read_bytes())
            )
        except Exception as exc:
            raise ActivationExecutionError(
                "JOURNAL_CORRUPT",
                f"an activation journal cannot be validated: {entry} "
                f"({str(exc)[:200]})",
            ) from exc
        if Path(intent.receipt.project_config_path) == resolved_config:
            intents.append(intent)
    return intents


def _load_persisted_receipt(
    path: Path,
) -> ProfileActivationReceiptV1:
    try:
        return ProfileActivationReceiptV1.model_validate(json.loads(path.read_bytes()))
    except Exception as exc:
        raise ActivationExecutionError(
            "RECEIPT_CORRUPT",
            f"the persisted receipt cannot be validated: {path} "
            f"({str(exc)[:200]})",
        ) from exc


def _stage_and_replace(
    *,
    config_path: Path,
    staged_name: str,
    content: bytes,
    expected_current_hash: str,
    blocked_status: str,
    blocked_code: str,
    blocked_detail: str,
    fault_hook: Callable[[str], None] | None = None,
) -> None:
    """Same-directory staged atomic replace with a CAS re-read before it."""

    temp_path = config_path.parent / staged_name
    if temp_path.is_symlink():
        raise ActivationExecutionError(
            "STAGING_PATH_SYMLINK",
            f"the staging path must not be a symlink: {temp_path}",
        )
    if temp_path.exists():
        # A deterministic staging path can only be a leftover of this very
        # operation's interrupted prior run (the exclusive lock is held and
        # the content is hash-verified); anything else fails closed.
        try:
            staged_bytes = temp_path.read_bytes()
        except OSError as exc:
            raise ActivationExecutionError(
                "STAGING_PATH_CONFLICT",
                f"the staging path exists and cannot be read: {temp_path} "
                f"({str(exc)[:200]})",
            ) from exc
        if _sha256_hex(staged_bytes) != _sha256_hex(content):
            raise ActivationExecutionError(
                "STAGING_PATH_CONFLICT",
                f"the staging path already exists with different content: "
                f"{temp_path}",
            )
        temp_path.unlink()
    descriptor = os.open(
        temp_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IMODE(os.lstat(config_path).st_mode),
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    if fault_hook is not None:
        fault_hook("temp_written")
    if _sha256_hex(_regular_file_bytes(config_path)) != expected_current_hash:
        temp_path.unlink(missing_ok=True)
        raise ActivationExecutionBlocked(
            {
                "status": blocked_status,
                "blockers": [blocked_code],
                "detail": blocked_detail,
            }
        )
    os.replace(temp_path, config_path)
    _fsync_dir(config_path.parent)


def apply_profile_activation(
    *,
    activation_root: str | Path,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    expected_plan_id: str,
    expected_config_sha256: str,
    boundary_input=None,
    decision_records: Sequence[OwnerPolicyDecisionRecordV1] = (),
    revocations: Sequence[OwnerPolicyDecisionRevocationV1] = (),
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
    authority_verifier=None,
    authority_evidence: LoadedOwnerDecisionEvidence | None = None,
    signed_revocations: Sequence[OwnerSignedRevocationEvidenceV1] = (),
    signed_supersessions: Sequence[OwnerSignedSupersessionEvidenceV1] = (),
    lifecycle_trust_root: OwnerProvenanceKeyRegistryV1 | None = None,
    project_config_path: str | Path,
    watchlist_paths: Sequence[str | Path] = (),
    normalized_input_paths: Sequence[str | Path] = (),
    backtest_manifest_paths: Sequence[str | Path] = (),
    surface_snapshot_paths: Sequence[str | Path] = (),
    runner_config_paths: Sequence[str | Path] = (),
    fault_hook: Callable[[str], None] | None = None,
) -> ActivationApplyResult:
    """Perform the guarded, idempotent, recoverable single-file activation.

    Everything authoritative is re-derived inside the per-config exclusive
    lock: the fresh plan (READY required), the executor association check and
    the byte-preserving edit.  The persisted intent journal, the
    content-addressed before-image, the same-directory atomic replace and the
    create-only receipt follow in crash-recoverable order.
    """

    root = _guard_activation_root(Path(activation_root))
    config_path = _guard_target_config(Path(project_config_path))
    # Refuse a hostile store layout before the lock exists: nothing may be
    # created inside — let alone outside — the private root.
    _guard_activation_store(root, _APPLY_STORE_DIRS)
    journal_dir = root / "journal"
    receipts_dir = root / "receipts"
    before_images_dir = root / "before-images"

    with _ConfigLock(root, config_path):
        current_hash = _sha256_hex(_regular_file_bytes(config_path))
        pending = _journals_for_config(journal_dir, config_path)
        resume_intent: ProfileActivationIntentV1 | None = None
        for intent in pending:
            receipt_file = receipts_dir / f"{intent.receipt.activation_id}.json"
            if receipt_file.is_file():
                if current_hash == intent.receipt.activated_config_sha256:
                    persisted = _load_persisted_receipt(receipt_file)
                    if persisted != intent.receipt:
                        raise ActivationExecutionError(
                            "RECEIPT_JOURNAL_MISMATCH",
                            "the persisted receipt differs from its intent "
                            f"journal: {receipt_file}",
                        )
                    return ActivationApplyResult(
                        status="COMPLETED_ALREADY",
                        receipt=persisted,
                        detail=(
                            "this exact activation already completed (receipt "
                            "present, config matches the activated hash); "
                            "zero mutation performed"
                        ),
                    )
                # A finished journal whose config was rolled back (or later
                # replaced) is history, not a blocker.
                continue
            if current_hash == intent.receipt.activated_config_sha256:
                # Crash window after replace, before receipt publication.
                result = _write_create_or_identical(
                    receipt_file,
                    intent.receipt.serialized_bytes(),
                    label="activation receipt",
                )
                return ActivationApplyResult(
                    status="FINALIZED_AFTER_INTERRUPTED_REPLACE",
                    receipt=intent.receipt,
                    detail=(
                        "the config replacement had already happened; the "
                        "deterministic receipt was finalized from the "
                        "persisted intent journal with zero further config "
                        f"mutation (publication: {result})"
                    ),
                )
            if current_hash == intent.receipt.prior_config_sha256:
                if resume_intent is not None:
                    raise ActivationExecutionBlocked(
                        {
                            "status": "ACTIVATION_INTENT_AMBIGUOUS",
                            "blockers": ["ACTIVATION_INTENT_AMBIGUOUS"],
                            "detail": (
                                "multiple unfinished activation intents exist "
                                "for this config; resolve them manually "
                                "(inspect the journal directory) before any "
                                "further activation"
                            ),
                        }
                    )
                resume_intent = intent
                continue
            raise ActivationExecutionBlocked(
                {
                    "status": "ACTIVATION_CONFIG_DIVERGED",
                    "blockers": ["ACTIVATION_CONFIG_DIVERGED"],
                    "detail": (
                        "an unfinished activation intent exists but the "
                        "config no longer matches either its prior or its "
                        "activated hash; the before-image is preserved — "
                        "inspect the journal and restore manually"
                    ),
                }
            )

        derived = _derive_execution(
            base_profile_path=base_profile_path,
            target_profile_path=target_profile_path,
            release_manifest_path=release_manifest_path,
            boundary_input=boundary_input,
            decision_records=decision_records,
            revocations=revocations,
            policy_exceptions=policy_exceptions,
            authority_evidence=authority_evidence,
            signed_revocations=signed_revocations,
            signed_supersessions=signed_supersessions,
            lifecycle_trust_root=lifecycle_trust_root,
            project_config_path=config_path,
            authority_verifier=authority_verifier,
            watchlist_paths=watchlist_paths,
            normalized_input_paths=normalized_input_paths,
            backtest_manifest_paths=backtest_manifest_paths,
            surface_snapshot_paths=surface_snapshot_paths,
            runner_config_paths=runner_config_paths,
        )
        plan = derived.plan
        blockers = sorted(set(plan.blockers) | set(derived.executor_blockers))
        if plan.plan_state != "READY_FOR_EXPLICIT_OWNER_EXECUTION" or blockers:
            raise ActivationExecutionBlocked(
                {
                    "status": "ACTIVATION_BLOCKED",
                    "blockers": blockers,
                    "plan_id": plan.plan_id,
                    "plan_state": plan.plan_state,
                    "detail": (
                        "the freshly derived plan is not READY; nothing was "
                        "written"
                    ),
                }
            )
        if derived.edited is None or derived.evidence is None:
            raise ActivationExecutionBlocked(
                {
                    "status": "ACTIVATION_BLOCKED",
                    "blockers": ["ACTIVATION_DERIVATION_INCOMPLETE"],
                    "detail": "executor derivation incomplete; nothing written",
                }
            )
        if plan.plan_id != expected_plan_id:
            raise ActivationExecutionBlocked(
                {
                    "status": "PLAN_ID_MISMATCH",
                    "blockers": ["PLAN_ID_MISMATCH"],
                    "expected_plan_id": expected_plan_id,
                    "derived_plan_id": plan.plan_id,
                    "detail": (
                        "the freshly derived plan identity differs from the "
                        "previewed intent; re-run the preview and apply the "
                        "current identities"
                    ),
                }
            )
        if current_hash != expected_config_sha256:
            raise ActivationExecutionBlocked(
                {
                    "status": "ACTIVATION_CONFIG_UNSTABLE",
                    "blockers": ["ACTIVATION_CONFIG_UNSTABLE"],
                    "expected_config_sha256": expected_config_sha256,
                    "current_config_sha256": current_hash,
                    "detail": (
                        "the config bytes changed since the preview; nothing "
                        "was written"
                    ),
                }
            )
        if current_hash != _sha256_hex(derived.edited.old_bytes):
            raise ActivationExecutionBlocked(
                {
                    "status": "ACTIVATION_CONFIG_UNSTABLE",
                    "blockers": ["ACTIVATION_CONFIG_UNSTABLE"],
                    "detail": (
                        "the config changed during derivation; nothing was "
                        "written"
                    ),
                }
            )

        receipt = build_activation_receipt(
            plan=plan,
            evidence=derived.evidence,
            project_config_path=config_path,
            edited=derived.edited,
        )
        if resume_intent is not None and resume_intent.receipt != receipt:
            raise ActivationExecutionBlocked(
                {
                    "status": "ACTIVATION_INTENT_CONFLICT",
                    "blockers": ["ACTIVATION_INTENT_CONFLICT"],
                    "detail": (
                        "an unfinished intent exists for this config whose "
                        "deterministic receipt differs from the freshly "
                        "derived one; resolve it manually (the before-image "
                        "is preserved under before-images/)"
                    ),
                }
            )

        intent = _build_intent(receipt)
        _write_create_or_identical(
            journal_dir / f"{receipt.activation_id}.json",
            intent.serialized_bytes(),
            label="activation intent journal",
        )
        if fault_hook is not None:
            fault_hook("journal_persisted")

        _write_create_or_identical(
            before_images_dir / receipt.before_image_name,
            derived.edited.old_bytes,
            label="activation before-image",
        )
        if fault_hook is not None:
            fault_hook("before_image_persisted")

        if fault_hook is not None:
            fault_hook("temp_written_pre")
        _stage_and_replace(
            config_path=config_path,
            staged_name=f".tve-activation-{receipt.activation_id}.tmp",
            content=derived.edited.new_bytes,
            expected_current_hash=current_hash,
            blocked_status="ACTIVATION_CONFIG_CHANGED_DURING_APPLY",
            blocked_code="ACTIVATION_CONFIG_CHANGED_DURING_APPLY",
            blocked_detail=(
                "the config changed between derivation and replace "
                "(intervening writer); the staged write was discarded and "
                "nothing was replaced — rerun preview + apply on the current "
                "bytes"
            ),
            fault_hook=fault_hook,
        )
        if fault_hook is not None:
            fault_hook("config_replaced")

        publication = _write_create_or_identical(
            receipts_dir / f"{receipt.activation_id}.json",
            receipt.serialized_bytes(),
            label="activation receipt",
        )
        return ActivationApplyResult(
            status=(
                "ACTIVATED_RESUMED" if resume_intent is not None else "ACTIVATED"
            ),
            receipt=receipt,
            detail=(
                f"[profiles] default changed {receipt.prior_default_profile!r} "
                f"-> {receipt.activated_default_profile!r}; receipt "
                f"publication: {publication}"
            ),
        )


# ---------------------------------------------------------------------------
# Rollback (explicit, byte-exact)
# ---------------------------------------------------------------------------


def load_activation_receipt(path: str | Path) -> ProfileActivationReceiptV1:
    try:
        return ProfileActivationReceiptV1.model_validate(
            json.loads(_regular_file_bytes(Path(path)))
        )
    except ActivationExecutionError:
        raise
    except Exception as exc:
        raise ActivationExecutionError(
            "RECEIPT_INVALID",
            f"the activation receipt cannot be validated: {path} "
            f"({str(exc)[:200]})",
        ) from exc


def _build_rollback_outcome(
    receipt: ProfileActivationReceiptV1, config_path: Path
) -> ProfileActivationRollbackOutcomeV1:
    outcome_payload = {
        "contract": "profile_activation_rollback_v1",
        "schema_version": "1.0.0",
        "activation_id": receipt.activation_id,
        "receipt_content_sha256": receipt.content_sha256,
        "project_config_path": str(config_path),
        "restored_config_sha256": receipt.prior_config_sha256,
        "restored_default_profile": receipt.prior_default_profile,
        "before_image_sha256": receipt.before_image_sha256,
        "outcome": "ROLLED_BACK",
        "rollback_was_explicit_opt_in": True,
    }
    outcome_payload["rollback_id"] = deterministic_id(
        "profile-activation-rollback",
        outcome_payload["activation_id"],
        outcome_payload["receipt_content_sha256"],
        outcome_payload["project_config_path"],
        outcome_payload["restored_config_sha256"],
    )
    outcome_payload["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {
                key: value
                for key, value in outcome_payload.items()
                if key != "content_sha256"
            }
        )
    )
    return ProfileActivationRollbackOutcomeV1.model_validate(outcome_payload)


def _build_rollback_intent(
    receipt: ProfileActivationReceiptV1, config_path: Path
) -> ProfileActivationRollbackIntentV1:
    outcome = _build_rollback_outcome(receipt, config_path)
    fields = {
        "contract": "profile_activation_rollback_intent_v1",
        "schema_version": "1.0.0",
        "rollback_id": outcome.rollback_id,
        "activation_id": receipt.activation_id,
        "receipt_content_sha256": receipt.content_sha256,
        "project_config_path": str(config_path),
        "activated_config_sha256": receipt.activated_config_sha256,
        "restored_config_sha256": receipt.prior_config_sha256,
        "before_image_sha256": receipt.before_image_sha256,
        "purpose": "ROLLBACK_RECOVERY_INTENT",
    }
    fields["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in fields.items() if key != "content_sha256"}
        )
    )
    return ProfileActivationRollbackIntentV1.model_validate(fields)


def _load_validated_rollback_outcome(
    path: Path, expected: ProfileActivationRollbackOutcomeV1
) -> ProfileActivationRollbackOutcomeV1:
    try:
        persisted = ProfileActivationRollbackOutcomeV1.model_validate(
            json.loads(path.read_bytes())
        )
    except Exception as exc:
        raise ActivationExecutionError(
            "ROLLBACK_OUTCOME_CORRUPT",
            f"the persisted rollback outcome cannot be validated: {path} "
            f"({str(exc)[:200]})",
        ) from exc
    if persisted != expected:
        raise ActivationExecutionError(
            "ROLLBACK_OUTCOME_CORRUPT",
            f"the persisted rollback outcome is bound to different content "
            f"than this receipt: {path}",
        )
    return persisted


def _load_validated_rollback_intent(
    path: Path, expected: ProfileActivationRollbackIntentV1
) -> ProfileActivationRollbackIntentV1:
    try:
        persisted = ProfileActivationRollbackIntentV1.model_validate(
            json.loads(path.read_bytes())
        )
    except Exception as exc:
        raise ActivationExecutionError(
            "ROLLBACK_INTENT_CORRUPT",
            f"the persisted rollback recovery intent cannot be validated: "
            f"{path} ({str(exc)[:200]})",
        ) from exc
    if persisted != expected:
        raise ActivationExecutionError(
            "ROLLBACK_INTENT_MISMATCH",
            f"the persisted rollback recovery intent is bound to different "
            f"content than this receipt: {path}",
        )
    return persisted


def _load_verified_before_image(
    before_image: Path, receipt: ProfileActivationReceiptV1
) -> bytes:
    try:
        image_bytes = _regular_file_bytes(before_image)
    except Exception as exc:
        raise ActivationExecutionError(
            "BEFORE_IMAGE_UNAVAILABLE",
            "the receipt-bound before-image cannot be read: "
            f"{before_image} ({str(exc)[:200]})",
        ) from exc
    if _sha256_hex(image_bytes) != receipt.before_image_sha256:
        raise ActivationExecutionError(
            "BEFORE_IMAGE_HASH_MISMATCH",
            "the before-image no longer hashes to its content-addressed "
            f"identity: {before_image}",
        )
    if _sha256_hex(image_bytes) != receipt.prior_config_sha256:
        raise ActivationExecutionError(
            "BEFORE_IMAGE_CONTENT_MISMATCH",
            "the before-image bytes disagree with the receipt's prior "
            "config hash",
        )
    image_parsed = tomllib.loads(image_bytes.decode("utf-8"))
    if image_parsed.get("profiles", {}).get("default") != (
        receipt.prior_default_profile
    ):
        raise ActivationExecutionError(
            "BEFORE_IMAGE_CONTENT_MISMATCH",
            "the before-image's [profiles] default disagrees with the "
            "receipt's prior default",
        )
    return image_bytes


def rollback_profile_activation(
    *,
    receipt_path: str | Path,
    activation_root: str | Path,
    fault_hook: Callable[[str], None] | None = None,
) -> ActivationRollbackResult:
    """Restore the exact prior config bytes from a valid receipt.

    Preconditions, all fail-closed: the receipt validates; the config path it
    binds exists and currently holds either the activated bytes (restore
    proceeds) or already the prior bytes (idempotent ALREADY_RESTORED); any
    other current hash is an intervening change the rollback refuses to
    clobber.  The before-image must still exist with its content-addressed
    hash and must parse with the prior default.

    Audit recoverability: an immutable recovery intent is persisted *before*
    the config restoration, and the immutable rollback outcome *after* it.
    A retry that observes the restored bytes distinguishes (a) a genuinely
    completed rollback (valid outcome present — explicit no-op), (b) an
    interrupted rollback (valid bound intent — the outcome is finalized
    deterministically with zero further config mutation) and (c) prior bytes
    without durable proof (reported truthfully; no outcome is fabricated).
    """

    root = _guard_activation_root(Path(activation_root))
    receipt = load_activation_receipt(receipt_path)
    config_path = _guard_target_config(Path(receipt.project_config_path))
    # Refuse a hostile store layout before the lock exists: nothing may be
    # created inside — let alone outside — the private root.
    _guard_activation_store(root, _ROLLBACK_STORE_DIRS)
    before_image = root / "before-images" / receipt.before_image_name
    rollback_dir = root / "rollbacks"
    outcome = _build_rollback_outcome(receipt, config_path)
    intent = _build_rollback_intent(receipt, config_path)
    outcome_path = rollback_dir / f"{outcome.rollback_id}.json"
    intent_path = rollback_dir / f"{outcome.rollback_id}.intent.json"

    with _ConfigLock(root, config_path):
        current_bytes = _regular_file_bytes(config_path)
        current_hash = _sha256_hex(current_bytes)
        if current_hash == receipt.prior_config_sha256:
            parsed = tomllib.loads(current_bytes.decode("utf-8"))
            if parsed.get("profiles", {}).get("default") == (
                receipt.prior_default_profile
            ):
                if outcome_path.is_file():
                    _load_validated_rollback_outcome(outcome_path, outcome)
                    return ActivationRollbackResult(
                        status="ALREADY_RESTORED",
                        outcome=None,
                        detail=(
                            "the config already holds the exact prior bytes "
                            "and this rollback's immutable outcome is valid; "
                            "zero mutation performed"
                        ),
                    )
                if intent_path.is_file():
                    _load_validated_rollback_intent(intent_path, intent)
                    # The interrupted rollback's evidence must still verify
                    # before the audit outcome may be finalized.
                    _load_verified_before_image(before_image, receipt)
                    publication = _write_create_or_identical(
                        outcome_path,
                        outcome.serialized_bytes(),
                        label="rollback outcome",
                    )
                    return ActivationRollbackResult(
                        status="FINALIZED_AFTER_INTERRUPTED_RESTORE",
                        outcome=outcome,
                        detail=(
                            "the config restoration had already completed; "
                            "the deterministic rollback outcome was finalized "
                            "from the persisted recovery intent with zero "
                            f"further config mutation (publication: "
                            f"{publication})"
                        ),
                    )
                return ActivationRollbackResult(
                    status="ALREADY_RESTORED",
                    outcome=None,
                    detail=(
                        "the config already holds the exact prior bytes; no "
                        "durable rollback record (outcome or recovery "
                        "intent) exists for this receipt, so no rollback "
                        "audit artifact is fabricated; zero mutation "
                        "performed"
                    ),
                )
        if current_hash != receipt.activated_config_sha256:
            raise ActivationExecutionBlocked(
                {
                    "status": "ROLLBACK_PRECONDITION_VIOLATED",
                    "blockers": ["ROLLBACK_PRECONDITION_VIOLATED"],
                    "current_config_sha256": current_hash,
                    "expected_config_sha256": receipt.activated_config_sha256,
                    "detail": (
                        "the config no longer holds the exact bytes this "
                        "receipt activated (intervening change); rollback "
                        "refuses to clobber it — inspect the before-image at "
                        f"{before_image} and resolve manually"
                    ),
                }
            )
        image_bytes = _load_verified_before_image(before_image, receipt)

        _write_create_or_identical(
            intent_path,
            intent.serialized_bytes(),
            label="rollback recovery intent",
        )
        if fault_hook is not None:
            fault_hook("rollback_intent_persisted")

        _stage_and_replace(
            config_path=config_path,
            staged_name=f".tve-rollback-{outcome.rollback_id}.tmp",
            content=image_bytes,
            expected_current_hash=current_hash,
            blocked_status="ROLLBACK_PRECONDITION_VIOLATED",
            blocked_code="ROLLBACK_PRECONDITION_VIOLATED",
            blocked_detail=(
                "the config changed between verification and restore "
                "(intervening writer); the staged restore was discarded and "
                "nothing was replaced"
            ),
        )
        if fault_hook is not None:
            fault_hook("config_restored")

        _write_create_or_identical(
            rollback_dir / f"{outcome.rollback_id}.json",
            outcome.serialized_bytes(),
            label="rollback outcome",
        )
        return ActivationRollbackResult(
            status="ROLLED_BACK",
            outcome=outcome,
            detail=(
                f"[profiles] default restored to "
                f"{receipt.prior_default_profile!r}; config bytes restored "
                f"exactly (sha256 {receipt.prior_config_sha256})"
            ),
        )


__all__ = [
    "ActivationApplyResult",
    "ActivationBusyError",
    "ActivationExecutionBlocked",
    "ActivationExecutionError",
    "ActivationRollbackResult",
    "FAULT_POINTS",
    "ProfileActivationIntentV1",
    "ProfileActivationPreviewV1",
    "ProfileActivationReceiptV1",
    "ProfileActivationRollbackIntentV1",
    "ProfileActivationRollbackOutcomeV1",
    "apply_profile_activation",
    "build_activation_receipt",
    "build_apply_command_hint",
    "build_rollback_command",
    "derive_default_profile_edit",
    "evidence_record_association_blockers",
    "load_activation_receipt",
    "preview_profile_activation",
    "rollback_profile_activation",
]
